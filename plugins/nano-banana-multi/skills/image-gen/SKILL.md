---
name: image-gen
description: Multi-provider image generation skill (nano-banana-multi). Use this skill when the user asks to "generate an image", "create an image", "make an image", uses "nano banana", asks for "gpt image", or requests multiple images. Generates images using Google Gemini 2.5 Flash, Gemini 3 Pro, or OpenAI gpt-image-2 for any purpose - frontend designs, web projects, illustrations, graphics, hero images, icons, backgrounds, or standalone artwork. Invoke for ANY image generation request.
---

# Nano Banana Multi - Multi-Provider Image Generation

Generate custom images using Google Gemini (Flash, Pro) or OpenAI gpt-image-2 — three backends behind one CLI.

## Prerequisites

- `GEMINI_API_KEY` — required for `--model flash` and `--model pro`
- `OPENAI_API_KEY` — required for `--model gpt`

Each variable is only needed if you use that provider's model.

## Available Models

| Model | ID | Provider | Best For | Notes |
|-------|-----|----------|----------|-------|
| **Flash** | `gemini-2.5-flash-image` | Google Gemini | Speed, high-volume tasks | 1024px max |
| **Pro** | `gemini-3-pro-image-preview` | Google Gemini | Professional quality, complex scenes | Up to 4K |
| **GPT** | `gpt-image-2` | OpenAI | Multimodal edits with multiple references, fine quality control | Up to 4K (no transparent bg) |

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
- `--model` (optional): Model to use - "flash" (Gemini fast), "pro" (Gemini high-quality), or "gpt" (OpenAI gpt-image-2) (default: flash)
- `--size` (optional): Image resolution for `pro` and `gpt` models - "1K", "2K", "4K" (default: 1K, ignored for flash)
- `--quality` (optional): Render quality for `gpt` model - "auto", "low", "medium", "high" (default: auto, ignored for flash and pro)

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

Reference images help the model understand the desired style, composition, or visual elements you want in the generated image. When multiple references are provided, all images are sent to the model together. With `--model gpt`, providing one or more `--reference` paths routes the call to OpenAI's image-edit endpoint instead of the text-to-image endpoint.

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
