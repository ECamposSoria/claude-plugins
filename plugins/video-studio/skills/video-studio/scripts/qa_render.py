#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy>=1.24"]
# ///
"""Check a rendered video with ffprobe/ffmpeg and optionally make a contact sheet."""

from __future__ import annotations

import argparse
import bisect
import json
import math
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class Finding:
    level: str
    check: str
    message: str
    t: float | None = None


def parse_rate(value: str | None) -> float | None:
    """Parse ffprobe's rational frame rate without raising on malformed input."""
    if not value or value in {"0/0", "N/A"}:
        return None
    try:
        numerator, denominator = value.split("/", 1)
        denominator_value = float(denominator)
        if denominator_value == 0:
            return None
        result = float(numerator) / denominator_value
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def select_video_stream(data: dict[str, Any]) -> dict[str, Any] | None:
    """Select the first video track that is not embedded cover art."""
    return next((s for s in data.get("streams", []) if s.get("codec_type") == "video"
                 and (s.get("disposition") or {}).get("attached_pic") != 1), None)


def decode_error_lines(stderr: str) -> list[str]:
    """Ignore muxer timestamp rounding noise, retaining other diagnostics."""
    return [line for line in stderr.splitlines()
            if not (re.search(r"\bnon[\s-]*monotonic(?:ally)?\b", line, re.I)
                    and re.search(r"\b(?:dts|pts)\b", line, re.I))]


def parse_probe(data: dict[str, Any], video: dict[str, Any] | None = None) -> list[Finding]:
    findings: list[Finding] = []
    streams = data.get("streams") or []
    video = video if video is not None else select_video_stream(data)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if video is None:
        return [Finding("FAIL", "probe", "no video stream found")]

    if sum(s.get("codec_type") == "video" for s in streams) > 1:
        findings.append(Finding("INFO", "probe", f"analysed video stream index={video['index']}"))
    size = f"{video.get('width', '?')}x{video.get('height', '?')}"
    findings.append(Finding("INFO", "probe", f"video codec={video.get('codec_name', '?')}, size={size}"))
    rate = parse_rate(video.get("r_frame_rate"))
    findings.append(Finding("INFO", "probe", f"frame rate={rate:g} fps" if rate is not None else "frame rate unavailable"))
    if rate is None:
        findings.append(Finding("WARN", "fps", "could not parse r_frame_rate"))
    pix_fmt = video.get("pix_fmt")
    if pix_fmt:
        level = "INFO" if pix_fmt == "yuv420p" else "WARN"
        note = "" if level == "INFO" else "; expected yuv420p for broad playback"
        findings.append(Finding(level, "pix_fmt", f"pixel format is {pix_fmt}{note}"))
    if audio:
        findings.append(Finding("INFO", "audio", f"audio codec={audio.get('codec_name', '?')}, sample_rate={audio.get('sample_rate', '?')}"))
    else:
        findings.append(Finding("INFO", "audio", "no audio stream found"))
    duration = _number((data.get("format") or {}).get("duration"))
    if duration is None:
        duration = _number(video.get("duration"))
    if duration is not None:
        findings.append(Finding("INFO", "duration", f"duration={duration:.3f}s"))
    else:
        findings.append(Finding("WARN", "duration", "could not read media duration"))
    return findings


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def parse_blackdetect(stderr: str) -> list[tuple[float, float]]:
    intervals = []
    for line in stderr.splitlines():
        start = re.search(r"black_start:\s*([\d.+-]+)", line)
        end = re.search(r"black_end:\s*([\d.+-]+)", line)
        if start and end:
            a, b = _number(start.group(1)), _number(end.group(1))
            if a is not None and b is not None and b >= a:
                intervals.append((a, b))
    return intervals


