# Leg: animation-remotion

Generated motion authored as **per-frame React** — `useCurrentFrame()`, `interpolate()`, `spring()`, hand-tuned component animation — or when the user wants to **reuse existing React components**. This is the mature, batteries-included promo path (voiceover + music + polished transitions).

## Delegate — do not reimplement

This leg is a **pointer**. Invoke the existing `promo-video` skill by name and let it drive the whole Remotion flow:

```
Skill: promo-video
```

Do **not** copy its phases, scripts, or hardcode its file paths here. It owns:

- Product understanding → duration/theme/voice questions
- Remotion project scaffold (`npx create-video`), 1920×1080 composition
- Scene building with `spring`/`interpolate`, 3D mockups, transitions (incl. metallic swoosh)
- ElevenLabs voiceover + Whisper timing verification. 🔴 It reads `ELEVEN_LABS_API_KEY`, but our key file
  (`~/.secrets/elevenlabs.env`) names it `ELEVENLABS_API_KEY`: export the former from the latter first.
- Bundled royalty-free music, final render + audio mux

It also depends on the `remotion-best-practices` skill for animation fundamentals — that chain stays intact when you delegate.

## When to prefer this leg over Hyperframes

- Motion is React-interpolation style, or reuses a React design system.
- The user wants the full guided promo experience (voiceover script matched to scenes, music, CTA).
- No pasted HTML/CSS and no library-clock timeline (those go to Hyperframes — see [../router.md](../router.md)).

## Handing its output into a hybrid

When Remotion produces an **intro/outro scene** for a hybrid video, take its rendered mp4 and pass it to `composite.sh concat` (see [composite.md](composite.md)) with the footage base cut. Match the base cut's resolution/fps, or let `concat` normalize (list the geometry you want first). For **transparent overlays**, prefer Hyperframes — Remotion's promo path renders opaque full scenes, not alpha lower-thirds.
