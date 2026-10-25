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


def decode_stereo(path: str | Path, duration: float) -> np.ndarray:
    # (samples, 2) at 8 kHz; a mono source comes back with two equal channels. async=1 turns a timestamp
    # gap into silence where it happened; a plain decode drops it and shifts the rest earlier.
    result = _run(["ffmpeg", "-nostdin", "-v", "error", "-threads", "1", "-filter_threads", "1",
                   "-i", str(path), "-map", "0:a:0", "-vn", "-af", "aresample=async=1", "-ac", "2", "-ar", "8000",
                   "-f", "f32le", "-"], duration)
    audio = np.frombuffer(result.stdout, dtype="<f4").astype(np.float64)
    if not audio.size or audio.size % 2 or not np.isfinite(audio).all():
        raise ValueError("empty or invalid audio decode")
    return audio.reshape(-1, 2)


def _align(video: np.ndarray, song: np.ndarray, lag: int) -> tuple[np.ndarray, np.ndarray]:
    if lag > 0:
        return video[lag:], song[:-lag]
    if lag < 0:
        return video[:lag], song[-lag:]
    return video, song


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a - a.mean(), b - b.mean()
    norm = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / norm) if norm > 1e-20 else 0.0


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
    aligned_video, aligned_song = _align(video, song, lag)
    pearson = _pearson(aligned_video, aligned_song)
    rms_a = float(np.mean(aligned_video ** 2))
    rms_b = float(np.mean(aligned_song ** 2))
    db = 10 * math.log10(max(rms_a, 1e-20) / max(rms_b, 1e-20))
    return 1000 * lag / sr, pearson, db


def _rms_db(audio: np.ndarray) -> float:
    return 10 * math.log10(max(float(np.mean(audio ** 2)) if audio.size else 0.0, 1e-20))


def _windows(duration: float, width: float = 4.0) -> list[tuple[float, float]]:
    starts = np.arange(0.0, duration, width) if duration > width else np.array([0.0])
    spans = [(float(a), float(min(a + width, duration))) for a in starts]
    if len(spans) > 1 and spans[-1][1] - spans[-1][0] < 1.0:
        tail = spans.pop()
        spans[-1] = (spans[-1][0], tail[1])
    return spans


def _short_db(audio: np.ndarray, width: int = 2000, hop: int = 400) -> np.ndarray:
    if len(audio) < width:
        return np.array([])
    power = np.concatenate(([0.0], np.cumsum(audio ** 2)))
    starts = np.arange(0, len(audio) - width + 1, hop)
    return 10 * np.log10(np.maximum((power[starts + width] - power[starts]) / width, 1e-20))


def _runs(start: float, flags: np.ndarray, hop: float = .05) -> list[float]:
    # Start time of each run of flagged 250 ms stretches, so one dropout is reported once.
    return [round(start + i * hop, 2) for i in np.flatnonzero(flags) if i == 0 or not flags[i - 1]]


def _channel_db(mid: np.ndarray, side: np.ndarray | None) -> float:
    # Mean power of L and R from mid = (L + R) / 2 and side = L - R.
    power = float(np.mean(mid ** 2)) + (float(np.mean(side ** 2)) / 4 if side is not None else 0.0) if mid.size else 0.0
    return 10 * math.log10(max(power, 1e-20))