def parse_freezedetect(stderr: str, duration: float) -> list[tuple[float, float]]:
    starts: list[float] = []
    intervals: list[tuple[float, float]] = []
    for line in stderr.splitlines():
        start = re.search(r"freeze_start:\s*([\d.+-]+)", line)
        end = re.search(r"freeze_end:\s*([\d.+-]+)", line)
        if start:
            value = _number(start.group(1))
            if value is not None:
                starts.append(value)
        if end and starts:
            value = _number(end.group(1))
            if value is not None and value >= starts[-1]:
                intervals.append((starts.pop(), value))
    intervals.extend((start, duration) for start in starts if duration >= start)
    return intervals


def parse_silencedetect(stderr: str, duration: float) -> list[tuple[float, float]]:
    starts: list[float] = []
    intervals: list[tuple[float, float]] = []
    for line in stderr.splitlines():
        start = re.search(r"silence_start:\s*([\d.+-]+)", line)
        end = re.search(r"silence_end:\s*([\d.+-]+)", line)
        if start:
            value = _number(start.group(1))
            if value is not None:
                starts.append(value)
        if end and starts:
            value = _number(end.group(1))
            if value is not None and value >= starts[-1]:
                intervals.append((starts.pop(), value))
    intervals.extend((start, duration) for start in starts if duration >= start)
    return intervals


def parse_ebur128(stderr: str) -> tuple[float | None, float | None]:
    summary = stderr.rsplit("Summary:", 1)[-1]
    integrated = re.search(r"\bI:\s*(-?\d+(?:\.\d+)?)\s+LUFS", summary)
    peak = re.search(r"\bPeak:\s*(-inf|-?\d+(?:\.\d+)?)\s+dBFS", summary)
    peak_value = None
    if peak:
        peak_value = float("-inf") if peak.group(1) == "-inf" else _number(peak.group(1))
    return (
        _number(integrated.group(1)) if integrated else None,
        peak_value,
    )


def stream_duration(stream: dict[str, Any] | None) -> float | None:
    """A stream's own length: its duration field, else the Matroska DURATION tag (HH:MM:SS.fff).

    ffmpeg's Matroska muxer writes the tag as the stream's END time, so a stream that starts at 2 s
    and lasts 2 s carries DURATION=4; the start is subtracted to get the length."""
    if not stream:
        return None
    seconds = _number(stream.get("duration"))
    if seconds:
        return seconds
    for key, value in (stream.get("tags") or {}).items():
        if key.upper().startswith("DURATION"):
            match = re.fullmatch(r"(\d+):(\d+):(\d+(?:\.\d+)?)", str(value).strip())
            if match:
                end = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))
                start = _number(stream.get("start_time")) or 0.0
                return end - start if end > start else end
    return None


def jump_indices(diffs: list[float]) -> list[int]:
    """Return the 0-based index of the frame after each jump (ffmpeg's n)."""
    if not diffs:
        return []
    median = float(np.median(diffs))
    threshold = max(4.0 * median, median + 6.0)
    return [index for index, diff in enumerate(diffs, 1) if diff > threshold]


def _finding_for_intervals(check: str, intervals: list[tuple[float, float]], duration: float) -> list[Finding]:
    findings: list[Finding] = []
    for start, end in intervals:
        length = end - start
        boundary_fade = length <= 0.5 and (start == 0.0 or abs(duration - end) <= 0.1)
        level = "INFO" if boundary_fade else "WARN"
        label = "brief boundary fade" if boundary_fade else "black interval detected"
        findings.append(Finding(level, check, f"{label} from {start:.3f}s to {end:.3f}s ({length:.3f}s)", start))
    return findings


def _run(command: list[str], timeout: float = 45) -> subprocess.CompletedProcess:
    if Path(command[0]).name == "ffmpeg":
        command = [command[0], "-nostdin", "-y", "-threads", "1", "-filter_threads", "1", *command[1:]]
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


def display_size(video: dict[str, Any]) -> tuple[int, int]:
    """Width and height as displayed: phones store portrait video as landscape plus a 90° rotation."""
    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    rotation = None
    for side in video.get("side_data_list") or []:
        if "rotation" in side:
            rotation = _number(side["rotation"])
    if rotation is None:
        rotation = _number((video.get("tags") or {}).get("rotate"))
    if rotation is not None and round(abs(rotation)) % 180 == 90:
        return height, width
    return width, height


