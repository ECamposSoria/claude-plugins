# Leg: composite (hybrid assembly)

Layer and join the outputs of the other legs into one deliverable. Used by the **hybrid** route: a footage base cut + generated animation (overlays, intro/outro) + audio. Driver: `scripts/composite.sh` (three subcommands). All ffmpeg, all local.

Read the geometry of the base cut first — everything should match it:

```bash
ffprobe -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate -of default=nw=1 basecut.mp4
```

## `overlay` — animation on top of footage

Title cards, lower-thirds, callouts. The overlay is usually an **alpha** clip (author it in Hyperframes/Remotion and render to a format that carries transparency, e.g. ProRes 4444 `.mov` or VP9 `.webm`). Author it at the base resolution.

```bash
composite.sh overlay --base basecut.mp4 --overlay lowerthird.mov --output out.mp4 \
  --x 80 --y 720 --start 3.0 --duration 5.0
```

- `--x/--y` position (top-left origin); omit for `(0,0)` full-frame overlays.
- `--start/--duration` time-box the overlay (`enable='between(t,…)'`); omit to show for its whole length. Base audio is passed through untouched; `eof_action=pass` keeps the base playing after the overlay ends.
- Chain multiple overlays by running `overlay` repeatedly, each on the previous output.

## `concat` — join intro / base / outro

```bash
composite.sh concat --output out.mp4 intro.mp4 basecut.mp4 outro.mp4
```

Inputs may differ in resolution/fps/audio — the script normalizes each to the **first input's** geometry and fps (scale + pad, no stretching), gives every segment a 48 kHz stereo track (silence if it had none), then splices with the concat demuxer. So **order matters**: put the clip whose geometry you want as the target first, or pre-scale your base and list it first.

## `mixaudio` — music bed under voiceover

```bash
composite.sh mixaudio --video out.mp4 --music bed.mp3 --output final.mp4 \
  --music-volume 0.12 --duck
```

- Video is copied (no re-encode); only audio is rebuilt. The `--video` must already have an audio track (the voiceover/main).
- Music is looped to cover the whole video, with a 1 s fade-in and 2 s fade-out, scaled by `--music-volume` (default `0.12`).
- `--duck` (recommended with narration) side-chain-compresses the music whenever the voice is present, so speech stays clear. Drop it for music-only pieces.
- Reuse `promo-video`'s bundled royalty-free tracks as the bed if the user has no music.

## Typical hybrid assembly

```
footage-edit  → basecut.mp4
hyperframes   → lowerthird.mov (alpha), intro.mov
composite overlay  --base basecut.mp4 --overlay lowerthird.mov --start 3 --duration 5 --output withLT.mp4
composite concat   --output joined.mp4 intro.mov withLT.mp4
composite mixaudio --video joined.mp4 --music bed.mp3 --duck --output final.mp4
ffprobe final.mp4   # verify streams/duration, then hand off for review
```

Verify with `ffprobe` after **each** step — never chain re-encodes blind. Long inputs make these heavy: background or hand to the user.
