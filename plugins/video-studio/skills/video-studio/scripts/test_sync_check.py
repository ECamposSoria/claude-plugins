# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest>=8", "numpy>=1.24"]
# ///
"""Synthetic music-video checks: uv run --with pytest python -m pytest test_sync_check.py."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import wave

import numpy as np
import pytest


SCRIPT = Path(__file__).with_name("sync_check.py")
SPEC = importlib.util.spec_from_file_location("sync_check", SCRIPT)
sync = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["sync_check"] = sync
SPEC.loader.exec_module(sync)


def write_wav(path: Path, audio: np.ndarray, sr: int = 44100) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(audio.shape[1] if audio.ndim == 2 else 1)
        output.setsampwidth(2)
        output.setframerate(sr)
        output.writeframes(np.round(np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())


@pytest.fixture
def song(tmp_path: Path) -> dict:
    sr = 44100
    rng = np.random.default_rng(0)
    audio = rng.normal(0, .01, sr * 12)
    beats = np.arange(.5, 12, .5)
    burst = .7 * np.sin(2 * np.pi * 1000 * np.arange(round(.005 * sr)) / sr)
    for beat in beats:
        start = round(beat * sr)
        audio[start:start + len(burst)] += burst
    path = tmp_path / "song.wav"
    noise = tmp_path / "noise.wav"
    write_wav(path, audio)
    write_wav(noise, rng.normal(0, .1, sr * 12))
    analysis = {"schema": 1, "beats": beats.tolist(), "downbeats": np.arange(2, 12, 2).tolist(),
                "drums": {"hits": [{"t": float(t), "type": "kick", "strength": 1.0} for t in beats]},
                "source": {"duration_sec": 12.0, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}
    analysis_path = tmp_path / "analysis.json"
    analysis_path.write_text(json.dumps(analysis), encoding="utf-8")
    return {"path": path, "noise": noise, "analysis": analysis_path, "beats": beats}


def make_video(path: Path, song: dict, lag: int = 0, duration: float = 12,
               audio: Path | None = None, audio_filter: str | None = None, silent: bool = False) -> None:
    frames = []
    changes = {round(beat * 30) + lag for beat in song["beats"]}
    colour = 0
    palette = [(25, 25, 25), (225, 225, 225), (60, 60, 60), (180, 180, 180)]
    for index in range(round(duration * 30)):
        if index in changes:
            colour = (colour + 1) % len(palette)
        frame = np.empty((180, 320, 3), dtype=np.uint8)
        frame[:] = palette[colour]
        frames.append(frame.tobytes())
    command = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-threads", "1", "-filter_threads", "1",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "320x180", "-r", "30", "-i", "pipe:0"]
    if not silent:
        command += ["-i", str(audio or song["path"])]
    command += ["-map", "0:v:0", "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p", "-crf", "18"]
    if not silent:
        command += ["-map", "1:a:0", "-c:a", "aac", "-ar", "48000"]
        if audio_filter:
            command += ["-af", audio_filter]
    command += ["-t", str(duration), str(path)]
    result = subprocess.run(command, input=b"".join(frames), capture_output=True, timeout=60 + 2 * duration)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")


def check(video: Path, song: dict, audio: Path | None = None) -> tuple[int, dict]:
    command = [sys.executable, str(SCRIPT), str(video), "--song", str(song["analysis"]),
               "--audio", str(audio or song["path"]), "--json"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=84)
    assert result.stdout, result.stderr
    return result.returncode, json.loads(result.stdout)


def test_aligned(tmp_path: Path, song: dict) -> None:
    video = tmp_path / "aligned.mp4"
    make_video(video, song)
    code, result = check(video, song)
    assert code == 0
    assert not any(f["level"] in ("FAIL", "WARN") for f in result["findings"]), result
    assert len(result["stats"]["audio_windows"]) == 3
    for window in result["stats"]["audio_windows"]:
        assert abs(window["lag_ms"]) <= 500 / 30
        assert window["correlation"] >= .9
    assert result["stats"]["accents"] == 23
    assert result["stats"]["within_1_frame"] == 1
    assert result["stats"]["downbeat_coverage"] == 1


def test_audio_delayed(tmp_path: Path, song: dict) -> None:
    video = tmp_path / "delayed.mp4"
    make_video(video, song, audio_filter="adelay=200:all=1,atrim=duration=12")
    code, result = check(video, song)
    assert code == 1
    assert any(f["check"] == "audio-match" and f["level"] == "FAIL" and "audio offset +" in f["message"] for f in result["findings"])
    for window in result["stats"]["audio_windows"]:
        assert window["lag_ms"] == pytest.approx(200, abs=10)


def test_audio_replaced(tmp_path: Path, song: dict) -> None:
    video = tmp_path / "noise.mp4"
    make_video(video, song, audio=song["noise"])
    code, result = check(video, song)
    assert code == 1
    assert any(f["check"] == "audio-match" and f["level"] == "FAIL" and "not the song" in f["message"] for f in result["findings"])


def test_picture_late(tmp_path: Path, song: dict) -> None:
    video = tmp_path / "late-picture.mp4"
    make_video(video, song, lag=3)
    code, result = check(video, song)
    assert code == 0
    assert result["stats"]["median_offset_frames"] == pytest.approx(3, abs=.5)
    assert any(f["check"] == "accents" and f["level"] == "WARN" and "late" in f["message"] for f in result["findings"])
    assert not any(f["level"] == "FAIL" for f in result["findings"])


def test_short_video(tmp_path: Path, song: dict) -> None:
    video = tmp_path / "short.mp4"
    make_video(video, song, duration=11)
    code, result = check(video, song)
    assert code == 1
    assert any(f["check"] == "duration" and f["level"] == "FAIL" for f in result["findings"])


def test_wrong_song_file(tmp_path: Path, song: dict) -> None:
    video = tmp_path / "wrong-file.mp4"
    make_video(video, song)
    code, result = check(video, song, audio=song["noise"])
    assert code == 1
    assert any(f["check"] == "song-file" and f["level"] == "FAIL" and f["message"] == "the analysis is for a different file" for f in result["findings"])


def test_no_audio(tmp_path: Path, song: dict) -> None:
    video = tmp_path / "silent.mp4"
    make_video(video, song, silent=True)
    code, result = check(video, song)
    assert code == 1
    assert any(f["check"] == "audio" and f["level"] == "FAIL" for f in result["findings"])


def test_audio_level_change(tmp_path: Path, song: dict) -> None:
    video = tmp_path / "quieter.mp4"
    make_video(video, song, audio_filter="volume=-6dB")
    code, result = check(video, song)
    assert code == 0
    assert not any(f["level"] == "FAIL" for f in result["findings"]), result
    assert any(f["check"] == "audio-match" and f["level"] == "WARN" and "audio level changed" in f["message"] for f in result["findings"])
    for window in result["stats"]["audio_windows"]:
        assert window["level_db"] == pytest.approx(-6, abs=.5)


def test_silent_windows(tmp_path: Path, song: dict) -> None:
    sr = 44100
    with wave.open(str(song["path"]), "rb") as source:
        audio = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float64) / 32767
    audio = audio.copy()
    audio[:4 * sr] = 0
    write_wav(song["path"], audio)
    analysis = json.loads(song["analysis"].read_text())
    analysis["source"]["sha256"] = hashlib.sha256(song["path"].read_bytes()).hexdigest()
    song["analysis"].write_text(json.dumps(analysis), encoding="utf-8")
    video = tmp_path / "silent-intro.mp4"
    make_video(video, song)
    code, result = check(video, song)
    assert not any(f["level"] == "FAIL" for f in result["findings"]), result
    assert code == 0
    assert [w["silent"] for w in result["stats"]["audio_windows"]] == ["both", None, None]
    audio[4 * sr:8 * sr] = 0
    muted_audio = tmp_path / "muted-middle.wav"
    write_wav(muted_audio, audio)
    muted = tmp_path / "muted-middle.mp4"
    make_video(muted, song, audio=muted_audio)
    code, result = check(muted, song)
    assert code == 1
    assert any(f["check"] == "audio-match" and f["level"] == "FAIL" and "silent where the song is not" in f["message"] for f in result["findings"])


def test_container_start_offset(tmp_path: Path, song: dict) -> None:
    aligned = tmp_path / "aligned.mp4"
    make_video(aligned, song)
    remux = tmp_path / "aligned.mkv"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(aligned), "-c", "copy", str(remux)], check=True, timeout=60)
    starts = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,start_time", "-of", "json", str(remux)],
                            capture_output=True, text=True, check=True).stdout
    video_start = next(float(s["start_time"]) for s in json.loads(starts)["streams"] if s["codec_type"] == "video")
    assert video_start > .01
    code, result = check(remux, song)
    assert code == 0, result
    for window in result["stats"]["audio_windows"]:
        assert abs(window["lag_ms"]) <= 2


def test_usage_errors(tmp_path: Path, song: dict) -> None:
    video = tmp_path / "placeholder.mp4"
    video.write_bytes(b"")
    assert sync.main([str(tmp_path / "missing.mp4"), "--song", str(song["analysis"])]) == 2
    assert sync.main([str(video), "--song", str(song["analysis"]), "--audio", "missing.wav"]) == 2
    bad = tmp_path / "bad.json"
    for content in ("not json", '{"schema":2}', '{"schema":1}', "[]"):
        bad.write_text(content)
        assert sync.main([str(video), "--song", str(bad)]) == 2


def test_offset_sign_and_drift() -> None:
    song = np.random.default_rng(0).normal(size=8000 * 12)
    video = np.concatenate([np.r_[np.zeros(delay), song[start:start + 32000 - delay]]
                            for start, delay in [(0, 800), (32000, 1600), (64000, 2400)]])
    findings, windows = sync.audio_match(video, song, 12, 30)
    assert [w["lag_ms"] for w in windows] == pytest.approx([100, 200, 300], abs=.125)
    assert any("drift" in f.message for f in findings)
    lag, correlation, _ = sync.correlate_window(song[800:32000], song[:31200])
    assert lag == pytest.approx(-100, abs=.125)
    assert correlation >= .99


def test_whole_song_is_compared() -> None:
    rng = np.random.default_rng(0)
    song = rng.normal(size=8000 * 120)
    video = song.copy()
    video[8000 * 25:8000 * 45] = rng.normal(size=8000 * 20)
    findings, windows = sync.audio_match(video, song, 120, 30)
    assert [(w["t"], w["end"]) for w in windows] == [(float(t), float(t + 4)) for t in range(0, 120, 4)]
    failures = [f for f in findings if f.level == "FAIL"]
    assert len(failures) == 1 and "not the song in 6 of 30 windows" in failures[0].message
    assert failures[0].t == 24
    assert sync._windows(10.5) == [(0.0, 4.0), (4.0, 8.0), (8.0, 10.5)]
    assert sync._windows(8.5) == [(0.0, 4.0), (4.0, 8.5)]
    assert sync._windows(3.0) == [(0.0, 3.0)]


def test_local_gain_change_is_reported() -> None:
    song = np.random.default_rng(0).normal(size=8000 * 120)
    video = song.copy()
    video[8000 * 24:8000 * 28] *= 10 ** (-20 / 20)
    findings, _ = sync.audio_match(video, song, 120, 30)
    assert not any(f.level == "FAIL" for f in findings)
    warnings = [f for f in findings if f.level == "WARN"]
    assert len(warnings) == 1
    assert "audio level changed in 1 of 30 windows (up to -20.0 dB at 0:24.0)" in warnings[0].message
    assert warnings[0].t == 24


def test_stereo_image_is_checked() -> None:
    rng = np.random.default_rng(0)
    a, b = rng.normal(size=8000 * 12), rng.normal(size=8000 * 12)
    song = np.stack([a, .6 * a + .8 * b], axis=1)
    findings, windows = sync.audio_match(song.copy(), song, 12, 30)
    assert not any(f.level in ("FAIL", "WARN") for f in findings)
    assert all(w["side_correlation"] == pytest.approx(1) for w in windows)
    for altered in (song[:, ::-1], np.repeat(song.mean(axis=1, keepdims=True), 2, axis=1)):
        findings, _ = sync.audio_match(altered.copy(), song, 12, 30)
        failures = [f for f in findings if f.level == "FAIL"]
        assert len(failures) == 1 and "stereo image differs from the song in 3 of 3 windows" in failures[0].message
    near_mono = np.stack([a, a], axis=1)
    findings, windows = sync.audio_match(near_mono[:, ::-1].copy(), near_mono, 12, 30)
    assert not any(f.level == "FAIL" for f in findings)
    assert all(w["side_correlation"] is None for w in windows)


def test_stereo_file_swap_and_fold(tmp_path: Path, song: dict) -> None:
    sr = 44100
    rng = np.random.default_rng(1)
    with wave.open(str(song["path"]), "rb") as source:
        mono = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float64) / 32767
    stereo = np.stack([mono, .5 * mono + rng.normal(0, .02, len(mono))], axis=1)
    path = tmp_path / "stereo-song.wav"
    write_wav(path, stereo, sr)
    analysis = json.loads(song["analysis"].read_text())
    analysis["source"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    stereo_song = {**song, "path": path, "analysis": tmp_path / "stereo-analysis.json"}
    stereo_song["analysis"].write_text(json.dumps(analysis), encoding="utf-8")
    cases = [("aligned", None, None), ("swapped", "pan=stereo|c0=c1|c1=c0", "stereo image differs"),
             ("folded", "pan=mono|c0=0.5*c0+0.5*c1", "video's audio is mono")]
    for name, audio_filter, expected in cases:
        video = tmp_path / f"stereo-{name}.mp4"
        make_video(video, stereo_song, audio_filter=audio_filter)
        code, result = check(video, stereo_song)
        failures = [f for f in result["findings"] if f["level"] == "FAIL"]
        if expected is None:
            assert code == 0 and not failures, result
            assert all(w["side_correlation"] >= .9 for w in result["stats"]["audio_windows"])
        else:
            assert code == 1 and any(expected in f["message"] for f in failures), result


def test_stereo_edge_cases() -> None:
    rng = np.random.default_rng(2)
    a, b = rng.normal(size=96992), rng.normal(size=96992)
    song = np.stack([a, .6 * a + .8 * b], axis=1)
    findings, windows = sync.audio_match(song[:96989].copy(), song, 12.124, 30)
    assert not any(f.level in ("FAIL", "WARN") for f in findings)
    assert windows[-1]["side_correlation"] == pytest.approx(1, abs=1e-4)
    mid, side = song.mean(axis=1), song[:, 0] - song[:, 1]
    narrow = np.stack([mid + .05 * side, mid - .05 * side], axis=1)
    findings, _ = sync.audio_match(narrow, song, 12.124, 30)
    assert not any(f.level == "FAIL" for f in findings)
    warnings = [f for f in findings if f.level == "WARN"]
    assert len(warnings) == 1 and "stereo width changed in 3 of 3 windows (side up to -20.0 dB" in warnings[0].message
    antiphase = np.stack([a, -a], axis=1)
    findings, windows = sync.audio_match(antiphase.copy(), antiphase, 12.124, 30)
    assert not any(f.level in ("FAIL", "WARN") for f in findings)
    assert [w["basis"] for w in windows] == ["side"] * 3
    muted = antiphase.copy()
    muted[8000 * 4:8000 * 8] = 0
    findings, _ = sync.audio_match(muted, antiphase, 12.124, 30)
    assert any(f.level == "FAIL" and "silent where the song is not in 1 of 3 windows, at 0:04.0" in f.message for f in findings)


def test_missing_audio_and_added_side() -> None:
    rng = np.random.default_rng(3)
    song = rng.normal(size=8000 * 12)
    findings, windows = sync.audio_match(song[:8000 * 8].copy(), song, 12, 30)
    assert any(f.level == "FAIL" and "silent where the song is not in 1 of 3 windows, at 0:08.0" in f.message for f in findings)
    dual = np.stack([song, song], axis=1)
    noise = .3 * rng.normal(size=len(song))
    findings, windows = sync.audio_match(dual.copy(), dual, 12, 30)
    assert not any(f.level in ("FAIL", "WARN") for f in findings)
    findings, _ = sync.audio_match(np.stack([song + noise, song - noise], axis=1), dual, 12, 30)
    failures = [f for f in findings if f.level == "FAIL"]
    assert len(failures) == 1 and "stereo content the song lacks in 3 of 3 windows" in failures[0].message


def test_audio_gap_and_mono_song_side(tmp_path: Path, song: dict) -> None:
    gap = tmp_path / "gap.mkv"
    make_video(gap, song, audio_filter="aselect='not(between(t,4,8))'")
    plain = subprocess.run(["ffmpeg", "-v", "error", "-i", str(gap), "-map", "0:a:0", "-ac", "1", "-ar", "8000", "-f", "f32le", "-"],
                           capture_output=True, check=True, timeout=60).stdout
    assert len(plain) / 4 / 8000 < 9
    code, result = check(gap, song)
    assert code == 1
    assert any(f["level"] == "FAIL" and f["check"] == "audio-match" and f["t"] == 4.0 for f in result["findings"]), result
    with wave.open(str(song["path"]), "rb") as source:
        mono = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float64) / 32767
    noise = np.random.default_rng(4).normal(0, .05, len(mono))
    noisy = tmp_path / "antiphase-noise.wav"
    write_wav(noisy, np.stack([mono + noise, mono - noise], axis=1))
    video = tmp_path / "antiphase-noise.mp4"
    make_video(video, song, audio=noisy)
    code, result = check(video, song)
    assert code == 1
    assert any(f["level"] == "FAIL" and "stereo content the song lacks" in f["message"] for f in result["findings"])


def test_few_accents_and_no_events() -> None:
    analysis = {"beats": [1.0], "downbeats": [1.0], "drums": {"hits": []}}
    diffs = [0.0] * 90
    diffs[30] = .5
    findings, stats = sync.accent_check(diffs, 30, analysis, 6)
    assert findings[0].level == "INFO"
    assert "too few visual accents" in findings[0].message
    assert stats["downbeat_coverage"] == 1
    assert stats["median_offset_frames"] == 0
    analysis["beats"] = []
    findings, _ = sync.accent_check(diffs, 30, analysis, 6)
    assert not any(f.level == "FAIL" for f in findings)
