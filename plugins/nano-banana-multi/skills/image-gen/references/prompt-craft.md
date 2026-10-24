# Prompt craft for images and clips

A short prompt is not a free prompt. It is one where the model decides, and the model always decides the
average: flat light, centred subject, neutral background. That is what reads as stock or as "AI".

Block structure and the fidelity anchor are adapted from Hainrixz/creative-architect (MIT); the traps at the
bottom come from our own deliveries.

## Before writing

Answer three things first: **what feeling** the image must give, **where the eye lands first**, and
**what must not appear**. Then decide what the image is for (ad, reel keyframe, site hero, product page),
because that sets the framing and the empty space text will need.

## Write in blocks, most important first

Models weight the start of a prompt most. Not every block is needed, but a prompt without **light** and
**composition** is a description, and a description returns the average.

1. **Concept**: the one-line idea.
2. **Subject**: what it is, with the fidelity anchor below when it is a real product.
3. **Composition**: shot size, camera angle, placement (centred, thirds, off-centre with air for text).
4. **Light**: a named setup (soft window light from the left, hard noon sun, rim light, overcast).
5. **Background and setting.**
6. **Materials and texture.**
7. **Lens**: focal length and depth of field (35 mm documentary, 85 mm shallow focus, macro).
8. **Palette**: brand colours by name or hex.
9. **Style reference**: describe the technique (grain, palette, framing), never a living artist's name.
10. **What to avoid**: the defaults you are cutting.

## The fidelity anchor (real products, real places, real uniforms)

When a real product appears, edit from its photo (`image.py` with `--reference`, or an `/edit` endpoint),
never generate it from text. Put this next to the subject block:

> Reproduce the product in the reference image exactly: same shape, colour, label, label text, proportions
> and logo. Do not redesign, improve or restyle it. Only the setting, light and framing change.

Then compare the result with the photo: colour, label, shape, logo. If anything changed, discard it.

## Motion prompts (image-to-video)

- **Describe the motion, not the scene.** The start frame already holds the scene; describing it again makes
  the model reinvent it. Say what the camera does, what the subject does, what the air does.
- **Less movement wins.** One camera move and one subject action per shot. Big state changes inside one
  clip (deflated to inflated, people entering and leaving) make Kling pop between frames: split into shorter
  shots or use a start frame only.
- **Decide the duration before generating.** It is the parameter that moves the price most.
- **Reject the take** if the product deforms mid-shot, a hand grows a finger, or the motion swings back and
  forth like a pendulum.

## Our traps (each one cost a delivery)

- 🔴 **Printed text is always hallucinated.** Packaging, badges, banners, shirts, screens: models misspell the
  client's name and invent other brands. Audit every surface with text by cropping 1:1 from the final
  render, not from a zoomed PNG.
- 🔴 **Never redraw a logo.** Use the real file: `/mnt/hgfs/vm-share/projects memory/company/brand-assets/`, or the
  brand's folder under `~/projects/uniteapp/marketing/`.
  A redrawn "close enough" logo was caught immediately.
- 🔴 **Text on clothing never survives motion**, and pasting a print onto moving cloth reads as fake. Keep
  shirts plain in the start frame, or accept the garment as generated.
- **No baked-in text** when the piece will carry overlay text: add "no text, no letters, no logos, no
  watermark" to the avoid block and set the type in the composition.
- **Never repeat a failed prompt unchanged.** Say what failed and which block you change. After two failed
  attempts at the same piece, stop and propose a different approach.
