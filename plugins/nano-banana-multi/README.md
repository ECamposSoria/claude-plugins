# nano-banana-multi

Claude Code plugin for AI generation: images (Gemini, gpt-image-2 through the Codex CLI, the Antigravity CLI
image subagent) and, through fal.ai, video clips and 3D models. Started as a fork of `nano-banana-pro`. The
skill registers as `image-gen`.

## Install

From the `eze-claude-plugins` marketplace: `claude plugin install nano-banana-multi@eze-claude-plugins`.
If the upstream `nano-banana-pro` plugin is also installed, disable it to avoid duplicate triggers.

## Credentials (each only for its backend)

| Backend | Needs |
|---|---|
| `--model flash` / `pro` | `export GEMINI_API_KEY=...` |
| `--model codex` | Codex CLI signed in (bills the ChatGPT plan; no `OPENAI_API_KEY`) |
| `--model agy` | Antigravity CLI signed in (bills the Google AI Pro subscription) |
| `fal.py` | `FAL_KEY=...` in `~/.secrets/fal.env` (mode 600), or exported |

## Spend guard

Every `fal.py run` estimates its cost first. Runs above `FAL_APPROVE_USD` (default $0.50) need `--approved`,
which the agent passes only after the user agrees. Set `FAL_MONTHLY_CAP_USD` (environment or `fal.env`) to
cap the month. `fal.py spend` shows real spend per endpoint.

## Smoke test (free)

```bash
uv run skills/image-gen/scripts/image.py --model agy \
  --prompt "A minimalist tangerine on white" --output ./smoke.png
uv run skills/image-gen/scripts/fal.py run fal-ai/flux/schnell --arg prompt="a tangerine" \
  --max-usd 0.01 --dry-run --out ./smoke/     # prints "Allowed", exits 0, submits nothing
```
