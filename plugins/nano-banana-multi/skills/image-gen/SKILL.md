---
name: image-gen
description: Multi-provider image AND video generation skill (nano-banana-multi). Use when the user asks to "generate/create/make an image", uses "nano banana", asks for "gpt image", requests multiple images, OR asks to "generate/make a video", "AI video", "video clip", "start/end frame video" (via fal.ai). Generates images via Google Gemini 2.5 Flash, Gemini 3 Pro, the Antigravity CLI image subagent (free on the Google AI Pro subscription, multi-reference), or the official gpt-image-2 through the Codex CLI (no OpenAI API key, billed to the ChatGPT plan), and reaches fal.ai's catalog of image AND video endpoints with one key (GPT Image 2/2.5, Nano Banana, Flux, Seedream for images; Kling, Seedance, Gemini Omni, Wan, Hailuo for video) when the CLI models aren't the right fit. For any purpose - frontend designs, web projects, illustrations, hero images, icons, backgrounds, standalone artwork, or short video. Invoke for ANY image or AI-video generation request.
---

# Nano Banana Multi - Multi-Provider Image & Video Generation

Generate **images** with Google Gemini (Flash, Pro) or the official **gpt-image-2 via the Codex CLI** — three backends behind `scripts/image.py` — **plus fal.ai** through `scripts/fal.py`, which reaches fal's hosted catalog of **both image and video** models with one key. `image.py` is image-only; video always goes through fal.

## Prerequisites

- `GEMINI_API_KEY` — required for `--model flash` and `--model pro`
- **Codex CLI** signed in (`codex` on PATH) — required for `--model codex`. It uses your Codex/ChatGPT login to call the native gpt-image-2 tool; **no `OPENAI_API_KEY` needed**, and it bills the ChatGPT plan rather than per image.
- `FAL_KEY` — required for `scripts/fal.py`. Read from the environment, else from `~/.secrets/fal.env` (`FAL_KEY=...`, mode 600). Never put it in a repo, a prompt or a log.

Each requirement is only needed if you use that backend.

## Available Models (`image.py`)

| Model | ID | Provider | Best For | Notes |
|-------|-----|----------|----------|-------|
| **Flash** | `gemini-2.5-flash-image` | Google Gemini | Speed, high-volume tasks | 1024px max |
| **Pro** | `gemini-3-pro-image-preview` | Google Gemini | Professional quality, complex scenes | Up to 4K |
| **Codex** | `gpt-image-2` (via Codex CLI) | OpenAI, through your Codex login | Multimodal edits with multiple references, fine quality control | No `OPENAI_API_KEY` needed; `gpt` is a deprecated alias |

## fal.ai (`scripts/fal.py`)

fal.ai hosts generative models behind one queue API: you submit to an **endpoint id** (e.g.
`kling/v4/image-to-video`), fal queues the job, and the script waits and downloads the outputs. Every
endpoint has its own input names, so the script is generic: find the endpoint, read its schema, then pass
inputs.

### Picking the right backend

| You need… | Use |
|-----------|-----|
| A photo edit with several reference images, free | `image.py --model agy` (Antigravity, Google AI Pro sub) — **try it first** |
| A photo edit billed to the ChatGPT plan instead of per image | `image.py --model codex` — second (multi-reference works; occasionally times out) |
| Fast or batch images, transparent background | `image.py --model flash` / `pro` |
| An edit that must keep everything else intact, or Codex timed out | fal → GPT Image 2.5 Flare/Sunburst edit, or Nano Banana Pro edit |
| **Any video** | fal → a video endpoint below |

### Workflow

1. **Find the endpoint.** The catalog changes weekly, so never trust a remembered id:
   `uv run "${SKILL_DIR}/scripts/fal.py" search "first last frame" --category image-to-video`
2. **Read its inputs.** Names differ per model (`image_url` vs `image_urls` vs `start_image_url`/`end_image_url`):
   `uv run "${SKILL_DIR}/scripts/fal.py" schema kling/v4/image-to-video`
3. **Check the price** (free call): `uv run "${SKILL_DIR}/scripts/fal.py" price kling/v4/image-to-video`
4. **Run.** Local files go in with `--file key=path` (uploaded to fal storage), plain values with
   `--arg key=value` (JSON-parsed when valid, so `--arg duration=10` is a number). A `[]` suffix on the
   key appends to a list:

