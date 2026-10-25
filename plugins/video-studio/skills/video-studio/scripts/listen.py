#!/usr/bin/env python3
"""Describe a song for an agent: python -I /tool/listen.py SONG -o OUTDIR."""

from __future__ import annotations

import argparse
from collections import Counter
import difflib
import gc
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import time
import unicodedata
from typing import Any

import librosa
import numpy as np
from scipy.signal import find_peaks
import soundfile as sf


VERSION = "0.1.0"
PITCHES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def _run(command: list[str], timeout: float = 3600) -> subprocess.CompletedProcess:
    result = subprocess.run(command, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace").strip()[-500:])
    return result


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_ebur128(stderr: str) -> tuple[float | None, float | None]:
    summary = stderr.rsplit("Summary:", 1)[-1]
    integrated = re.search(r"\bI:\s*(-?\d+(?:\.\d+)?)\s+LUFS", summary)
    peak = re.search(r"\bPeak:\s*(-inf|-?\d+(?:\.\d+)?)\s+dBFS", summary)
    return (float(integrated.group(1)) if integrated else None,
            float(peak.group(1)) if peak else None)


def probe_source(path: str | Path) -> dict:
    data = json.loads(_run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)]).stdout)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if audio is None:
        raise ValueError("no audio stream")
    measured = _run(["ffmpeg", "-nostdin", "-hide_banner", "-nostats", "-i", str(path),
                     "-map", "0:a:0", "-af", "ebur128=peak=true", "-vn", "-f", "null", "-"])
    lufs, peak = parse_ebur128(measured.stderr.decode("utf-8", "replace"))
    container_duration = data.get("format", {}).get("duration")
    return {"file": Path(path).name, "sha256": _sha256(path),
            "container_duration_sec": float(container_duration) if container_duration else None,
            "sample_rate": int(audio["sample_rate"]), "channels": int(audio["channels"]),
            "integrated_lufs": lufs, "true_peak_dbfs": peak}


def decode_audio(path: str | Path) -> tuple[np.ndarray, int]:
    raw = _run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-map", "0:a:0",
                "-ac", "2", "-ar", "44100", "-f", "f32le", "-"]).stdout
    audio = np.frombuffer(raw, dtype="<f4")
    if not len(audio) or len(audio) % 2 or not np.isfinite(audio).all():
        raise ValueError("empty or invalid decoded audio")
    return audio.reshape(-1, 2).T.copy(), 44100


def _device(device: str, threads: int | None = None) -> str:
    import torch

    if threads is not None:
        torch.set_num_threads(threads)
    return ("cuda" if torch.cuda.is_available() else "cpu") if device == "auto" else device


def _release(device: str) -> None:
    import torch

    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()


def separate_stems(stereo: np.ndarray, sr: int, device: str, threads: int) -> dict[str, np.ndarray]:
    import demucs.pretrained
    import demucs.apply
    import torch

    device = _device(device, threads)
    random.seed(0)
    np.random.seed(0)
    torch.manual_seed(0)
    model = demucs.pretrained.get_model("htdemucs")
    model.eval()
    try:
        wav = torch.from_numpy(stereo)
        ref = wav.mean(0)
        scale = ref.std().clamp_min(1e-8)
        wavn = (wav - ref.mean()) / scale
        with torch.no_grad():
            out = demucs.apply.apply_model(model, wavn[None], device=device, shifts=1, split=True,
                                           overlap=0.25, progress=False)[0]
        out = out * scale + ref.mean()
        stems = {name: out[i].cpu().numpy().copy() for i, name in enumerate(model.sources)}
        del out, wav, ref, wavn, scale
        return stems
    finally:
        del model
        _release(device)


def track_beats(mono: np.ndarray, sr: int, device: str) -> tuple[np.ndarray, np.ndarray]:
    from beat_this.inference import Audio2Beats

    device = _device(device, int(os.environ.get("LISTEN_THREADS", "8")))
    model = Audio2Beats(checkpoint_path="final0", device=device, dbn=False)
    try:
        beats, downbeats = model(mono.astype(np.float32), sr)
        return np.asarray(beats), np.asarray(downbeats)
    finally:
        del model
        _release(device)


def transcribe_vocals(audio16k: np.ndarray, language: str | None, model_name: str,
                      device: str, threads: int) -> tuple[list[dict], dict]:
    from faster_whisper import WhisperModel

    device = _device(device, threads)
    model = WhisperModel(model_name, device=device, compute_type="int8" if device == "cpu" else "float16",
                         cpu_threads=threads)
    try:
        # No VAD: Silero is trained on speech and dropped 7/8 of a sung vocal stem; silence is filtered later.
        segments, info = model.transcribe(audio16k, language=language, word_timestamps=True,
                                         vad_filter=False, condition_on_previous_text=False)
        result = [{"start": s.start, "end": s.end, "text": s.text.strip(),
                   "words": [{"start": w.start, "end": w.end, "word": w.word,
                              "probability": w.probability} for w in (s.words or [])]} for s in segments]
        return result, {"language": info.language, "language_probability": info.language_probability}
    finally:
        del model
        _release(device)


def build_grid(beats: np.ndarray, downbeats: np.ndarray, duration: float) -> dict:
    beats = np.unique(np.asarray(beats, dtype=float))
    beats = beats[np.isfinite(beats) & (beats >= 0) & (beats <= duration)]
    snapped = []
    for downbeat in downbeats:
        if len(beats):
            nearest = int(np.argmin(abs(beats - downbeat)))
            if abs(beats[nearest] - downbeat) <= .07:
                snapped.append(nearest)
    indices = sorted(set(snapped))
    downs = beats[indices]
    intervals = np.diff(beats)
    bpm = round(60 / float(np.median(intervals)), 1) if len(intervals) else None
    cv = float(np.std(intervals) / np.mean(intervals)) if len(intervals) else 0.0
    warnings = []
    if cv > .08:
        warnings.append("tempo varies: follow the beats, not a fixed BPM")
    if len(indices) < 2:
        meter = 4
        warnings.append("fewer than 2 downbeats: assuming 4 beats per bar")
    else:
        counts = Counter(np.diff(indices).tolist())
        meter = min(counts, key=lambda n: (-counts[n], n))
    bars = []
    if len(beats) < 8:
        warnings.append("no clear beat: pace by sections and loudness")
    elif len(downs):
        if indices[0] > 0:
            bars.append({"index": 0, "start": 0.0, "end": float(downs[0]), "beats": beats[:indices[0]].tolist()})
        length = float(np.median(np.diff(downs))) if len(downs) > 1 else float(np.median(intervals)) * meter
        for i, start in enumerate(downs):
            end = float(downs[i + 1]) if i + 1 < len(downs) else min(duration, float(start) + length)
            bars.append({"index": i + 1, "start": float(start), "end": end,
                         "beats": beats[(beats >= start) & (beats < end)].tolist()})
    return {"beats": beats.tolist(), "downbeats": downs.tolist(), "bars": bars, "bpm": bpm,
            "beats_per_bar": meter, "stability_cv": round(cv, 3), "warnings": warnings}