def expected_frame_count(video: dict[str, Any], duration: float, fps: float) -> tuple[float, str]:
    """Frames the video stream should decode to: its own header count, else its own duration × average rate.

    The container duration can be longer than the picture (a music bed) and r_frame_rate overstates
    variable-rate phone footage, so neither is used when the stream says better.
    """
    frames = _number(video.get("nb_frames"))
    if frames:
        return frames, "nb_frames"
    seconds = stream_duration(video) or duration
    return seconds * (parse_rate(video.get("avg_frame_rate")) or fps), "duration × rate"


def playback_end(last_pts: float | None, last_duration: float | None, fps: float) -> float:
    """When decoded playback ends: the last frame's timestamp plus how long that frame is shown.

    A VFR clip can hold its final frame far longer than one frame interval (an end card)."""
    if last_pts is None:
        return 0.0
    return last_pts + (last_duration if last_duration and last_duration > 0 else 1.0 / fps)


def stream_start(stream: dict[str, Any] | None) -> float:
    return (_number((stream or {}).get("start_time")) or 0.0) if stream else 0.0


def pass_timeout(duration: float | None) -> float:
    """Each pass decodes the whole file on one thread, so the limit grows with its length."""
    return max(60.0, 4.0 * (duration or 0.0))


def _ffmpeg_filter(video: str, filter_name: str, filter_expr: str, timeout: float = 60.0, video_index: int = 0) -> str:
    if filter_name in {"silencedetect", "ebur128"}:
        command = ["ffmpeg", "-hide_banner", "-nostats", "-i", video, "-map", "0:a:0", "-af", filter_expr, "-vn", "-f", "null", "-"]
    else:
        command = ["ffmpeg", "-hide_banner", "-nostats", "-i", video, "-map", f"0:{video_index}", "-vf", filter_expr, "-an", "-f", "null", "-"]
    proc = _run(command, timeout=timeout)
    if proc.returncode:
        raise RuntimeError(f"{filter_name} ffmpeg failed: {(proc.stderr or proc.stdout).strip()[-500:]}")
    return proc.stderr


def _jump_indices(video: str, timeout: float = 60.0, video_index: int = 0) -> tuple[list[tuple[int, float]], int, float | None, float | None]:
    command = ["ffmpeg", "-nostdin", "-threads", "1", "-filter_threads", "1", "-hide_banner", "-loglevel", "info", "-nostats", "-i", video, "-map", f"0:{video_index}", "-vf", "scale=320:180,format=gray,showinfo=checksum=0", "-an", "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    frame_size = 320 * 180
    error_file = tempfile.TemporaryFile()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=error_file, bufsize=0)
    assert process.stdout is not None
    os.set_blocking(process.stdout.fileno(), False)
    previous: np.ndarray | None = None
    diffs: list[float] = []
    deadline = time.monotonic() + timeout
    try:
        while True:
            chunk = bytearray()
            while len(chunk) < frame_size:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("frame-difference ffmpeg pass timed out")
                readable, _, _ = select.select([process.stdout], [], [], min(remaining, 1.0))
                if not readable:
                    if process.poll() is not None:
                        break
                    continue
                part = process.stdout.read(frame_size - len(chunk))
                if not part:
                    break
                chunk.extend(part)
            if len(chunk) != frame_size:
                break
            frame = np.frombuffer(chunk, dtype=np.uint8).astype(np.int16)
            if previous is not None:
                diffs.append(float(np.abs(frame - previous).mean()))
            previous = frame
        try:
            code = process.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise RuntimeError("frame-difference ffmpeg pass timed out")
        error_file.seek(0)
        if code:
            error_file.seek(max(0, os.fstat(error_file.fileno()).st_size - 2000))
            error = error_file.read().decode("utf-8", "replace")
            raise RuntimeError(f"frame-difference ffmpeg failed: {error.strip()[-500:]}")
        # Spool stderr to disk to avoid blocking the raw-frame pipe. Retain only
        # jump timestamps while reading showinfo one line at a time.
        indices = set(jump_indices(diffs))
        jumps: list[tuple[int, float]] = []
        timestamp_count = 0
        last_timestamp: float | None = None
        last_duration: float | None = None
        for line in error_file:
            match = re.search(rb"\bn:\s*(\d+).*?\bpts_time:\s*(\S+)", line)
            if not match:
                continue
            index = int(match.group(1))
            timestamp = _number(match.group(2))
            if index != timestamp_count or timestamp is None:
                raise RuntimeError("invalid frame presentation timestamps")
            timestamp_count += 1
            last_timestamp = timestamp
            held = re.search(rb"\bduration_time:\s*(\S+)", line)
            last_duration = _number(held.group(1)) if held else None
            if index in indices:
                jumps.append((index, timestamp))
        if timestamp_count != len(diffs) + int(previous is not None):
            raise RuntimeError("frame presentation timestamp count does not match decoded frames")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()
        error_file.close()
    return jumps, len(diffs) + int(previous is not None), last_timestamp, last_duration


