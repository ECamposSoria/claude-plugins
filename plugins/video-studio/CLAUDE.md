# video-studio — Unified Video Skill

One router over the video tools you already have. It classifies a request and drives the right **leg** — it is instructions, not an engine. Nothing leaves the VM.

## The three legs

| Leg | Tool | Use when |
|-----|------|----------|
| **Animation / Remotion** | delegates to the `promo-video` skill | Motion authored as per-frame React (`useCurrentFrame`, `interpolate`, `spring`), or you reuse React components. |
| **Animation / Hyperframes** | `npx hyperframes` (Node 22+) | You paste existing web content (landing page, CodePen, HTML), or motion is a library-clock timeline (GSAP, Anime.js, Lottie, Three.js). |
| **Footage edit** | `faster-whisper` (venv) + `ffmpeg` | You have a real recorded clip to cut/trim/tighten (talking-head, screen recording, demo). |

**Hybrid** = footage leg produces a base cut, an animation leg produces overlays/intro, then `composite.sh` layers and muxes them.

Routing logic lives in `skills/video-studio/router.md`. Leg playbooks live in `skills/video-studio/legs/`.

## Environment (verified on this VM)

- ffmpeg 6.1.1 (libx264 + aac), ffprobe, node v22.22.1, npm/npx, python 3.12, git, chromium — all present.
- **No system `pip3`** → Python installs go into a venv at `~/.venvs/video-studio` (see `skills/video-studio/setup/install.md`).
- Hyperframes is fetched on demand via `npx hyperframes` (it may download `chrome-headless-shell` into its own cache for deterministic renders; falls back to screenshot mode on system chromium).

## Non-blocking policy (VM rule)

Transcription and video renders are long. **Never run them blocking in the foreground.** Either run with `run_in_background`, or print the exact command and ask the user to run it and paste the output. Short ops — `ffprobe`, building the edit-decision list, cutting short clips, `ls` — run inline.

## Handoff for review

Renders can't be watched inside the terminal. Copy finals to `/mnt/hgfs/vm-share/` (host shared folder), or serve them detached with `python3 -m http.server` bound to `192.168.171.128` so the user can watch from Windows.