def _db(signal: np.ndarray) -> float:
    return max(-90.0, 10 * math.log10(max(float(np.mean(np.square(signal, dtype=np.float64))) if signal.size else 0, 1e-9)))


def _slice(signal: np.ndarray, sr: int, start: float, end: float) -> np.ndarray:
    return signal[max(0, round(start * sr)):max(0, round(end * sr))]


def _blocks(duration: float) -> list[dict]:
    return [{"index": i + 1, "start": float(t), "end": min(float(t + 2), duration), "beats": []}
            for i, t in enumerate(np.arange(0, duration, 2))]


def _level(value: float, values: list[float]) -> str:
    q25, q60, q90 = np.percentile(values, [25, 60, 90])
    return "quiet" if value < q25 else "peak" if value >= q90 else "loud" if value >= q60 else "medium"


def detect_drum_hits(drums_mono: np.ndarray, sr: int, beats: np.ndarray) -> list[dict]:
    hop = 256
    envelope = librosa.onset.onset_strength(y=drums_mono, sr=sr, hop_length=hop)
    rms = librosa.feature.rms(y=drums_mono, frame_length=512, hop_length=hop)[0]
    onsets = librosa.onset.onset_detect(onset_envelope=envelope, sr=sr, hop_length=hop, units="time")
    power = abs(librosa.stft(drums_mono, n_fft=2048, hop_length=hop)) ** 2
    frequencies = librosa.fft_frequencies(sr=sr, n_fft=2048)
    denominator = max(float(np.percentile(envelope, 99)), 1e-10)
    beats = np.asarray(beats)
    hits = []
    for onset in onsets:
        frame = round(onset * sr / hop)
        # Spectral flux peaks lag the attack; use the preceding energy minimum as its timestamp.
        attack = int(librosa.onset.onset_backtrack(np.array([frame]), rms)[0])
        first, last = attack * hop, min(len(drums_mono), (frame + 1) * hop)
        attack_audio = abs(drums_mono[first:last])
        active = np.flatnonzero(attack_audio > max(float(attack_audio.max()) * .03, 1e-8)) if attack_audio.size else []
        t = (first + int(active[0])) / sr if len(active) else attack * hop / sr
        if _db(_slice(drums_mono, sr, t, t + .05)) < -45:
            continue
        column = round(t * sr / hop)
        columns = power[:, column:max(column + 1, math.ceil((t + .06) * sr / hop))]
        energies = np.array([columns[(frequencies >= lo) & (frequencies < hi)].sum()
                             for lo, hi in [(20, 150), (150, 3000), (5000, 16000)]])
        low, mid, high = energies / max(float(energies.sum()), 1e-20)
        kind = "kick" if low >= .5 else "hat" if high >= .5 else "snare" if mid >= .3 else "perc"
        nearest = int(np.argmin(abs(beats - t))) if len(beats) else -1
        offset = t - beats[nearest] if nearest >= 0 else 0.0
        grid = "off"
        if nearest >= 0 and abs(offset) <= .04:
            grid = "on"
        else:
            left = int(np.searchsorted(beats, t, side="right")) - 1
            if 0 <= left < len(beats) - 1:
                step = beats[left + 1] - beats[left]
                if abs(t - (beats[left] + .5 * step)) <= .04:
                    grid = "half"
                elif min(abs(t - (beats[left] + q * step)) for q in [.25, .75]) <= .04:
                    grid = "sixteenth"
        hits.append({"t": t, "type": kind, "strength": float(np.clip(envelope[frame] / denominator, 0, 1)),
                     "beat": nearest, "offset": float(offset), "grid": grid})
    # One attack can raise two flux peaks a frame apart; both backtrack to it. 30 ms stays under 32nds at 180 BPM.
    merged: list[dict] = []
    for hit in sorted(hits, key=lambda h: h["t"]):
        if merged and hit["t"] - merged[-1]["t"] < .03:
            if hit["strength"] > merged[-1]["strength"]:
                merged[-1] = hit
            continue
        merged.append(hit)
    return merged


def bar_patterns(hits: list[dict], bars: list[dict], beats_per_bar: int) -> list[dict]:
    result = []
    steps = beats_per_bar * 4
    for bar in bars:
        result.append({**bar, "patterns": {kind: "." * steps for kind in ("kick", "snare", "hat")},
                       "counts": {kind: 0 for kind in ("kick", "snare", "hat", "perc")}})
    for hit in hits:
        for i, bar in enumerate(result):
            if bar["start"] <= hit["t"] < bar["end"] and bar["end"] > bar["start"]:
                step = round((hit["t"] - bar["start"]) / (bar["end"] - bar["start"]) * steps)
                if step == steps:
                    if i + 1 == len(result):
                        break
                    bar, step = result[i + 1], 0
                kind = hit["type"]
                bar["counts"][kind] = bar["counts"].get(kind, 0) + 1
                if kind in bar["patterns"]:
                    pattern = list(bar["patterns"][kind])
                    pattern[step] = "x"
                    bar["patterns"][kind] = "".join(pattern)
                break
    return result


