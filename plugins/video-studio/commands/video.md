---
name: video
description: Make, edit or finish a video — promo animation, footage editing, AI-clip assembly and repair, voice, music and captions
argument-hint: [what you want — e.g. "promo for X", "cut the filler from clip.mp4", "assemble these Kling clips into a reel", "make one like <reel link>"]
---

The user wants to create, edit or finish a video. Invoke the `video-studio` skill and follow it from Step 0.

**Request:** $ARGUMENTS

A pasted reel or video link means Step 0 (watch it, write the brief) comes first. Then route with the skill's
`router.md` to one of: animation-remotion, animation-hyperframes, footage-edit, ai-footage, or hybrid.
Voice, music and captions use the shared audio leg. Every render passes `qa_render.py` before delivery.

If the request doesn't say what we start from, ask with AskUserQuestion before doing work.
