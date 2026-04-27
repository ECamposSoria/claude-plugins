# Nano Banana Multi Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fork the upstream `nano-banana-pro` Claude Code plugin into a local plugin that adds OpenAI `gpt-image-2` as a third image-generation backend alongside Gemini Flash and Pro.

**Architecture:** Single Python script (`uv run` with PEP 723 inline deps) dispatches on `--model` to either the Gemini path (existing) or the new OpenAI path. New skill name `image-gen` to avoid collision with the upstream `generate` skill.

**Tech Stack:** Python 3.10+, `uv`, `google-genai`, `openai>=1.0.0`, `pillow`. No test framework needed beyond `pytest` for two pure helper functions.

**Spec:** [docs/2026-04-27-nano-banana-multi-design.md](2026-04-27-nano-banana-multi-design.md)

---

## File Structure

| File | Purpose |
|---|---|
| `.claude-plugin/plugin.json` | Plugin manifest (name, version, description) |
| `.gitignore` | Standard Python + ignore `.env*` defensively |
| `CLAUDE.md` | Top-level guidance, mirrors upstream with multi-provider notes |
| `README.md` | Install + env setup instructions for this VM |
| `skills/image-gen/SKILL.md` | Skill definition; updated triggers + docs for all three providers |
| `skills/image-gen/scripts/image.py` | Main script. Provider dispatcher + `generate_gemini` + `generate_openai` |
| `skills/image-gen/scripts/test_image.py` | pytest unit tests for the pure helpers (`_openai_size`, aspect mapping) |

---

## Task 1: Plugin scaffolding

**Files:**
- Create: `.claude-plugin/plugin.json`
- Create: `.gitignore`
- Create: `CLAUDE.md`
- Create: `README.md`

- [ ] **Step 1: Create the plugin manifest**

Path: `/home/eze/projects/claude-plugins/nano-banana-multi/.claude-plugin/plugin.json`

```json
{
  "name": "nano-banana-multi",
  "version": "0.1.0",
  "description": "Multi-provider image generation skill: Google Gemini (Flash, Pro) + OpenAI gpt-image-2.",
  "author": "eze"
}
```

- [ ] **Step 2: Create `.gitignore`**

Path: `/home/eze/projects/claude-plugins/nano-banana-multi/.gitignore`

```
__pycache__/
*.pyc
.pytest_cache/
.env
.env.*
*.egg-info/
.uv-cache/
```

- [ ] **Step 3: Create `CLAUDE.md`**

Path: `/home/eze/projects/claude-plugins/nano-banana-multi/CLAUDE.md`

```markdown
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
```

- [ ] **Step 4: Create `README.md`**

Path: `/home/eze/projects/claude-plugins/nano-banana-multi/README.md`

```markdown
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
```

- [ ] **Step 5: Commit**

```bash
cd /home/eze/projects/claude-plugins/nano-banana-multi
git add .claude-plugin/plugin.json .gitignore CLAUDE.md README.md
git commit -m "chore: scaffold nano-banana-multi plugin"
```

---

## Task 2: Port upstream script verbatim as baseline

**Files:**
- Create: `skills/image-gen/scripts/image.py` (copy of upstream)
- Create: `skills/image-gen/SKILL.md` (copy of upstream, skill name renamed)

- [ ] **Step 1: Copy the upstream script**

```bash
mkdir -p /home/eze/projects/claude-plugins/nano-banana-multi/skills/image-gen/scripts
cp /home/eze/.claude/plugins/marketplaces/buildatscale-claude-code/plugins/nano-banana-pro/skills/generate/scripts/image.py \
   /home/eze/projects/claude-plugins/nano-banana-multi/skills/image-gen/scripts/image.py
```

- [ ] **Step 2: Copy the upstream SKILL.md and rename the skill**

```bash
cp /home/eze/.claude/plugins/marketplaces/buildatscale-claude-code/plugins/nano-banana-pro/skills/generate/SKILL.md \
   /home/eze/projects/claude-plugins/nano-banana-multi/skills/image-gen/SKILL.md
```

Then edit the frontmatter `name:` line at the top of the new SKILL.md from:

```
name: generate
```

