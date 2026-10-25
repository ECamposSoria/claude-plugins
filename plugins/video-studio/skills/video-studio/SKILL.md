---
name: video-studio
description: Use when the user wants a video made, edited or finished — a music video, visualizer or lyric video for a song, cutting or tightening a recording, assembling AI-generated clips into a reel, promo or explainer animation, captions or subtitles, a voiceover or music bed, dubbing, repairing a generated clip that pops or mangles lettering, or "make one like this" from a pasted reel or YouTube link. Invoke with /video. Generating the clips or images themselves belongs to image-gen.
allowed-tools: Bash(npm:*), Bash(npx:*), Bash(ffmpeg:*), Bash(ffprobe:*), Bash(python3:*), Bash(uv:*), Bash(bash:*), Bash(docker:*), Bash(ssh:*), Bash(git:*), Bash(ls:*), Bash(cp:*), Bash(mkdir:*), Read, Write, Edit, Glob, Grep, AskUserQuestion, Skill
---

# Video Studio

You produce and edit video on this VM. There is no single renderer: each request goes to a **leg** that drives
a real tool. Route first, build second. `$SKILL` in every command is the directory holding this file.

## Step 0: start from a reference when there is one

A pasted reel, Short, TikTok or YouTube link ("make one like this") → invoke the `watch` skill on it first (it
handles public Instagram reels: frames plus a Whisper transcript), then
write a five-line brief before routing: hook length, average shot length, caption style, music energy, and
what to keep versus change for our brand. Copy structure, never content.

Costs, provider choices and tool traps from earlier pieces are in the shared media memory,
`~/projects/image-video-generation/memory/README.md`: read it before generating or rendering.

When the video is for a brand, read that brand's notes in `~/projects/uniteapp/memory/marketing/<brand>/`
(palette, typography) and take logos from `/mnt/hgfs/vm-share/projects memory/company/brand-assets/` or the
brand's `~/projects/uniteapp/marketing/` folder. Use the real logo file, never a redrawn one.

## Step 1: route

Read [router.md](router.md) and pick exactly one route. Ask with `AskUserQuestion` when the request does not
say what we start from. Announce the route in one line.

| Route | Playbook | Engine |
|---|---|---|
| animation-remotion | [legs/animation-remotion.md](legs/animation-remotion.md) | `promo-video` skill (Remotion) |
| animation-hyperframes | [legs/animation-hyperframes.md](legs/animation-hyperframes.md) | `hyperframes:*` skills, `npx hyperframes` |
| footage-edit | [legs/footage-edit.md](legs/footage-edit.md) | `faster-whisper` + `ffmpeg` |
| ai-footage | [legs/ai-footage.md](legs/ai-footage.md) | clips from `nano-banana-multi:image-gen` (fal), repaired and assembled here |
| hybrid | "Hybrid assembly" below | footage or AI clips + animation + `composite.sh` |
| music-video | [legs/music-video.md](legs/music-video.md) | the song listener (`listen.py`), then Hyperframes, AI clips or footage cut on its beat grid; `sync_check.py` |

Voice, music, captions and loudness are shared by every route: [legs/audio.md](legs/audio.md).

## Step 2: execute the leg

Follow the playbook. Paid or cloud calls (fal clips through the `nano-banana-multi:image-gen` spend guard, ElevenLabs voice and music
in the audio leg) are quoted to the user before the call.

### Who writes the code

A composition (Hyperframes, Remotion) is mostly code, and its build and fix rounds are where the tokens go.
**Claude directs and checks; Codex builds** through the `codex-delegate` skill (one brief per build pass), which
moves the bulk of the work onto the ChatGPT plan. Claude keeps the brief, the look at every still and draft, the
final render and the checks; Codex writes files only (no renders, no containers).

| Piece | Who | Why (checked 2026-10-25) |
|---|---|---|
| 3D scenes: three.js characters, cameras, lighting, shaders | Codex `gpt-6-astra`, medium | Leads DesignArena's 3D board (Astra 1461, Astra max 1503; Claude Opus 5.5 1466; GPT-6.1 Sol 1436) but costs 5× Sol per token: spend it on 3D only |
| Everything else: 2D, typography, lyrics, per-scene pieces, data plumbing, a batch of fixes | Codex `gpt-6.1-sol`, medium (low for purely mechanical edits) | WebDev Arena 1749 vs Astra's 1774 at about a fifth of the cost per task; 500K context |
| A one- or two-line tweak (a colour, one timing) | Claude, inline | A delegation round (10–20 min) costs more than the edit |

`gpt-6-luna` is 20× cheaper again but ranks far lower on visual code (DesignArena 3D 1213): not for anything that
is seen. Batch fixes: after each draft, one brief with every change, not one per finding.

## Step 3: check, then deliver

Run the QA script on every render before anyone sees it:

```bash
uv run "$SKILL/scripts/qa_render.py" final.mp4 --expect-size 1080x1920 --expect-fps 30 \
  --expect-audio --mode edit --sheet /tmp/sheet.jpg
```

- `--expect-fps 24` for pieces built from AI clips.
- `--mode clip` for a single generated shot (any frame jump is a pop); `--mode edit` for a cut piece (jumps
  are cuts).
- Read the contact sheet with the Read tool and look at it. Fix every FAIL; explain or fix every WARN.
- The checks are measurements, not proof. If a FAIL contradicts what the frames and `ffprobe` show on unusual
  media (an exotic container, timestamp offsets, odd edit lists), say which check and why it is wrong, and
  deliver with that note instead of forcing a re-encode.
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
| Reels, Stories, TikTok, Shorts | 1080×1920, 30 fps (24 when built from AI clips: keep their native rate) | Keep text and logos between y=248 and y=1690 (Instagram covers the rest) |
| Feed 4:5 | 1080×1350 | |
| YouTube, web hero | 1920×1080 | |

h264 + yuv420p + AAC 48 kHz, loudness −14 LUFS / −1.5 dBTP (see the audio leg).

## Rules

- **Route before you build.**
- **Non-blocking.** Transcription, renders and generation run with `run_in_background` or go to the user.
  Short ops (ffprobe, EDLs, cuts of short clips) run inline. Never run parallel ffmpeg jobs or Hyperframes
  renders with more than 4 workers: the VM has hard memory ceilings.
- **Processing stays local** (cuts, renders, QA). Generation and voice may call paid or cloud services: fal and
  Gemini through image-gen, ElevenLabs and HeyGen's free path in the audio leg. Quote the cost first.
- **GPU when a job needs it.** Voice (VoiceStudio) and song analysis (`listen_remote.sh`) run on the laptop's
  RTX 4070 when it is free; check `nvidia-smi` there first and ask the owner if another session holds it. The VM's
  CPU is the fallback, not the default, for those.
- **Reuse, don't reimplement.** Remotion goes through `promo-video`, Hyperframes through its own skills.
- **Correctness over speed.** Re-encode at edit points, keep fps and sample rate explicit, verify each stage.