```bash
uv run "${SKILL_DIR}/scripts/fal.py" run openai/gpt-image-2.5/flare/edit \
  --file 'image_urls[]=/path/base.jpg' --file 'image_urls[]=/path/ref.jpg' \
  --arg prompt="..." --arg image_size=landscape_16_9 --arg quality=high \
  --out /path/out/

uv run "${SKILL_DIR}/scripts/fal.py" run kling/v4/image-to-video \
  --file start_image_url=/path/start.png --file end_image_url=/path/end.png \
  --arg prompt="..." --arg duration=10 --arg resolution=1080p \
  --out /path/clip.mp4
```

Inputs nested inside a JSON value (e.g. Kling O3 `elements[].frontal_image_url`) can't use `--file`:
upload first with `uv run "${SKILL_DIR}/scripts/fal.py" upload a.png b.jpg` (prints path → URL), then
pass the URLs inside `--arg elements='[...]'`.

`--out` is a file path when the run returns one output, otherwise a directory. The raw result JSON is
saved next to the outputs as `fal-<request_id>.json`.

5. **Recover instead of paying twice.** The `request_id` is printed before the script starts waiting. If
   the process dies (video runs take minutes), fetch the finished result later:
   `uv run "${SKILL_DIR}/scripts/fal.py" result kling/v4/image-to-video <request_id> --out /path/clip.mp4`

Run video jobs with `run_in_background` — they take several minutes.

### Endpoints worth knowing (checked 2026-10-23 — confirm with `search` before use)

| Endpoint | Kind | Price | Reach for it when… |
|---|---|---|---|
| `openai/gpt-image-2.5/flare/edit` | image edit | **$0.039** high @1920×1072 (+$0.008/ref) | **default edit**: precise, keeps subject, composition and background; 4× cheaper than GPT Image 2 |
| `openai/gpt-image-2.5/sunburst/edit` | image edit | variable, see `price` | tightest scoping across many revision rounds |
| `openai/gpt-image-2/edit` | image edit | $0.158 high @1920×1080 | same model as `image.py --model codex`; prefer 2.5 Flare on fal |
| `fal-ai/nano-banana-pro/edit` | image edit | $0.15 / image | 4K, multi-image composition |
| `kling/v4/image-to-video` | video | $0.157 / s | realistic people and physics; start + end frame, 3–30 s, per-shot `multi_prompt`, 1080p |
| `fal-ai/kling-video/v3/pro/image-to-video` | video | $0.14 / s | proven fallback if Kling 4 misbehaves |
| `bytedance/seedance-2.5/us/image-to-video` | video | $0.0214 / 1K tokens | end frame plus **synced audio**, up to 30 s |
| `google/gemini-omni-flash/v1.1/image-to-video` | video | $0.03 / s | cheapest option with an end frame, for motion drafts |

When both the first and the last frame matter, pass both: on per-second pricing an end frame costs nothing
extra.

### Cost traps

- Every submit that passes validation **starts a billable run**. Read `schema` instead of probing by
  omitting params.
- Unknown params are ignored, so a misspelled input name runs the job without it. Copy names from `schema`.
- 🔴 **`price` returns the 720p rate; resolution tiers live on the model page** (fal.ai/models/<id>).
  Kling 4.0: $0.157/s at 720p, $0.235/s at 1080p; Kling 3.0 Pro: $0.112/s audio off, $0.168 audio on.
  Seedance 2.5 bills per token (w×h×s×24/1024) and costs ~2× BytePlus's own API at 1080p. Check real
  spend with `GET https://api.fal.ai/v1/models/usage?start=<ISO date>&expand=summary` before quoting totals.
- Cheapest realistic video here is **Kling 3.0 Pro at $0.112/s**; reach for Kling 4.0 ($0.235/s) only for
  30 s clips, keyframes or native audio. Draft at 720p, render finals at 1080p.
- An empty balance locks the account: every call fails at upload with `403` on
  `rest.fal.ai/storage/auth/token` ("User is locked. Reason: Exhausted balance"). Nothing is billed;
  top up at fal.ai/dashboard/billing.
