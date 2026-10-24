#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "google-genai",
#     "pillow",
# ]
# ///
"""
Generate images using Google Gemini (Flash, Pro) or the official gpt-image-2 via the Codex CLI.

The "codex" model shells out to the local Codex CLI and triggers its native image_gen
tool (gpt-image-2). It uses your Codex login — no OPENAI_API_KEY required.

Usage:
    uv run image.py --prompt "A colorful abstract pattern" --output "./hero.png"
    uv run image.py --prompt "Minimalist icon" --output "./icon.png" --aspect landscape
    uv run image.py --prompt "Similar style image" --output "./new.png" --reference "./existing.png"
    uv run image.py --prompt "High quality art" --output "./art.png" --model pro --size 2K
    uv run image.py --prompt "A photorealistic espresso cup" --output "./cup.png" --model codex --quality high
    uv run image.py --prompt "Combine these refs" --output "./blend.png" --model codex --reference "./a.png" --reference "./b.png"
"""

import argparse
import os
import sys

MODEL_IDS = {
    "flash": "gemini-2.5-flash-image",
    "pro":   "gemini-3-pro-image-preview",
    "codex": "gpt-image-2",   # via Codex CLI's native image_gen tool (no OPENAI_API_KEY)
    "gpt":   "gpt-image-2",   # backward-compat alias for "codex"
    "agy":   "antigravity",   # Antigravity CLI's image-generator subagent (Google AI Pro sub)
}

PROVIDERS = {
    "flash": "gemini",
    "pro":   "gemini",
    "codex": "codex",
    "gpt":   "codex",  # deprecated alias -> codex
    "agy":   "agy",
}


def get_aspect_instruction(aspect: str) -> str:
    """Return aspect ratio instruction for the prompt."""
    aspects = {
        "square": "Generate a square image (1:1 aspect ratio).",
        "landscape": "Generate a landscape/wide image (16:9 aspect ratio).",
        "portrait": "Generate a portrait/tall image (9:16 aspect ratio).",
    }
    return aspects.get(aspect, aspects["square"])


# gpt-image-2 pixel-dimension hints per (aspect, size) tuple, passed to Codex as a
# target resolution in the prompt. 4K square (3840x3840 = 14.7M px) exceeds the
# 8.29M-px cap, so we hint 2K square instead.
_PIXEL_SIZES = {
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


def _pixel_size(aspect: str, size: str) -> str:
    """Resolve (aspect, size) to a gpt-image-2 pixel-dimension hint."""
    return _PIXEL_SIZES[(aspect, size)]


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
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    aspect_instruction = get_aspect_instruction(aspect)
    full_prompt = f"{aspect_instruction} {prompt}"

    # Build contents with optional reference images
    contents: list = []
    if references:
        for ref_path in references:
            if not os.path.exists(ref_path):
                print(f"Error: Reference image not found: {ref_path}", file=sys.stderr)
                sys.exit(1)
            contents.append(Image.open(ref_path))
        if len(references) == 1:
            full_prompt = f"{full_prompt} Use the provided image as a reference for style, composition, or content."
        else:
            full_prompt = f"{full_prompt} Use the provided {len(references)} images as references for style, composition, or content."
    contents.append(full_prompt)

    model_id = MODEL_IDS[model]

    # Pro model supports additional config for resolution
    if model == "pro":
        aspect_ratios = {"square": "1:1", "landscape": "16:9", "portrait": "9:16"}
        config = types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
            image_config=types.ImageConfig(
                aspect_ratio=aspect_ratios.get(aspect, "1:1"),
                image_size=size,
            ),
        )
        response = client.models.generate_content(
            model=model_id,
            contents=contents,
            config=config,
        )
    else:
        response = client.models.generate_content(
            model=model_id,
            contents=contents,
        )

    # Ensure output directory exists
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # Extract image from response
    for part in response.parts:
        if part.text is not None:
            print(f"Model response: {part.text}")
        elif part.inline_data is not None:
            image = part.as_image()
            image.save(output_path)
            print(f"Image saved to: {output_path}")
            return

    print("Error: No image data in response", file=sys.stderr)
    sys.exit(1)


