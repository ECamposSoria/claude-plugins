# Router: classify the request

Walk the gates in order. The first match wins.

## Gate 0: is a song the spine?

A music video, a visualizer, a lyric video, or footage or AI clips cut to a track, where the picture follows the
song's beats and sections and the song plays unchanged.

- Yes → **music-video**. It listens to the song first, then builds the picture from motion graphics, AI clips or
  footage (it borrows the other legs for that).
- A voiceover-led piece with a music bed underneath → not this gate; the bed is the audio leg's job.
- No → Gate 1.

## Gate 1: is there real footage to cut?

A clip the user already has (talking head, screen recording, phone video, demo capture).

- Cutting it is the whole job (trim, remove filler, tighten, subtitle) → **footage-edit**.
- It also needs generated animation (intro, title card, lower-thirds, motion graphics) → **hybrid**.
- No → Gate 2.

## Gate 2: does the video need footage that doesn't exist?

Real-looking people, places or products in motion that nobody filmed: workers assembling a stand, a product
in use, a rooftop at dusk, a reel built from AI keyframes.

- Yes → **ai-footage**. Generation runs through the `nano-banana-multi:image-gen` skill; repair, assembly and delivery happen
  here. If it also needs animated overlays, finish the clips first, then treat it as **hybrid**.
- Only still photos to animate into a story or slideshow → Gate 4 (that is animation, not AI footage).
- No → Gate 3.

## Gate 3: is the user pointing at existing web content?

A landing page, component, CodePen, HTML email, Stitch or Claude artifact they want animated as-is.

- Yes → **animation-hyperframes** (it plays HTML as-is; Remotion would force a rewrite into JSX).
- No → Gate 4.

## Gate 4: where does the motion come from?

- A library-clock timeline (GSAP, Anime.js, Motion One, Lottie, Three.js, SplitText), kinetic typography,
  a brand story from event photos, captions-led social video → **animation-hyperframes**. Hyperframes seeks
  these libraries frame by frame; Remotion runs them at wall-clock and they race to the end.
- Per-frame React (`useCurrentFrame`, `interpolate`, `spring`), or reusing React components, or the full
  guided promo with voiceover and music → **animation-remotion**.
- No preference → **animation-remotion** via `promo-video`, and offer Hyperframes.

## When to ask instead of guess

- "Make a video about X" with no footage named and no style cue: ask what we start from (their footage,
  generated footage, pure animation).
- "Make my demo look nicer": ask whether they want cuts, motion graphics, or both.
- AI footage with people: ask whether a continuous shot or several cuts is wanted. A fast-paced cut hides
  generation errors; a continuous shot shows every one.

## Quick reference

| Signal in the request | Route |
|---|---|
| "cut / trim / tighten this clip", "remove the ums", a named recording | footage-edit |
| named recording + "add an intro / titles / lower-thirds" | hybrid |
| "realistic video of people doing X", start/end frames, Kling or Seedance clips to assemble | ai-footage |
| "this generated clip pops / the sign text changes / the shirt logo is wrong" | ai-footage (repair) |
| "animate this landing page / CodePen / HTML", GSAP, Lottie, Three.js | animation-hyperframes |
| "story from these event photos", kinetic type, captions-first social cut | animation-hyperframes |
| "promo / product teaser / animated explainer", React components | animation-remotion |
| "add a voiceover / music / captions / dub it" to an existing video | the audio leg on its own |
| "music video / visualizer / lyric video for this song", "cut these clips to the beat" | music-video |
| a pasted reel or YouTube link, "make one like this" | Step 0 first, then route |
| "recreate this video", "the same animation for our product" | Step 0 with [recreate.md](recreate.md), then route (usually animation-hyperframes) |

## Considered and not adopted (2026-10-24)

OpenMontage (full agentic studio, AGPL: we borrowed its pre-delivery checks instead), `/brag` (same job as
`hyperframes:product-launch-video`), ManimGX (math/3D explainer engine, v0.1, untested without a GPU) and the
Hainrixz motion/editor agents. Reasons in the shared media memory, `~/projects/image-video-generation/memory/reference_reel_tools_eval_2026-10.md`.

## Considered and not adopted (2026-10-27)

From a walkthrough of Codex recreating launch videos (adopted from it: [recreate.md](recreate.md), timestamped and
side-by-side contact sheets, the "Revisions" section of SKILL.md, the line-work and 3D-product notes in the
Hyperframes leg):

- **DaVinci Resolve driven by computer use**: a desktop app the agent clicks through (about 20 minutes for 10 s),
  GPU only (the laptop), and every change is another clicking session rather than an edit to a file. Its smoother
  curves were SVG path animation, which Hyperframes does.
- **Diffusion Studio**: a third composition engine beside Remotion and Hyperframes, with nothing they lack.
- **Clicky** (Mac voice-to-clipboard prompts), **MagicPath** (a canvas to annotate frames) and **Mobbin** (a
  library of app screenshots): tools for a person typing into the Codex app. Their ideas live here as one brief
  per revision round and timestamped sheets; UI references are website-builder's job.
- **Blender**: unchanged since 2026-10-25 (realism only, not installed).
