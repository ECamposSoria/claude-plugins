---
name: video-studio
description: Use when the user wants a video made, edited or finished — cutting or tightening a recording, assembling AI-generated clips into a reel, promo or explainer animation, captions or subtitles, a voiceover or music bed, dubbing, repairing a generated clip that pops or mangles lettering, or "make one like this" from a pasted reel or YouTube link. Invoke with /video. Generating the clips or images themselves belongs to image-gen.
allowed-tools: Bash(npm:*), Bash(npx:*), Bash(ffmpeg:*), Bash(ffprobe:*), Bash(python3:*), Bash(uv:*), Bash(git:*), Bash(ls:*), Bash(cp:*), Bash(mkdir:*), Read, Write, Edit, Glob, Grep, AskUserQuestion, Skill
---

# Video Studio

You produce and edit video on this VM. There is no single renderer: each request goes to a **leg** that drives
a real tool. Route first, build second. `$SKILL` in every command is the directory holding this file.

## Step 0: start from a reference when there is one

A pasted reel, Short, TikTok or YouTube link ("make one like this") → invoke the `watch` skill on it first, then
write a five-line brief before routing: hook length, average shot length, caption style, music energy, and
what to keep versus change for our brand. Copy structure, never content.

When the video is for a brand, read that brand's `memory/marketing/<brand>/` notes (palette, typography, real
logo files). Use the real logo file, never a redrawn one.

## Step 1: route

Read [router.md](router.md) and pick exactly one route. Ask with `AskUserQuestion` when the request does not
say what we start from. Announce the route in one line.

| Route | Playbook | Engine |
|---|---|---|
| animation-remotion | [legs/animation-remotion.md](legs/animation-remotion.md) | `promo-video` skill (Remotion) |
| animation-hyperframes | [legs/animation-hyperframes.md](legs/animation-hyperframes.md) | `hyperframes:*` skills, `npx hyperframes` |
| footage-edit | [legs/footage-edit.md](legs/footage-edit.md) | `faster-whisper` + `ffmpeg` |
| ai-footage | [legs/ai-footage.md](legs/ai-footage.md) | clips from `image-gen` (fal), repaired and assembled here |
| hybrid | "Hybrid assembly" below | footage or AI clips + animation + `composite.sh` |

Voice, music, captions and loudness are shared by every route: [legs/audio.md](legs/audio.md).

## Step 2: execute the leg

Follow the playbook. Paid generation (fal clips, ElevenLabs voice and music) goes through the `image-gen`
skill's spend guard or the audio leg, with the cost stated before the call.

## Step 3: check, then deliver

Run the QA script on every render before anyone sees it:

```bash
uv run "$SKILL/scripts/qa_render.py" final.mp4 --expect-size 1080x1920 --expect-fps 30 \
  --expect-audio --mode edit --sheet /tmp/sheet.jpg
```

- `--mode clip` for a single generated shot (any frame jump is a pop); `--mode edit` for a cut piece (jumps
  are cuts).
- Read the contact sheet with the Read tool and look at it. Fix every FAIL; explain or fix every WARN.
- Then deliver: copy to `/mnt/hgfs/vm-share/videos/<project>/` (the owner watches from Windows) and state the
  exact path. Keep drafts in a `borradores/` subfolder so the final is unambiguous.

## Hybrid assembly

For recorded footage or AI clips **plus** generated animation (title cards, lower-thirds, an intro):

1. Base: footage-edit gives `basecut.mp4`, or ai-footage gives the assembled clips.
2. Animation leg: overlays that need transparency come from Hyperframes (alpha `.mov`/`.webm`); a full intro
   or outro scene can come from Remotion. Match the base's size and fps (`ffprobe`).
3. Composite with [legs/composite.md](legs/composite.md): `overlay`, then `concat`, then audio.
4. QA the result (Step 3).

## Formats

| Where it goes | Size | Notes |
|---|---|---|
| Reels, Stories, TikTok, Shorts | 1080×1920, 30 fps | Keep text and logos between y=248 and y=1690 (Instagram covers the rest) |
| Feed 4:5 | 1080×1350 | |
| YouTube, web hero | 1920×1080 | |

h264 + yuv420p + AAC 48 kHz, loudness −14 LUFS / −1.5 dBTP (see the audio leg).

## Rules

- **Route before you build.**
- **Non-blocking.** Transcription, renders and generation run with `run_in_background` or go to the user.
  Short ops (ffprobe, EDLs, cuts of short clips) run inline. Never run parallel ffmpeg jobs or Hyperframes
  renders with more than 4 workers: the VM has hard memory ceilings.
- **Processing stays local.** The only paid services are fal (through image-gen) and ElevenLabs (audio leg).
- **Reuse, don't reimplement.** Remotion goes through `promo-video`, Hyperframes through its own skills.
- **Correctness over speed.** Re-encode at edit points, keep fps and sample rate explicit, verify each stage.