def generate_codex(
    prompt: str,
    output_path: str,
    aspect: str = "square",
    references: list[str] | None = None,
    size: str = "1K",
    quality: str = "auto",
) -> None:
    """Generate an image via the Codex CLI's native image_gen tool (gpt-image-2).

    Uses the local Codex login (no OPENAI_API_KEY). Codex writes generated PNGs to
    ~/.codex/generated_images/<session>/; we copy the newest one produced by this
    run to output_path.
    """
    import glob
    import shutil
    import subprocess
    import time

    codex = shutil.which("codex")
    if not codex:
        print(
            "Error: 'codex' CLI not found on PATH. Install the Codex CLI and sign in — "
            "it provides the official gpt-image-2 image generation used by --model codex.",
            file=sys.stderr,
        )
        sys.exit(1)

    references = references or []
    for ref_path in references:
        if not os.path.exists(ref_path):
            print(f"Error: Reference image not found: {ref_path}", file=sys.stderr)
            sys.exit(1)

    if aspect == "square" and size == "4K":
        print(
            "Warning: 4K square exceeds gpt-image-2's 8.29M-px cap; "
            "hinting 2K square (2048x2048) instead.",
            file=sys.stderr,
        )

    out_abs = os.path.abspath(output_path)
    out_dir = os.path.dirname(out_abs)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    aspect_word = {
        "square": "square (1:1)",
        "landscape": "landscape (16:9)",
        "portrait": "portrait (9:16)",
    }.get(aspect, "square (1:1)")
    pixel_hint = _pixel_size(aspect, size)

    if len(references) > 1:
        ref_note = (
            f" Use the {len(references)} attached images as references for style, "
            "composition, or content."
        )
    elif references:
        ref_note = " Use the attached image as a reference for style, composition, or content."
    else:
        ref_note = ""
    quality_note = "" if quality == "auto" else f" Aim for {quality} rendering quality."

    instruction = (
        "Use your built-in image generation tool to generate exactly ONE image. "
        "Do not write or run any code, and do not ask for confirmation — just call the "
        f"image generation tool directly. Image description: {prompt}. "
        f"Render it as a {aspect_word} PNG, approximately {pixel_hint} pixels."
        f"{quality_note}{ref_note}"
    )

    # The prompt goes through stdin: `--image` takes multiple values, so a trailing
    # positional prompt would be swallowed as one more image path.
    cmd = [codex, "exec", "--skip-git-repo-check"]
    for ref_path in references:
        cmd += ["--image", os.path.abspath(ref_path)]

    images_dir = os.path.expanduser("~/.codex/generated_images")
    start = time.time() - 2  # small clock-skew buffer

    try:
        proc = subprocess.run(
            cmd, input=instruction, capture_output=True, text=True, timeout=900
        )
    except subprocess.TimeoutExpired:
        print("Error: Codex image generation timed out (900s).", file=sys.stderr)
        sys.exit(1)

    # Copy the newest PNG Codex produced during this run to the requested path.
    newest = None
    newest_mtime = start
    for candidate in glob.glob(os.path.join(images_dir, "**", "*.png"), recursive=True):
        try:
            mtime = os.path.getmtime(candidate)
        except OSError:
            continue
        if mtime >= newest_mtime:
            newest_mtime = mtime
            newest = candidate

    if newest:
        shutil.copyfile(newest, out_abs)
        print(f"Image saved to: {out_abs}")
        return

    # Nothing produced — surface Codex output to aid debugging.
    tail = ((proc.stdout or "")[-1500:] + (proc.stderr or "")[-1500:]).strip()
    if tail:
        sys.stderr.write(tail + "\n")
    print(
        "Error: Codex did not produce an image. Ensure you are signed in to Codex "
        "(`codex` runs) and that image generation is available on your plan.",
        file=sys.stderr,
    )
    sys.exit(1)