- `price` units differ per endpoint (per image, per second, per megapixel, per 1K tokens). Multiply by the
  duration or size before submitting a video. OpenAI endpoints report a placeholder `1 USD per units`; their
  real price table is on the model page (GPT Image 2 edit at high quality ≈ $0.16 for 1920×1080).
- Schema enums can be stale: `fal-ai/finegrain-eraser/mask` still lists `mode=premium`, but the API rejects
  it ("premium mode has been removed"). Use `standard`.

### Removing an object from a photo (observed 2026-10-23)

- **Use an eraser** (`fal-ai/finegrain-eraser/mask`, `mode=standard`, $0.045): it keeps the camera geometry
  pixel for pixel, so real pixels can be pasted back outside the mask. Its fill is good on floors and sky,
  but it re-renders the whole frame slightly softer and invents junk where it has to continue printed text.
- **Not Flux Fill** (`fal-ai/flux-pro/v1/fill`): given an object-shaped mask it paints a new object of the same
  silhouette (a tent became a concrete arch).
- **Not `mask_url` on `openai/gpt-image-2/edit`**: the mask was ignored and the whole scene was regenerated,
  with an invented brand printed on the wall.

## Image Generation Workflow

### Step 1: Generate the Image

Use `scripts/image.py` with uv. The script is located in the skill directory at `skills/image-gen/scripts/image.py`:

```bash
uv run "${SKILL_DIR}/scripts/image.py" \
  --prompt "Your image description" \
  --output "/path/to/output.png"
```

Where `${SKILL_DIR}` is the directory containing this SKILL.md file.

Options:
- `--prompt` (required): Detailed description of the image to generate
- `--output` (required): Output file path (PNG format)
- `--aspect` (optional): Aspect ratio - "square", "landscape", "portrait" (default: square)
- `--reference` (optional, repeatable): Path to a reference image for style, composition, or content guidance. Can be specified multiple times for multiple references.
- `--model` (optional): Model to use - "flash" (Gemini fast), "pro" (Gemini high-quality), "codex" (official gpt-image-2 via the Codex CLI; "gpt" still works as a deprecated alias), or "agy" (Antigravity CLI image subagent, free on the Google AI Pro subscription) (default: flash)
- `--size` (optional): "1K", "2K", "4K" (default: 1K, ignored for flash). Exact for `pro`; for `codex` it is only an **approximate hint** — Codex's `image_gen` has no size parameter and returns non-standard dimensions (observed 1254×1254, 1448×1086, 1672×941), so it follows aspect ratio loosely but never a guaranteed pixel size.
- `--quality` (optional): Render quality hint for `codex` model - "auto", "low", "medium", "high" (default: auto, ignored for flash and pro)

### Using Different Models

**Flash model (default)** - Fast generation, good for iterations:
```bash
uv run "${SKILL_DIR}/scripts/image.py" \
  --prompt "A minimalist logo design" \
  --output "/path/to/logo.png" \
  --model flash
```

**Pro model** - Higher quality for final assets:
```bash
uv run "${SKILL_DIR}/scripts/image.py" \
  --prompt "A detailed hero illustration for a tech landing page" \
  --output "/path/to/hero.png" \
  --model pro \
  --size 2K
```

**Codex model** - official gpt-image-2 via the Codex CLI (uses your Codex login, no `OPENAI_API_KEY`):
```bash
uv run "${SKILL_DIR}/scripts/image.py" \
  --prompt "A photorealistic cup of espresso on a marble counter" \
  --output /path/to/espresso.png \
  --model codex \
  --size 2K \
  --quality high
```

**Codex with multiple reference images** (attached to Codex via `--image`):
```bash
uv run "${SKILL_DIR}/scripts/image.py" \
  --prompt "Combine the subject of the first image with the lighting of the second" \
  --output /path/to/blend.png \
  --model codex \
  --reference /path/to/subject.png \
  --reference /path/to/lighting.png
```

