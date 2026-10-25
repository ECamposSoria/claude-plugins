# Leg: music-video

A video for a song: an official-style music video, a visualizer, a lyric video, or footage or AI clips cut to
the beat. The song is the spine. It goes into the final file **unchanged**, and the picture is built on its
measured beats, bars, sections, drum hits, loudness and lyrics.

You cannot hear the song. The listener turns it into text and numbers. Never write that you listened to or
watched something; write what the analysis says.

## Budget: why this leg is strict about tokens

A public test (Devarf, 2026-10: Opus 5.5, one 79 s song, no guides) produced six finished videos. Low effort
took 42 min and ~78K output tokens (~$3 at API prices), 26 of those minutes waiting on renders. Max effort took
2 h 54 m and 625K tokens (~$49). Max with Ultracode (multi-agent review) wrote 2.5M+ tokens (~$348+), never
finished, and used three 5-hour limits. He could not rank the six results. Most of the cost was the agent
rediscovering a workflow and waiting on renders, which is what this leg removes. So:

- **One agent does the whole piece.** No Ultracode, no sub-agent per scene, no multi-agent review.
  (`hyperframes:music-to-video` dispatches one sub-agent per frame; use it only for a short lyric or kinetic-type
  cut, never for a full music video.)
- **Effort medium**; high only for 3D with characters. Never max by default.
- **Picture checks are stills and low-frame-rate drafts**, not full renders. One full-quality render at the end.
- **Three status posts** (in autonomous mode, post and continue): after the treatment, after the first
  full-length draft, before the final render.

## Picture sources

| The picture is | Build it with |
|---|---|
| Motion graphics: 2D, 3D (three.js), lyrics, characters, abstract | Hyperframes, this leg's Step 3 |
| AI footage nobody filmed | clips from `nano-banana-multi:image-gen`, repaired per [ai-footage.md](ai-footage.md), cut on the beat grid (Step 3b) |
| Real footage (an event, a band, a product) | [footage-edit.md](footage-edit.md) for the selects, cut on the beat grid (Step 3b) |
| A mix | the base from 3b, motion graphics over it, joined per SKILL.md "Hybrid assembly" |

## Step 1: listen

