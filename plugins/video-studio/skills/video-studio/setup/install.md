# Setup

State of this VM, verified 2026-10-24. Check before reinstalling anything.

| Piece | State | Check |
|---|---|---|
| ffmpeg / ffprobe | 6.1.1 (libx264 + aac) | `ffmpeg -version` |
| faster-whisper | 1.2.1 in `~/.venvs/video-studio` | `~/.venvs/video-studio/bin/python -c "import faster_whisper"` |
| node / npx | v22 | `node -v` |
| uv | installed (runs `qa_render.py` with numpy, no venv needed) | `uv --version` |
| Hyperframes | via `npx`; its own `chrome-headless-shell` in `~/.cache/hyperframes/chrome/` | `npx hyperframes doctor` |
| `unzip` | installed (without it Hyperframes falls back to snap Chromium and hangs) | `which unzip` |
| ElevenLabs key | `~/.secrets/elevenlabs.env` as `ELEVENLABS_API_KEY` | never print it |
| fal key | `~/.secrets/fal.env`, used through the `image-gen` skill | never print it |

## Rebuilding the transcription venv (a fresh VM only)

Heavy (CTranslate2 and tokenizers wheels): hand these to the user or run them in the background.

```bash
python3 -m venv ~/.venvs/video-studio
~/.venvs/video-studio/bin/pip install --upgrade pip
~/.venvs/video-studio/bin/pip install "faster-whisper==1.2.1"
```

Models download on first use into `~/.cache/huggingface/`:

| Model | Size | CPU speed (int8) | Use for |
|-------|------|------------------|---------|
| `small` | ~0.5 GB | ~5–8× realtime | default; clean speech |
| `medium` | ~1.5 GB | ~2–3× realtime | accents, some noise |
| `large-v3` | ~3 GB | ~1× realtime | noisy audio, max accuracy |

## Hyperframes browser

If `render` hangs with no output, point it at its own headless shell (see
[../legs/animation-hyperframes.md](../legs/animation-hyperframes.md), trap 1):

```bash
export HYPERFRAMES_BROWSER_PATH=$(ls -d ~/.cache/hyperframes/chrome/chrome-headless-shell/*/chrome-headless-shell-linux64)/chrome-headless-shell
```

## Not installed, on purpose

VoiceStudio (local voice cloning) and the `heygen` CLI (Hyperframes' free TTS path) are not installed. See
[../legs/audio.md](../legs/audio.md) before adding either.