@dataclass
class SheetReference:
    path: str
    index: int
    offset: float
    frames: list[float]


def _seek(timestamp: float) -> str:
    return f"{math.floor(timestamp * 1000) / 1000:.3f}"


def _frame_chain(label: str | None, height: int | None = None) -> str:
    # square pixels first, so anamorphic frames and side-by-side pairs keep the shape a player shows
    chain = "scale=trunc(iw*sar/2)*2:ih,setsar=1," + (f"scale=-2:{height}" if height else "scale=320:-2")
    if label:
        chain += f",drawtext=text={label}:x=6:y=6:fontsize=18:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=4"
    return chain


def _frame_times(path: str, index: int, format_start: float, timeout: float) -> list[float]:
    """When each decoded frame of one stream starts, on the timeline input -ss uses (the file's start is 0)."""
    proc = _run(["ffprobe", "-v", "error", "-select_streams", str(index), "-show_entries",
                 "frame=best_effort_timestamp_time", "-of", "csv=p=0", path], timeout=timeout)
    if proc.returncode:
        raise RuntimeError(f"{path}: listing frame times failed: {proc.stderr.strip()[-300:]}")
    # a frame carrying side data prints a trailing field: "0.000000,"
    starts = (_number(line.split(",", 1)[0]) for line in proc.stdout.splitlines())
    times = sorted({start - format_start for start in starts if start is not None})
    if not times:
        raise RuntimeError(f"{path}: no frame times to compare")
    return times


def _on_screen(frames: list[float], moment: float) -> float:
    """Start of the frame shown at `moment`: the last one starting at or before it (the first, before it)."""
    return frames[max(0, bisect.bisect_right(frames, moment + 1e-6) - 1)]


def _frame_command(video: str, video_index: int, seek: float, label: str | None, target: Path,
                   reference: SheetReference | None = None, reference_seek: float = 0.0,
                   reference_label: str | None = None) -> list[str]:
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", _seek(seek), "-i", video]
    if reference is None:
        return command + ["-map", f"0:{video_index}", "-frames:v", "1", "-vf", _frame_chain(label), "-q:v", "3", str(target)]
    # each input is seeked to the start of a frame, so that frame comes first; trim and setpts keep exactly
    # it at pts 0, because hstack pairs by timestamp and would otherwise advance one side to meet the other
    graph = (f"[0:{video_index}]trim=end_frame=1,setpts=0,{_frame_chain(label, 320)}[a];"
             f"[1:{reference.index}]trim=end_frame=1,setpts=0,{_frame_chain(reference_label, 320)}[b];[a][b]hstack")
    return command + ["-ss", _seek(reference_seek), "-i", reference.path, "-filter_complex", graph,
                      "-frames:v", "1", "-q:v", "3", str(target)]


