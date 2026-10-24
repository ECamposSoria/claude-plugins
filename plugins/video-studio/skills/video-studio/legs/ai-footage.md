# Leg: ai-footage (generated clips → finished video)

Footage nobody filmed, generated with the `nano-banana-multi:image-gen` skill (fal: Kling, Seedance) and then checked, repaired
and assembled here. Generation is the cheap part; most of the work and most of the client-visible errors are
in what comes after.

## 1. Plan the shots before paying for any

- Write the shot list: one camera move and one action per shot, 3–10 s each. A single clip that has to carry
  a big change (an inflatable going from flat to full, people entering and leaving) pops between frames.
- Build each start frame (and end frame, when both matter) as a still first, with `nano-banana-multi:image-gen`,
  in the delivery aspect (1080×1920 for reels). Check the first generated clip's size with `ffprobe` before
  paying for the rest. Fix the still,
  not the video: lettering, logos, uniforms and products must be right in the frame before motion.
- 🔴 Clothing text never survives motion. Keep shirts plain in the frames, or accept the garment as generated.
- Decide with the user: one continuous shot (shows every error) or a fast cut (hides them). Quote the total
  cost from image-gen's `references/fal-endpoints.md`: draft at 720p, finals at 1080p, at most three takes per
  shot. Kling 3.0 Pro generates audio by default ($0.168/s instead of $0.112/s): pass `generate_audio=false`
  unless you will use its sound.
- Kling clips come out at **24 fps**. Keep the whole piece at 24 fps (QA with `--expect-fps 24`); converting to
  30 fps duplicates frames and judders.

## 2. Generate

Through image-gen's `fal.py` (spend guard, `--dry-run` first; video always needs `--max-usd` from the model
page), each clip with `run_in_background`. Keep each
`request_id`; `fal.py result` recovers a finished clip without paying again.

## 3. Check every clip

```bash
uv run "$SKILL/scripts/qa_render.py" shot1.mp4 --mode clip --sheet shot1_sheet.jpg
```

Every WARN "possible one-frame pop" is real until you have looked at the frames either side:

```bash
# flagged frame 43 → frames 40..45 side by side (the report uses ffmpeg's n: 0-based, frame after the jump)
ffmpeg -i shot1.mp4 -vf "select='between(n\,40\,45)',scale=384:-2,tile=6x1" -frames:v 1 -fps_mode passthrough strip.jpg
```

How to read the flags:

- **Two consecutive flags, N and N+1**: one bad frame N (the jump into it and out of it).
- **One flag at N**: a state jump between N−1 and N (an object morphs, a person teleports), or a hard cut.
- **Fast but continuous motion** can also trip the detector; if each frame follows from the last, it is not a pop.
Also look at the contact sheet for: background lettering that changed, logos invented on clothing, hands and
products that deform mid-shot, people who vanish behind others.

## 4. Repair, cheapest fix first

| Defect | Fix |
|---|---|
| One bad frame N (flags at N and N+1) | Extract frames (`ffmpeg -fps_mode passthrough`), replace frame N with fal `fal-ai/film` between frames N−1 and N+1 (`start_image_url`, `end_image_url`, `num_frames=1`). |
| State jump at N (one flag) | `fal-ai/film` between N−1 and N with `num_frames` up to 8, splice the new frames in between them, `atempo`-stretch the audio by the added length. A real morph, not a dissolve. |
| Pop at the very end of a clip | Trim the last frames; if the end frame matters, regenerate shorter. |
| Background lettering rewritten (signs, banners, walls) | Restore from a clean plate: SAM 3 video masks of the foreground, a per-frame plate→frame homography (ORB + RANSAC), reject weak fits (< 150 inliers or > 30 px off) and interpolate them from neighbours, then paste the plate's wall outside the masks. |
| A mark the model invented on clothing | Remove it with a Poisson clone (`cv2.seamlessClone`) of neighbouring plain cloth, tracked per frame. Not Telea inpainting: it leaves a pale ghost. Never paste a print onto moving cloth: it reads as fake. |
| Deformed product, extra fingers, a pendulum motion | Regenerate the shot; no post fix is worth it. |

`fal-ai/film` bills per second of output, which the spend guard cannot estimate: pass `--max-usd 0.01`
(it costs $0.0013/s).

Reference implementations of each repair, with the parameters that worked, live in
`~/projects/uniteapp/marketing/macgroup/video/doble-a/scripts/` (`find_jumps.py`, `restore_wall.py`,
`cloth_fill.py`, `fix_shirts.py`) with its README. Run them with
`uv run --with opencv-python-headless --with numpy python -I <script>`. 🔴 SAM 3 masks have holes exactly at
printed logos; dilate or chase them before using a mask to protect a logo.

## 5. Assemble and finish

- Hard cuts with `composite.sh concat` (normalises size, fps and audio), transitions in Hyperframes when the
  cut needs designed motion.
- Voice, music, captions: [audio.md](audio.md). Overlays: [composite.md](composite.md).
- QA the assembled piece with `--mode edit`, then deliver (SKILL.md Step 3). Before publishing, crop 1:1 from
  the final MP4 every surface with printed text and read it: models misspell client names.