to:

```
name: image-gen
```

(Use `Edit` tool with the exact line replacement; do not touch the description yet — that gets updated in Task 6.)

- [ ] **Step 3: Smoke-check that it still runs (Gemini Flash baseline)**

Skip if `GEMINI_API_KEY` is not set in your shell. If set:

```bash
cd /home/eze/projects/claude-plugins/nano-banana-multi
uv run skills/image-gen/scripts/image.py \
  --prompt "A small green apple on white background" \
  --output /tmp/baseline.png \
  --model flash
```

Expected: `Image saved to: /tmp/baseline.png` and the file exists. If `GEMINI_API_KEY` is unset, that's fine — skip and note it for the user to do manually later.

- [ ] **Step 4: Commit**

```bash
git add skills/image-gen/
git commit -m "chore: copy upstream script as baseline"
```

---

## Task 3: Add unit tests for OpenAI size mapping (failing)

**Files:**
- Create: `skills/image-gen/scripts/test_image.py`

The size mapping is the one piece of pure business logic worth unit-testing. We TDD that.

- [ ] **Step 1: Write the failing tests**

Path: `/home/eze/projects/claude-plugins/nano-banana-multi/skills/image-gen/scripts/test_image.py`

```python
# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""Pure-function tests. Run: `uv run pytest skills/image-gen/scripts/test_image.py -v`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest
from image import _openai_size


@pytest.mark.parametrize(
    "aspect,size,expected",
    [
        ("square",    "1K", "1024x1024"),
        ("landscape", "1K", "1536x1024"),
        ("portrait",  "1K", "1024x1536"),
        ("square",    "2K", "2048x2048"),
        ("landscape", "2K", "2048x1152"),
        ("portrait",  "2K", "1152x2048"),
        ("landscape", "4K", "3840x2160"),
        ("portrait",  "4K", "2160x3840"),
    ],
)
def test_openai_size_supported(aspect, size, expected):
    assert _openai_size(aspect, size) == expected


def test_openai_size_4k_square_falls_back_to_2k_square():
    # 4K square (3840x3840 = 14.7M px) exceeds the 8.29M px cap;
    # the helper must downgrade to 2K square rather than return an invalid size.
    assert _openai_size("square", "4K") == "2048x2048"
```

- [ ] **Step 2: Run tests to verify they fail (function not defined)**

```bash
cd /home/eze/projects/claude-plugins/nano-banana-multi
uv run --with pytest pytest skills/image-gen/scripts/test_image.py -v
```

Expected: collection or import error — `_openai_size` is not defined in `image.py` yet.

- [ ] **Step 3: Commit the failing tests**

```bash
git add skills/image-gen/scripts/test_image.py
git commit -m "test: add failing tests for openai size mapping"
```

---

## Task 4: Implement `_openai_size` to make tests pass

**Files:**
- Modify: `skills/image-gen/scripts/image.py` (move SDK imports inside `generate_image`, add `_openai_size` helper)

- [ ] **Step 1: Make SDK imports lazy so `_openai_size` is independently importable**

Currently `image.py` does `from google import genai`, `from google.genai import types`, and `from PIL import Image` at module top level. The pytest test env declares only `pytest` (correctly — it's a pure-function test), so importing `image` blows up at SDK load before reaching the `_openai_size` symbol. Move those three imports inside `generate_image()`.

Concretely, in `skills/image-gen/scripts/image.py`:

a) Delete these three lines from the top of the file (keep `argparse`, `os`, `sys`):

```python
from google import genai
from google.genai import types
from PIL import Image
```

b) Add them as the first lines inside the `generate_image(...)` function body, before any other code:

```python
def generate_image(
    prompt: str,
    output_path: str,
    aspect: str = "square",
    references: list[str] | None = None,
    model: str = "flash",
    size: str = "1K",
) -> None:
    """Generate an image using Gemini and save to output_path."""
    from google import genai
    from google.genai import types
    from PIL import Image

    api_key = os.environ.get("GEMINI_API_KEY")
    # ... rest unchanged
```

This is a pure import relocation — no runtime behavior change for end users (the SDK is still loaded the first time `generate_image` runs).