def _sheet_reference(path: str) -> SheetReference:
    proc = _run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path])
    if proc.returncode:
        raise RuntimeError(f"reference {path}: ffprobe failed: {proc.stderr.strip()[-300:]}")
    probe = json.loads(proc.stdout)
    video = select_video_stream(probe)
    if video is None:
        raise RuntimeError(f"reference {path} has no video stream")
    index = int(video["index"])
    duration = _number((probe.get("format") or {}).get("duration")) or stream_duration(video)
    start = stream_start(probe.get("format"))
    return SheetReference(path, index, max(0.0, stream_start(video) - start),
                          _frame_times(path, index, start, pass_timeout(duration)))


def _make_sheet(video: str, destination: str, duration: float, frames: int, video_index: int = 0,
                last_frame: float | None = None, offset: float = 0.0,
                reference: SheetReference | None = None,
                own_frames: list[float] | None = None) -> tuple[list[float], str | None]:
    """Return the sampled times and, when the timestamps could not be printed, ffmpeg's reason."""
    count = max(1, frames)
    # offset = where the picture starts on the file's timeline (video that starts after the audio)
    times = [offset + i * duration / count for i in range(count)]
    if last_frame is not None:
        # never seek past the last decoded frame (tiny clips, containers longer than the picture)
        times = [min(t, last_frame) for t in times]
    unlabelled_reason = None
    with tempfile.TemporaryDirectory(prefix="qa-render-") as tmp:
        paths = []
        for index, timestamp in enumerate(times):
            target = Path(tmp) / f"frame-{index:02d}.jpg"
            seek, reference_seek, reference_moment = timestamp, 0.0, 0.0
            if reference is not None:
                # the same moment of both pictures, each showing its frame on screen then; a reference shorter
                # than ours stays on its last frame, and its label gives that frame's start
                seek = _on_screen(own_frames, timestamp) if own_frames else timestamp
                reference_moment = reference.offset + (timestamp - offset)
                reference_seek = _on_screen(reference.frames, reference_moment)
                reference_moment = min(reference_moment, reference.frames[-1])
            # drawtext needs a usable font; without one the sheet is still made, unlabelled
            for labelled in ((False,) if unlabelled_reason else (True, False)):
                target.unlink(missing_ok=True)
                proc = _run(_frame_command(video, video_index, seek, f"{timestamp:.2f}s" if labelled else None, target,
                                           reference, reference_seek, f"ref {reference_moment:.2f}s" if labelled else None))
                if not proc.returncode and target.exists():
                    break
                if labelled:
                    # ffmpeg names the cause on its first line; the rest echoes the filter graph back
                    unlabelled_reason = next((line.strip() for line in (proc.stderr or proc.stdout or "").splitlines()
                                              if line.strip()), f"ffmpeg exited {proc.returncode}")[:200]
            else:
                raise RuntimeError(f"contact sheet frame at {timestamp:.3f}s failed: {(proc.stderr or proc.stdout).strip()[-300:]}")
            paths.append(target)
        # ffmpeg's image2 demuxer needs sequential numbered files; all chosen times are evenly spaced.
        columns = min(2 if reference else 4, len(paths))
        rows = math.ceil(len(paths) / columns)
        proc = _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-framerate", "1", "-i", str(Path(tmp) / "frame-%02d.jpg"), "-vf", f"tile={columns}x{rows}:padding=8:margin=8", "-frames:v", "1", destination])
        if proc.returncode:
            raise RuntimeError(f"contact sheet failed: {(proc.stderr or proc.stdout).strip()[-300:]}")
    return times, unlabelled_reason


