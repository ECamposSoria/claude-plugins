# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fal-client>=0.5.0",
# ]
# ///
"""
Run any fal.ai model (image or video) from the command line.

fal.ai hosts 1000+ generative endpoints (GPT Image, Nano Banana, Flux, Seedream for
images; Kling, Seedance, Gemini Omni, Wan, Hailuo for video) behind one queue API and
one key. Every endpoint has its own input schema, so this script stays generic:
discover the endpoint, read its schema, then pass inputs as --arg / --file.

Usage:
    uv run fal.py search "first last frame" --category image-to-video
    uv run fal.py schema kling/v4/image-to-video
    uv run fal.py price kling/v4/image-to-video openai/gpt-image-2/edit
    uv run fal.py run openai/gpt-image-2/edit \
        --file 'image_urls[]=base.jpg' --file 'image_urls[]=ref.jpg' \
        --arg prompt="..." --arg quality=high --out ./out/
    uv run fal.py run kling/v4/image-to-video \
        --file start_image_url=start.png --file end_image_url=end.png \
        --arg prompt="..." --arg duration=10 --out ./clip.mp4
    uv run fal.py result kling/v4/image-to-video <request_id> --out ./clip.mp4

Auth: FAL_KEY env var, else FAL_KEY=... read from ~/.secrets/fal.env.
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

PLATFORM_API = "https://api.fal.ai/v1"
USER_AGENT = "nano-banana-multi/fal.py"


def _load_key() -> str:
    key = os.environ.get("FAL_KEY")
    if not key:
        env_file = Path.home() / ".secrets" / "fal.env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("FAL_KEY="):
                    key = line.split("=", 1)[1].strip().strip("'\"")
    if not key:
        print("Error: set FAL_KEY or create ~/.secrets/fal.env with FAL_KEY=...", file=sys.stderr)
        sys.exit(1)
    os.environ["FAL_KEY"] = key  # fal_client reads it from the environment
    return key


def _platform_get(path: str, params: list[tuple[str, str]]) -> dict:
    url = f"{PLATFORM_API}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url, headers={"Authorization": f"Key {_load_key()}", "User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def cmd_search(args) -> None:
    params = [("q", args.query), ("limit", str(args.limit)), ("status", "active")]
    if args.category:
        params.append(("category", args.category))
    for m in _platform_get("/models", params).get("models", []):
        md = m.get("metadata", {})
        print(f"{m['endpoint_id']} | {md.get('category')} | {md.get('display_name')}")


def cmd_schema(args) -> None:
    data = _platform_get("/models", [("endpoint_id", args.endpoint), ("expand", "openapi-3.0")])
    model = data["models"][0]
    md = model.get("metadata", {})
    print(f"{model['endpoint_id']} — {md.get('display_name')}\n{md.get('description', '')}\n")
    schemas = (model.get("openapi") or {}).get("components", {}).get("schemas", {})
    for name, schema in schemas.items():
        if not name.endswith("Input"):
            continue
        required = set(schema.get("required", []))
        for prop, spec in schema.get("properties", {}).items():
            enum = spec.get("enum") or next(
                (s["enum"] for s in spec.get("anyOf", []) if "enum" in s), None
            )
            line = f"  {prop}{' (required)' if prop in required else ''}"
            if enum:
                line += f"  enum={enum}"
            if spec.get("default") is not None:
                line += f"  default={spec['default']!r}"
            print(line)
            if spec.get("description"):
                print(f"      {spec['description'].splitlines()[0][:160]}")


def _prices(endpoints: list[str]) -> list[dict]:
    return _platform_get("/models/pricing", [("endpoint_id", e) for e in endpoints]).get(
        "prices", []
    )


def cmd_price(args) -> None:
    for p in _prices(args.endpoints):
        print(f"{p['endpoint_id']} | {p['unit_price']} {p['currency']} per {p['unit']}")


def _parse_value(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _set_input(arguments: dict, key: str, value) -> None:
    if key.endswith("[]"):
        arguments.setdefault(key[:-2], []).append(value)
    else:
        arguments[key] = value


def _media_urls(node) -> list[str]:
    """Every downloadable file URL in a fal result, in document order."""
    found = []
    if isinstance(node, dict):
        url = node.get("url")
        if isinstance(url, str) and url.startswith("http"):
            found.append(url)
        for value in node.values():
            found.extend(_media_urls(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_media_urls(item))
    return found


def _save_outputs(result: dict, out: str, request_id: str) -> None:
    out_path = Path(out)
    urls = list(dict.fromkeys(_media_urls(result)))
    as_file = out_path.suffix != "" and len(urls) == 1
    out_dir = out_path.parent if as_file else out_path
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / f"fal-{request_id}.json").write_text(json.dumps(result, indent=2))
    for i, url in enumerate(urls, 1):
        if as_file:
            target = out_path
        else:
            ext = Path(urllib.parse.urlparse(url).path).suffix or ".bin"
            target = out_dir / f"fal-{request_id}-{i}{ext}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=300) as resp:
            target.write_bytes(resp.read())
        print(f"Saved: {target}")
    if not urls:
        print(json.dumps(result, indent=2))


def cmd_run(args) -> None:
    try:
        _run(args)
    except Exception as exc:  # surface fal's own message (e.g. "Exhausted balance") instead of a traceback
        response = getattr(exc, "response", None)
        detail = getattr(response, "text", "") if response is not None else ""
        print(f"Error: {exc}\n{detail}".rstrip(), file=sys.stderr)
        sys.exit(1)


def _run(args) -> None:
    import fal_client

    _load_key()
    arguments: dict = {}
    if args.json:
        arguments.update(json.loads(Path(args.json).read_text()))
    for item in args.arg or []:
        key, _, raw = item.partition("=")
        _set_input(arguments, key, _parse_value(raw))
    for item in args.file or []:
        key, _, path = item.partition("=")
        if not os.path.exists(path):
            print(f"Error: file not found: {path}", file=sys.stderr)
            sys.exit(1)
        _set_input(arguments, key, fal_client.upload_file(path))

    for p in _prices([args.endpoint]):
        print(f"Price: {p['unit_price']} {p['currency']} per {p['unit']}", file=sys.stderr)

    handle = fal_client.submit(args.endpoint, arguments=arguments)
    # Printed before waiting so a killed process can still recover the result.
    print(f"request_id: {handle.request_id}", file=sys.stderr, flush=True)
    _save_outputs(handle.get(), args.out, handle.request_id)


def cmd_upload(args) -> None:
    import fal_client

    _load_key()
    for path in args.paths:
        print(f"{path}\t{fal_client.upload_file(path)}")


def cmd_result(args) -> None:
    import fal_client

    _load_key()
    status = fal_client.status(args.endpoint, args.request_id)
    if type(status).__name__ != "Completed":
        print(f"Not finished yet: {type(status).__name__}", file=sys.stderr)
        sys.exit(2)
    _save_outputs(fal_client.result(args.endpoint, args.request_id), args.out, args.request_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run any fal.ai model (image or video)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("search", help="Find active endpoints")
    p.add_argument("query")
    p.add_argument("--category", help="e.g. text-to-image, image-to-image, image-to-video")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("schema", help="Show an endpoint's input parameters")
    p.add_argument("endpoint")
    p.set_defaults(func=cmd_schema)

    p = sub.add_parser("price", help="Show unit prices")
    p.add_argument("endpoints", nargs="+")
    p.set_defaults(func=cmd_price)

    p = sub.add_parser("run", help="Submit a generation, wait, download outputs")
    p.add_argument("endpoint")
    p.add_argument("--arg", action="append", help="key=value (JSON-parsed if valid); key[]=v appends")
    p.add_argument("--file", action="append", help="key=path, uploaded to fal storage; key[]=path appends")
    p.add_argument("--json", help="JSON file with base arguments")
    p.add_argument("--out", required=True, help="Output file (single output) or directory")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("upload", help="Upload files to fal storage and print their URLs (for nested inputs)")
    p.add_argument("paths", nargs="+")
    p.set_defaults(func=cmd_upload)

    p = sub.add_parser("result", help="Fetch the outputs of an earlier request")
    p.add_argument("endpoint")
    p.add_argument("request_id")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_result)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
