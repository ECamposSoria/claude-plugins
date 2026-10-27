# Recreate a reference video

For a reference the owner wants matched closely, timing and motion included ("recreate this", "same animation for
our product", "this launch video but ours"), not just its feel. Step 0's rule still holds: copy the structure,
timing and motion; the content (brand, product, words, logo, characters) is ours. Never deliver a one-to-one copy
of another brand's piece.

## 1. Read the reference

- `watch` it for the overview and transcript. It samples at most 2 frames a second: enough to find the scenes,
  too coarse to read easing.
- Find the cuts. Flat-colour motion graphics score low (a blue-to-orange cut measured 0.12), so start at 0.1 and
  read the scores; a run of consecutive frames is fast motion, not a cut:

  ```bash
  ffmpeg -hide_banner -i ref.mp4 -vf "select='gt(scene,0.1)',metadata=print" -f null - 2>&1 \
    | grep -E 'pts_time|scene_score'
  ```

- For each moving part, pull frames at the source rate and read them in order (every second or third frame on a
  long move). Easing, overshoot, stagger and motion blur only show here:

  ```bash
  mkdir -p ref-frames && ffmpeg -ss 2.4 -t 0.8 -i ref.mp4 -vf scale=480:-2 ref-frames/s03-%03d.jpg
  ```

## 2. Write the shot list before any code

`shotlist.md` in the project, one row per scene:

| # | Start–end | On screen | Motion: property, from → to, easing, overshoot, stagger | Colours | Type | Out |
|---|---|---|---|---|---|---|

- **Colours are sampled, not guessed.** The hex of a 5×5 patch at (x, y) at 1.5 s:
  `ffmpeg -v error -ss 1.5 -i ref.mp4 -frames:v 1 -vf "crop=5:5:x-2:y-2,scale=1:1:flags=area" -f rawvideo -pix_fmt rgb24 - | xxd -p`
  (replace `x-2` and `y-2` with numbers).
- **Type**: the closest free family and weight, size as a share of frame height. Vendor the font
  ([animation-hyperframes.md](legs/animation-hyperframes.md), trap 5).
- **What we swap**: list every piece of their content and what replaces it (our logo from the brand assets, our
  copy, our product).

## 3. Build scene by scene

Route as usual; a motion-graphics reference goes to **animation-hyperframes**. Each Codex brief carries the shot
list rows and the reference frames for the scenes in that pass. Build in timeline order and look at a draft every
scene or two, not only once the whole piece exists. Curved line work and products that come apart in 3D: see the
Hyperframes leg, "Line work and 3D products".

## 4. Compare side by side

```bash
uv run "$SKILL/scripts/qa_render.py" draft.mp4 --sheet compare.jpg --sheet-frames 16 --compare ref.mp4
```

Each tile is our frame on the left and the reference on the right at the same moment (the same offset from where
each picture starts), both timestamped; a reference shorter than ours repeats its last frame, and its label
shows that time. Read it with the Read tool:

- Pairs that look one step apart are timing drift: fix the shot list's times first, then the motion.
- For one scene's motion, trim both to it and compare densely:
  `ffmpeg -ss 2.4 -t 0.8 -i draft.mp4 d.mp4`, the same for `ref.mp4`, then `--compare` with `--sheet-frames 8`.

Once it matches, changes ("make it blue", "swap the character") are revisions (SKILL.md, "Revisions"), and the
delivery render goes through Step 3 as usual.
