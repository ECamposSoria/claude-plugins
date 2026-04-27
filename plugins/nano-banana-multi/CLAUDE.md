# CLAUDE.md

## Overview

Local fork of `nano-banana-pro` that adds OpenAI `gpt-image-2` as a third image-generation backend alongside Google Gemini Flash and Pro. Single CLI surface, provider selected via `--model`.

## Running the script

```bash
uv run skills/image-gen/scripts/image.py \
  --prompt "Your image description" \
  --output "/path/to/output.png"
```

Options:
- `--prompt` (required): Image description
- `--output` (required): Output PNG path
- `--aspect` (optional): `square` (default) | `landscape` | `portrait`
- `--reference` (optional, repeatable): Path to a reference image
- `--model` (optional): `flash` (default) | `pro` | `gpt`
- `--size` (optional): `1K` (default) | `2K` | `4K` (applies to `pro` and `gpt`)
- `--quality` (optional): `auto` (default) | `low` | `medium` | `high` (applies to `gpt` only)

## Prerequisites

- `GEMINI_API_KEY` env var: required for `--model flash` and `--model pro`
- `OPENAI_API_KEY` env var: required for `--model gpt`
- Python 3.10+ with `uv`. Dependencies are inline (PEP 723).
