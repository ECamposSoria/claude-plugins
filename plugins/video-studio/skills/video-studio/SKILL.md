---
name: video-studio
description: Make or edit any video by routing to the right tool — promo animation (Remotion via promo-video, or Hyperframes for GSAP/HTML), self-hosted footage editing (faster-whisper transcript + ffmpeg), or a hybrid of both with compositing. Use when the user wants to create, generate, cut, trim, edit, or assemble a video. Invoke with /video.
allowed-tools: Bash(npm:*), Bash(npx:*), Bash(ffmpeg:*), Bash(ffprobe:*), Bash(python3:*), Bash(git:*), Bash(ls:*), Bash(cp:*), Bash(mkdir:*), Read, Write, Edit, Glob, Grep, AskUserQuestion, Skill
---

# Video Studio

You produce and edit video on a self-hosted VM. You do not have one renderer — you have three **legs**, and your first job on every request is to **route** to the correct one. Never start authoring before you have classified the request.

A skill is instructions, not an engine. Each leg drives a real tool: Remotion (via the `promo-video` skill), Hyperframes (`npx hyperframes`), or `faster-whisper` + `ffmpeg`.

## Step 1 — Route

Read [router.md](router.md) and classify the request into exactly one of: **animation-remotion**, **animation-hyperframes**, **footage-edit**, or **hybrid**. When the request is ambiguous (e.g. "make me a video about X" with no footage mentioned and no style cue), ask with `AskUserQuestion` before doing any work — do not guess.

Announce the route in one line, e.g. *"Routing to the footage-edit leg: you have a recorded clip to tighten."*

## Step 2 — Execute the leg

| Route | Playbook | Engine |
|-------|----------|--------|
| animation-remotion | [legs/animation-remotion.md](legs/animation-remotion.md) | `promo-video` skill (Remotion) |
| animation-hyperframes | [legs/animation-hyperframes.md](legs/animation-hyperframes.md) | `npx hyperframes` |
| footage-edit | [legs/footage-edit.md](legs/footage-edit.md) | `faster-whisper` + `ffmpeg` |
| hybrid | this file, "Hybrid orchestration" below | footage + animation + `composite.sh` |

## Step 3 — Deliver for review

The terminal can't play video. When a render or cut finishes, run `ffprobe` to confirm streams/duration, then hand it off: copy to `/mnt/hgfs/vm-share/` or serve it detached (`python3 -m http.server` on `192.168.171.128`) so the user can watch from the Windows host. State the exact path/URL.

## Hybrid orchestration

Use when a request needs **recorded footage AND generated animation** (e.g. "edit this talk and add an animated title card + lower-thirds").

Assembly order:

1. **Footage leg first** → produce `basecut.mp4` (the tightened recording). See [legs/footage-edit.md](legs/footage-edit.md).
2. **Animation leg** → produce the overlay/intro pieces. Prefer **Hyperframes** for overlays that need transparency (title cards, lower-thirds, callouts) — render with an alpha-capable format. Use **Remotion** (`promo-video`) for a full generated intro/outro scene. Match the animation's resolution and fps to the base cut (`ffprobe basecut.mp4` to read them).
3. **Composite** → layer and join with [legs/composite.md](legs/composite.md):
   - Timed overlays on the base cut → `composite.sh overlay`.
   - Intro/outro joined to the base → `composite.sh concat` (all inputs must share codec/resolution/fps — re-encode intros to match).
   - Music bed / voiceover ducking → `composite.sh mixaudio`.
4. **Verify** each stage with `ffprobe` before the next; never chain re-encodes blindly.

## Prerequisites

First run of a leg checks its tools. If `faster-whisper` or Hyperframes is missing, follow [setup/install.md](setup/install.md) — propose the install commands to the user (they run them); do not assume a heavy install will succeed silently.

## Rules

- **Route before you build.** Every request starts at Step 1.
- **Non-blocking.** Transcription and renders run with `run_in_background` or are handed to the user to run. Never block the foreground. Short ops run inline.
- **Self-hosted only.** No SaaS video services. All processing stays on the VM.
- **Reuse, don't reimplement.** The Remotion leg *invokes the `promo-video` skill by name* — never copies its logic or hardcodes its paths.
- **Correctness over speed** in cuts and concats: re-encode at edit points, keep fps/sample-rate explicit, verify with `ffprobe`.
