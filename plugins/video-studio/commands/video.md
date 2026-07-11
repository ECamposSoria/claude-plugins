---
name: video
description: Make or edit a video — routes to promo animation, footage editing, or a hybrid of both
argument-hint: [what you want — e.g. "promo for X", "cut the filler from clip.mp4", "add an animated intro to talk.mp4"]
---

The user wants to create or edit a video. Invoke the `video-studio` skill and follow its router.

**Request:** $ARGUMENTS

Use the `video-studio` skill's `router.md` to classify the request into one of:
- **Animation** (generated from code) → Remotion (via the `promo-video` skill) or Hyperframes
- **Footage edit** (a real recorded clip) → transcript + ffmpeg cut pipeline
- **Hybrid** (recorded footage + animated overlays/intro) → both legs, then composite

If the request is ambiguous about which leg applies, ask with AskUserQuestion before doing work.
