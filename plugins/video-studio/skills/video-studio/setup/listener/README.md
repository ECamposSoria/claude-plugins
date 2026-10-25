# Song listener (`scripts/listen.py`)

Turns a song into text and numbers for an agent that cannot hear it: separated stems, beats and bars, drum
hits, loudness, sections, melody, bass, key and chords, timed lyrics, per-frame features, and a `README.md`
song brief. Used by the music-video leg ([../../legs/music-video.md](../../legs/music-video.md)).

Everything runs locally from open models; no API key and no per-use cost. The models download once into the
`listener-models` volume:

| Stage | Model / library | Licence |
|---|---|---|
| Stems (vocals, drums, bass, other) | Demucs 4.1.0, `htdemucs` | MIT |
| Beats and downbeats | Beat This! 1.1.0, checkpoint `final0` (77 MB) | MIT |
| Lyrics with word times | faster-whisper 1.2.1, `large-v3-turbo` (~1.6 GB) | MIT |
| Onsets, pitch, chroma, loudness | librosa 1.0.0 | ISC |

## Two images, same script

| Where | Image | Build | Speed (measured 2026-10-25) |
|---|---|---|---|
| The laptop's RTX 4070 (WSL Docker), **default when free** | `video-studio-listener:0.1.0-cu128` (13.2 GB) | on the laptop, from `~/listener/setup/`: `docker compose -p listener -f docker-compose.gpu.yml build` | 3:34 song: 2 min 20 s wall (stems 17 s, lyrics 13 s, the rest is CPU-bound pitch and structure work); 32 s song: 45 s |
| The VM (CPU, when the laptop is off or busy) | `video-studio-listener:0.1.0` (3.3 GB) | `docker compose -p listener -f docker-compose.yml build` | 3:34 song: 4 min 53 s (stems 133 s, lyrics 96 s); peak 3.3 GB of the 5 GB cap |

Both pin Python 3.12.12, torch and
torchaudio 2.11.0, and the rest from `requirements.txt` (a `pip freeze` of the working image, torch excluded
because the Dockerfile installs the CPU or CUDA build first).

## Run

On the VM (background it: a 3-minute song takes a few minutes):

```bash
docker compose -p listener -f "$SKILL/setup/listener/docker-compose.yml" run --rm \
  -v "<song dir>":/work -v "$SKILL/scripts":/tool:ro listener /tool/listen.py "/work/<song file>" -o /work
```

On the laptop GPU, from the VM, with local paths:

```bash
bash "$SKILL/scripts/listen_remote.sh" "<song dir>/<song file>" [-o <out dir>] [--language es] [--lyrics lyrics.txt]
```

It checks the GPU is free first (exit 3 and the list of containers there when it is not: ask the owner, or use
the CPU), copies the song and `listen.py` by `scp` into `C:\Users\docam\listener\jobs\<job>\` (WSL sees it as
`/mnt/c/...`), runs the CUDA image with `--device cuda` (`run --rm`, so the VRAM is free afterwards), copies the
results back by `scp` and deletes the job folder, also on failure. Exit 3 also means unreachable, image missing or
a failed transfer: run the CPU command instead. 🔴 Files never go through the ssh→cmd→WSL pipe: 150 MB of stems
stalled it until ssh gave up, while `scp` to the Windows side moved the same 147 MB in 1.3 s.

Updating the laptop copy after changing the Dockerfile or `requirements.txt`:

```bash
tar -C "$SKILL/setup/listener" -cf - Dockerfile requirements.txt .dockerignore docker-compose.gpu.yml \
  | ssh lenovo-nat 'wsl -- bash -lc "mkdir -p ~/listener/setup && tar -C ~/listener/setup -xf - && cd ~/listener/setup && docker compose -p listener -f docker-compose.gpu.yml build"'
```

## Tests

```bash
docker compose -p listener -f "$SKILL/setup/listener/docker-compose.yml" run --rm --entrypoint sh \
  -v "$SKILL/scripts":/tool:ro listener -c 'pip install --quiet --user pytest && cd /tmp && python -m pytest -q -p no:cacheprovider /tool/test_listen.py'
```

The tests replace the three models with fakes, so they need no downloads.

## Notes

- One-shot tool, not a service: no ports, no healthcheck, `restart: "no"`; `run --rm` removes the container.
- It runs as uid 1000 so output files belong to the VM user (and the laptop's `eze`).
- Lyrics: Whisper runs **without** its voice-activity filter. Silero VAD is trained on speech and kept 39 words of
  a live pop vocal stem; without it, 316 words at median confidence 0.97, close to verbatim. Text invented over
  silence is dropped by the listener's own check (vocals below -45 dBFS). When exact words matter, give the
  lyrics as a text file with `--lyrics` and the listener only times them.
- Sections: librosa's Laplacian segmentation (repetition clusters, McFee & Ellis), cluster count from the
  eigengap, sections at least 4 bars (2 for songs under a minute). The live test song came out verse, chorus,
  bridge, chorus, verse, chorus. Labels with `?` are guesses.
- Drums: one type per onset. On a dense mix a clap or hat that lands with a kick counts as the kick (band-split
  detection was tried: the kick leaks into every band). `drums` (the stem's level) and `kick` are the reliable
  signals for motion.
- Basic Pitch (Spotify's note transcriber) is not included: it needs TensorFlow < 2.15.1, which has no Python 3.12
  build, and librosa 1.0 requires 3.12. Melody and bass come from librosa's pYIN on the separated stems.
