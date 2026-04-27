# nano-banana-multi

Multi-provider image generation Claude Code plugin. Forked from the upstream `nano-banana-pro` plugin to add OpenAI `gpt-image-2` support.

## Install (local plugin)

Add this folder to Claude Code's plugin sources, then enable in `/plugin`. The skill registers as `image-gen`.

To avoid duplicate triggers, disable the upstream `nano-banana-pro` plugin (or leave both — the skill names don't collide).

## Environment setup (this VM)

Add to `~/.bashrc`:

```bash
export GEMINI_API_KEY="<your-google-ai-key>"
export OPENAI_API_KEY="<your-openai-key>"
```

Each key is only required if you actually use that provider.

## Manual smoke test

```bash
uv run skills/image-gen/scripts/image.py \
  --prompt "A minimalist tangerine on white" \
  --output /tmp/smoke.png \
  --model gpt
```
