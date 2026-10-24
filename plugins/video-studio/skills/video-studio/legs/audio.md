# Leg: audio (voiceover, music, captions, loudness)

Shared by every route. Audio is muxed **after** the picture is final, never baked into a render: you can then
replace the music or re-voice a line without re-rendering.

## Order of work

1. Picture locked (cuts, overlays) → `picture.mp4`.
2. Voiceover generated or recorded → `voice.m4a`.
3. Captions timed from the **voice**: transcribe it (`transcribe.py voice.m4a --language es`), then burn them
   onto the picture.
4. Attach the voice, mix the music bed under it, normalise loudness.
5. `qa_render.py --expect-audio` (SKILL.md Step 3).

## Voiceover options

| Option | Cost | Clone a voice? | Notes |
|---|---|---|---|
| ElevenLabs TTS | pay-as-you-go: 10,000 characters per cycle (checked 2026-10-24) | **No: instant cloning is not enabled on this plan** | Best Spanish quality. Key in `~/.secrets/elevenlabs.env` as `ELEVENLABS_API_KEY`. Check quota first: `GET https://api.elevenlabs.io/v1/user/subscription` (`character_count`/`character_limit`). 🔴 `promo-video` reads `ELEVEN_LABS_API_KEY`: `export ELEVEN_LABS_API_KEY="$ELEVENLABS_API_KEY"` first. |
| Hyperframes `media-use` voice | free | No | Local **Kokoro** with `--local-only` (runs on this VM), or HeyGen's free path (a cloud service; needs the `heygen` CLI signed in, not installed). Check Kokoro has a voice for the language first. |
| VoiceStudio (debpalash/VoiceStudio, AGPL) | free, local | **Yes** | **Not installed.** The only free cloning option found. CPU-only here (no GPU) so slow, ~5 GB. Install through its Docker guide, never its `curl ... \| sh`. |
| The user records it | free | it is their voice | Often the best option: transcribe it with `transcribe.py` and cut it like footage. |

🔴 Clone a voice only with the explicit permission of the person whose voice it is.

## Music

- **ElevenLabs Music API**: `POST https://api.elevenlabs.io/v1/music` with `{"prompt": ..., "music_length_ms": ...}`
  returns an MP3 in the body. Verified on the old `starter` plan (2026-09-02); recheck on pay-as-you-go before
  promising it. It overshoots the length slightly, so trim to the exact second.
- `promo-video`'s bundled royalty-free tracks, or Hyperframes `media-use` (`bgm`).

## Captions

- Reels and Shorts with word-by-word captions: the `hyperframes:embedded-captions` skill.
- Plain subtitles: build an `.srt` from `transcribe.py`'s segments and burn it onto the picture with
  `ffmpeg -vf "subtitles=subs.srt:fontsdir=<folder with the brand's .ttf>:force_style='Fontname=Poppins,Fontsize=14,Outline=2'"`.
  Brand fonts are not installed system-wide (only DejaVu and Liberation are), so `fontsdir` is required or
  libass silently falls back to DejaVu Sans.
- Keep captions inside the format's safe zone (SKILL.md, Formats).

## Attach and mix

```bash
# attach the voice; apad pads it with silence so the picture keeps its full length
ffmpeg -i picture.mp4 -i voice.m4a -map 0:v -map 1:a -c:v copy -af apad -c:a aac -ar 48000 -shortest with_voice.mp4

# music bed under it, ducked under the voice
bash "$SKILL/scripts/composite.sh" mixaudio --video with_voice.mp4 --music bed.mp3 --duck --output mixed.mp4
```

Never attach with `-shortest` alone: when the voice is shorter than the picture, it cuts the picture.

## Loudness: −14 LUFS integrated, −1.5 dBTP true peak

```bash
ffmpeg -i mixed.mp4 -c:v copy -af "loudnorm=I=-14:TP=-1.5:LRA=11" -ar 48000 -c:a aac -b:a 192k final.mp4
```

For a music-only piece, add `afade` in and out to the same filter chain after trimming. `qa_render.py`
warns when integrated loudness is more than 1.5 LU off target or the true peak is above −1.0 dBFS (0.5 dB of
tolerance over the −1.5 target).
