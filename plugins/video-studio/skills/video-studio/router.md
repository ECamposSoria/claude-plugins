# Router — classify the request

Walk these gates in order. The first one that matches wins. Stop and route.

## Gate 1 — Is there recorded footage?

Does the request involve a **real recorded clip** the user already has (a file they name or attach: talking-head, screen recording, webcam, phone video, demo capture)?

- **Yes, and that's the whole job** (cut it, trim it, remove filler, tighten, subtitle) → **footage-edit**.
- **Yes, plus generated animation** (add an intro, title card, lower-thirds, animated overlay, B-roll motion) → **hybrid**.
- **No recorded footage at all** → continue to Gate 2.

## Gate 2 — Is the user pasting or pointing at existing web content?

A landing page, a design-system component, a CodePen/JSFiddle demo, an HTML email, a Claude/Stitch artifact — anything that already exists **as HTML/CSS** and they want animated or turned into video as-is.

- **Yes** → **animation-hyperframes**. (Remotion would force a rewrite into JSX; Hyperframes plays HTML as-is.)
- **No** → continue to Gate 3.

## Gate 3 — Where does the motion come from?

- Motion authored as a **library-clock timeline** — GSAP, Anime.js, Motion One, Lottie, Three.js, ScrollTrigger, SplitText, physics eases → **animation-hyperframes**. (Hyperframes seeks these libraries to `frame/fps`; Remotion runs their clocks at wall-clock and they race to the end.)
- Motion authored as **per-frame React** — `useCurrentFrame()`, `interpolate()`, `spring()`, hand-tuned component animation — or the user wants to **reuse existing React components** → **animation-remotion**.
- **Unclear / no preference** → default to **animation-remotion** via `promo-video` (it's the mature, batteries-included promo path with voiceover + music), but say so and offer Hyperframes if they're GSAP/HTML-minded.

## When to ask instead of guess

Use `AskUserQuestion` when:

- The request is "make a video about X" with **no footage named and no style cue** — you can't tell promo-animation from footage-edit. Ask what they're starting from.
- It's plausibly hybrid but the animation role is vague ("make my demo look nicer") — ask whether they want cuts only, added motion graphics, or both.

## Quick reference

| Signal in the request | Route |
|---|---|
| "cut / trim / tighten this clip", "remove the ums", a named `.mp4` of a real recording | footage-edit |
| named recording **+** "add an intro / title / lower-thirds / motion graphics" | hybrid |
| "animate this landing page / CodePen / HTML" | animation-hyperframes |
| "GSAP / Lottie / Three.js animation", pasted HTML+CSS | animation-hyperframes |
| "promo / product teaser / animated explainer" (no footage, no style cue) | animation-remotion (offer Hyperframes) |
| React components to reuse, `interpolate`/`spring` phrasing | animation-remotion |