def generate_agy(
    prompt: str,
    output_path: str,
    aspect: str = "square",
    references: list[str] | None = None,
    size: str = "1K",
) -> None:
    """Generate an image with the Antigravity CLI's image-generator subagent.

    Runs on the Google AI Pro subscription (no API spend). Reference images are passed
    by absolute path inside the prompt. The subagent saves to the requested path; if it
    only leaves its own artifact under ~/.gemini/antigravity-cli/brain/, the newest image
    written there during this run is copied instead.
    """
    import glob
    import shutil
    import subprocess
    import time

    agy = shutil.which("agy") or os.path.expanduser("~/.local/bin/agy")
    if not os.path.exists(agy):
        print("Error: 'agy' (Antigravity CLI) not found. Install it and sign in once.", file=sys.stderr)
        sys.exit(1)

    references = [os.path.abspath(r) for r in (references or [])]
    for ref_path in references:
        if not os.path.exists(ref_path):
            print(f"Error: Reference image not found: {ref_path}", file=sys.stderr)
            sys.exit(1)

    out_abs = os.path.abspath(output_path)
    out_dir = os.path.dirname(out_abs)
    os.makedirs(out_dir, exist_ok=True)
    aspect_word = {"square": "1:1", "landscape": "16:9", "portrait": "9:16"}.get(aspect, "1:1")
    refs_text = "".join(f"\n{i}. {p}" for i, p in enumerate(references, 1))
    instruction = (
        "Use your image-generator subagent to create exactly ONE image and save it as "
        f"{out_abs}. Aspect ratio {aspect_word}, {size} resolution or the closest available. "
        + (f"Pass ALL of these reference images to the subagent by path:{refs_text}\n" if references else "")
        + f"Image description: {prompt}\n"
        "Do not ask questions. When done, reply only with the output path."
    )
    env = {k: v for k, v in os.environ.items() if k not in ("GEMINI_API_KEY", "GOOGLE_API_KEY")}
    cmd = [agy, "-p", instruction, "--model", os.environ.get("AGY_IMAGE_MODEL", "gemini-3.8-flash-high"),
           "--dangerously-skip-permissions", "--print-timeout", "840s", "--add-dir", out_dir]
    for ref_dir in sorted({os.path.dirname(p) for p in references} - {out_dir}):
        cmd += ["--add-dir", ref_dir]

    brain = os.path.expanduser("~/.gemini/antigravity-cli/brain")
    start = time.time() - 2
    try:
        proc = subprocess.run(cmd, cwd=out_dir, env=env, capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        print("Error: Antigravity image generation timed out (900s).", file=sys.stderr)
        sys.exit(1)

    if os.path.exists(out_abs) and os.path.getmtime(out_abs) >= start:
        print(f"Image saved to: {out_abs}")
        return
    newest, newest_mtime = None, start
    for pattern in ("**/*.png", "**/*.jpg", "**/*.jpeg", "**/*.webp"):
        for candidate in glob.glob(os.path.join(brain, pattern), recursive=True):
            mtime = os.path.getmtime(candidate)
            if mtime >= newest_mtime:
                newest, newest_mtime = candidate, mtime
    if newest:
        shutil.copyfile(newest, out_abs)
        print(f"Image saved to: {out_abs} (from {newest})")
        return
    tail = ((proc.stdout or "")[-1500:] + (proc.stderr or "")[-1500:]).strip()
    if tail:
        sys.stderr.write(tail + "\n")
    print("Error: Antigravity did not produce an image (quota? sign-in?).", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Generate images using Gemini (Flash, Pro) or gpt-image-2 via the Codex CLI"
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
        choices=["flash", "pro", "codex", "gpt", "agy"],
        default="flash",
        help=(
            "Model: flash (Gemini fast), pro (Gemini high-quality), "
            "codex (official gpt-image-2 via the Codex CLI; 'gpt' is a deprecated alias), "
            "agy (Antigravity CLI image-generator subagent on the Google AI Pro subscription)"
        ),
    )
    parser.add_argument(
        "--size",
        choices=["1K", "2K", "4K"],
        default="1K",
        help=(
            "Image resolution. Exact for pro; for codex it is only an APPROXIMATE "
            "hint (Codex's image_gen has no size control and returns non-standard "
            "dimensions). Ignored for flash."
        ),
    )
    parser.add_argument(
        "--quality",
        choices=["auto", "low", "medium", "high"],
        default="auto",
        help="Render quality hint for codex model (default: auto, ignored for flash and pro)",
    )

    args = parser.parse_args()

    if PROVIDERS[args.model] == "codex":
        generate_codex(
            args.prompt, args.output, args.aspect, args.references, args.size, args.quality,
        )
    elif PROVIDERS[args.model] == "agy":
        generate_agy(args.prompt, args.output, args.aspect, args.references, args.size)
    else:
        generate_image(
            args.prompt, args.output, args.aspect, args.references, args.model, args.size,
        )


if __name__ == "__main__":
    main()
