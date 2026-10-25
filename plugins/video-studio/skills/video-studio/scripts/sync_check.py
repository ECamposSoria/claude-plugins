#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy>=1.24"]
# ///
"""Check music-video sync: uv run sync_check.py VIDEO --song analysis.json [--audio SONG] [--json]."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import select
import subprocess
import sys
import time
from typing import Any

import numpy as np


@dataclass
class Finding:
    level: str
    check: str
    message: str
    t: float | None = None


def format_time(seconds: float) -> str:
    tenths = int(math.floor(seconds * 10 + .5 + 1e-9))
    return f"{tenths // 600}:{(tenths % 600) / 10:04.1f}"


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def parse_rate(value: str | None) -> float | None:
    try:
        numerator, denominator = str(value).split("/", 1)
        result = float(numerator) / float(denominator)
        return result if math.isfinite(result) and result > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def stream_duration(stream: dict) -> float | None:
    duration = _number(stream.get("duration"))
    if duration is not None:
        return duration
    for key, value in stream.get("tags", {}).items():
        if key.upper().startswith("DURATION"):
            match = re.fullmatch(r"(\d+):(\d+):(\d+(?:\.\d+)?)", str(value))
            if match:
                end = int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3])
                return end - (_number(stream.get("start_time")) or 0)
    return None


def _run(command: list[str], duration: float) -> subprocess.CompletedProcess:
    result = subprocess.run(command, capture_output=True, timeout=60 + 2 * duration)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace").strip()[-500:])
    return result


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_analysis(path: str | Path) -> dict:
    analysis = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(analysis, dict) or type(analysis.get("schema")) is not int or analysis["schema"] != 1:
        raise ValueError("analysis must have schema 1")
    source = analysis.get("source")
    if not isinstance(source, dict) or (_number(source.get("duration_sec")) or 0) <= 0:
        raise ValueError("analysis source.duration_sec must be positive")
    if not isinstance(source.get("sha256"), str) or not re.fullmatch(r"[0-9a-fA-F]{64}", source["sha256"]):
        raise ValueError("analysis source.sha256 is invalid")
    for name in ("beats", "downbeats"):
        values = analysis.get(name)
        if not isinstance(values, list) or any(_number(v) is None or float(v) < 0 for v in values):
            raise ValueError(f"analysis {name} is invalid")
    drums = analysis.get("drums")
    if not isinstance(drums, dict) or not isinstance(drums.get("hits"), list):
        raise ValueError("analysis drums.hits is invalid")
    for hit in drums["hits"]:
        if not isinstance(hit, dict) or _number(hit.get("t")) is None or _number(hit.get("strength")) is None:
            raise ValueError("analysis drum hit is invalid")
    return analysis


def decode_mono(path: str | Path, duration: float) -> np.ndarray:
    result = _run(["ffmpeg", "-nostdin", "-v", "error", "-threads", "1", "-filter_threads", "1",
                   "-i", str(path), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "8000", "-f", "f32le", "-"], duration)
    audio = np.frombuffer(result.stdout, dtype="<f4").astype(np.float64)
    if not audio.size or not np.isfinite(audio).all():
        raise ValueError("empty or invalid audio decode")
    return audio


def correlate_window(video: np.ndarray, song: np.ndarray, sr: int = 8000) -> tuple[float, float, float]:
    count = min(len(video), len(song))
    if count < 2:
        return 0.0, 0.0, 0.0
    video, song = video[:count], song[:count]
    a, b = video - video.mean(), song - song.mean()
    size = 1 << (2 * count - 1).bit_length()
    correlation = np.fft.irfft(np.fft.rfft(a, size) * np.conj(np.fft.rfft(b, size)), size)
    limit = min(sr, count - 2)
    lags = np.arange(-limit, limit + 1)
    lag = int(lags[int(np.argmax(correlation[lags % size]))])
    if lag > 0:
        aligned_video, aligned_song = video[lag:], song[:-lag]
    elif lag < 0:
        aligned_video, aligned_song = video[:lag], song[-lag:]
    else:
        aligned_video, aligned_song = video, song
    a, b = aligned_video - aligned_video.mean(), aligned_song - aligned_song.mean()
    norm = float(np.linalg.norm(a) * np.linalg.norm(b))
    pearson = float(np.dot(a, b) / norm) if norm > 1e-20 else 0.0
    rms_a = float(np.mean(aligned_video ** 2))
    rms_b = float(np.mean(aligned_song ** 2))
    db = 10 * math.log10(max(rms_a, 1e-20) / max(rms_b, 1e-20))
    return 1000 * lag / sr, pearson, db


def audio_match(video: np.ndarray, song: np.ndarray, duration: float, fps: float) -> tuple[list[Finding], list[dict]]:
    width = min(20.0, duration / 3)
    windows = []
    for start in (0.0, (duration - width) / 2, duration - width):
        lo, hi = round(start * 8000), round((start + width) * 8000)
        lag, correlation, db = correlate_window(video[lo:hi], song[lo:hi])
        windows.append({"t": start, "lag_ms": lag, "correlation": correlation, "level_db": db})
    findings = []
    drift = len({w["lag_ms"] for w in windows}) > 1
    for window in windows:
        if window["correlation"] < .8:
            findings.append(Finding("FAIL", "audio-match", f"the video's audio is not the song (correlation {window['correlation']:.2f})", window["t"]))
        elif abs(window["lag_ms"]) > 500 / fps:
            findings.append(Finding("FAIL", "audio-match", f"audio offset {window['lag_ms']:+.1f} ms at {format_time(window['t'])}" + ("; drift across windows" if drift else ""), window["t"]))
        if window["correlation"] >= .8 and abs(window["level_db"]) > 1:
            findings.append(Finding("WARN", "audio-match", f"audio level changed by {window['level_db']:+.1f} dB (normalised or remixed?)", window["t"]))
    if not findings:
        findings.append(Finding("PASS", "audio-match", "; ".join(f"{format_time(w['t'])}: lag {w['lag_ms']:+.1f} ms, correlation {w['correlation']:.3f}" for w in windows)))
    return findings, windows


def frame_differences(path: str | Path, fps: float, duration: float, video_index: int) -> list[float]:
    command = ["ffmpeg", "-nostdin", "-v", "error", "-threads", "1", "-filter_threads", "1", "-i", str(path),
               "-map", f"0:{video_index}", "-an", "-vf", f"scale=160:90,format=gray,fps={fps:.12g}",
               "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    assert process.stdout is not None and process.stderr is not None
    os.set_blocking(process.stdout.fileno(), False)
    os.set_blocking(process.stderr.fileno(), False)
    deadline = time.monotonic() + 60 + 2 * duration
    readers = [process.stdout, process.stderr]
    buffer = bytearray()
    errors = bytearray()
    previous = None
    diffs = []
    frame_size = 160 * 90
    try:
        while readers:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("video frame decode timed out")
            ready, _, _ = select.select(readers, [], [], min(remaining, 1.0))
            for stream in ready:
                chunk = os.read(stream.fileno(), frame_size if stream is process.stdout else 4096)
                if not chunk:
                    readers.remove(stream)
                    continue
                if stream is process.stderr:
                    errors.extend(chunk)
                    errors = errors[-4000:]
                    continue
                buffer.extend(chunk)
                if len(buffer) >= frame_size:
                    current = np.frombuffer(bytes(buffer[:frame_size]), dtype=np.uint8).astype(np.int16)
                    del buffer[:frame_size]
                    diffs.append(float(np.abs(current - previous).mean() / 255) if previous is not None else 0.0)
                    previous = current
        code = process.wait(timeout=max(.01, deadline - time.monotonic()))
        if code or buffer:
            raise RuntimeError("video frame decode failed: " + errors.decode("utf-8", "replace"))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=60 + 2 * duration)
        process.stdout.close()
        process.stderr.close()
    return diffs


def accent_check(diffs: list[float], fps: float, analysis: dict, accent_k: float) -> tuple[list[Finding], dict]:
    values = np.asarray(diffs)
    median = float(np.median(values)) if values.size else 0.0
    mad = float(np.median(abs(values - median))) if values.size else 0.0
    indices = [i for i in range(1, len(values)) if values[i] > median + accent_k * mad and values[i] >= .02
               and values[i] == max(values[max(0, i - 2):i + 3])]
    times = np.array(indices) / fps
    events = sorted([float(t) for t in analysis["beats"]] + [float(h["t"]) for h in analysis["drums"]["hits"] if h["strength"] >= .3])
    merged = []
    for event in events:
        if not merged or event - merged[-1] > .02:
            merged.append(event)
    events_array = np.asarray(merged)
    offsets = np.array([(t - events_array[np.argmin(abs(events_array - t))]) * fps for t in times]) if merged else np.array([])
    coverage = float(np.mean([bool(times.size and np.min(abs(times - downbeat)) * fps <= 2 + 1e-8)
                              for downbeat in analysis["downbeats"]])) if analysis["downbeats"] else 0.0
    share = float(np.mean(abs(offsets) <= 1 + 1e-8)) if offsets.size else 0.0
    median_offset = float(np.median(offsets)) if offsets.size else None
    stats = {"accents": len(indices), "within_1_frame": share, "median_offset_frames": median_offset,
             "downbeat_coverage": coverage}
    worst = sorted(zip(times.tolist(), offsets.tolist()), key=lambda pair: -abs(pair[1]))[:5]
    detail = "; worst accents: " + ", ".join(f"{format_time(t)} ({offset:+.1f} frames)" for t, offset in worst) if worst else ""
    if len(indices) < 8:
        finding = Finding("INFO", "accents", "too few visual accents to judge picture sync" + detail)
    elif not offsets.size:
        finding = Finding("INFO", "accents", "no music events to judge picture sync")
    elif abs(median_offset) >= 1.5 and share < .5:
        direction = "late" if median_offset > 0 else "early"
        finding = Finding("WARN", "accents", f"picture is consistently {direction} by {abs(median_offset):.1f} frames" + detail)
    else:
        finding = Finding("PASS", "accents", f"{share:.1%} within 1 frame; median offset {median_offset:+.1f} frames" + detail)
    return [finding, Finding("INFO", "downbeat-coverage", f"{coverage:.1%} of downbeats have an accent within 2 frames")], stats


def run_checks(args: argparse.Namespace, analysis: dict) -> dict:
    duration = float(analysis["source"]["duration_sec"])
    findings: list[Finding] = []
    stats: dict = {}
    try:
        probe = json.loads(_run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", args.video], duration).stdout)
        streams = probe.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        findings.append(Finding("PASS" if audio else "FAIL", "audio", "audio stream present" if audio else "video has no audio stream"))
        if video is None:
            raise ValueError("no video stream")
        fps = parse_rate(video.get("avg_frame_rate")) or parse_rate(video.get("r_frame_rate"))
        if fps is None:
            raise ValueError("cannot determine video frame rate")
        for name, stream in (("video", video), ("audio", audio)):
            if stream is None:
                continue
            measured = stream_duration(stream)
            if measured is None:
                findings.append(Finding("FAIL", "duration", f"{name} stream duration unavailable"))
                continue
            delta = abs(measured - duration)
            level = "PASS" if delta <= 1 / fps + 1e-8 else "WARN" if delta <= .1 + 1e-8 else "FAIL"
            findings.append(Finding(level, "duration", f"{name} {measured:.3f} s; song {duration:.3f} s; difference {measured - duration:+.3f} s"))
        if args.audio:
            matches = _sha256(args.audio) == analysis["source"]["sha256"]
            findings.append(Finding("PASS" if matches else "FAIL", "song-file", "song SHA-256 matches" if matches else "the analysis is for a different file"))
            if audio:
                video_audio = decode_mono(args.video, duration)
                song_audio = decode_mono(args.audio, duration)
                # A container can place an otherwise unshifted audio stream after picture time zero.
                start = _number(audio.get("start_time")) or 0.0
                if start > 0:
                    video_audio = np.pad(video_audio, (round(start * 8000), 0))
                elif start < 0:
                    video_audio = video_audio[round(-start * 8000):]
                checks, windows = audio_match(video_audio, song_audio, duration, fps)
                findings.extend(checks)
                stats["audio_windows"] = windows
        diffs = frame_differences(args.video, fps, duration, int(video["index"]))
        checks, accent_stats = accent_check(diffs, fps, analysis, args.accent_k)
        findings.extend(checks)
        stats.update(accent_stats)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        findings.append(Finding("FAIL", "decode", " ".join(str(error).splitlines())))
    return {"video": args.video, "song": args.song, "findings": [asdict(f) for f in findings], "stats": stats}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video")
    parser.add_argument("--song", required=True)
    parser.add_argument("--audio")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--accent-k", type=float, default=6.0)
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code)
    try:
        for path in (args.video, args.song, args.audio):
            if path is not None and not Path(path).is_file():
                raise ValueError(f"file not found: {path}")
        if not math.isfinite(args.accent_k) or args.accent_k < 0:
            raise ValueError("--accent-k must be finite and non-negative")
        analysis = load_analysis(args.song)
    except (OSError, ValueError, TypeError) as error:
        print(f"sync_check: {' '.join(str(error).splitlines())}", file=sys.stderr)
        return 2
    result = run_checks(args, analysis)
    failures = sum(f["level"] == "FAIL" for f in result["findings"])
    warnings = sum(f["level"] == "WARN" for f in result["findings"])
    if args.json:
        print(json.dumps(result, indent=2, allow_nan=False))
    else:
        for finding in result["findings"]:
            print(f"{finding['level']}  {finding['check']}: {finding['message']}")
        print(f"summary: {failures} FAIL, {warnings} WARN")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
