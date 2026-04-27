# Nano Banana Multi — Design

**Date:** 2026-04-27
**Status:** Approved (brainstorming)

## Objective

Fork the upstream `nano-banana-pro` Claude Code plugin into a local plugin that, in addition to Google Gemini Flash and Pro image models, also supports OpenAI's `gpt-image-2`. Single CLI surface, three providers selected via `--model`.

## Why a fork

The upstream plugin lives under `/home/eze/.claude/plugins/marketplaces/buildatscale-claude-code/plugins/nano-banana-pro/`. Edits there get wiped on marketplace sync. A local fork at `/home/eze/projects/claude-plugins/nano-banana-multi/` is owned by us and survives upstream updates. The plugin is small (one Python script + one SKILL.md), so the maintenance cost is near zero.

## Repository layout

```
/home/eze/projects/claude-plugins/nano-banana-multi/
├── .claude-plugin/
│   └── plugin.json
├── CLAUDE.md
├── README.md
├── docs/
│   └── 2026-04-27-nano-banana-multi-design.md   # this file
└── skills/
    └── image-gen/
        ├── SKILL.md
        └── scripts/
            └── image.py
```

Skill renamed from `generate` to `image-gen` to avoid collision with the upstream `nano-banana-pro` skill if both stay installed. Triggers in the SKILL.md description still cover phrases like "generate an image", "create an image", "nano banana", "gpt image".

## CLI surface

Single script, single `--model` switch.

| Flag | Values | Required | Notes |
|---|---|---|---|
| `--model` | `flash` (default) \| `pro` \| `gpt` | no | `gpt` → `gpt-image-2` |
| `--prompt` | str | yes | all models |
| `--output` | path | yes | all models, written as PNG |
| `--aspect` | `square` \| `landscape` \| `portrait` | no | square is default |
| `--reference` | path (repeatable) | no | for `gpt`, routes call to `images.edit` |
| `--size` | `1K` \| `2K` \| `4K` | no | applies to `pro` and `gpt`; ignored for `flash` |
| `--quality` | `auto` (default) \| `low` \| `medium` \| `high` | no | `gpt` only; ignored for `flash` and `pro` |

### `gpt` size mapping

| `--size` | square | landscape (16:9) | portrait (9:16) |
|---|---|---|---|
| 1K | `1024x1024` | `1536x1024` | `1024x1536` |
| 2K | `2048x2048` | `2048x1152` | `1152x2048` |
| 4K | not supported (8.29M-px cap) — falls back to 2K square with stderr warning | `3840x2160` | `2160x3840` |

## Script architecture

```python
PROVIDERS = {
    "flash": ("gemini", "gemini-2.5-flash-image"),
    "pro":   ("gemini", "gemini-3-pro-image-preview"),
    "gpt":   ("openai", "gpt-image-2"),
}

def main():
    args = parse_args()
    provider, model_id = PROVIDERS[args.model]
    if provider == "gemini":
        generate_gemini(model_id, args)   # existing logic, unchanged
    else:
        generate_openai(model_id, args)   # new
```

### `generate_openai`

1. Read `OPENAI_API_KEY` from env. Exit 1 with a clear message if unset.
2. Resolve `(aspect, size) → openai_size` using the mapping above. Warn-and-downgrade for the unsupported 4K-square case.
3. Build args: `prompt`, `size`, `quality`. Default `quality="auto"`.
4. Branch on references:
   - With references: `client.images.edit(model=..., image=[open(p, "rb") for p in refs], prompt=..., size=..., quality=...)`. Validate each reference path exists first.
   - Without: `client.images.generate(model=..., prompt=..., size=..., quality=...)`.
5. Decode `result.data[0].b64_json` → write bytes to `--output`. Ensure parent directory exists.
6. Print `Image saved to: <output>` on success.

### Dependencies (PEP 723 inline)

Add `openai>=1.0.0` alongside the existing `google-genai` and `pillow`. `uv run` resolves them per invocation.

## Environment / API keys

- `GEMINI_API_KEY` — required for `--model flash` and `--model pro`. Already documented upstream.
- `OPENAI_API_KEY` — required only for `--model gpt`. To be exported in `~/.bashrc` on this VM. The actual key value is the `sk-proj-...` already in use by the `scraper-api` / `scraper-worker` / `scraper-stealth` containers on the DigitalOcean droplet.

The script never reads any secret outside `os.environ`.

## SKILL.md / docs updates

- Add a third row to the model table: `gpt` → `gpt-image-2`, "OpenAI multimodal, supports edits with multi-reference".
- Update the Prerequisites section to list both env vars, marked as "required only if using that provider".
- Add one usage block per new capability: text→image with `--model gpt` and a multi-reference edit example.

## Out of scope

- Mask-based inpainting (OpenAI's `mask` parameter). Easy to add later behind a `--mask` flag.
- Alternate output formats / compression (`jpeg` / `webp` / `output_compression`). Default to PNG to match existing behavior.
- Transparent background. `gpt-image-2` does not support it; flash/pro behavior unchanged.
- Streaming / batch.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Both upstream `nano-banana-pro` and our fork register skills that match the same triggers — duplicate or non-deterministic skill invocation. | README instructs the user to disable the upstream plugin. Skill name is also unique (`image-gen` vs upstream `generate`) so it's possible to coexist if the user prefers. |
| `OPENAI_API_KEY` accidentally committed to a `.env` file in the project. | We rely on `~/.bashrc` (per user choice), so no `.env` file is created. `.gitignore` will still ignore `.env*` defensively. |
| `gpt-image-2` API surface changes between snapshot dates. | Pin nothing in the SDK call beyond `model="gpt-image-2"`; the SDK pin is `openai>=1.0.0`. Any breakage surfaces as a clear API error and we update the script. |
