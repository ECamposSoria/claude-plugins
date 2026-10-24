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
| VoiceStudio (debpalash/VoiceStudio 0.5.6, AGPL) | free, local | **Yes** | Installed in Docker (below). **Slow on this CPU-only VM: a 30 s voiceover takes ~9 min.** The only way to a natural Argentine voice: clone a consenting native speaker. |
| The user records it | free | it is their voice | Often the best option: transcribe it with `transcribe.py` and cut it like footage. |

🔴 Clone a voice only with the explicit permission of the person whose voice it is. VoiceStudio does **not**
enforce this: its API generates with a profile that has no consent recorded. Record consent anyway (below).

**Which one** (measured 2026-10-24 on the same 446-character Spanish script):

| | ElevenLabs (Matilda, multilingual v2) | VoiceStudio (OmniVoice, CPU) |
|---|---|---|
| Time for ~30 s of audio | **9 s** | **~9 min** in sentence chunks (13 min as one block) |
| Intelligibility (Whisper word error rate) | 1.4 % | 1.4 % |
| Accent | foreign (premade voices are not native Spanish speakers) | foreign with the built-in voices; **native only when cloning a native speaker** |
| Cloning | not on our plan | yes, 3–20 s of clean reference |
| Cost | 10,000 characters a month included (~20 voiceovers of 30 s); the plan cannot be extended | free |

Use ElevenLabs for quick drafts and anything iterated many times. Use VoiceStudio when the piece needs a specific
real voice (cloned, with consent), or when the month's ElevenLabs characters are spent, and run it in the background.

### VoiceStudio: how to run it

```bash
C="$SKILL/setup/voicestudio/docker-compose.yml"
# --wait returns only once the healthcheck passes (~10 s); without it the first request can hit a 503
docker compose -p voicestudio -f "$C" up -d --wait --wait-timeout 300
set -a; . ~/.secrets/voicestudio.env; set +a        # OMNIVOICE_API_KEY, never print it
H="Authorization: Bearer $OMNIVOICE_API_KEY"

# speech (run with run_in_background: ~11-19x slower than realtime); add -F profile_id=<id> for a cloned voice
# text fields use --form-string: with -F a value starting with " or @ is curl syntax, not text
curl -fsS -H "$H" --form-string "text=$(cat script.txt)" -F language=es -F max_chunk_chars=140 \
     -o voice.wav --max-time 1800 http://127.0.0.1:3900/generate && file voice.wav   # -f: an error never lands in voice.wav

# clone a voice: 3-20 s of clean speech plus its exact transcript (transcribe it with transcribe.py)
curl -fsS -H "$H" --form-string "name=<person>" -F kind=clone -F language=es --form-string "ref_text=<transcript>" \
     -F ref_audio=@reference.wav http://127.0.0.1:3900/profiles          # -> {"id": "<profile id>", ...}
# consent: the person reads a consent statement; store both with the profile
curl -fsS -H "$H" --form-string "consent_text=<what they read>" -F consent_audio=@consent.wav \
     http://127.0.0.1:3900/profiles/<id>/consent

docker compose -p voicestudio -f "$C" down            # when done; voices and the model stay in the volume
```

Output is 24 kHz mono WAV. Peak memory was 3.4 GB of the container's 5 GB cap. `max_chunk_chars=140` renders the
script sentence by sentence, which is ~1.5x faster than one long block; the default step count is already the
fastest (raising `num_step` only slows it). Other routes: `GET /profiles`, `DELETE /profiles/<id>`,
`/v1/audio/speech` (OpenAI-compatible), and an MCP server at `http://127.0.0.1:3900/mcp/`.

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
