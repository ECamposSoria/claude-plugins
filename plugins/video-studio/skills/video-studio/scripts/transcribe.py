#!/usr/bin/env python3
"""Transcribe a media file to word-level JSON using faster-whisper (CPU-friendly).

Output JSON shape (consumed by the footage-edit leg to build an edit-decision list):

    {
      "media": "input.mp4",
      "model": "small",
      "language": "en",
      "duration": 123.4,
      "text": "full transcript ...",
      "segments": [
        {"id": 0, "start": 0.0, "end": 3.2, "text": "...",
         "words": [{"start": 0.0, "end": 0.3, "word": "Hello", "prob": 0.98}, ...]}
      ]
    }

Run inside the video-studio venv:  ~/.venvs/video-studio/bin/python transcribe.py <media>
This is a HEAVY op on CPU — run it in the background or hand it to the user.
"""
import argparse
import json
import os
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description="Transcribe media to word-level JSON (faster-whisper).")
    ap.add_argument("media", help="Path to the audio/video file to transcribe.")
    ap.add_argument("--model", default="small",
                    help="Whisper model: tiny|base|small|medium|large-v3 (default: small).")
    ap.add_argument("--output", default=None,
                    help="Output JSON path (default: <media-stem>.transcript.json next to the media).")
    ap.add_argument("--language", default=None,
                    help="Force a language code (e.g. en, es). Default: auto-detect.")
    ap.add_argument("--device", default="cpu", help="cpu or cuda (default: cpu).")
    ap.add_argument("--compute-type", default="int8",
                    help="int8|int8_float16|float16|float32 (default: int8 for CPU).")
    args = ap.parse_args()

    if not os.path.isfile(args.media):
        print(f"error: media not found: {args.media}", file=sys.stderr)
        return 2

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("error: faster-whisper not installed. See setup/install.md "
              "(python3 -m venv ~/.venvs/video-studio && pip install faster-whisper).",
              file=sys.stderr)
        return 3

    out_path = args.output or f"{os.path.splitext(args.media)[0]}.transcript.json"

    print(f"[transcribe] loading model '{args.model}' ({args.device}/{args.compute_type})...",
          file=sys.stderr)
    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)

    print(f"[transcribe] transcribing {args.media} ...", file=sys.stderr)
    segments_iter, info = model.transcribe(
        args.media,
        language=args.language,
        word_timestamps=True,
        vad_filter=True,  # drop long silences → tighter word timings
    )

    segments = []
    full_text_parts = []
    for seg in segments_iter:
        words = []
        for w in (seg.words or []):
            words.append({
                "start": round(w.start, 3),
                "end": round(w.end, 3),
                "word": w.word.strip(),
                "prob": round(w.probability, 3),
            })
        seg_text = seg.text.strip()
        full_text_parts.append(seg_text)
        segments.append({
            "id": seg.id,
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": seg_text,
            "words": words,
        })
        # progress to stderr so a background run shows life
        print(f"  [{seg.start:7.2f} → {seg.end:7.2f}] {seg_text}", file=sys.stderr)

    result = {
        "media": os.path.abspath(args.media),
        "model": args.model,
        "language": info.language,
        "language_probability": round(info.language_probability, 3),
        "duration": round(info.duration, 3),
        "text": " ".join(full_text_parts).strip(),
        "segments": segments,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[transcribe] wrote {out_path} "
          f"({len(segments)} segments, {result['duration']}s, lang={info.language})",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