- [ ] **Step 2: Add the helper to `image.py`**

Insert this block after the existing `get_aspect_instruction` function in `skills/image-gen/scripts/image.py`:

```python
# OpenAI gpt-image-2 size presets per (aspect, size) tuple.
# 4K square (3840x3840 = 14.7M px) exceeds the 8.29M-px cap, so we downgrade
# it to 2K square and emit a warning at call sites.
_OPENAI_SIZES = {
    ("square",    "1K"): "1024x1024",
    ("landscape", "1K"): "1536x1024",
    ("portrait",  "1K"): "1024x1536",
    ("square",    "2K"): "2048x2048",
    ("landscape", "2K"): "2048x1152",
    ("portrait",  "2K"): "1152x2048",
    ("square",    "4K"): "2048x2048",  # downgrade
    ("landscape", "4K"): "3840x2160",
    ("portrait",  "4K"): "2160x3840",
}


def _openai_size(aspect: str, size: str) -> str:
    """Resolve (aspect, size) to a gpt-image-2 size string."""
    return _OPENAI_SIZES[(aspect, size)]
```

- [ ] **Step 3: Run tests to verify they pass**

```bash
cd /home/eze/projects/claude-plugins/nano-banana-multi
uv run --with pytest pytest skills/image-gen/scripts/test_image.py -v
```

Expected: `9 passed`. The tests must now actually exercise `_openai_size`, not fail at SDK import.

- [ ] **Step 4: Commit**

```bash
cd /home/eze/projects/claude-plugins/nano-banana-multi
git -c user.email=ezetommycien@gmail.com -c user.name=eze \
  add skills/image-gen/scripts/image.py
git -c user.email=ezetommycien@gmail.com -c user.name=eze \
  commit -m "feat: add openai size mapping helper"
```

---

## Task 5: Wire up the OpenAI provider end-to-end

**Files:**
- Modify: `skills/image-gen/scripts/image.py`

This task does several edits to the same file. Group them into one commit since they only make sense together.

- [ ] **Step 1: Add `openai` to inline dependencies**

Top of `skills/image-gen/scripts/image.py`. Replace the existing PEP 723 block:

```python
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "google-genai",
#     "pillow",
# ]
# ///
```

with:

```python
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "google-genai",
#     "openai>=1.0.0",
#     "pillow",
# ]
# ///
```

- [ ] **Step 2: Update `MODEL_IDS` and add a provider mapping**

Replace the existing `MODEL_IDS` dict near the top of the file with:

```python
MODEL_IDS = {
    "flash": "gemini-2.5-flash-image",
    "pro":   "gemini-3-pro-image-preview",
    "gpt":   "gpt-image-2",
}

PROVIDERS = {
    "flash": "gemini",
    "pro":   "gemini",
    "gpt":   "openai",
}
```

- [ ] **Step 3: Add the `generate_openai` function**

Insert this function after the existing `generate_image` function in `image.py`:

```python
def generate_openai(
    prompt: str,
    output_path: str,
    aspect: str = "square",
    references: list[str] | None = None,
    size: str = "1K",
    quality: str = "auto",
) -> None:
    """Generate an image using OpenAI gpt-image-2 and save to output_path."""
    import base64
    import contextlib
    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)

    if aspect == "square" and size == "4K":
        print(
            "Warning: 4K square exceeds gpt-image-2's 8.29M-px cap; "
            "downgrading to 2K square (2048x2048).",
            file=sys.stderr,
        )

    openai_size = _openai_size(aspect, size)
    client = OpenAI(api_key=api_key)
    model_id = MODEL_IDS["gpt"]

    if references:
        for ref_path in references:
            if not os.path.exists(ref_path):
                print(f"Error: Reference image not found: {ref_path}", file=sys.stderr)
                sys.exit(1)
        with contextlib.ExitStack() as stack:
            image_files = [stack.enter_context(open(p, "rb")) for p in references]
            result = client.images.edit(
                model=model_id,
                image=image_files,
                prompt=prompt,
                size=openai_size,
                quality=quality,
            )
    else:
        result = client.images.generate(
            model=model_id,
            prompt=prompt,
            size=openai_size,
            quality=quality,
        )

    if not result.data or not result.data[0].b64_json:
        print("Error: No image data in OpenAI response", file=sys.stderr)
        sys.exit(1)

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    image_bytes = base64.b64decode(result.data[0].b64_json)
    with open(output_path, "wb") as f:
        f.write(image_bytes)

    print(f"Image saved to: {output_path}")
```