def audio_match(video: np.ndarray, song: np.ndarray, duration: float, fps: float) -> tuple[list[Finding], list[dict]]:
    # Timing and identity come from the mid signal; with two channels the side signal (L - R) also has to
    # match, because a channel swap or a fold-down to mono leaves the mid untouched.
    if len(video) < len(song):
        # Missing audio is compared as silence; trimming the song instead would hide it.
        video = np.pad(video, [(0, len(song) - len(video))] + [(0, 0)] * (video.ndim - 1))
    stereo = video.ndim == 2 and song.ndim == 2
    video_side = video[:, 0] - video[:, 1] if stereo else None
    song_side = song[:, 0] - song[:, 1] if stereo else None
    video = video.mean(axis=1) if video.ndim == 2 else video
    song = song.mean(axis=1) if song.ndim == 2 else song
    # Contiguous windows over the whole song: sampled windows let a replaced middle pass.
    windows = []
    for start, end in _windows(duration):
        lo, hi = round(start * 8000), round(end * 8000)
        count = min(len(video[lo:hi]), len(song[lo:hi]))
        v_mid, s_mid = video[lo:lo + count], song[lo:lo + count]
        v_side = video_side[lo:lo + count] if stereo else None
        s_side = song_side[lo:lo + count] if stereo else None
        # Silence is judged on the channels: an antiphase passage cancels in the mid signal.
        video_silent, song_silent = _channel_db(v_mid, v_side) < -60, _channel_db(s_mid, s_side) < -60
        if video_silent or song_silent:
            # Silence has no variance, so its correlation says nothing: judge it by level instead.
            windows.append({"t": start, "end": end, "lag_ms": None, "correlation": None, "level_db": None,
                            "silent": "both" if video_silent and song_silent else "video" if video_silent else "song"})
            continue
        # Match on the side only where the mid has cancelled (antiphase); wide stereo still matches on the mid.
        basis = "side" if stereo and _rms_db(s_mid) < _rms_db(s_side) - 20 else "mid"
        (p_video, p_song), (q_video, q_song) = ((v_side, s_side), (v_mid, s_mid)) if basis == "side" else ((v_mid, s_mid), (v_side, s_side))
        lag, correlation, db = correlate_window(p_video, p_song)
        other = "mid" if basis == "side" else "side"
        row = {"t": start, "end": end, "lag_ms": lag, "correlation": correlation, "level_db": db, "basis": basis,
               "side_correlation": None, "side_db": None, "mid_correlation": None, "mid_db": None, "added": None,
               "added_db": None, "silent": None}
        # The signal not matched on must agree too: where the song has it, by correlation and level; where the
        # song has none, any energy in the video was added (it cancels in the signal that was matched).
        # A short dropout or insert barely moves a 4 s correlation: compare 250 ms stretches too. 30 dB keeps a
        # dip (a level WARN) apart from audio that is gone or added.
        aligned_video, aligned_song = _align(p_video, p_song, round(lag * 8))
        # 250 ms stretches every 50 ms: any mute of 250 ms or more fills at least one of them.
        video_db, song_db = _short_db(aligned_video), _short_db(aligned_song)
        offset = max(lag, 0) / 1000
        row["dropouts"] = _runs(start + offset, (song_db > -50) & (video_db < song_db - 30))
        row["inserts"] = _runs(start + offset, (video_db > -50) & (video_db > song_db + 30))
        if stereo and _rms_db(q_song) - _rms_db(p_song) > -30:
            aligned_video, aligned_song = _align(q_video, q_song, round(lag * 8))
            row[f"{other}_correlation"] = _pearson(aligned_video, aligned_song)
            row[f"{other}_db"] = _rms_db(aligned_video) - _rms_db(aligned_song)
        elif stereo and _rms_db(q_video) - _rms_db(p_video) > -30:
            row["added"], row["added_db"] = other, _rms_db(q_video) - _rms_db(p_video)
        windows.append(row)
    findings = []
    total = len(windows)

    def where(rows: list[dict]) -> str:
        return ", ".join(format_time(w["t"]) for w in rows[:5]) + (" …" if len(rows) > 5 else "")

    for side, message in (("video", "the video's audio is silent where the song is not"),
                          ("song", "the video has sound where the song is silent")):
        rows = [w for w in windows if w["silent"] == side]
        if rows:
            findings.append(Finding("FAIL", "audio-match", f"{message} in {len(rows)} of {total} windows, at {where(rows)}", rows[0]["t"]))
    measured = [w for w in windows if w["silent"] is None]
    foreign = [w for w in measured if w["correlation"] < .8]
    if foreign:
        lowest = min(w["correlation"] for w in foreign)
        findings.append(Finding("FAIL", "audio-match", f"the video's audio is not the song in {len(foreign)} of {total} windows "
                                f"(lowest correlation {lowest:.2f}), at {where(foreign)}", foreign[0]["t"]))
    matched = [w for w in measured if w["correlation"] >= .8]
    shifted = [w for w in matched if abs(w["lag_ms"]) > 500 / fps]
    if shifted:
        lags = [w["lag_ms"] for w in shifted]
        drift = max(w["lag_ms"] for w in matched) - min(w["lag_ms"] for w in matched) > .25
        findings.append(Finding("FAIL", "audio-match", f"audio offset {lags[0]:+.1f} ms at {format_time(shifted[0]['t'])} "
                                f"({len(shifted)} of {total} windows, {min(lags):+.1f} to {max(lags):+.1f} ms)"
                                + ("; drift across windows" if drift else ""), shifted[0]["t"]))
    def secondary(w: dict, key: str) -> float | None:
        return w.get(f"side_{key}") if w.get(f"side_{key}") is not None else w.get(f"mid_{key}")

    image = [w for w in matched if secondary(w, "correlation") is not None and secondary(w, "correlation") < .8]
    if image:
        lowest = min(image, key=lambda w: secondary(w, "correlation"))
        findings.append(Finding("FAIL", "audio-match", f"the stereo image differs from the song in {len(image)} of {total} windows "
                                f"({'side' if lowest['side_correlation'] is not None else 'mid'} correlation "
                                f"{secondary(lowest, 'correlation'):.2f} at {format_time(lowest['t'])}), at {where(image)}: "
                                "channels swapped, folded to mono or remixed?", image[0]["t"]))
    for key, message in (("dropouts", "the video's audio drops out where the song plays"),
                         ("inserts", "the video's audio has sound where the song is quiet")):
        times = [t for w in matched for t in w.get(key, [])]
        if times:
            findings.append(Finding("FAIL", "audio-match", f"{message} in {len(times)} stretch{'es' if len(times) > 1 else ''} of 0.25 s, at "
                                    + ", ".join(format_time(t) for t in times[:5]) + (" …" if len(times) > 5 else ""), times[0]))
    for signal, kind in (("side", "stereo"), ("mid", "mono")):
        added = [w for w in matched if w.get("added") == signal]
        if added:
            loudest = max(added, key=lambda w: w["added_db"])
            reference = "mid" if signal == "side" else "side"
            findings.append(Finding("FAIL", "audio-match", f"the video's audio has {kind} content the song lacks in {len(added)} of {total} "
                                    f"windows ({signal} {loudest['added_db']:+.1f} dB of the {reference} at {format_time(loudest['t'])}), "
                                    f"at {where(added)}: noise or effects added?", added[0]["t"]))
    width = [w for w in matched if secondary(w, "db") is not None and secondary(w, "correlation") >= .8 and abs(secondary(w, "db")) > 2]
    if width:
        biggest = max(width, key=lambda w: abs(secondary(w, "db")))
        findings.append(Finding("WARN", "audio-match", f"stereo width changed in {len(width)} of {total} windows "
                                f"({'side' if biggest['side_db'] is not None else 'mid'} up to {secondary(biggest, 'db'):+.1f} dB at "
                                f"{format_time(biggest['t'])}), at {where(width)}: widened, narrowed or remixed?", width[0]["t"]))
    changed = [w for w in matched if abs(w["level_db"]) > 1]
    if changed:
        biggest = max(changed, key=lambda w: abs(w["level_db"]))
        findings.append(Finding("WARN", "audio-match", f"audio level changed in {len(changed)} of {total} windows (up to "
                                f"{biggest['level_db']:+.1f} dB at {format_time(biggest['t'])}), at {where(changed)}: "
                                "normalised, ducked or remixed?", changed[0]["t"]))
    if not findings and not measured:
        findings.append(Finding("INFO", "audio-match", "song and video are silent in every window; correlation not measured"))
    elif not any(f.level == "FAIL" for f in findings):
        lags = [w["lag_ms"] for w in measured]
        silent = total - len(measured)
        findings.append(Finding("PASS", "audio-match", f"{len(measured)} windows of 4 s match: lag {min(lags):+.1f} to {max(lags):+.1f} ms, "
                                f"lowest correlation {min(w['correlation'] for w in measured):.3f}"
                                + (f"; {silent} silent in both" if silent else "")))
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
                song_stream = next((s for s in json.loads(_run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", args.audio],
                                                                duration).stdout).get("streams", []) if s.get("codec_type") == "audio"), {})
                song_channels, video_channels = int(song_stream.get("channels") or 0), int(audio.get("channels") or 0)
                if song_channels >= 2 and video_channels == 1:
                    findings.append(Finding("FAIL", "audio-layout", f"the song has {song_channels} channels but the video's audio is mono"))
                elif song_channels == 1 and video_channels >= 2:
                    findings.append(Finding("INFO", "audio-layout", f"the song is mono; the video's audio has {video_channels} channels"))
                video_audio = decode_stereo(args.video, duration)
                song_audio = decode_stereo(args.audio, duration)
                if video_channels == 1:
                    video_audio, song_audio = video_audio.mean(axis=1), song_audio.mean(axis=1)
                # Picture time zero is the first video frame; containers offset either stream from it
                # (an MKV remux starts the video at 0.021 s to cover AAC priming).
                start = (_number(audio.get("start_time")) or 0.0) - (_number(video.get("start_time")) or 0.0)
                if start > 0:
                    video_audio = np.pad(video_audio, [(round(start * 8000), 0)] + [(0, 0)] * (video_audio.ndim - 1))
                elif start < 0:
                    video_audio = video_audio[round(-start * 8000):]
                if (len(song_audio) - len(video_audio)) / 8000 > 1 / fps:
                    findings.append(Finding("FAIL", "audio", f"the video's audio decodes to {len(video_audio) / 8000:.3f} s; "
                                            f"the song is {len(song_audio) / 8000:.3f} s"))
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
