# Leg: audio (voiceover, music, captions, loudness)

Shared by every route. Audio is muxed **after** the picture is final, never baked into a render: you can then
replace the music or re-voice a line without re-rendering.

## Voiceover options

| Option | Cost | Clone a voice? | Notes |
|---|---|---|---|
| ElevenLabs TTS | paid plan (we are on `starter`) | Instant voice cloning, plan permitting: check before promising | Best Spanish quality. Key in `~/.secrets/elevenlabs.env` as `ELEVENLABS_API_KEY`. 🔴 `promo-video` reads `ELEVEN_LABS_API_KEY`: `export ELEVEN_LABS_API_KEY="$ELEVENLABS_API_KEY"` first. |
| Hyperframes `media-use` voice | free | No | Local **Kokoro** with `--local-only`, or HeyGen's free path (needs the `heygen` CLI signed in; not installed). Check Kokoro has a voice for the language before relying on it. |
| VoiceStudio (debpalash/VoiceStudio, AGPL) | free, local | **Yes** | **Not installed.** The only free local cloning option found. CPU-only here (no GPU) so slow, ~5 GB. Install through its Docker guide, never its `curl ... \| sh`. |
| The user records it | free | it is their voice | Often the best option: transcribe it with `transcribe.py` and cut it like footage. |

🔴 Clone a voice only with the owner of that voice's explicit permission.

## Music

- **ElevenLabs Music API** works on `starter`: `POST https://api.elevenlabs.io/v1/music` with
  `{"prompt": ..., "music_length_ms": ...}` returns an MP3 in the body. It overshoots the length slightly, so
  trim to the exact second.
- `promo-video`'s bundled royalty-free tracks, or Hyperframes `media-use` (`bgm`).

## Captions

- Reels and Shorts with word-by-word captions: the `hyperframes:embedded-captions` skill (word timestamps from
  its transcription engine).
- Plain subtitles on a cut: build an `.srt` from `transcribe.py`'s segments and burn it with
  `ffmpeg -vf "subtitles=subs.srt:fontsdir=<folder with the brand's .ttf>:force_style='Fontname=Poppins,Fontsize=14,Outline=2'"`.
  Brand fonts are not installed system-wide (only DejaVu and Liberation are), so `fontsdir` is required or
  libass silently falls back to DejaVu Sans.
- Keep captions inside the format's safe zone (SKILL.md, Formats).

## Attach and mix

```bash
# put a voiceover (or any audio) on a silent or replaced-audio video
ffmpeg -i video.mp4 -i voice.m4a -map 0:v -map 1:a -c:v copy -c:a aac -ar 48000 -shortest with_voice.mp4

# music bed under it, ducked under the voice
bash "$SKILL/scripts/composite.sh" mixaudio --video with_voice.mp4 --music bed.mp3 --duck --output mixed.mp4
```

## Loudness: −14 LUFS integrated, −1.5 dBTP true peak

Normalise the final mix (or a music-only track) before delivery:

```bash
ffmpeg -i mixed.mp4 -c:v copy -af "loudnorm=I=-14:TP=-1.5:LRA=11" -ar 48000 -c:a aac -b:a 192k final.mp4
```

For a music-only piece, add `afade` in and out to the same filter chain after trimming. Then
`qa_render.py --expect-audio` confirms the loudness and that nothing went silent.