def loudness_profile(mono: np.ndarray, sr: int, bars: list[dict], duration: float) -> dict:
    times = np.arange(0, duration, .1)
    curve = [round(_db(_slice(mono, sr, t - .2, t + .2)), 1) for t in times]
    measures = []
    for bar in bars or _blocks(duration):
        values = [v for t, v in zip(times, curve) if bar["start"] <= t < bar["end"]]
        measures.append({"index": bar["index"], "start": bar["start"], "end": bar["end"],
                         "db": round(float(np.mean(values)) if values else -90, 1)})
    for measure in measures:
        measure["level"] = _level(measure["db"], [m["db"] for m in measures])
    silences = []
    start = None
    for t in [*times, duration]:
        silent = t < duration and _db(_slice(mono, sr, t, min(t + .1, duration))) < -50
        if silent and start is None:
            start = float(t)
        elif not silent and start is not None:
            if t - start >= .3 - 1e-8:
                silences.append({"start": start, "end": float(t)})
            start = None
    changes = [{"t": b["start"], "db": round(b["db"] - a["db"], 1)} for a, b in zip(measures, measures[1:])]
    quiet = min(measures, key=lambda b: b["db"]) if measures else None
    return {"curve_hz": 10, "curve": curve, "bars": measures, "silences": silences,
            "rises": [c for c in changes if c["db"] >= 6], "falls": [c for c in changes if c["db"] <= -6],
            "loudest_bar": max(measures, key=lambda b: b["db"])["index"] if measures else None,
            "quietest_span": {k: quiet[k] for k in ("start", "end", "db")} if quiet else None}


def _sync_features(values: np.ndarray, beats: np.ndarray, sr: int, hop: int = 512) -> np.ndarray:
    frames = librosa.time_to_frames(beats, sr=sr, hop_length=hop)
    frames = np.clip(frames, 0, values.shape[1] - 1)
    synced = librosa.util.sync(values, frames, aggregate=np.mean, pad=True)
    edges = np.unique(np.concatenate(([0], frames, [values.shape[1]])))
    indices = np.clip(np.searchsorted(edges, frames, side="right") - 1, 0, synced.shape[1] - 1)
    return synced[:, indices]


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    norm = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / norm) if norm > 1e-12 else 0.0


def _laplacian_labels(cqt: np.ndarray, mfcc: np.ndarray, max_k: int) -> np.ndarray:
    """Repetition clusters per unit (McFee & Ellis 2014, librosa's Laplacian segmentation recipe)."""
    import scipy.linalg
    import scipy.ndimage
    import scipy.sparse.csgraph
    from sklearn.cluster import KMeans

    recurrence = librosa.segment.recurrence_matrix(cqt, width=3, mode="affinity", sym=True)
    recurrence = librosa.segment.timelag_filter(scipy.ndimage.median_filter)(recurrence, size=(1, 7))
    distance = np.sum(np.diff(mfcc, axis=1) ** 2, axis=0)
    path = np.exp(-distance / max(float(np.median(distance)), 1e-12))
    path = np.diag(path, 1) + np.diag(path, -1)
    deg_path, deg_rec = path.sum(axis=1), recurrence.sum(axis=1)
    mu = deg_path.dot(deg_path + deg_rec) / max(float(np.sum((deg_path + deg_rec) ** 2)), 1e-12)
    # The tiny diagonal keeps every degree positive; identical frames otherwise break the normalised Laplacian.
    affinity = np.nan_to_num(mu * recurrence + (1 - mu) * path) + 1e-6 * np.eye(len(distance) + 1)
    values, vectors = scipy.linalg.eigh(scipy.sparse.csgraph.laplacian(affinity, normed=True))
    vectors = scipy.ndimage.median_filter(vectors, size=(9, 1))
    k = int(np.argmax(np.diff(values[:max_k + 1]))) + 1
    k = max(2, min(k, max_k))
    embedding = vectors[:, :k] / np.maximum(np.linalg.norm(vectors[:, :k], axis=1, keepdims=True), 1e-8)
    return KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(embedding)


