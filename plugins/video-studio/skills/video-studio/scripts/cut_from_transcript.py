#!/usr/bin/env python3
"""Cut a video down to a set of keep-spans (an edit-decision list) with ffmpeg.

The transcript (from transcribe.py) is read by Claude, who writes an EDL of the
spans to KEEP. This script does the ffmpeg work — the LLM never touches ffmpeg math.

EDL JSON shape (either form accepted):

    {"source": "input.mp4", "keep": [{"start": 0.0, "end": 12.3, "reason": "intro"}, ...]}
    # or a bare list:
    [{"start": 0.0, "end": 12.3}, {"start": 30.0, "end": 45.0}]

Approach: a single filter_complex pass — trim+concat all spans in one re-encode.
Frame-accurate (no keyframe/stream-copy artifacts), no temp segment files, and the
output has uniform codec/fps/sample-rate so it concatenates cleanly downstream.

Usage:
    python3 cut_from_transcript.py --edl edl.json --output basecut.mp4 [--source in.mp4]
This re-encodes video → a HEAVY op. Run in the background or hand it to the user.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile


def probe(source: str):
    """Return (fps: float, has_audio: bool, duration: float) via ffprobe."""
    def _run(args):
        return subprocess.run(["ffprobe", "-v", "error", *args, source],
                              capture_output=True, text=True).stdout.strip()

    rate = _run(["-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                 "-of", "default=nk=1:nw=1"])
    fps = 30.0
    if rate and "/" in rate:
        num, den = rate.split("/")
        fps = float(num) / float(den) if float(den) else float(num)
    elif rate:
        fps = float(rate)

    acodec = _run(["-select_streams", "a:0", "-show_entries", "stream=codec_type",
                   "-of", "default=nk=1:nw=1"])
    has_audio = acodec == "audio"

    dur = _run(["-show_entries", "format=duration", "-of", "default=nk=1:nw=1"])
    duration = float(dur) if dur else 0.0
    return fps, has_audio, duration


def load_edl(edl_path: str):
    with open(edl_path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("source"), data.get("keep", [])
    return None, data


def main() -> int:
    ap = argparse.ArgumentParser(description="Cut a video to an EDL of keep-spans (single ffmpeg pass).")
    ap.add_argument("--edl", required=True, help="Path to the EDL JSON.")
    ap.add_argument("--output", required=True, help="Output video path (e.g. basecut.mp4).")
    ap.add_argument("--source", default=None,
                    help="Source video. Overrides the EDL's 'source' field if given.")
    ap.add_argument("--crf", type=int, default=18, help="x264 CRF quality (default 18).")
    ap.add_argument("--preset", default="veryfast", help="x264 preset (default veryfast).")
    ap.add_argument("--dry-run", action="store_true", help="Print the ffmpeg command, don't run it.")
    args = ap.parse_args()

    edl_source, keep = load_edl(args.edl)
    source = args.source or edl_source
    if not source:
        print("error: no source given (pass --source or set 'source' in the EDL).", file=sys.stderr)
        return 2
    if not os.path.isfile(source):
        print(f"error: source not found: {source}", file=sys.stderr)
        return 2
    if not keep:
        print("error: EDL has no keep-spans.", file=sys.stderr)
        return 2

    fps, has_audio, duration = probe(source)

    # sort, validate, clamp
    spans = sorted(({"start": float(s["start"]), "end": float(s["end"])} for s in keep),
                   key=lambda s: s["start"])
    clean = []
    prev_end = -1.0
    for s in spans:
        st, en = max(0.0, s["start"]), s["end"]
        if duration:
            en = min(en, duration)
        if en - st < 0.02:
            print(f"warn: skipping empty/tiny span {st:.3f}-{en:.3f}", file=sys.stderr)
            continue
        if st < prev_end - 0.001:
            print(f"warn: span {st:.3f}-{en:.3f} overlaps previous (ends {prev_end:.3f}); "
                  "trimming start.", file=sys.stderr)
            st = prev_end
            if en - st < 0.02:
                continue
        clean.append((st, en))
        prev_end = en
    if not clean:
        print("error: no valid spans after validation.", file=sys.stderr)
        return 2

    # build filter graph
    parts, concat_inputs = [], []
    for i, (st, en) in enumerate(clean):
        parts.append(f"[0:v]trim=start={st:.3f}:end={en:.3f},setpts=PTS-STARTPTS[v{i}];")
        if has_audio:
            parts.append(f"[0:a]atrim=start={st:.3f}:end={en:.3f},asetpts=PTS-STARTPTS[a{i}];")
        concat_inputs.append(f"[v{i}]" + (f"[a{i}]" if has_audio else ""))
    n = len(clean)
    if has_audio:
        parts.append("".join(concat_inputs) + f"concat=n={n}:v=1:a=1[outv][outa]")
    else:
        parts.append("".join(concat_inputs) + f"concat=n={n}:v=1:a=0[outv]")
    filtergraph = "\n".join(parts)

    kept = sum(en - st for st, en in clean)
    print(f"[cut] {source}: keeping {n} span(s), {kept:.2f}s of {duration:.2f}s, fps={fps:.3f}, "
          f"audio={has_audio}", file=sys.stderr)

    with tempfile.NamedTemporaryFile("w", suffix=".fffilter", delete=False, encoding="utf-8") as tf:
        tf.write(filtergraph)
        filter_path = tf.name

    cmd = ["ffmpeg", "-y", "-i", source, "-filter_complex_script", filter_path,
           "-map", "[outv]"]
    if has_audio:
        cmd += ["-map", "[outa]", "-c:a", "aac", "-ar", "48000", "-ac", "2"]
    cmd += ["-c:v", "libx264", "-crf", str(args.crf), "-preset", args.preset,
            "-r", f"{fps:.5f}", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            args.output]

    if args.dry_run:
        print("filtergraph:\n" + filtergraph, file=sys.stderr)
        print("command:\n" + " ".join(cmd), file=sys.stderr)
        os.unlink(filter_path)
        return 0

    try:
        proc = subprocess.run(cmd)
    finally:
        os.unlink(filter_path)
    if proc.returncode != 0:
        print("error: ffmpeg failed.", file=sys.stderr)
        return proc.returncode
    print(f"[cut] wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