def run_qa(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    video_path = Path(args.video)
    findings: list[Finding] = []
    if not video_path.is_file():
        findings.append(Finding("FAIL", "input", f"file not found: {args.video}"))
        return _result(args.video, None, findings), 1
    if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
        findings.append(Finding("FAIL", "tools", "ffprobe and ffmpeg must be installed"))
        return _result(args.video, None, findings), 1
    try:
        probe_proc = _run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", args.video])
        if probe_proc.returncode:
            raise RuntimeError(f"ffprobe failed: {probe_proc.stderr.strip()[-500:]}")
        probe = json.loads(probe_proc.stdout)
        video = select_video_stream(probe)
        findings.extend(parse_probe(probe, video))
        if video is None:
            return _result(args.video, None, findings), 1
        video_index = int(video["index"])
        actual_size = display_size(video)
        if args.expect_size:
            expected_size = tuple(int(part) for part in args.expect_size.lower().split("x", 1))
            if actual_size != expected_size:
                findings.append(Finding("FAIL", "size", f"expected {expected_size[0]}x{expected_size[1]}, got {actual_size[0]}x{actual_size[1]}"))
        actual_fps = parse_rate(video.get("r_frame_rate"))
        if actual_fps is None or actual_fps <= 0:
            findings.append(Finding("FAIL", "fps", "cannot measure frame times: frame rate unavailable"))
            return _result(args.video, probe, findings), 1
        if actual_fps is not None:
            if args.expect_fps is not None and abs(actual_fps - args.expect_fps) > 0.01:
                findings.append(Finding("FAIL", "fps", f"expected {args.expect_fps:g} fps, got {actual_fps:g} fps"))
            elif args.expect_fps is not None:
                findings.append(Finding("PASS", "fps", f"frame rate {actual_fps:g} fps matches"))
            else:
                findings.append(Finding("INFO", "fps", f"frame rate {actual_fps:g} fps"))
        duration = _number((probe.get("format") or {}).get("duration")) or _number(video.get("duration"))
        if duration is not None:
            if args.expect_duration is not None and abs(duration - args.expect_duration) > args.duration_tol:
                findings.append(Finding("FAIL", "duration", f"expected {args.expect_duration:.3f}s ±{args.duration_tol:.3f}s, got {duration:.3f}s"))
            elif args.expect_duration is not None:
                findings.append(Finding("PASS", "duration", f"duration {duration:.3f}s matches"))
            else:
                findings.append(Finding("INFO", "duration", f"duration {duration:.3f}s"))
        else:
            findings.append(Finding("FAIL", "duration", "could not read media duration"))
            return _result(args.video, probe, findings), 1
        audio_stream = next((stream for stream in probe.get("streams", []) if stream.get("codec_type") == "audio"), None)
        if args.expect_audio and audio_stream is None:
            findings.append(Finding("FAIL", "audio", "expected audio stream, found none"))
        elif audio_stream is None:
            findings.append(Finding("INFO", "audio", "audio checks skipped; no audio stream"))

        limit = pass_timeout(duration)
        try:
            # video and audio only: phone files carry data tracks that ffmpeg cannot "decode"
            decoded = _run(["ffmpeg", "-v", "error", "-i", args.video, "-map", f"0:{video_index}", "-map", "0:a:0?", "-f", "null", "-"], timeout=limit)
            errors = decode_error_lines(decoded.stderr)
            if decoded.returncode or errors:
                detail = "\n".join(errors[:3]) or f"ffmpeg exited {decoded.returncode}"
                findings.append(Finding("FAIL", "decode", detail))
            else:
                findings.append(Finding("PASS", "decode", "selected streams decoded without errors"))
        except (OSError, subprocess.TimeoutExpired) as exc:
            findings.append(Finding("FAIL", "decode", str(exc)))

        black = parse_blackdetect(_ffmpeg_filter(args.video, "blackdetect", "blackdetect=d=0.1:pix_th=0.10", limit, video_index))
        findings.extend(_finding_for_intervals("black", black, duration or 0))
        if not black:
            findings.append(Finding("PASS", "black", "no black intervals detected"))
        frozen = parse_freezedetect(_ffmpeg_filter(args.video, "freezedetect", "freezedetect=n=-60dB:d=0.5", limit, video_index), duration or 0)
        for start, end in frozen:
            findings.append(Finding("WARN", "freeze", f"possible freeze from {start:.3f}s to {end:.3f}s ({end-start:.3f}s)", start))
        if not frozen:
            findings.append(Finding("PASS", "freeze", "no freeze intervals detected"))

        if audio_stream is not None:
            silence = parse_silencedetect(_ffmpeg_filter(args.video, "silencedetect", "silencedetect=noise=-50dB:d=1.0", limit), duration or 0)
            silent_total = sum(max(0, end - start) for start, end in silence)
            for start, end in silence:
                findings.append(Finding("WARN", "silence", f"silence from {start:.3f}s to {end:.3f}s ({end-start:.3f}s)", start))
            # measure against the audio track itself: a short silent track must not hide in a long container
            audio_duration = stream_duration(audio_stream) or duration
            picture_duration = stream_duration(video) or duration
            # compare END times on one timeline: delayed audio can be shorter and still end with the picture
            audio_end = stream_start(audio_stream) + (audio_duration or 0.0)
            picture_end = stream_start(video) + (picture_duration or 0.0)
            if audio_duration and picture_duration and audio_end < picture_end - 0.5:
                findings.append(Finding("WARN", "audio", f"audio ends at {audio_end:.3f}s, picture runs to {picture_end:.3f}s"))
            if audio_duration and silent_total >= audio_duration * 0.95:
                findings.append(Finding("FAIL", "silence", f"audio is silent for {silent_total:.3f}s of {audio_duration:.3f}s"))
            elif not silence:
                findings.append(Finding("PASS", "silence", "no silence intervals of 1s or longer"))
            loudness = _ffmpeg_filter(args.video, "ebur128", "ebur128=peak=true", limit)
            integrated, peak = parse_ebur128(loudness)
            if peak is not None and peak <= -60:
                # catches silent tracks shorter than silencedetect's 1 s minimum; the true peak is
                # used because EBU R128 reports -70 LUFS for any audio under its 400 ms window
                findings.append(Finding("FAIL", "silence", f"audio track is silent (true peak {peak:.1f} dBFS)"))
            if audio_duration and audio_duration < 0.4:
                findings.append(Finding("INFO", "loudness", f"audio too short ({audio_duration:.3f}s) to measure loudness"))
            elif integrated is not None:
                level = "WARN" if abs(integrated - args.loudness_target) > 1.5 else "PASS"
                findings.append(Finding(level, "loudness", f"integrated loudness {integrated:.1f} LUFS (target {args.loudness_target:g})"))
            else:
                findings.append(Finding("WARN", "loudness", "could not parse integrated loudness"))
            if peak is not None:
                level = "WARN" if peak > -1 else "PASS"
                findings.append(Finding(level, "peak", f"true peak {peak:.1f} dBFS"))
            else:
                findings.append(Finding("WARN", "peak", "could not parse true peak"))

        jumps, frame_count, last_frame, last_frame_duration = _jump_indices(args.video, limit, video_index)
        expected_frames, source = expected_frame_count(video, duration, actual_fps)
        # Truncation is judged on the timeline: where decoded playback actually ends. Header counts
        # can include edit-list preroll (stream-copied trims) and estimates use nominal rates.
        # the container length is only the picture's length when nothing else is in the file
        picture_duration = stream_duration(video) or (duration if len(probe.get("streams", [])) == 1 else None)
        played = playback_end(last_frame, last_frame_duration, actual_fps)
        # decoded timestamps start at the file's start time, so place the picture on the same timeline
        picture_end = (stream_start(video) - stream_start(probe.get("format"))) + (picture_duration or 0.0)
        if picture_duration and played < picture_end - max(0.5, 0.05 * picture_duration):
            findings.append(Finding("FAIL", "frames", f"playback ends at {played:.3f}s of {picture_end:.3f}s "
                                                      f"({frame_count} frames decoded)"))
        elif frame_count < 0.98 * expected_frames:
            findings.append(Finding("WARN", "frames", f"decoded {frame_count} of ~{expected_frames:g} frames counted by "
                                                      f"{source}; the timeline is complete (edit-list preroll or nominal rate)"))
        for frame_index, timestamp in jumps:
            level = "WARN" if args.mode == "clip" else "INFO"
            desc = "possible one-frame pop" if args.mode == "clip" else "cut"
            findings.append(Finding(level, "jump", f"{desc} at frame {frame_index} ({timestamp:.3f}s)", timestamp))
        if not jumps:
            findings.append(Finding("PASS", "jump", "no isolated frame jumps detected"))

        if args.sheet:
            sheet_duration = stream_duration(video)
            reference = _sheet_reference(args.compare) if args.compare else None
            own_frames = (_frame_times(args.video, video_index, stream_start(probe.get("format")), limit)
                          if reference else None)
            times, unlabelled_reason = _make_sheet(args.video, args.sheet,
                                                   sheet_duration if sheet_duration is not None else duration, args.sheet_frames,
                                                   video_index, last_frame,
                                                   max(0.0, stream_start(video) - stream_start(probe.get("format"))), reference,
                                                   own_frames)
            message = f"contact sheet saved to {args.sheet}"
            if reference is not None:
                message += f", each tile beside {args.compare} at the same moment"
            message += (f"; timestamps not printed on the tiles (drawtext: {unlabelled_reason})" if unlabelled_reason
                        else "; timestamps printed on each tile")
            findings.append(Finding("INFO", "sheet", message + "; frames at " + ", ".join(f"{t:.2f}s" for t in times)))
        return _result(args.video, probe, findings), int(any(f.level == "FAIL" for f in findings))
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError, RuntimeError) as exc:
        findings.append(Finding("FAIL", "qa", str(exc)))
        return _result(args.video, None, findings), 1