def segment_sections(harmonic: np.ndarray, mono: np.ndarray, sr: int, beats: np.ndarray,
                     downbeats: np.ndarray, bars: list[dict], beats_per_bar: int, duration: float,
                     loudness: dict, hits: list[dict], vocals: np.ndarray | None = None) -> list[dict]:
    units = np.asarray(beats if bars else np.arange(0, duration, 2), dtype=float)
    if not len(units):
        units = np.array([0.0])
    low_sr = 22050
    harmonic_low = librosa.resample(harmonic, orig_sr=sr, target_sr=low_sr, res_type="soxr_hq") if sr != low_sr else harmonic
    mono_low = librosa.resample(mono, orig_sr=sr, target_sr=low_sr, res_type="soxr_hq") if sr != low_sr else mono
    cqt = _sync_features(librosa.amplitude_to_db(np.abs(librosa.cqt(y=harmonic_low, sr=low_sr, bins_per_octave=36,
                                                                     n_bins=252, hop_length=512)), ref=np.max), units, low_sr)
    mfcc = _sync_features(librosa.feature.mfcc(y=mono_low, sr=low_sr, n_mfcc=13), units, low_sr)
    chroma = _sync_features(librosa.feature.chroma_cqt(y=harmonic_low, sr=low_sr), units, low_sr)
    raw = np.vstack((chroma, mfcc))
    values = (raw - raw.mean(axis=1, keepdims=True)) / np.maximum(raw.std(axis=1, keepdims=True), 1e-8)
    blocks = bars or _blocks(duration)
    unit_seconds = float(np.median(np.diff(units))) if len(units) > 1 else 2.0
    min_bars = 4 if duration >= 60 else 2
    min_units = min_bars * (beats_per_bar if bars else 1)
    if len(units) >= 3 * min_units:
        clusters = _laplacian_labels(cqt, mfcc, max_k=max(2, min(6, len(units) // (2 * min_units))))
    else:
        clusters = np.zeros(len(units), dtype=int)
    runs = []
    for i, cluster in enumerate(clusters):
        if runs and runs[-1][1] == cluster:
            continue
        t = 0.0 if i == 0 else float(units[i])
        if i and bars and len(downbeats):
            t = float(downbeats[np.argmin(abs(np.asarray(downbeats) - t))])
        if runs and t <= runs[-1][0]:
            runs[-1][1] = cluster
            continue
        runs.append([t, int(cluster)])

    def mean_vector(start: float, end: float) -> np.ndarray:
        mask = (units >= start) & (units < end)
        return values[:, mask].mean(axis=1) if mask.any() else values[:, int(np.argmin(abs(units - start)))]

    def length(i: int) -> int:
        start, end = runs[i][0], runs[i + 1][0] if i + 1 < len(runs) else duration
        return sum(start <= b["start"] < end for b in blocks) if bars else round((end - start) / unit_seconds)

    while len(runs) > 1:
        short = [i for i in range(len(runs)) if length(i) < (min(2, min_bars) if i in (0, len(runs) - 1) else min_bars)]
        if not short:
            break
        i = min(short, key=length)
        end = runs[i + 1][0] if i + 1 < len(runs) else duration
        current = mean_vector(runs[i][0], end)
        neighbours = [j for j in (i - 1, i + 1) if 0 <= j < len(runs)]
        target = max(neighbours, key=lambda j: (runs[j][1] == runs[i][1],
                                                _cosine(current, mean_vector(runs[j][0], runs[j + 1][0] if j + 1 < len(runs) else duration))))
        if target < i:
            del runs[i]
        else:
            runs[target][0] = runs[i][0]
            del runs[i]
        merged = [runs[0]]
        for run in runs[1:]:
            if run[1] == merged[-1][1]:
                continue
            merged.append(run)
        runs = merged
    letters: dict[int, str] = {}
    sections = []
    for i, (start, cluster) in enumerate(runs):
        end = runs[i + 1][0] if i + 1 < len(runs) else duration
        label = letters.setdefault(cluster, chr(ord("A") + len(letters)))
        contained = [b for b in blocks if b["start"] < end and b["end"] > start]
        db_values = [v for j, v in enumerate(loudness["curve"]) if start <= j / 10 < end]
        vocal = None if vocals is None else bool(np.mean([_db(_slice(vocals, sr, t, min(t + .1, end))) > -35
                                                         for t in np.arange(start, end, .1)]) >= .3)
        sections.append({"index": i + 1, "label": label, "start": start, "end": end,
                         "first_bar": contained[0]["index"] if contained else None,
                         "last_bar": contained[-1]["index"] if contained else None, "bars": len(contained),
                         "db": round(float(np.mean(db_values)) if db_values else -90, 1), "vocals": vocal,
                         "drums": sum(start <= h["t"] < end for h in hits) >= 2 * max(1, len(contained)),
                         "repeats": [], "hint": None})
    for section in sections:
        section["level"] = _level(section["db"], [s["db"] for s in sections])
        section["repeats"] = [s["index"] for s in sections if s["label"] == section["label"] and s is not section]
    chorus_counts = Counter(s["label"] for s in sections if s["vocals"] and s["level"] in ("loud", "peak"))
    chorus = chorus_counts.most_common(1)[0][0] if chorus_counts else None
    verse = next((s["label"] for s in sections if s["vocals"]), None)
    for i, section in enumerate(sections):
        if section["label"] == chorus:
            section["hint"] = "chorus?"
        elif section["label"] == verse and verse != chorus:
            section["hint"] = "verse?"
        elif i == 0 and section["vocals"] is False:
            section["hint"] = "intro?"
        elif i == len(sections) - 1 and section["vocals"] is False:
            section["hint"] = "outro?"
    return sections


def melody_notes(signal: np.ndarray, sr: int, fmin: float, fmax: float, min_dur: float) -> list[dict]:
    pitches, voiced, probability = librosa.pyin(signal, sr=sr, fmin=fmin, fmax=fmax, frame_length=2048, hop_length=256)
    midi = librosa.hz_to_midi(pitches)
    runs = []
    start = None
    values: list[float] = []
    probabilities: list[float] = []
    for i in range(len(midi) + 1):
        valid = i < len(midi) and voiced[i] and probability[i] >= .5 and np.isfinite(midi[i])
        if start is not None and (not valid or abs(midi[i] - float(np.median(values))) > .6):
            runs.append({"start": start * 256 / sr, "end": min(i * 256 / sr, len(signal) / sr),
                         "midi": int(round(float(np.median(values)))), "confidence": float(np.mean(probabilities))})
            start, values, probabilities = None, [], []
        if valid:
            if start is None:
                start = i
            values.append(float(midi[i]))
            probabilities.append(float(probability[i]))
    merged = []
    for note in runs:
        if merged and note["midi"] == merged[-1]["midi"] and note["start"] - merged[-1]["end"] < .04:
            previous = merged[-1]
            a, b = previous["end"] - previous["start"], note["end"] - note["start"]
            previous["confidence"] = (a * previous["confidence"] + b * note["confidence"]) / (a + b)
            previous["end"] = note["end"]
        else:
            merged.append(note)
    return [{**n, "name": librosa.midi_to_note(n["midi"], unicode=False)} for n in merged if n["end"] - n["start"] >= min_dur]


def estimate_key(chroma_mean: np.ndarray) -> dict:
    chroma_mean = np.asarray(chroma_mean)
    scores = []
    for tonic, name in enumerate(PITCHES):
        for mode, profile in [("major", MAJOR), ("minor", MINOR)]:
            r = float(np.corrcoef(chroma_mean, np.roll(profile, tonic))[0, 1]) if np.std(chroma_mean) > 1e-12 else 0.0
            scores.append((r, name, mode))
    scores.sort(key=lambda x: -x[0])
    best, second = scores[:2]
    return {"key": f"{best[1]} {best[2]}", "tonic": best[1], "mode": best[2], "confidence": best[0],
            "runner_up": f"{second[1]} {second[2]}"}


def beat_chords(chroma_per_beat: np.ndarray, beats: np.ndarray, duration: float) -> list[dict]:
    templates, names = [], []
    for root, name in enumerate(PITCHES):
        for third, suffix in [(4, ""), (3, "m")]:
            template = np.zeros(12)
            template[[(root + n) % 12 for n in (0, third, 7)]] = 1
            templates.append(template / np.sqrt(3))
            names.append(name + suffix)
    spans = []
    for i, beat in enumerate(beats):
        chroma = chroma_per_beat[:, i]
        norm = np.linalg.norm(chroma)
        scores = np.asarray(templates) @ chroma / max(float(norm), 1e-12)
        chord = names[int(np.argmax(scores))] if norm > 1e-8 and max(scores) >= .6 else "N"
        end = float(beats[i + 1]) if i + 1 < len(beats) else duration
        if spans and spans[-1]["chord"] == chord:
            spans[-1]["end"] = end
        else:
            spans.append({"start": float(beat), "end": end, "chord": chord})
    return spans


def _tokens(text: str) -> list[str]:
    text = "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))
    return re.findall(r"[^\W_]+(?:'[^\W_]+)*", text, flags=re.UNICODE)


def filter_hallucinations(segments: list[dict], vocals_mono: np.ndarray, sr: int) -> tuple[list[dict], list[dict]]:
    phrases = {"thank you", "thanks for watching", "thank you for watching", "subtitles by the amara org community",
               "gracias", "gracias por ver el video", "subtitulos realizados por la comunidad de amara org"}
    kept, dropped = [], []
    for segment in segments:
        silent = [_db(_slice(vocals_mono, sr, t, min(t + .1, segment["end"]))) < -45
                  for t in np.arange(segment["start"], segment["end"], .1)]
        text = " ".join(_tokens(segment["text"]))
        reason = "silent vocals" if silent and np.mean(silent) >= .8 else None
        if reason is None and len(segment["text"].split()) <= 6 and text in phrases:
            reason = "known hallucination phrase"
        if reason:
            dropped.append({**segment, "reason": reason})
        else:
            kept.append(segment)
    return kept, dropped


def align_lyrics(lines: list[str], words: list[dict]) -> list[dict]:
    provided, owners = [], []
    for i, line in enumerate(lines):
        tokens = _tokens(line)
        provided.extend(tokens)
        owners.extend([i] * len(tokens))
    heard, timed = [], []
    for word in words:
        for token in _tokens(word["word"]):
            heard.append(token)
            timed.append(word)
    matches: dict[int, list[dict]] = {i: [] for i in range(len(lines))}
    for block in difflib.SequenceMatcher(None, provided, heard, autojunk=False).get_matching_blocks():
        for offset in range(block.size):
            matches[owners[block.a + offset]].append(timed[block.b + offset])
    result = [{"start": matches[i][0]["start"] if matches[i] else None,
               "end": matches[i][-1]["end"] if matches[i] else None, "text": line,
               "aligned": bool(matches[i]), "matched_words": len(matches[i]), "words": len(_tokens(line))}
              for i, line in enumerate(lines)]
    i = 0
    while i < len(result):
        if result[i]["aligned"]:
            i += 1
            continue
        j = i
        while j < len(result) and not result[j]["aligned"]:
            j += 1
        left = result[i - 1]["end"] if i else None
        right = result[j]["start"] if j < len(result) else None
        if left is not None or right is not None:
            total = sum(max(1, r["words"]) for r in result[i:j])
            if left is None:
                left = max(0.0, right - total * .3)
            if right is None:
                right = left + total * .3
            cursor = left
            for row in result[i:j]:
                row["start"] = cursor
                cursor += max(0.0, right - left) * max(1, row["words"]) / total
                row["end"] = cursor
        i = j
    return result


def _normalise_db(values: np.ndarray, low: float, high: float) -> np.ndarray:
    return np.clip((values - low) / max(high - low, 1e-8), 0, 1)


def frame_features(mono: np.ndarray, sr: int, duration: float, fps: int, beats: np.ndarray,
                   bars: list[dict], sections: list[dict], hits: list[dict], stems: dict | None = None) -> dict:
    total = max(1, round(duration * fps))
    times = np.arange(total) / fps
    signals = {"level": mono, **{name: audio.mean(axis=0) if audio.ndim == 2 else audio for name, audio in (stems or {}).items()}}
    levels = {}
    for name, signal in signals.items():
        db = np.array([_db(_slice(signal, sr, t, t + 1 / fps)) for t in times])
        levels[name] = _normalise_db(db, -60, float(np.percentile(db, 99)))
    mel = librosa.feature.melspectrogram(y=mono, sr=sr, n_mels=16, fmin=30, fmax=16000, hop_length=256)
    db = librosa.power_to_db(mel, ref=1.0, top_db=None)
    low, high = np.percentile(db, [5, 99], axis=1)
    mel_scaled = np.clip((db - low[:, None]) / np.maximum(high - low, 1e-8)[:, None], 0, 1)
    mel_times = librosa.frames_to_time(np.arange(db.shape[1]), sr=sr, hop_length=256)
    envelopes = {kind: np.zeros(total) for kind in ("kick", "snare", "hat")}
    for hit in hits:
        if hit["type"] not in envelopes:
            continue
        first = max(0, math.floor(hit["t"] * fps))
        tau = {"kick": .15, "snare": .12, "hat": .06}[hit["type"]]
        # A subframe attack counts at full strength in the frame containing it.
        elapsed = np.maximum(0, times[first:] - hit["t"])
        envelopes[hit["type"]][first:] += hit["strength"] * np.exp(-elapsed / tau)
    beats = np.asarray(beats)
    effective_bars = bars or _blocks(duration)
    frames = []
    for f, t in enumerate(times):
        beat = int(np.searchsorted(beats, t, side="right")) - 1
        phase = float((t - beats[beat]) / (beats[beat + 1] - beats[beat])) if 0 <= beat < len(beats) - 1 else 0.0
        bar = next((b for b in effective_bars if b["start"] <= t < b["end"]), None)
        section = next((s for s in sections if s["start"] <= t < s["end"]), None)
        mask = (mel_times >= t) & (mel_times < t + 1 / fps)
        bands = mel_scaled[:, mask].mean(axis=1) if mask.any() else mel_scaled[:, int(np.argmin(abs(mel_times - t)))]
        frames.append({**{name: float(values[f]) for name, values in levels.items()},
                       **{kind: float(np.clip(values[f], 0, 1)) for kind, values in envelopes.items()},
                       "beat": beat, "beat_phase": phase, "bar": bar["index"] if bar else -1,
                       "bar_phase": (t - bar["start"]) / (bar["end"] - bar["start"]) if bar else 0.0,
                       "section": section["index"] if section else -1, "bands": bands.tolist()})
    return {"schema": 1, "fps": fps, "totalFrames": total, "duration_sec": duration, "stems": bool(stems),
            "fields": list(frames[0]), "frames": frames}


def key_moments(downbeats: list[float], sections: list[dict], loudness: dict, bars: list[dict],
                lyrics: dict | None, vocal_notes: list[dict], duration: float) -> list[dict]:
    moments = []

    def add(t: float, kind: str, detail: str) -> None:
        moments.append({"t": t, "kind": kind, "detail": detail})

    if len(downbeats):
        add(float(downbeats[0]), "first_downbeat", "first downbeat")
    for section in sections:
        add(section["start"], "section_start", section["label"] + (" " + section["hint"] if section.get("hint") else ""))
    for plural, kind in [("rises", "rise"), ("falls", "fall")]:
        for change in loudness.get(plural, []):
            add(change["t"], kind, f"{change['db']:+.1f} dB")
    measures = loudness.get("bars", bars)
    for silence in loudness.get("silences", []):
        add(silence["start"], "silence", f"until {format_time(silence['end'])}")
        if any(abs(b["end"] - silence["start"]) <= .1 and b.get("level") in ("loud", "peak") for b in measures):
            add(silence["start"], "hard_stop", "silence after a loud bar")
    loudest = next((b for b in measures if b["index"] == loudness.get("loudest_bar")), None)
    if loudest:
        add(loudest["start"], "loudest_bar", f"bar {loudest['index']}")
    lines = [line for line in (lyrics or {}).get("lines", []) if line.get("start") is not None and line.get("end") is not None]
    spans = lines or vocal_notes
    if spans:
        add(min(n["start"] for n in spans), "first_vocal", "first vocal")
        add(max(n["end"] for n in spans), "last_vocal", "last vocal")
    add(duration, "end", "song ends")
    unique = {(round(m["t"], 3), m["kind"]): m for m in moments}
    return sorted(unique.values(), key=lambda m: (m["t"], m["kind"]))


def format_time(value: float | None) -> str:
    if value is None:
        return "?:??.?"
    tenths = int(math.floor(value * 10 + .5 + 1e-9))
    return f"{tenths // 600}:{(tenths % 600) / 10:04.1f}"


def _common_pattern(section: dict, bars: list[dict], kind: str) -> str:
    patterns = [b.get("patterns", {}).get(kind, "") for b in bars if section["start"] <= b["start"] < section["end"]]
    return Counter(patterns).most_common(1)[0][0] if patterns else ""


def render_readme(analysis: dict) -> str:
    source, tempo, notes = analysis["source"], analysis["tempo"], analysis["notes"]
    key = notes["key"]
    bpm = f"{tempo['bpm']:.1f}" if tempo.get("bpm") is not None else "unknown"
    lufs = f"{source['integrated_lufs']:.1f}" if source.get("integrated_lufs") is not None else "unknown"
    rows = [f"# Song: {source['file']}", "",
            f"{format_time(source['duration_sec'])} · {bpm} BPM · {tempo['beats_per_bar']}/4 · {key['key']} ({key['confidence']:.2f}) · {lufs} LUFS", "",
            "_Made by listen.py 0.1.0 from the audio data. Every line is a measurement or an estimate; estimates are marked._", "",
            "## What the song is about", "",
            "<!-- Write 3–5 sentences from the lyrics below. Say so if they look unreliable. Do not claim to have heard the song. -->", "",
            "## Structure", "", "| # | Time | Bars | Label | Level | Vocals | Drums | Kick / snare (most common bar) |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    bars = analysis.get("bars", [])
    for section in analysis["sections"]:
        label = section["label"] + (f" ({section['hint']})" if section.get("hint") else "")
        vocal = "unknown" if section.get("vocals") is None else "yes" if section["vocals"] else "no"
        patterns = " / ".join(f"`{_common_pattern(section, bars, kind)}`" for kind in ("kick", "snare"))
        rows.append(f"| {section['index']} | {format_time(section['start'])}–{format_time(section['end'])} | {section.get('first_bar')}–{section.get('last_bar')} | {label} | {section['level']} | {vocal} | {'yes' if section.get('drums') else 'no'} | {patterns} |")
    rows += ["", "## Loud and quiet", ""]
    loudness = analysis["loudness"]
    loudest = next((b for b in loudness.get("bars", []) if b["index"] == loudness.get("loudest_bar")), None)
    rows.append(f"- Loudest bar: {loudness.get('loudest_bar')}" + (f" at {format_time(loudest['start'])} ({loudest['db']:.1f} dBFS)" if loudest else ""))
    quiet = loudness.get("quietest_span")
    if quiet:
        rows.append(f"- Quietest stretch: {format_time(quiet['start'])}–{format_time(quiet['end'])}, {quiet['db']:.1f} dBFS")
    for name in ("rises", "falls"):
        for change in loudness.get(name, []):
            rows.append(f"- {name.title()}: {format_time(change['t'])}, {change['db']:+.1f} dB")
    for silence in loudness.get("silences", []):
        rows.append(f"- Silence: {format_time(silence['start'])}–{format_time(silence['end'])}")
    for moment in analysis.get("key_moments", []):
        if moment["kind"] == "hard_stop":
            rows.append(f"- Hard stop: {format_time(moment['t'])}")
    cv = tempo.get("stability_cv", 0)
    stability = "steady" if cv <= .08 else f"varies (cv {cv:.2f})"
    rows += ["", "## Beat and drums", "", f"{bpm} BPM; {stability}; meter {tempo['beats_per_bar']}/4.",
             f"First downbeat: {format_time(analysis['downbeats'][0]) if analysis.get('downbeats') else 'unknown'}.",
             "Hits: " + ", ".join(f"{kind} {count}" for kind, count in analysis["drums"]["counts"].items()) + "."]
    for section in analysis["sections"]:
        rows.append(f"- Section {section['index']}: kick `{_common_pattern(section, bars, 'kick')}`, snare `{_common_pattern(section, bars, 'snare')}`")
    rows += ["", "## Notes and harmony", "", f"Key estimate: {key['key']}, confidence {key['confidence']:.2f}; runner-up {key['runner_up']}.",
             f"Vocal range: {'–'.join(notes['vocal_range']) if notes.get('vocal_range') else 'unknown'}.",
             f"Bass range: {'–'.join(notes['bass_range']) if notes.get('bass_range') else 'unknown'}."]
    for section in analysis["sections"]:
        seconds: Counter = Counter()
        for chord in notes.get("chords", []):
            overlap = min(chord["end"], section["end"]) - max(chord["start"], section["start"])
            if overlap > 0 and chord["chord"] != "N":
                seconds[chord["chord"]] += overlap
        total = sum(seconds.values())
        top = ", ".join(f"{name} {share / total:.0%}" for name, share in seconds.most_common(3)) if total else "unknown"
        rows.append(f"- Section {section['index']} ({section['label']}): {top}")
    rows += ["", "## Lyrics", ""]
    lyrics = analysis.get("lyrics")
    if not lyrics or not lyrics.get("lines"):
        rows.append("_No lyrics_")
    else:
        rows.append(f"Source: {lyrics['source']}; {lyrics['model']}; language {lyrics['language']} ({lyrics['language_probability']:.2f}); median word confidence {lyrics['confidence']:.2f}. `(?)` marks a word Whisper was unsure of.")
        rows.append("")
        for line in lyrics["lines"]:
            text = line["text"]
            if lyrics["source"] == "whisper" and line.get("words"):
                text = " ".join(w["word"].strip() + ("(?)" if w["p"] < .4 else "") for w in line["words"])
            text = text.replace("|", "\\|")
            suffix = " (time estimated)" if line.get("aligned") is False else ""
            rows.append(f"- `{format_time(line['start'])}` {text}{suffix}")
    rows += ["", "## Key moments", ""]
    for moment in analysis.get("key_moments", []):
        rows.append(f"- `{format_time(moment['t'])}` {moment['kind']} — {moment['detail']}")
    fields = ["level"] + (["drums", "bass", "other", "vocals"] if analysis["settings"]["stems"] else [])
    fields += ["kick", "snare", "hat", "beat", "beat_phase", "bar", "bar_phase", "section", "bands"]
    rows += ["", "## Files", "", "- `analysis.json`: song measurements and estimates.",
             "- `features.json`: " + ", ".join(fields) + ".",
             "- `stems/`: drums, bass, other, vocals." if analysis["settings"]["stems"] else "- `stems/`: omitted (--no-stems).",
             "", "## Uncertain", ""]
    rows += ["- " + warning for warning in analysis.get("warnings", [])]
    rows += ["- Section labels ending in `?` are guesses.",
             "- Drum types are a band-energy heuristic on the separated drum stem: a snare or hat that lands with a kick "
             "counts as the kick. For motion, `drums` (the stem's level) and `kick` are the reliable signals.",
             "- Chords are triads estimated per beat; read the shares, not single beats."]
    return "\n".join(rows) + "\n"


def _rounded(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {k: _rounded(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_rounded(v, key) for v in value]
    if isinstance(value, (float, np.floating)):
        if not math.isfinite(value):
            return None
        rounded = round(float(value), 1 if key in ("db", "integrated_lufs", "true_peak_dbfs", "curve", "bpm") else 3)
        return min(rounded, .999) if key in ("beat_phase", "bar_phase") else rounded
    if isinstance(value, np.integer):
        return int(value)
    return value


def _note_range(notes: list[dict]) -> list[str] | None:
    return [min(notes, key=lambda n: n["midi"])["name"], max(notes, key=lambda n: n["midi"])["name"]] if notes else None


def analyze(song_path: str | Path, options: argparse.Namespace) -> tuple[dict, dict, dict, dict]:
    timings = {}

    def stage(name: str, function: Any, *args: Any) -> Any:
        start = time.monotonic()
        result = function(*args)
        timings[name] = round(time.monotonic() - start, 3)
        print(f"[listen] {name} {timings[name]:.1f} s", file=sys.stderr)
        return result

    source = stage("probe", probe_source, song_path)
    stereo, sr = stage("decode", decode_audio, song_path)
    mono = stereo.mean(axis=0)
    duration = len(mono) / sr
    source["duration_sec"] = duration
    warnings = []
    for field in ("integrated_lufs", "true_peak_dbfs"):
        if source[field] is None or not math.isfinite(source[field]):
            warnings.append(f"could not parse {field}")
    threads = int(os.environ.get("LISTEN_THREADS", "8"))
    stems = {} if options.no_stems else stage("stems", separate_stems, stereo, sr, options.device, threads)
    if not stems:
        warnings.append("missing stems (--no-stems): using the mix; melody and bass notes are unavailable")
    beats, downbeats = stage("beats", track_beats, mono, sr, options.device)
    grid = build_grid(beats, downbeats, duration)
    beats, downbeats = np.array(grid["beats"]), np.array(grid["downbeats"])
    warnings.extend(grid["warnings"])
    drum_signal = stems["drums"].mean(axis=0) if stems else librosa.effects.percussive(mono)
    harmonic = sum(stems[name].mean(axis=0) for name in ("bass", "other", "vocals")) if stems else librosa.effects.harmonic(mono)
    chord_signal = (stems["other"] + stems["bass"]).mean(axis=0) if stems else harmonic
    hits = stage("drums", detect_drum_hits, librosa.resample(drum_signal, orig_sr=sr, target_sr=22050, res_type="soxr_hq"), 22050, beats)
    bars = bar_patterns(hits, grid["bars"], grid["beats_per_bar"])
    loudness = stage("loudness", loudness_profile, mono, sr, bars, duration)
    for bar, measured in zip(bars, loudness["bars"]):
        bar.update({k: measured[k] for k in ("db", "level")})
    vocals = stems["vocals"].mean(axis=0) if stems else None
    sections = stage("sections", segment_sections, harmonic, mono, sr, beats, downbeats, bars,
                     grid["beats_per_bar"], duration, loudness, hits, vocals)
    vocal_notes, bass_notes = [], []
    if stems:
        for name, fmin, fmax, minimum in [("vocals", "C2", "C6", .1), ("bass", "E1", "C4", .12)]:
            audio = librosa.resample(stems[name].mean(axis=0), orig_sr=sr, target_sr=22050, res_type="soxr_hq")
            notes = stage(name + " notes", melody_notes, audio, 22050, librosa.note_to_hz(fmin), librosa.note_to_hz(fmax), minimum)
            if name == "vocals":
                vocal_notes = notes
            else:
                bass_notes = notes
    chroma = librosa.feature.chroma_cqt(y=chord_signal, sr=sr)
    key = estimate_key(chroma.mean(axis=1))
    chord_beats = beats if len(beats) >= 8 else np.arange(0, duration, 2)
    chords = beat_chords(_sync_features(chroma, chord_beats, sr), chord_beats, duration)
    for bar in bars:
        counts: Counter = Counter()
        for chord in chords:
            counts[chord["chord"]] += sum(bar["start"] <= beat < bar["end"] and chord["start"] <= beat < chord["end"]
                                           for beat in chord_beats)
        bar["chord"] = counts.most_common(1)[0][0] if counts else "N"
    lyrics = None
    if not options.no_lyrics:
        voice = vocals if vocals is not None else mono
        audio16k = librosa.resample(voice, orig_sr=sr, target_sr=16000, res_type="soxr_hq").astype(np.float32)
        segments, info = stage("lyrics", transcribe_vocals, audio16k, options.language, options.whisper_model, options.device, threads)
        kept, dropped = filter_hallucinations(segments, voice, sr)
        lines = []
        for segment in kept:
            words = [{"start": w["start"], "end": w["end"], "word": w["word"], "p": w["probability"]} for w in segment["words"]]
            lines.append({"start": segment["start"], "end": segment["end"], "text": segment["text"],
                          "mean_p": float(np.mean([w["p"] for w in words])) if words else 0.0, "words": words})
        words = [w for line in lines for w in line["words"]]
        confidence = float(np.median([w["p"] for w in words])) if words else 0.0
        lyrics = {"source": "whisper", "model": options.whisper_model, **info, "confidence": confidence,
                  "lines": lines, "dropped": dropped}
        if confidence < .6:
            warnings.append("lyrics transcription is unreliable: ask the user for the lyrics text and rerun with --lyrics")
        if options.lyrics:
            provided = [line for line in Path(options.lyrics).read_text(encoding="utf-8").splitlines() if line.strip()]
            lyrics.update(source="provided+aligned", transcript_lines=lines, lines=align_lyrics(provided, words))
    moments = key_moments(grid["downbeats"], sections, loudness, bars, lyrics, vocal_notes, duration)
    features = stage("frames", frame_features, mono, sr, duration, options.fps, beats, bars, sections, hits, stems)
    analysis = {"schema": 1, "listener_version": VERSION, "source": source,
                "settings": {"fps": options.fps, "stems": not options.no_stems,
                             "lyrics": lyrics["source"] if lyrics else "off", "whisper_model": options.whisper_model,
                             "language": options.language, "device": options.device},
                "tempo": {k: grid[k] for k in ("bpm", "beats_per_bar", "stability_cv")},
                "beats": grid["beats"], "downbeats": grid["downbeats"], "bars": bars, "sections": sections,
                "loudness": loudness, "drums": {"hits": hits, "counts": {kind: sum(h["type"] == kind for h in hits) for kind in ("kick", "snare", "hat", "perc")}},
                "notes": {"key": key, "vocal_melody": vocal_notes, "bass": bass_notes, "vocal_range": _note_range(vocal_notes),
                          "bass_range": _note_range(bass_notes), "chords": chords}, "lyrics": lyrics, "key_moments": moments, "warnings": warnings}
    analysis["tempo"].update(beat_count=len(beats), bar_count=len(bars))
    versions = {}
    for package in ("torch", "torchaudio", "demucs", "beat-this", "librosa", "faster-whisper", "numpy", "scipy", "soundfile"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    torch = sys.modules.get("torch")
    device = options.device if options.device != "auto" else ("cuda" if torch is not None and torch.cuda.is_available() else "cpu")
    return _rounded(analysis), _rounded(features), stems, {"timings": timings, "versions": versions, "device": device, "threads": threads}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("song")
    parser.add_argument("-o", dest="outdir")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--language")
    parser.add_argument("--lyrics")
    parser.add_argument("--whisper-model", default="large-v3-turbo")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--no-stems", action="store_true")
    parser.add_argument("--no-lyrics", action="store_true")
    parser.add_argument("--force", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code)
    if not 1 <= args.fps <= 120 or (args.lyrics and args.no_lyrics):
        print("[listen] --fps must be 1–120; --lyrics cannot be combined with --no-lyrics", file=sys.stderr)
        return 2
    outdir = Path(args.outdir) if args.outdir else Path(args.song).parent
    if not args.force and any((outdir / name).exists() for name in ("README.md", "analysis.json", "features.json")):
        print("[listen] output already exists; use --force to overwrite", file=sys.stderr)
        return 2
    names = ["README.md", "analysis.json", "features.json", "listen-run.json"]
    if not args.no_stems:
        names += [f"stems/{name}.wav" for name in ("drums", "bass", "other", "vocals")]
    inputs = {Path(args.song).resolve()}
    if args.lyrics:
        inputs.add(Path(args.lyrics).resolve())
    for name in names:
        target = outdir / name
        if target.resolve() in inputs or not target.resolve().is_relative_to(outdir.resolve()):
            print("[listen] output would overwrite an input or write outside OUTDIR", file=sys.stderr)
            return 2
    try:
        analysis, features, stems, run_info = analyze(args.song, args)
        outdir.mkdir(parents=True, exist_ok=True)
        written = []
        for name, data in (("analysis.json", analysis), ("features.json", features), ("listen-run.json", run_info)):
            path = outdir / name
            path.write_text(json.dumps(data, sort_keys=True, indent=1, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
            written.append(path)
        path = outdir / "README.md"
        path.write_text(render_readme(analysis), encoding="utf-8")
        written.insert(0, path)
        if stems:
            (outdir / "stems").mkdir(exist_ok=True)
            for name in ("drums", "bass", "other", "vocals"):
                path = outdir / "stems" / (name + ".wav")
                sf.write(path, np.clip(stems[name].T, -1, 1), 44100, subtype="PCM_16")
                written.append(path)
        for path in written:
            print(path)
        bpm = analysis["tempo"]["bpm"]
        print(f"{analysis['source']['duration_sec']:.1f} s, {bpm if bpm is not None else 'unknown'} BPM, {analysis['tempo']['beats_per_bar']}/4, {analysis['notes']['key']['key']}, {len(analysis['sections'])} sections, {len(analysis['warnings'])} warnings")
        return 0
    except Exception as error:
        print(f"[listen] {' '.join(str(error).splitlines())}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
