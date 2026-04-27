#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "google-genai",
#     "openai>=1.0.0",
#     "pillow",
# ]
# ///
"""
Generate images using Google Gemini (Flash, Pro) or OpenAI (gpt-image-2).

Usage:
    uv run image.py --prompt "A colorful abstract pattern" --output "./hero.png"
    uv run image.py --prompt "Minimalist icon" --output "./icon.png" --aspect landscape
    uv run image.py --prompt "Similar style image" --output "./new.png" --reference "./existing.png"
    uv run image.py --prompt "High quality art" --output "./art.png" --model pro --size 2K
    uv run image.py --prompt "A photorealistic espresso cup" --output "./cup.png" --model gpt --quality high
    uv run image.py --prompt "Combine these refs" --output "./blend.png" --model gpt --reference "./a.png" --reference "./b.png"
"""

import argparse
import os
import sys

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


def get_aspect_instruction(aspect: str) -> str:
    """Return aspect ratio instruction for the prompt."""
    aspects = {
        "square": "Generate a square image (1:1 aspect ratio).",
        "landscape": "Generate a landscape/wide image (16:9 aspect ratio).",
        "portrait": "Generate a portrait/tall image (9:16 aspect ratio).",
    }
    return aspects.get(aspect, aspects["square"])


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


if __name__ == "__main__":
    main()
