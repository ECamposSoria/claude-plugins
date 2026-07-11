# One-time setup

Run these once per VM. All local, no sudo. **Propose them to the user and let them run and paste output** — the whisper install pulls sizeable wheels (CTranslate2, tokenizers) and is a heavy op.

## Footage-edit leg — faster-whisper in a venv

The VM has no system `pip3`, so use a venv. `python3 -m venv` is verified working here.

```bash
python3 -m venv ~/.venvs/video-studio
~/.venvs/video-studio/bin/pip install --upgrade pip
~/.venvs/video-studio/bin/pip install "faster-whisper==1.2.1"
```

Verify:

```bash
~/.venvs/video-studio/bin/python -c "import faster_whisper; print('faster-whisper', faster_whisper.__version__)"
```

Then always run the transcription script with that interpreter:

```bash
~/.venvs/video-studio/bin/python <skill>/scripts/transcribe.py <media> --model small
```

**Models** download on first use into `~/.cache/huggingface/`. Rough sizes / CPU speed:

| Model | Size | CPU speed (int8) | Use for |
|-------|------|------------------|---------|
| `small` | ~0.5 GB | ~5–8× realtime | default; clean speech |
| `medium` | ~1.5 GB | ~2–3× realtime | accents, some noise |
| `large-v3` | ~3 GB | ~1× realtime | noisy audio, max accuracy |

## Hyperframes leg — no install step

Hyperframes runs via `npx` (Node 22+ is present, v22.22.1). First `npx hyperframes ...` fetches the CLI. For deterministic BeginFrame renders it may download `chrome-headless-shell` into its own cache; if that fetch fails it falls back to screenshot mode on the system chromium.

Optionally vendor its agent skills (authoring rules that track upstream):

```bash
npx skills add heygen-com/hyperframes --full-depth --yes
```

## Already present (verified)

ffmpeg 6.1.1 (libx264 + aac), ffprobe, node v22.22.1, npm/npx, python 3.12, git, chromium. Nothing to do.