**Antigravity model** - the Antigravity CLI's `image-generator` subagent, on the Google AI Pro
subscription (no API spend). Best free option for multi-reference edits: in a 3-reference test
(location + people + uniform) it kept the wall lettering nearly pixel-exact, rendered the back print
upright in the right typeface and left the front plain, in 2.5 min (a 2-reference run: 1.5 min). **Output is fixed at 1376×768 for 16:9 even when 2K is requested** — for 1080p keyframes upscale with `fal.py run fal-ai/seedvr/upscale/image --file image_url=... --arg upscale_factor=2` (~$0.003);
it reported "Imagen 3" but that size is Nano Banana's 1K — don't trust its self-report. No video.
```bash
uv run "${SKILL_DIR}/scripts/image.py" --model agy --aspect landscape \
  --reference /path/location.jpg --reference /path/person.jpg --reference /path/uniform.jpg \
  --prompt "..." --output /path/out.png
```
Traps: `GEMINI_API_KEY`/`GOOGLE_API_KEY` are stripped so it bills the subscription, not the API;
orchestrator model defaults to `gemini-3.8-flash-high` (`AGY_IMAGE_MODEL` overrides) because heavy
use of Gemini 4 Argon exhausts its weekly quota; reference images must be readable paths (the script
adds their folders with `--add-dir`).

> How it works: `--model codex` runs `codex exec` to trigger Codex's native image_gen tool. Codex
> writes the PNG to `~/.codex/generated_images/<session>/`; the script then copies the newest one to
> your `--output` path. First run may take ~1–3 min (Codex startup + generation). Requires a Codex plan
> with image generation enabled.

### Using Reference Images

To generate an image based on an existing reference:

```bash
uv run "${SKILL_DIR}/scripts/image.py" \
  --prompt "Create a similar abstract pattern with warmer colors" \
  --output "/path/to/output.png" \
  --reference "/path/to/reference.png"
```

To use multiple reference images (e.g., blend styles from several sources):

```bash
uv run "${SKILL_DIR}/scripts/image.py" \
  --prompt "Combine the color palette of the first image with the composition of the second" \
  --output "/path/to/output.png" \
  --reference "/path/to/style-ref.png" \
  --reference "/path/to/composition-ref.png"
```

Reference images help the model understand the desired style, composition, or visual elements you want in the generated image. When multiple references are provided, all images are sent to the model together. With `--model codex`, each `--reference` is attached to the Codex prompt via `codex exec --image`, so Codex uses them as visual references for the generation.

### Step 2: Integrate with Frontend Design

After generating images, incorporate them into frontend code:

**HTML/CSS:**
```html
<img src="./generated-hero.png" alt="Description" class="hero-image" />
```

**React:**
```jsx
import heroImage from './assets/generated-hero.png';
<img src={heroImage} alt="Description" className="hero-image" />
```

**CSS Background:**
```css
.hero-section {
  background-image: url('./generated-hero.png');
  background-size: cover;
  background-position: center;
}
```

## Crafting Effective Prompts

Write detailed, specific prompts for best results:

**Good prompt:**
> A minimalist geometric pattern with overlapping translucent circles in coral, teal, and gold on a deep navy background, suitable for a modern fintech landing page hero section

**Avoid vague prompts:**
> A nice background image

### Prompt Elements to Include

1. **Subject**: What the image depicts
2. **Style**: Artistic style (minimalist, abstract, photorealistic, illustrated)
3. **Colors**: Specific color palette matching the design system
4. **Mood**: Atmosphere (professional, playful, elegant, bold)
5. **Context**: How it will be used (hero image, icon, texture, illustration)
6. **Technical**: Aspect ratio needs, transparency requirements

## Integration with Frontend-Design Skill

When used alongside the frontend-design skill:

1. **Plan the visual hierarchy** - Identify where generated images add value
2. **Match the aesthetic** - Ensure prompts align with the chosen design direction (brutalist, minimalist, maximalist, etc.)
3. **Generate images first** - Create visual assets before coding the frontend
4. **Reference in code** - Use relative paths to generated images in your HTML/CSS/React

### Example Workflow

1. User requests a landing page with custom hero imagery
2. Invoke nano-banana-multi to generate the hero image with a prompt matching the design aesthetic
3. Invoke frontend-design to build the page, referencing the generated image
4. Result: A cohesive design with custom AI-generated visuals

## Output Location

By default, save generated images to the project's assets directory:
- `./assets/` for simple HTML projects
- `./src/assets/` or `./public/` for React/Vue projects
- Use descriptive filenames: `hero-abstract-gradient.png`, `icon-user-avatar.png`
