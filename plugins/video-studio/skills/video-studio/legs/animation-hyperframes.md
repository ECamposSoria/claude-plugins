# Leg: animation-hyperframes

Generated motion where the source of truth is **HTML/CSS/JS**, not React. Use this leg when the router landed here: the user pasted existing web content, or the motion is a library-clock timeline (GSAP, Anime.js, Motion One, Lottie, Three.js).

Why this leg and not Remotion: Hyperframes seeks each animation library to `frame/fps` before capturing, so a 4-second GSAP timeline renders across the full 4 seconds. Remotion runs those libraries at wall-clock and they race to the end. And you can drop in arbitrary HTML/CSS as-is — no JSX rewrite.

Engine: `npx hyperframes` (verified: `hyperframes@0.7.52` on npm). Requires Node 22+ (VM has v22.22.1) and ffmpeg (present). It's a young project — **pin the version**.

## Commands (verified CLI surface)

```bash
npx hyperframes@0.7.52 init my-video      # scaffold project
cd my-video
npx hyperframes@0.7.52 preview            # live preview in the browser
npx hyperframes@0.7.52 render --output out.mp4
```

`init` and the first render are **heavy/network** (the CLI fetches, and a deterministic render may pull `chrome-headless-shell`). Propose them to the user or run with `run_in_background` — never block. Optionally vendor the upstream authoring skills once: `npx skills add heygen-com/hyperframes --full-depth --yes`.

## Project structure

```
my-video/
  meta.json          # project metadata
  index.html         # root composition (entry point)
  compositions/      # sub-compositions
  assets/            # media (images, audio, fonts)
```

## Authoring rules (the data-* contract)

- The **root element** must carry `data-composition-id`, `data-width`, `data-height`.
- Every **timed element** needs `class="clip"` plus `data-start`, `data-duration`, `data-track-index`. Timing is expressed on the DOM via these attributes — that's what makes the same DOM both the render layer and an editable source.
- Author animation with normal web tools: CSS `@keyframes` / Web Animations API, GSAP, Lottie, Three.js. Hyperframes seeks them per frame, so **avoid raw `requestAnimationFrame` loops and inline `<iframe>`s** — those force the slower screenshot-mode fallback (still correct, just non-deterministic across machines).

## Pasting existing web content

Landing page / CodePen / HTML email / Stitch or Claude artifact → drop the markup into `index.html` (or a sub-composition), wrap the moving pieces as timed `clip` elements, and add the animation timeline. No rewrite. This is the leg's core advantage — lean on it.

## Render modes

- **BeginFrame (deterministic)**: default on Linux with `chrome-headless-shell`; byte-reproducible. Good for anything CSS/WAAPI/GSAP/Lottie/Three.js.
- **Screenshot (fallback)**: auto-selected when the composition has raw rAF or iframes; runs on system chromium. Hyperframes prints a diagnostic when it falls back — surface that to the user.

## Voiceover / music

Hyperframes renders visuals only. If the piece needs narration or a music bed, reuse the `promo-video` skill's audio flow (ElevenLabs voiceover + bundled royalty-free music, needs `ELEVEN_LABS_API_KEY`), then mux with `composite.sh mixaudio` (see [composite.md](composite.md)).

## Verify & deliver

```bash
ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height,duration -of default=nw=1 out.mp4
```

Confirm h264 + the expected resolution/duration, then hand off for review (copy to `/mnt/hgfs/vm-share/` or serve on `192.168.171.128`).

## Status note

The CLI surface and project contract above are from the official Hyperframes quickstart and were confirmed resolvable on npm. A full local render has **not** yet been exercised on this VM — the first `init`/`render` is the heavy step to run (background or hand to the user); if `chrome-headless-shell` fails to fetch, expect the screenshot-mode fallback on chromium.