The listener runs in a container (models in the `listener-models` volume; build once, see
[../setup/listener/README.md](../setup/listener/README.md)). **Use the laptop GPU when it is free** (a 3:34 song:
2 min 20 s there, ~5 min on the VM's CPU; a 32 s song: 45 s). Put the song in the project's `song/` folder and
run it in the background:

```bash
P=<project dir>; mkdir -p "$P/song" && cp "<song file>" "$P/song/"
bash "$SKILL/scripts/listen_remote.sh" "$P/song/<song file>"          # laptop GPU; exit 3 = use the CPU line
docker compose -p listener -f "$SKILL/setup/listener/docker-compose.yml" run --rm \
  -v "$P/song":/work -v "$SKILL/scripts":/tool:ro listener /tool/listen.py "/work/<song file>" -o /work
```

Add `--language es` when you know it, and `--lyrics <file>` when the user can give the lyrics: the listener then
keeps their text and only times it. `--no-lyrics` for an instrumental. Whisper on separated vocals came out close
to verbatim on a live pop recording (median word confidence 0.97); words it was unsure of are marked `(?)`.

It writes into `song/`:

| File | What it holds |
|---|---|
| `README.md` | **Read this first.** Tempo, meter, key, a section table (time, bars, energy, vocals), loud and quiet parts, drum pattern per section, key moments, timed lyrics, and what is uncertain |
| `analysis.json` | Every measurement: beats, downbeats, bars, sections, drum hits (kick/snare/hat with strength), loudness per bar, silences, vocal melody and bass notes, chords, lyrics with word times, the source's SHA-256 and integrated loudness |
| `features.json` | One entry per video frame (default 30 fps): loudness, per-stem levels, kick/snare/hat envelopes, beat phase, bar and section index, 16 bands. Drives motion that reacts to the music |
| `stems/*.wav` | vocals, drums, bass, other (Demucs). For checking a moment, never for the final mix |

Then write the README's **"What the song is about"** section yourself, from the lyrics: 3–5 sentences, the
mood, the story if there is one. Say when the transcription looks unreliable rather than inventing meaning.

## Step 2: treatment (one page, before any code)

Write `treatment.md` in the project:

1. **Idea** in two sentences, and why it fits this song.
2. **Look**: palette, type (open-licensed fonts only, keep the licence file), 2D, 3D or both, one reference
   frame described in words.
3. **Story or dance logic**: who or what is on screen and how it changes across the sections.
4. **Music to picture**, from the README's numbers: section → scene; downbeats → cuts; kick → camera pulse or
   impact; snare → flash or accent; vocals → the character, mouth or lyric lines; bass → ground, scale or
   weight; quiet parts → slow and sparse; the biggest energy jump → the biggest visual change.
5. **Scene table** keyed to the README's section table: start–end, bars, what happens, what reacts to what.

Post it (checkpoint 1).

## Step 3: build with Hyperframes

Follow [animation-hyperframes.md](animation-hyperframes.md) and its traps, plus:

- **One project, one root composition, full song length.** Set the root `data-duration` to
  `analysis.json` → `source.duration_sec` and `data-fps` to the features' fps. Scenes are wrappers inside one
  full-length clip (Hyperframes trap 3). Keep templates and spare HTML outside the project folder: a second root
  file with `data-composition-id` fails lint (`multiple_root_compositions`) and can double the audio.
- **Song data as a script, not a fetch:** `printf 'window.SONG=%s;\n' "$(cat song/analysis.json)" > assets/song.js`
  and the same for `features.json` as `window.SONG_FEATURES`; load both with plain `<script src>` before the
  timeline. A `fetch` can land after the timeline is built.
- **Time comes only from the seek.** Read `SONG_FEATURES.frames[Math.min(n - 1, Math.round(t * fps))]` for the
  time Hyperframes gives you (GSAP `tl.call` per frame, as in `hyperframes:hyperframes-animation` §
  audio-reactive; three.js via `window.__hfThreeTime` / the `hf-seek` event, see its `adapters/three.md`).
  Never Web Audio, `requestAnimationFrame` loops, `Date.now()` or `performance.now()`: the renderer seeks frames
  out of order and has no live audio.
- **Cut times come from `analysis.json`**, never typed by hand: downbeats for cuts, section starts for scene
  changes. Snap each to the frame grid (`Math.round(t * fps) / fps`).
- **Randomness is seeded** (a small PRNG with a fixed seed), so a re-render gives the same frames.
- **Vendor everything** (three.js, GSAP, fonts) into `assets/`: no network at render time. Pin three.js in the
  project README.
- **3D on this VM is software WebGL** (Chrome's SwiftShader; the render summary says `software gpu`). Measured
  2026-10-25 with Hyperframes 0.8.198: twelve low-poly dancers, a floor, one shadow-casting light, fog and 2,000
  particles at 1080p rendered 120 frames in 11.8 s on 4 workers (~0.1 s a frame, so ~4 min for a 79 s song).
  Heavier looks (post-processing, many lights, big textures) cost more: time a 4 s draft of the heaviest scene
  before committing to it.
- **A three.js-only composition needs `data-no-timeline` on the root** (no GSAP timeline registered), or every
  render waits 45 s polling for one; `lint` flags it.
- Audio-reactive intensity: ≤5 % scale on text and logos, 10–30 % on big backgrounds; no equalizer bars,
  spectrum analysers or strobing unless the treatment asks for them.

### Step 3b: footage or AI clips cut to the beat

Take cut times from `analysis.json` (`bars[].start` for one cut per bar, every second or fourth bar for slower
songs, `sections[].start` for scene changes). Trim each clip to its slot with frame-accurate cuts
(`scripts/cut_from_transcript.py` takes an EDL), concatenate with `scripts/composite.sh concat`, then add any
motion graphics as a hybrid. AI clips come from image-gen at 24 fps: build the cut at 24 fps, or convert once,
not per clip.

## Step 4: check cheaply while building

- **Stills at the moments that matter:** `npx hyperframes snapshot --at <t>` at each section start, the biggest
  energy jump and two random bars; read the images.
- **Draft of the whole song:** `npx hyperframes render -q draft -f 10 -w 4` in the background (a third of the
  frames), then mux the song (Step 5) and run `qa_render.py --sheet` and `sync_check.py` on it. Post it
  (checkpoint 2).
- Fix, re-snapshot the changed scenes only. Re-render the draft only when timing changed.

## Step 5: final render, audio, checks

```bash
npx hyperframes render -q delivery -f 30 -w 4 -o renders/picture.mp4      # run_in_background; checkpoint 3 first
D=$(python3 -c 'import json;print(json.load(open("song/analysis.json"))["source"]["duration_sec"])')
ffmpeg -i renders/picture.mp4 -i "song/<song file>" -map 0:v -map 1:a -c:v copy -c:a aac -b:a 256k -ar 48000 \
  -t "$D" final/music-video.mp4
```

The song is mastered: **no `loudnorm`, no fades, no ducking** (the audio leg's −14 LUFS rule is for mixes we
make). Then both checks:

```bash
L=$(python3 -c 'import json;print(json.load(open("song/analysis.json"))["source"]["integrated_lufs"])')
uv run "$SKILL/scripts/qa_render.py" final/music-video.mp4 --expect-size 1920x1080 --expect-fps 30 \
  --expect-audio --expect-duration "$D" --duration-tol 0.05 --loudness-target "$L" --mode edit --sheet /tmp/sheet.jpg
uv run "$SKILL/scripts/sync_check.py" final/music-video.mp4 --song song/analysis.json --audio "song/<song file>"
```

`sync_check.py` FAILs when the file's audio is not the song (correlation), is offset from it by more than half a
frame, or is a different length; it WARNs when the picture's accents (cuts, flashes, hits) sit consistently
early or late against the beats and drum hits, and lists the worst ones. A creative off-beat cut is fine; a
constant 3-frame lag is a bug. Continuous motion (a swing peaking mid-beat) shows up as worst accents about half a
beat off with a median near 0: that is the motion, not a sync error. `qa_render.py`'s true-peak WARN is expected
when it matches the song's own `source.true_peak_dbfs`; say so in the report instead of limiting the audio.

Measured end to end on 2026-10-25 (a 32 s test song, a three.js scene of 12 dancers reacting to `kick`,
`beat_phase`, `level` and section starts): listener 45 s on the laptop GPU, draft at 10 fps 34 s, delivery at
30 fps 96 s, both checks PASS with audio lag 0.0 ms and correlation 1.000.

## Step 6: report

Write `report.md` next to the video: what it is and the idea behind it, how it was made (tools, versions),
what was checked (paste the two summaries), and what you are unsure about (lyrics accuracy, a section the
analysis labelled with low confidence, a look that suffers at software-WebGL quality). Deliver per SKILL.md
Step 3.
