"""Pure stages and fake-model integration: python -I -m pytest test_listen.py."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
import sys

import librosa
import numpy as np
import pytest
from scipy.signal import butter, sosfilt
import soundfile as sf


SCRIPT = Path(__file__).with_name("listen.py")
SPEC = importlib.util.spec_from_file_location("listen", SCRIPT)
listen = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["listen"] = listen
SPEC.loader.exec_module(listen)


def test_build_grid() -> None:
    beats = np.arange(.04, 30.05, .5)
    grid = listen.build_grid(beats, beats[1::4], 31)
    assert grid["bpm"] == 120.0
    assert grid["beats_per_bar"] == 4
    assert grid["stability_cv"] < .01
    assert grid["bars"][0]["index"] == 0
    assert grid["bars"][0]["beats"] == pytest.approx([.04])
    assert grid["bars"][1]["start"] == pytest.approx(.54)
    assert listen.build_grid(beats, beats[1::3], 31)["beats_per_bar"] == 3
    short = listen.build_grid(beats[:5], [], 3)
    assert short["bars"] == []
    assert "no clear beat: pace by sections and loudness" in short["warnings"]
    snapped = listen.build_grid(np.r_[beats[::-1], beats[0], -1, 40], np.r_[beats[1::4] + .03, 40], 31)
    assert snapped["beats"] == grid["beats"]
    assert snapped["downbeats"] == grid["downbeats"]


def test_detect_drum_hits() -> None:
    sr = 22050
    rng = np.random.default_rng(0)
    signal = np.zeros(sr * 4, dtype=np.float32)
    expected = [(0.5, "kick"), (.75, "hat"), (1.0, "snare"), (1.25, "hat"),
                (1.5, "kick"), (1.75, "hat"), (3.0, "snare")]
    for start, kind in expected:
        duration, tau, amplitude = {"kick": (.12, .04, .8), "snare": (.1, .03, .5), "hat": (.04, .01, .3)}[kind]
        t = np.arange(round(duration * sr)) / sr
        if kind == "kick":
            sound = np.sin(2 * np.pi * 60 * t)
        elif kind == "snare":
            sound = sosfilt(butter(4, [200, 4000], btype="bandpass", fs=sr, output="sos"), rng.normal(size=len(t)))
        else:
            sound = sosfilt(butter(4, 7000, btype="highpass", fs=sr, output="sos"), rng.normal(size=len(t)))
        offset = round(start * sr)
        signal[offset:offset + len(t)] += (amplitude * sound * np.exp(-t / tau)).astype(np.float32)
    hits = listen.detect_drum_hits(signal, sr, np.arange(0, 4, .5))
    assert len(hits) == 7
    for hit, (t, kind) in zip(hits, expected):
        assert hit["t"] == pytest.approx(t, abs=.015)
        assert hit["type"] == kind
        assert hit["grid"] == ("half" if kind == "hat" else "on")
        assert 0 <= hit["strength"] <= 1


def test_bar_patterns() -> None:
    bars = [{"index": 1, "start": .5, "end": 2.5, "beats": [.5, 1, 1.5, 2]}]
    hits = [{"t": t, "type": kind} for t, kind in [(.5, "kick"), (1, "snare"), (1.5, "kick"), (2, "snare")]]
    result = listen.bar_patterns(hits, bars, 4)
    assert result[0]["patterns"]["kick"] == "x.......x......."
    assert result[0]["patterns"]["snare"] == "....x.......x..."
    assert result[0]["counts"]["kick"] == result[0]["counts"]["snare"] == 2
    extended = bars + [{"index": 2, "start": 2.5, "end": 4.5, "beats": []}]
    result = listen.bar_patterns([{"t": 2.49, "type": "kick"}], extended, 4)
    assert result[0]["counts"]["kick"] == 0
    assert result[1]["patterns"]["kick"] == "x..............."
    partial = [{"index": 0, "start": 0.0, "end": .54, "beats": [.04]},
               {"index": 1, "start": .54, "end": 2.54, "beats": [.54, 1.04, 1.54, 2.04]},
               {"index": 2, "start": 2.54, "end": 4.54, "beats": [2.54, 3.04, 3.54, 4.04]},
               {"index": 3, "start": 4.54, "end": 5.54, "beats": [4.54, 5.04]}]
    result = listen.bar_patterns([{"t": .04, "type": "kick"}, {"t": 4.54, "type": "kick"}, {"t": 5.04, "type": "kick"}], partial, 4)
    assert result[0]["patterns"]["kick"] == "............x..."
    assert result[3]["patterns"]["kick"] == "x...x..........."
    tempo = [{"index": 1, "start": 0.0, "end": 2.0, "beats": [0.0, .5, 1.0, 1.5]},
             {"index": 2, "start": 2.0, "end": 6.0, "beats": [2.0, 3.0, 4.0, 5.0]},
             {"index": 3, "start": 6.0, "end": 8.0, "beats": [6.0, 6.5, 7.0, 7.5]}]
    result = listen.bar_patterns([{"t": float(t), "type": "kick"} for t in (2, 3, 4, 5)], tempo, 4)
    assert result[1]["patterns"]["kick"] == "x...x...x...x..."
    assert result[1]["counts"]["kick"] == 4 and result[2]["counts"]["kick"] == 0
    assert listen.bar_patterns([{"t": 2.5, "type": "snare"}], tempo, 4)[1]["patterns"]["snare"] == "..x............."


def test_loudness_profile_and_hard_stop() -> None:
    sr = 22050
    signal = np.random.default_rng(0).normal(size=sr * 12)
    signal[:4 * sr] *= 10 ** (-30 / 20)
    signal[4 * sr:8 * sr] *= 10 ** (-10 / 20)
    signal[8 * sr:round(8.5 * sr)] = 0
    signal[round(8.5 * sr):] *= 10 ** (-20 / 20)
    bars = [{"index": i + 1, "start": float(i * 2), "end": float(i * 2 + 2)} for i in range(6)]
    profile = listen.loudness_profile(signal, sr, bars, 12)
    for bar in profile["bars"][:2]:
        assert bar["db"] == pytest.approx(-30, abs=1)
        assert bar["level"] not in ("loud", "peak")
    for bar in profile["bars"][2:4]:
        assert bar["db"] == pytest.approx(-10, abs=1)
        assert bar["level"] in ("loud", "peak")
    rise = next(r for r in profile["rises"] if r["t"] == 4)
    assert rise["db"] == pytest.approx(20, abs=1)
    assert len(profile["silences"]) == 1
    assert profile["silences"][0]["start"] == pytest.approx(8, abs=.05)
    assert profile["silences"][0]["end"] == pytest.approx(8.5, abs=.05)
    moments = listen.key_moments([], [], profile, bars, None, [], 12)
    assert any(m["kind"] == "hard_stop" and abs(m["t"] - 8) <= .05 for m in moments)


def test_segment_sections_finds_repeats() -> None:
    sr = 22050
    t = np.arange(sr * 64) / sr
    signal = np.zeros_like(t)
    for part in range(4):
        span = slice(part * 16 * sr, (part + 1) * 16 * sr)
        for midi in ([60, 64, 67] if part % 2 == 0 else [66, 70, 73]):
            wave = np.sin(2 * np.pi * librosa.midi_to_hz(midi) * t[span])
            signal[span] += .1 * wave + (0 if part % 2 == 0 else .05 * np.sign(wave))
    signal += .003 * np.random.default_rng(0).normal(size=len(t))
    beats = np.arange(0, 64, .5)
    grid = listen.build_grid(beats, beats[::4], 64)
    bars = listen.bar_patterns([], grid["bars"], grid["beats_per_bar"])
    loudness = listen.loudness_profile(signal, sr, bars, 64)
    sections = listen.segment_sections(signal, signal, sr, beats, np.array(grid["downbeats"]), bars, 4, 64, loudness, [])
    assert [s["label"] for s in sections] == ["A", "B", "A", "B"]
    assert [s["start"] for s in sections] == [0.0, 16.0, 32.0, 48.0]
    assert sections[0]["repeats"] == [3] and sections[1]["repeats"] == [4]
    short = listen.segment_sections(signal[:sr * 8], signal[:sr * 8], sr, beats[:16], beats[:16:4], bars[:4], 4, 8,
                                    listen.loudness_profile(signal[:sr * 8], sr, bars[:4], 8), [])
    assert [(s["label"], s["start"], s["end"]) for s in short] == [("A", 0.0, 8)]


def test_decode_keeps_timestamp_gaps(tmp_path: Path) -> None:
    gap = tmp_path / "gap.mka"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=12:r=44100",
                    "-af", "aselect='not(between(t,4,8))'", "-c:a", "aac", str(gap)], check=True, timeout=60)
    stereo, sr = listen.decode_audio(gap)
    assert stereo.shape[1] / sr == pytest.approx(12, abs=.1)
    assert float(np.abs(stereo[:, round(5 * sr):round(7 * sr)]).max()) < 1e-3


def test_segment_sections_without_beats() -> None:
    sr = 22050
    for duration in (12, 13, 40):
        signal = np.random.default_rng(duration).normal(0, .1, sr * duration)
        loudness = listen.loudness_profile(signal, sr, [], duration)
        sections = listen.segment_sections(signal, signal, sr, np.array([]), np.array([]), [], 4, duration, loudness, [])
        assert sections[0]["start"] == 0.0 and sections[-1]["end"] == duration
        assert all(a["end"] == b["start"] for a, b in zip(sections, sections[1:]))
        if duration < 32:
            assert len(sections) == 1


def test_melody_notes() -> None:
    sr = 22050
    signal = np.zeros(round(sr * 2.6))
    expected = [(0, .5, 69), (.5, 1, 72), (1, 1.5, 76), (2, 2.6, 69)]
    for start, end, midi in expected:
        lo, hi = round(start * sr), round(end * sr)
        signal[lo:hi] = .5 * np.sin(2 * np.pi * librosa.midi_to_hz(midi) * np.arange(hi - lo) / sr)
    notes = listen.melody_notes(signal, sr, librosa.note_to_hz("C2"), librosa.note_to_hz("C6"), .1)
    assert len(notes) == 4
    assert [n["midi"] for n in notes] == [69, 72, 76, 69]
    assert [n["name"] for n in notes] == ["A4", "C5", "E5", "A4"]
    for note, (start, end, _) in zip(notes, expected):
        assert note["start"] == pytest.approx(start, abs=.05)
        assert note["end"] == pytest.approx(end, abs=.05)


def test_estimate_key() -> None:
    major = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    minor = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
    assert listen.estimate_key(np.roll(major, 2))["key"] == "D major"
    assert listen.estimate_key(np.roll(minor, 9))["key"] == "A minor"


def test_beat_chords() -> None:
    beats = np.arange(0, 4.1, .5)
    chroma = np.zeros((12, 9))
    chroma[[0, 4, 7], :4] = 1
    chroma[[9, 0, 4], 4:8] = 1
    assert listen.beat_chords(chroma, beats, 4.5) == [
        {"start": 0.0, "end": 2.0, "chord": "C"},
        {"start": 2.0, "end": 4.0, "chord": "Am"},
        {"start": 4.0, "end": 4.5, "chord": "N"}]


def test_filter_hallucinations() -> None:
    sr = 16000
    signal = np.zeros(12 * sr)
    signal[sr:3 * sr] = np.random.default_rng(0).normal(0, .1, 2 * sr)
    segments = [{"start": 1, "end": 3, "text": "Hello there my friend", "words": []},
                {"start": 10, "end": 12, "text": "Thank you for watching", "words": []},
                {"start": 1, "end": 3, "text": "Thanks for watching.", "words": []}]
    kept, dropped = listen.filter_hallucinations(segments, signal, sr)
    assert kept == segments[:1]
    assert [s["reason"] for s in dropped] == ["silent vocals", "known hallucination phrase"]
    sung = [{"start": 1, "end": 2, "text": "Gracias", "words": [{"start": 1, "end": 2, "word": "Gracias", "probability": .99}]},
            {"start": 2, "end": 3, "text": "Thank you", "words": [{"start": 2, "end": 2.5, "word": "Thank", "probability": .3},
                                                                {"start": 2.5, "end": 3, "word": "you", "probability": .4}]}]
    kept, dropped = listen.filter_hallucinations(sung, signal, sr)
    assert [s["text"] for s in kept] == ["Gracias"]
    assert [(s["text"], s["reason"]) for s in dropped] == [("Thank you", "known hallucination phrase")]


def test_align_lyrics() -> None:
    words = [{"word": word, "start": start, "end": end} for word, start, end in [
        ("hello", 1, 1.3), ("their", 1.3, 1.5), ("my", 1.5, 1.7), ("friend", 1.7, 2.1),
        ("good", 5, 5.3), ("bye", 5.3, 5.6), ("now", 5.6, 6)]]
    lines = listen.align_lyrics(["Hello there my friend", "La la la", "Goodbye now"], words)
    assert lines[0] == {"start": 1, "end": 2.1, "text": "Hello there my friend", "aligned": True, "matched_words": 3, "words": 4}
    assert lines[2] == {"start": 5.6, "end": 6, "text": "Goodbye now", "aligned": True, "matched_words": 1, "words": 2}
    assert lines[1]["aligned"] is False
    assert 2.1 <= lines[1]["start"] < lines[1]["end"] <= 5.6
    assert listen.align_lyrics(["untimed"], [])[0]["start"] is None
    assert listen.align_lyrics(["Héllo"], words)[0]["matched_words"] == 1


def test_frame_features() -> None:
    sr = 44100
    mono = np.random.default_rng(0).normal(0, .1, sr * 2).astype(np.float32)
    features = listen.frame_features(mono, sr, 2, 30, np.array([.5, 1, 1.5]), [], [],
                                     [{"t": 1.0, "type": "kick", "strength": 1.0}])
    assert features["totalFrames"] == 60
    assert features["frames"][15]["beat_phase"] == 0
    assert features["frames"][22]["beat_phase"] == pytest.approx(.4667, abs=.001)
    assert features["frames"][30]["kick"] == 1
    assert features["frames"][34]["kick"] == pytest.approx(.411, abs=.01)
    assert all(0 <= f["level"] <= 1 for f in features["frames"])
    assert all(len(f["bands"]) == 16 for f in features["frames"])
    assert all(0 <= band <= 1 for f in features["frames"] for band in f["bands"])
    subframe = listen.frame_features(mono, sr, 2, 30, np.array([]), [], [],
                                     [{"t": 1.01, "type": "kick", "strength": 1.0}])
    assert subframe["frames"][30]["kick"] == 1


def test_render_readme() -> None:
    analysis = {"source": {"file": "song.wav", "duration_sec": 12.4, "integrated_lufs": -9.8},
                "settings": {"stems": False}, "tempo": {"bpm": 125, "beats_per_bar": 4, "stability_cv": .01},
                "downbeats": [0], "bars": [],
                "sections": [{"index": 1, "start": 0, "end": 12.4, "label": "A", "hint": "intro?", "level": "quiet", "vocals": False, "drums": False}],
                "notes": {"key": {"key": "A minor", "confidence": .71, "runner_up": "C major"}, "chords": []},
                "loudness": {}, "drums": {"counts": {"kick": 2}}, "key_moments": [], "warnings": [],
                "lyrics": {"source": "whisper", "model": "large-v3-turbo", "language": "en", "language_probability": .9,
                           "confidence": .3, "lines": [{"start": 0, "end": 1, "text": "word |", "words": [
                               {"word": "word", "p": .3}, {"word": "|", "p": .9}]}]}}
    text = listen.render_readme(analysis)
    headings = ["# Song: song.wav", "## What the song is about", "## Structure", "## Loud and quiet", "## Beat and drums",
                "## Notes and harmony", "## Lyrics", "## Key moments", "## Files", "## Uncertain"]
    positions = [text.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert "0:00.0–0:12.4" in text
    assert "A (intro?)" in text
    assert "<!-- Write 3–5 sentences from the lyrics below. Say so if they look unreliable. Do not claim to have heard the song. -->" in text
    assert "word(?)" in text
    assert "\\|" in text
    assert all(phrase not in text for phrase in ("I listened", "I heard", "listening to"))
    assert listen.format_time(65.25) == "1:05.3"
    assert listen.format_time(0) == "0:00.0"


def test_overwrite_guard(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("keep me", encoding="utf-8")
    assert listen.main([str(tmp_path / "song.wav"), "-o", str(tmp_path)]) == 2
    assert readme.read_text(encoding="utf-8") == "keep me"
    assert listen.main(["song.wav", "--lyrics", "lyrics.txt", "--no-lyrics"]) == 2
    assert listen.main(["song.wav", "--fps", "121"]) == 2


@pytest.fixture
def fake_song(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    sr = 44100
    t = np.arange(sr * 6) / sr
    clicks = np.zeros(len(t), dtype=np.float32)
    burst = .6 * np.sin(2 * np.pi * 1000 * np.arange(round(.01 * sr)) / sr)
    for start in np.arange(0, 6, .5):
        offset = round(start * sr)
        clicks[offset:offset + len(burst)] += burst
    bass = .1 * np.sin(2 * np.pi * 110 * t).astype(np.float32)
    vocals = (.1 * np.sin(2 * np.pi * 440 * t) * ((t >= 2) & (t < 4))).astype(np.float32)
    noise = np.random.default_rng(0).normal(0, 10 ** (-50 / 20), len(t)).astype(np.float32)
    stems = {name: np.stack([audio, audio]) for name, audio in [("drums", clicks), ("bass", bass), ("other", noise), ("vocals", vocals)]}
    path = tmp_path / "song.wav"
    sf.write(path, np.stack([clicks + bass, clicks + bass], axis=1), sr, subtype="PCM_16")
    monkeypatch.setattr(listen, "separate_stems", lambda *args: stems)
    monkeypatch.setattr(listen, "track_beats", lambda *args: (np.arange(0, 6, .5), np.arange(0, 6, 2)))
    words = [{"start": start, "end": end, "word": "la", "probability": .9} for start, end in [(2, 2.6), (2.6, 3.3), (3.3, 4)]]
    monkeypatch.setattr(listen, "transcribe_vocals", lambda *args: ([{"start": 2, "end": 4, "text": "la la la", "words": words}],
                                                                  {"language": "en", "language_probability": .99}))
    return path


def test_end_to_end_with_fakes(fake_song: Path, tmp_path: Path) -> None:
    out = tmp_path / "analysis"
    args = [str(fake_song), "-o", str(out)]
    assert listen.main(args) == 0
    for name in ("README.md", "analysis.json", "features.json", "listen-run.json", "stems/drums.wav", "stems/bass.wav", "stems/other.wav", "stems/vocals.wav"):
        assert (out / name).is_file()
    analysis = json.loads((out / "analysis.json").read_text())
    features = json.loads((out / "features.json").read_text())
    assert analysis["source"]["sha256"] == hashlib.sha256(fake_song.read_bytes()).hexdigest()
    assert analysis["tempo"]["bpm"] == 120.0
    assert features["totalFrames"] == 180
    assert analysis["lyrics"]["lines"][0]["text"] == "la la la"
    assert isinstance(analysis["source"]["integrated_lufs"], float)
    originals = [(out / name).read_bytes() for name in ("analysis.json", "features.json")]
    assert listen.main(args + ["--force"]) == 0
    assert originals == [(out / name).read_bytes() for name in ("analysis.json", "features.json")]
    for name in ("drums", "bass", "other", "vocals"):
        info = sf.info(out / "stems" / f"{name}.wav")
        assert (info.samplerate, info.channels, info.subtype) == (44100, 2, "PCM_16")


def test_no_stems_no_lyrics(fake_song: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object) -> None:
        raise AssertionError("disabled model stage called")

    monkeypatch.setattr(listen, "separate_stems", forbidden)
    monkeypatch.setattr(listen, "transcribe_vocals", forbidden)
    out = tmp_path / "mix-only"
    assert listen.main([str(fake_song), "-o", str(out), "--no-stems", "--no-lyrics"]) == 0
    assert not (out / "stems").exists()
    analysis = json.loads((out / "analysis.json").read_text())
    features = json.loads((out / "features.json").read_text())
    assert features["stems"] is False
    assert all("drums" not in frame and "vocals" not in frame for frame in features["frames"])
    assert any("missing stems" in warning for warning in analysis["warnings"])
    assert analysis["lyrics"] is None
    assert analysis["notes"]["vocal_melody"] == analysis["notes"]["bass"] == []
