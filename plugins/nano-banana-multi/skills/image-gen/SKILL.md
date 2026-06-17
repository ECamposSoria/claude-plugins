---
name: image-gen
description: Multi-provider image AND video generation skill (nano-banana-multi). Use when the user asks to "generate/create/make an image", uses "nano banana", asks for "gpt image", requests multiple images, OR asks to "generate/make a video", "AI video", "video clip" (via the FLORA MCP). Generates images via Google Gemini 2.5 Flash, Gemini 3 Pro, or the official gpt-image-2 through the Codex CLI (no OpenAI API key), and selects from FLORA's 50+ image AND video models (Flux, Ideogram, Recraft, Imagen, Seedream for images; Veo, Runway, Kling, Luma, Sora for video) when the CLI models aren't the right fit. For any purpose - frontend designs, web projects, illustrations, hero images, icons, backgrounds, standalone artwork, or short video. Invoke for ANY image or AI-video generation request.
---

# Nano Banana Multi - Multi-Provider Image Generation

Generate custom **images** using Google Gemini (Flash, Pro) or the official **gpt-image-2 via the Codex CLI** — three backends behind one CLI — **plus FLORA** (`flora` MCP), which adds a selectable catalog of 50+ models spanning **both images and video** (the CLI is image-only; video is FLORA-only). Pick the backend/model per task — see "FLORA (MCP)" below.

## Prerequisites

- `GEMINI_API_KEY` — required for `--model flash` and `--model pro`
- **Codex CLI** signed in (`codex` on PATH) — required for `--model codex`. It uses your Codex/ChatGPT login to call the native gpt-image-2 tool; **no `OPENAI_API_KEY` needed**.

Each requirement is only needed if you use that backend.

The **FLORA MCP** (`flora`) is bundled with this plugin via `.mcp.json` (remote HTTP server at
`https://agents.flora.ai/mcp`). It is separate from the CLI above — use it when you want FLORA's curated
**techniques** and broader **model catalog** rather than the three direct CLI backends. Auth is **OAuth**:
the first FLORA tool call opens a browser to sign in at `app.flora.ai` (no API key in config). See
"FLORA (MCP)" below.

## Available Models

| Model | ID | Provider | Best For | Notes |
|-------|-----|----------|----------|-------|
| **Flash** | `gemini-2.5-flash-image` | Google Gemini | Speed, high-volume tasks | 1024px max |
| **Pro** | `gemini-3-pro-image-preview` | Google Gemini | Professional quality, complex scenes | Up to 4K |
| **Codex** | `gpt-image-2` (via Codex CLI) | OpenAI, through your Codex login | Multimodal edits with multiple references, fine quality control | No `OPENAI_API_KEY` needed; `gpt` is a deprecated alias |

## FLORA (MCP)

FLORA is a generative-media platform exposed as a **remote MCP server** (bundled in this plugin's
`.mcp.json`). Unlike the three CLI models above, FLORA is driven through MCP tool calls — no script, no
`GEMINI_API_KEY`/`OPENAI_API_KEY`. Critically, FLORA is **not just another image model**: it fronts a
catalog of **50+ models that you choose between**, covering **both image and video** generation, plus
curated *techniques* (multi-step recipes). So FLORA is how this skill does **video** at all, and how it
reaches image models the CLI doesn't have (Ideogram, Recraft, Imagen, Flux, Seedream, …).

### Picking the right backend

| You need… | Use |
|-----------|-----|
| Quick one-shot image, transparent background, or scripted/batch output | **CLI** (`flash` / `pro` / `codex`) |
| An image model the CLI lacks (text-in-image, vector/print, photoreal 4K) | **FLORA** → pick an image model below |
| **Any video** | **FLORA** → pick a video model below (the CLI cannot do video) |
| Multi-step / reference-guided recipe | **FLORA** → `list_techniques` |

> **Always `list_models` first.** The tables below are *illustrative* of what FLORA hosts and go stale
> quickly — confirm the exact model id/name from the live `list_models` output before starting a run.

### Choosing a FLORA **image** model (best-for)

| Model (family) | Reach for it when… |
|----------------|--------------------|
| **Flux / Flux Pro / Dev** | fast iteration + premium general quality |
| **Ideogram 3.0** | logos, posters, crisp **text inside the image** |
| **Recraft V4.x Pro** | hero imagery, campaign/brand work, **print/vector** |
| **GPT Image 2** | narrative visuals, branding mock-ups, multi-reference edits |
| **Imagen 3/4** | photoreal generation + high-quality editing |
| **Nano Banana Pro** (Gemini 3 Pro Image) | premium **4K** + multi-image composition |
| **Seedream 4.5** | photoreal 4K with sharp text |
| **Stable Diffusion 3.5** | general-purpose, heavy customization |

### Choosing a FLORA **video** model (best-for)

| Model (family) | Reach for it when… |
|----------------|--------------------|
| **Veo 3.1** (+ Lite/Frames) | premium, frame-based, or reference-driven video |
| **Runway Gen-4.x** | high-fidelity cinematic motion |
| **Kling 3.0 Pro / Standard** | cinematic generation — Pro premium, Standard cost-effective |
| **Luma Ray 2 / Flash** | realistic motion; **Flash** for fast previews |
| **Sora 2 Pro** | premium video with **synced audio/voice** |
| **Seedance 2.0 / Reference** | keyframed or reference-guided video |
| **WAN 2.x** | audio-driven, multi-shot storytelling |

Rule of thumb for video: **Veo / Runway / Kling-Pro** for final hero shots; **Luma Flash / Kling-Standard**
for cheap fast previews; pick **Sora 2 Pro** when you need synced audio in the clip.

**Typical FLORA tool flow** (tool names load after the MCP connects):
1. `list_models` (and `list_techniques`) — discover the live catalog; pick the model id for your task.
2. `start_generation_run` (or `create_technique_run`) — kick off the image **or video** generation with the chosen model.
3. `retrieve_technique_run` / `list_assets` / `retrieve_asset` — poll and fetch the resulting asset(s). Video runs take longer — poll until complete.

**Auth:** OAuth 2.1 (PKCE). The first FLORA tool call opens a browser to FLORA's authorization page — sign
in with the same account you use at `app.flora.ai` and approve the scopes; tokens are then cached locally
by the client. No API key lives in `.mcp.json`. MCP access requires a FLORA **Starter** plan or above.

> For server-side/headless automation FLORA also supports a static key via `Authorization: Bearer sk_live_…`
> (add a `--header`/`headers` block). Note: only `sk_live_…` server keys work — `ak_…` REST/CLI keys are
> rejected by the MCP endpoint with `401 invalid_token`.

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
- `--model` (optional): Model to use - "flash" (Gemini fast), "pro" (Gemini high-quality), or "codex" (official gpt-image-2 via the Codex CLI; "gpt" still works as a deprecated alias) (default: flash)
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
