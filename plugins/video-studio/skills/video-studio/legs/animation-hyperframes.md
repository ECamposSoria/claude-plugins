# Leg: animation-hyperframes

Motion whose source of truth is HTML/CSS/JS: pasted web content, GSAP / Lottie / Three.js timelines, kinetic
type, brand stories built from event photos, captions-first social cuts. Hyperframes seeks each animation
library frame by frame, so a 4 s GSAP timeline renders across the full 4 s (Remotion would let it race).

## Delegate to the Hyperframes skills

The `hyperframes` plugin is installed and owns the authoring rules. Invoke by name; don't restate them here.

| Need | Skill |
|---|---|
| The composition contract (`data-*` timing, `class="clip"`, tracks) — read before writing any HTML | `hyperframes:hyperframes-core` |
| `init`, `lint`, `check`, `snapshot`, `render`, `doctor` | `hyperframes:hyperframes-cli` |
| Voiceover, music, SFX, transcription, captions, background removal | `hyperframes:media-use` |
| Word-by-word captions | `hyperframes:embedded-captions` |
| Product launch from a site or repo | `hyperframes:product-launch-video`, `hyperframes:pr-to-video` |
| Re-cut a talking-head recording | `hyperframes:talking-head-recut` |
| A short lyric or kinetic-type cut to a track | `hyperframes:music-to-video` (a full music video goes to [music-video.md](music-video.md)) |

The CLI runs via `npx hyperframes`. Pin the version per project (`npx hyperframes@<ver>`) and write it in the
project README so a re-render months later produces the same frames. Last version rendered on this VM:
**0.8.26** (2026-09-02).

## 🔴 Traps on this VM (each one cost a render)

1. **A render that hangs with no output is the browser.** Hyperframes keeps its own `chrome-headless-shell`
   under `~/.cache/hyperframes/chrome/`. If it is missing (needs `unzip`, which is installed), it falls back
   to snap Chromium, whose private `/tmp` hides the DevTools port and hangs silently. Fix:
   `export HYPERFRAMES_BROWSER_PATH=$(ls -d ~/.cache/hyperframes/chrome/chrome-headless-shell/*/chrome-headless-shell-linux64)/chrome-headless-shell`,
   then `npx hyperframes doctor`.
2. **`hyperframes:slideshow` never makes an MP4.** It builds a navigable deck; `render` resolves only the first
   composition and writes a **silently truncated** file. For linear video: `hyperframes-core` with one root
   composition.
3. **Elements of later scenes are not in the DOM when the timeline is built.** Use one `.clip` spanning the
   whole video with the scenes as wrappers faded by `autoAlpha` inside it; `tl.set(selector, vars, time)`
   works where `gsap.set()` on a future clip fails.
4. **Never a CSS `transform` plus a GSAP tween of the same property**: lint stops it
   (`gsap_css_transform_conflict`). Put the static `rotate()` on a wrapper and animate the child.
5. **No network at render time.** Vendor fonts (`woff2`, latin subset) and GSAP into `assets/`. A Google Fonts
   `<link>` breaks determinism.
6. **Always `-w 4` on `render`.** Each worker is a Chrome (~256 MB); the user session has a 20 GB ceiling.
   450 frames at 1080×1920 take ~58 s with 4 workers.
7. `container_overflow` from `check` is not always a bug (a Ken Burns that leaves the card on purpose).
   Look with `snapshot` before silencing it with `data-layout-allow-overflow`.

## Brand and layout

- Real logo file only. Mac Group's isotype needs ~300 px for the inner text to read; at small sizes pair it
  with the wordmark. Palette and type per brand: `~/projects/uniteapp/memory/marketing/<brand>/design.md`.
- WhatsApp event photos (1200×1600) cut subjects when cropped full-bleed to 9:16: put them in a 3:4 card on a
  brand-colour field instead.
- Stories safe zone: critical content between y=248 and y=1690.

## Audio and delivery

Hyperframes renders the picture; mux audio afterwards with the audio leg ([audio.md](audio.md)). For a
transparent overlay in a hybrid, render an alpha format (ProRes 4444 `.mov` or VP9 `.webm`). Then QA and
deliver per SKILL.md Step 3.
