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
}

PROVIDERS = {
    "flash": "gemini",
    "pro":   "gemini",
    "codex": "codex",
    "gpt":   "codex",  # deprecated alias -> codex
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

    cmd = [codex, "exec", "--skip-git-repo-check"]
    for ref_path in references:
        cmd += ["--image", os.path.abspath(ref_path)]
    cmd.append(instruction)

    images_dir = os.path.expanduser("~/.codex/generated_images")
    start = time.time() - 2  # small clock-skew buffer

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
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
        choices=["flash", "pro", "codex", "gpt"],
        default="flash",
        help=(
            "Model: flash (Gemini fast), pro (Gemini high-quality), "
            "codex (official gpt-image-2 via the Codex CLI; 'gpt' is a deprecated alias)"
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
    else:
        generate_image(
            args.prompt, args.output, args.aspect, args.references, args.model, args.size,
        )


if __name__ == "__main__":
    main()
