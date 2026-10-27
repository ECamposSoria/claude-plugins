# video-studio

One router over the video tools on this VM. It classifies a request and drives the right **leg**; it is
instructions plus a few scripts, not an engine.

## Legs

| Leg | Tool | Use when |
|-----|------|----------|
| animation-remotion | the `promo-video` skill | Per-frame React motion, reused React components, the guided promo |
| animation-hyperframes | the `hyperframes:*` skills, `npx hyperframes` | Pasted web content, GSAP/Lottie/Three.js timelines, stories from photos, captions-first social cuts |
| footage-edit | `faster-whisper` (venv) + `ffmpeg` | A real recording to cut, trim or tighten |
| ai-footage | clips from the `nano-banana-multi:image-gen` skill (fal), repaired and assembled here | Footage nobody filmed; repairing pops, rewritten lettering, invented clothing marks |
| music-video | the song listener (`listen.py`, Docker on the VM or the laptop GPU), then Hyperframes, AI clips or footage cut on its beat grid | A song is the spine: music videos, visualizers, lyric videos, beat-cut montages |
| audio (shared) | VoiceStudio on the laptop GPU via the always-on tunnel (default), ElevenLabs, VoiceStudio on the VM CPU, Hyperframes `media-use`, ffmpeg `loudnorm` | Voiceover, music, captions, −14 LUFS |

**Hybrid** = a base (footage or AI clips) + animation overlays, joined with `scripts/composite.sh`.

Routing: `skills/video-studio/router.md`. Playbooks: `skills/video-studio/legs/`. Matching a reference video
closely: `skills/video-studio/recreate.md`. Setup state: `skills/video-studio/setup/install.md`.

## Scripts (`skills/video-studio/scripts/`)

- `transcribe.py`: faster-whisper word timestamps (run with the venv's Python).
- `cut_from_transcript.py`: one-pass frame-accurate cut from an edit-decision list.
- `composite.sh`: `overlay`, `concat`, `mixaudio`.
- `listen.py`: song → stems, beats, bars, drum hits, loudness, sections, notes, chords, timed lyrics,
  per-frame features and a README brief. Runs in `setup/listener/` (Docker). Tests: `test_listen.py`, in that image.
- `listen_remote.sh`: the same on the laptop's RTX 4070 over ssh; exit 3 = use the CPU image.
- `sync_check.py`: a music video's audio is the song, unshifted and full length; picture accents against the
  beats. Tests: `test_sync_check.py`, run in a container.
- `qa_render.py`: pre-delivery check (probe, black, freeze, silence, loudness, one-frame pops, contact sheet with
  a timestamp on each tile; `--compare REF` puts the reference's frame from the same moment beside each tile).
  Tests: `test_qa_render.py`, run in a container.

## Policies

- **Non-blocking.** Long renders, transcriptions and generations run in the background or go to the user.
- **Processing is local.** Generation and voice may call paid or cloud services (fal and Gemini through
  `nano-banana-multi:image-gen`, ElevenLabs, HeyGen's free path), always quoted first.
- **GPU when a job needs it.** The VM has no GPU; the laptop's RTX 4070 runs VoiceStudio and the listener
  (`listen_remote.sh`) through the always-on tunnel. Check it is free first (`nvidia-smi`, `docker ps` in its
  WSL; another session may hold ~6 GB) and ask the owner if it is not. CPU on the VM is the fallback.
- **QA before delivery.** Every render passes `qa_render.py` (music videos also `sync_check.py`); finals go to
  `/mnt/hgfs/vm-share/videos/<project>/`.

## Considered and not adopted (2026-10-24)

OpenMontage, `/brag`, ManimGX and the Hainrixz motion/editor agents. Reasons in the shared media memory
`~/projects/image-video-generation/memory/reference_reel_tools_eval_2026-10.md`. On 2026-10-27: DaVinci Resolve
driven by computer use, Diffusion Studio, Clicky, MagicPath and Mobbin; reasons at the end of `router.md`.
