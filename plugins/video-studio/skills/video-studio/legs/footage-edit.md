# Leg: footage-edit (self-hosted)

Edit a **real recorded clip** — tighten it, cut rambling, remove filler words, drop a section — by editing its transcript, not by scrubbing a timeline. Whisper produces word-level timestamps; you turn intent into a keep-list; ffmpeg does the cutting.

Everything runs on the VM. No SaaS.

## Pipeline

```
input.mp4 ─▶ transcribe.py ─▶ transcript.json ─▶ (you build) edl.json ─▶ cut_from_transcript.py ─▶ basecut.mp4
```

## Step 1 — Transcribe

Check the venv exists (`~/.venvs/video-studio/bin/python`); if not, follow [../setup/install.md](../setup/install.md) (propose to the user). Then:

```bash
~/.venvs/video-studio/bin/python "$SKILL/scripts/transcribe.py" input.mp4 --model small
```

This is **heavy on CPU** — run with `run_in_background`, or hand the command to the user. It writes `input.transcript.json` (segments + word timestamps + full text). Escalate `--model medium|large-v3` if the transcript is inaccurate.

## Step 2 — Read the transcript, build the EDL

Read `input.transcript.json`. Apply the user's intent to decide which spans to **keep**:

- **"Remove filler words"** → drop words like *um, uh, like, you know, so…* using their word-level `start`/`end`. Keep spans are the gaps between removed words. Leave ~40–80 ms of padding around each cut so speech doesn't sound clipped.
- **"Cut the rambling intro / this section"** → find the matching sentences in the text, drop that `start`→`end` range, keep the rest.
- **"Tighten it / make it punchy"** → drop long silences (VAD already trimmed word timings), false starts, and repeated takes ("let me start over").
- **"Keep only the part about X"** → keep only the segment range covering X.

Write `edl.json` (list of **keep**-spans, in order):

```json
{
  "source": "input.mp4",
  "keep": [
    {"start": 0.00,  "end": 8.40,  "reason": "hook"},
    {"start": 12.10, "end": 45.30, "reason": "main point (dropped the tangent at 8.4–12.1)"}
  ]
}
```

Rules for a clean cut:
- Spans in chronological order, non-overlapping (the script sorts and warns, but do it right).
- Prefer cutting on **word boundaries** (use word `end` of the last kept word and `start` of the next) so you don't clip syllables.
- Show the user the plan (what you're dropping and why) before rendering when the edit is substantial.

## Step 3 — Cut

```bash
python3 "$SKILL/scripts/cut_from_transcript.py" --edl edl.json --output basecut.mp4
```

(Plain `python3` is fine — this script only needs ffmpeg, not the venv.) It does one frame-accurate filter_complex pass (trim+concat, re-encode x264/aac), so `basecut.mp4` has uniform fps/sample-rate and concatenates cleanly in the hybrid leg. Also heavy → background or hand off. Use `--dry-run` to inspect the filtergraph first.

## Step 4 — Verify

```bash
ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 basecut.mp4
```

Kept duration should equal the sum of your keep-spans (±0.2s). Spot-check the audio doesn't clip mid-word. Then deliver for review (copy to `/mnt/hgfs/vm-share/` or serve on `192.168.171.128`).

## Notes

- **No audio track** (silent screen recording): transcription won't help — ask the user for cut points by timestamp/description, write the EDL directly. `cut_from_transcript.py` handles video-only sources.
- **Subtitles**: the transcript is already a subtitle source. Burned-in captions, word-by-word reel captions and the font trap are in [audio.md](audio.md).
- **Check before delivery**: `qa_render.py basecut.mp4 --mode edit --expect-audio` (SKILL.md Step 3).
- **Filler-word removal makes many small cuts** — that's expected; the single-pass concat handles dozens of spans fine.