- [ ] **Step 4: Add `--quality` to the argparse layer and dispatch on provider**

Find the `main()` function in `image.py`. Replace its body with:

```python
def main():
    parser = argparse.ArgumentParser(
        description="Generate images using Gemini (Flash, Pro) or OpenAI (gpt-image-2)"
    )
    parser.add_argument("--prompt", required=True, help="Description of the image to generate")
    parser.add_argument("--output", required=True, help="Output file path (PNG format)")
    parser.add_argument(
        "--aspect",
        choices=["square", "landscape", "portrait"],
        default="square",
        help="Aspect ratio (default: square)",
    )
    parser.add_argument(
        "--reference",
        action="append",
        dest="references",
        help="Path to a reference image (repeatable for multiple references)",
    )
    parser.add_argument(
        "--model",
        choices=["flash", "pro", "gpt"],
        default="flash",
        help="Model: flash (Gemini fast), pro (Gemini high-quality), gpt (OpenAI gpt-image-2)",
    )
    parser.add_argument(
        "--size",
        choices=["1K", "2K", "4K"],
        default="1K",
        help="Image resolution for pro and gpt models (default: 1K, ignored for flash)",
    )
    parser.add_argument(
        "--quality",
        choices=["auto", "low", "medium", "high"],
        default="auto",
        help="Render quality for gpt model (default: auto, ignored for flash and pro)",
    )

    args = parser.parse_args()

    if PROVIDERS[args.model] == "openai":
        generate_openai(
            args.prompt, args.output, args.aspect, args.references, args.size, args.quality,
        )
    else:
        generate_image(
            args.prompt, args.output, args.aspect, args.references, args.model, args.size,
        )
```

- [ ] **Step 5: Run the unit tests to make sure nothing regressed**

```bash
cd /home/eze/projects/claude-plugins/nano-banana-multi
uv run --with pytest pytest skills/image-gen/scripts/test_image.py -v
```

Expected: `9 passed`.

- [ ] **Step 6: Argparse smoke test (no API call)**

```bash
cd /home/eze/projects/claude-plugins/nano-banana-multi
uv run skills/image-gen/scripts/image.py --help
```

Expected: usage shows `--model {flash,pro,gpt}` and `--quality {auto,low,medium,high}`.

- [ ] **Step 7: Missing-key smoke test**

```bash
cd /home/eze/projects/claude-plugins/nano-banana-multi
env -u OPENAI_API_KEY uv run skills/image-gen/scripts/image.py \
  --prompt test --output /tmp/x.png --model gpt
```

Expected: stderr `Error: OPENAI_API_KEY environment variable not set` and exit code 1.

- [ ] **Step 8: Commit**

```bash
git add skills/image-gen/scripts/image.py
git commit -m "feat: add openai gpt-image-2 backend"
```

---

## Task 6: Update SKILL.md docs

**Files:**
- Modify: `skills/image-gen/SKILL.md`

- [ ] **Step 1: Update the description in the frontmatter**

Replace the `description:` line in the YAML frontmatter with:

```
description: Multi-provider image generation skill (nano-banana-multi). Use this skill when the user asks to "generate an image", "create an image", "make an image", uses "nano banana", asks for "gpt image", or requests multiple images. Generates images using Google Gemini 2.5 Flash, Gemini 3 Pro, or OpenAI gpt-image-2 for any purpose - frontend designs, web projects, illustrations, graphics, hero images, icons, backgrounds, or standalone artwork. Invoke for ANY image generation request.
```

- [ ] **Step 2: Update the "Available Models" table**

Replace the existing models table with:

```markdown
| Model | ID | Provider | Best For | Notes |
|-------|-----|----------|----------|-------|
| **Flash** | `gemini-2.5-flash-image` | Google Gemini | Speed, high-volume tasks | 1024px max |
| **Pro** | `gemini-3-pro-image-preview` | Google Gemini | Professional quality, complex scenes | Up to 4K |
| **GPT** | `gpt-image-2` | OpenAI | Multimodal edits with multiple references, fine quality control | Up to 4K (no transparent bg) |
```

- [ ] **Step 3: Update Prerequisites section**

Replace the existing Prerequisites paragraph with:

```markdown
## Prerequisites

- `GEMINI_API_KEY` — required for `--model flash` and `--model pro`
- `OPENAI_API_KEY` — required for `--model gpt`

Each variable is only needed if you use that provider's model.
```

- [ ] **Step 4: Add usage examples for `--model gpt`**

Append this section right after the existing "Pro model" example block:

```markdown
**GPT model** - OpenAI gpt-image-2, multimodal text+image input:
```bash
uv run "${SKILL_DIR}/scripts/image.py" \
  --prompt "A photorealistic cup of espresso on a marble counter" \
  --output /path/to/espresso.png \
  --model gpt \
  --size 2K \
  --quality high
```

**GPT with multiple reference images** (uses the OpenAI image-edit endpoint):
```bash
uv run "${SKILL_DIR}/scripts/image.py" \
  --prompt "Combine the subject of the first image with the lighting of the second" \
  --output /path/to/blend.png \
  --model gpt \
  --reference /path/to/subject.png \
  --reference /path/to/lighting.png
```
```

- [ ] **Step 5: Commit**

```bash
git add skills/image-gen/SKILL.md
git commit -m "docs: document gpt-image-2 in SKILL.md"
```

---

## Task 7: Manual end-to-end smoke test

This task is for the human (or for an agent that's allowed to make a real OpenAI API call). It is the only step that costs API credits.

**Files:**
- None (read-only verification)

- [ ] **Step 1: Verify `OPENAI_API_KEY` is exported in the current shell**

```bash
test -n "$OPENAI_API_KEY" && echo "key is set" || echo "key is NOT set"
```

If "key is NOT set", add `export OPENAI_API_KEY="sk-proj-..."` to `~/.bashrc`, source it, and re-run.

- [ ] **Step 2: Generate a 1K image with `--model gpt`**

```bash
cd /home/eze/projects/claude-plugins/nano-banana-multi
uv run skills/image-gen/scripts/image.py \
  --prompt "A minimalist tangerine on a clean white background, soft daylight" \
  --output /tmp/nbm-gpt-1k.png \
  --model gpt
```

Expected: `Image saved to: /tmp/nbm-gpt-1k.png`. Open the file and confirm it looks right.

- [ ] **Step 3: Generate a 2K landscape image**

```bash
uv run skills/image-gen/scripts/image.py \
  --prompt "Wide landscape: misty pine forest at dawn, soft pastel sky" \
  --output /tmp/nbm-gpt-2k.png \
  --model gpt \
  --aspect landscape \
  --size 2K \
  --quality high
```

Expected: `Image saved to: /tmp/nbm-gpt-2k.png`, dimensions `2048x1152`.

- [ ] **Step 4: 4K square downgrade warning**

```bash
uv run skills/image-gen/scripts/image.py \
  --prompt "Geometric pattern, navy and gold" \
  --output /tmp/nbm-gpt-4k-square.png \
  --model gpt \
  --aspect square \
  --size 4K
```

Expected: stderr warning about downgrade to 2K square; output file is `2048x2048`.

- [ ] **Step 5: Reference image (edits endpoint)**

Pre-req: any small PNG at `/tmp/ref.png`. If you don't have one, reuse `/tmp/nbm-gpt-1k.png` from Step 2.

```bash
uv run skills/image-gen/scripts/image.py \
  --prompt "Same subject, but in claymation style" \
  --output /tmp/nbm-gpt-edit.png \
  --model gpt \
  --reference /tmp/nbm-gpt-1k.png
```

Expected: `Image saved to: /tmp/nbm-gpt-edit.png`. The output should clearly relate to the reference.

- [ ] **Step 6: No commit needed for this task**

Manual verification only. If any step failed, stop and report the failure.