def _result(video: str, probe: dict[str, Any] | None, findings: list[Finding]) -> dict[str, Any]:
    serialized = []
    for finding in findings:
        item = asdict(finding)
        if item["t"] is None:
            del item["t"]
        serialized.append(item)
    return {"file": video, "probe": probe or {}, "findings": serialized}


def _parse_size(value: str) -> str:
    if not re.fullmatch(r"\d+x\d+", value.lower()):
        raise argparse.ArgumentTypeError("size must be WxH, for example 1920x1080")
    return value.lower()


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run local ffprobe/ffmpeg checks on a rendered video.")
    parser.add_argument("video", help="video file to inspect")
    parser.add_argument("--expect-size", type=_parse_size)
    parser.add_argument("--expect-fps", type=float)
    parser.add_argument("--expect-duration", type=float)
    parser.add_argument("--duration-tol", type=float, default=0.25)
    parser.add_argument("--expect-audio", action="store_true")
    parser.add_argument("--loudness-target", type=float, default=-14.0)
    parser.add_argument("--mode", choices=("edit", "clip"), default="edit")
    parser.add_argument("--sheet", help="write an evenly sampled JPEG contact sheet")
    parser.add_argument("--sheet-frames", type=_positive_int, default=12)
    parser.add_argument("--compare", metavar="REF",
                        help="with --sheet: put REF's frame from the same moment beside each tile (recreating a reference)")
    parser.add_argument("--json", action="store_true", help="emit one JSON result object")
    args = parser.parse_args(argv)
    if args.compare and not args.sheet:
        parser.error("--compare needs --sheet")
    result, status = run_qa(args)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for finding in result["findings"]:
            suffix = f" t={finding['t']:.3f}s" if finding.get("t") is not None else ""
            print(f"{finding['level']}  {finding['check']}: {finding['message']}{suffix}")
        counts = {level: sum(f["level"] == level for f in result["findings"]) for level in ("FAIL", "WARN")}
        print(f"summary: {counts['FAIL']} FAIL, {counts['WARN']} WARN")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
