# CLAUDE.md

## Overview

Generation plugin (started as a fork of `nano-banana-pro`). One skill, `image-gen`, with two scripts:

- `skills/image-gen/scripts/image.py`: images via `--model flash | pro | codex | agy` (Gemini API, gpt-image-2
  through the Codex CLI login, the Antigravity CLI image subagent). `gpt` is a deprecated alias of `codex`.
- `skills/image-gen/scripts/fal.py`: any fal.ai endpoint (`search`, `schema`, `price`, `run`, `result`,
  `upload`, `spend`). `run` passes a spend guard first: exit code 3 means refused; `--dry-run`, `--max-usd`,
  `--approved` and `--over-cap` control it, `FAL_APPROVE_USD` (default 0.50) and `FAL_MONTHLY_CAP_USD`
  configure it.

Usage, routing and traps live in `skills/image-gen/SKILL.md`; endpoint prices in
`skills/image-gen/references/fal-endpoints.md`; prompt structure in `references/prompt-craft.md`.

## Prerequisites

- `GEMINI_API_KEY` for `flash` / `pro`; a signed-in Codex CLI for `codex`; a signed-in `agy` for `agy`.
- `FAL_KEY` in the environment or `~/.secrets/fal.env`.
- Python 3.10+ with `uv`. Dependencies are inline (PEP 723).

## Tests

`scripts/test_image.py` and `scripts/test_fal.py` (pytest, fully offline; `test_fal.py` blocks the network and
never reads the real key). Run them in a container:

```bash
docker run --rm -v "$PWD":/repo:ro -w /repo/skills/image-gen/scripts python:3.12.11-slim \
  bash -c 'pip install -q pytest numpy fal-client && python -m pytest -q -p no:cacheprovider'
```
