# video-studio

One router over the video tools on this VM. It classifies a request and drives the right **leg**; it is
instructions plus three small scripts, not an engine.

## Legs

| Leg | Tool | Use when |
|-----|------|----------|
| animation-remotion | the `promo-video` skill | Per-frame React motion, reused React components, the guided promo |
| animation-hyperframes | the `hyperframes:*` skills, `npx hyperframes` | Pasted web content, GSAP/Lottie/Three.js timelines, stories from photos, captions-first social cuts |
| footage-edit | `faster-whisper` (venv) + `ffmpeg` | A real recording to cut, trim or tighten |
| ai-footage | clips from the `nano-banana-multi:image-gen` skill (fal), repaired and assembled here | Footage nobody filmed; repairing pops, rewritten lettering, invented clothing marks |
| audio (shared) | ElevenLabs, Hyperframes `media-use`, ffmpeg `loudnorm` | Voiceover, music, captions, −14 LUFS |

**Hybrid** = a base (footage or AI clips) + animation overlays, joined with `scripts/composite.sh`.

Routing: `skills/video-studio/router.md`. Playbooks: `skills/video-studio/legs/`. Setup state:
`skills/video-studio/setup/install.md`.

## Scripts (`skills/video-studio/scripts/`)

- `transcribe.py`: faster-whisper word timestamps (run with the venv's Python).
- `cut_from_transcript.py`: one-pass frame-accurate cut from an edit-decision list.
- `composite.sh`: `overlay`, `concat`, `mixaudio`.
- `qa_render.py`: pre-delivery check (probe, black, freeze, silence, loudness, one-frame pops, contact sheet).
  Tests: `test_qa_render.py`, run in a container.

## Policies

- **Non-blocking.** Long renders, transcriptions and generations run in the background or go to the user.
- **Processing is local.** Generation and voice may call paid or cloud services (fal and Gemini through
  `nano-banana-multi:image-gen`, ElevenLabs, HeyGen's free path), always quoted first.
- **QA before delivery.** Every render passes `qa_render.py`; finals go to `/mnt/hgfs/vm-share/videos/<project>/`.

## Considered and not adopted (2026-10-24)

OpenMontage, `/brag`, ManimGX and the Hainrixz motion/editor agents. Reasons in project memory
`image-video-generation/reference_reel_tools_eval_2026-10.md`.
