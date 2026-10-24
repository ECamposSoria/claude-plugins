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

    uv run fal.py run ENDPOINT --arg duration=5 --max-usd 2 --approved --out ./out/
    uv run fal.py run ENDPOINT --dry-run --max-usd 0.40 --out ./out/
    uv run fal.py spend [--since YYYY-MM-DD]

Run flags: --max-usd FLOAT, --approved, --over-cap, --dry-run.
Exit code 3 means refused by the spend guard.
Auth: FAL_KEY env var, else FAL_KEY=... read from ~/.secrets/fal.env.
"""

import argparse
import fcntl
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

PLATFORM_API = "https://api.fal.ai/v1"
USER_AGENT = "nano-banana-multi/fal.py"


def _config(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if not value:
        env_file = Path.home() / ".secrets" / "fal.env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith(f"{name}="):
                    value = line.split("=", 1)[1].strip().strip("'\"")
    return value or default


def _load_key() -> str:
    key = _config("FAL_KEY")
    if not key:
        print("Error: set FAL_KEY or create ~/.secrets/fal.env with FAL_KEY=...", file=sys.stderr)
        sys.exit(1)
    os.environ["FAL_KEY"] = key  # fal_client reads it from the environment
    return key


@dataclass
class Estimate:
    usd: float | None
    lower_bound: bool
    note: str


def _number(value) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError("Expected a finite, nonnegative number")
    return number


def estimate_cost(price: dict, arguments: dict) -> Estimate:
    """Estimate documented units without guessing model-specific pricing."""
    unit = str(price.get("unit", "unknown")).strip().lower()
    lower = unit in ("second", "seconds")
    note = ("Per-second video prices vary with resolution and audio; the pricing API rate "
            "is only a hint; read the model page.") if lower else ""
    if lower and any(x in str(arguments.get("resolution", "")).lower() for x in ("1080", "4k", "2160")):
        note += " Pricing uses the 720p rate; higher resolution costs more."
    try:
        rate = _number(price["unit_price"])
        if price.get("currency", "USD") != "USD":
            return Estimate(None, lower, "Non-USD price; read the model page.")
        if unit in ("second", "seconds"):
            try:
                quantity = _number(str(arguments["duration"]).strip().removesuffix("s"))
            except (KeyError, TypeError, ValueError):
                return Estimate(None, lower, f"Duration is unknown. {note}".strip())
        elif unit in ("image", "images"):
            quantity = _number(arguments.get("num_images", 1))
        elif unit in ("megapixel", "megapixels"):
            size = arguments.get("image_size")
            if not isinstance(size, dict):
                return Estimate(None, False, "Megapixel image dimensions are unknown.")
            quantity = _number(size["width"]) * _number(size["height"]) / 1e6
            quantity *= _number(arguments.get("num_images", 1))
        elif unit in ("generation", "generations", "request", "requests", "video", "videos"):
            quantity = 1
        elif unit == "units" and rate == 1:
            return Estimate(None, False, "Placeholder price; read the model page.")
        else:
            return Estimate(None, False, f"Unknown cost for unit {unit!r}; read the model page.")
        return Estimate(_number(rate * quantity), lower, note)
    except (KeyError, TypeError, ValueError, OverflowError):
        return Estimate(None, lower, f"Invalid price or quantity for {unit}. {note}".strip())


def guard(est: Estimate, max_usd: float | None, approved: bool, threshold: float,
          month_spend: float | None, monthly_cap: float | None, over_cap: bool) -> tuple[bool, str]:
    """Decide whether the estimated spend is authorized."""
    try:
        for value in (est.usd, max_usd, threshold, month_spend, monthly_cap):
            if value is not None:
                _number(value)
    except (TypeError, ValueError):
        return False, "Spend values must be finite and nonnegative."
    if (est.usd is None or est.lower_bound) and max_usd is None:
        return False, ("Read the price on https://fal.ai/models/<endpoint> and rerun with "
                       "--max-usd <estimate>.")
    if est.usd is not None and not est.lower_bound and max_usd is not None and est.usd > max_usd:
        return False, f"Estimated ${est.usd:.4f} exceeds the stated ceiling --max-usd ${max_usd:.4f}."
    effective = _effective_usd(est, max_usd)
    if effective > threshold and not approved:
        return False, (f"Estimated ${effective:.4f} is above the ${threshold:.4f} approval threshold "
                       "(FAL_APPROVE_USD). Ask the user to approve this spend, then rerun with --approved.")
    if monthly_cap is not None and not over_cap:
        if month_spend is None:
            return False, (f"Month-to-date spend unknown; run ${effective:.4f}; cannot enforce "
                           f"FAL_MONTHLY_CAP_USD=${monthly_cap:.4f}. Usage lookup failed.")
        if month_spend + effective > monthly_cap:
            return False, (f"Month-to-date spend ${month_spend:.4f} + run ${effective:.4f} exceeds "
                           f"FAL_MONTHLY_CAP_USD=${monthly_cap:.4f}. Rerun with --over-cap to override.")
    return True, f"Allowed: estimated ${effective:.4f}."


def _month_start() -> str:
    return datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


def _usage(since: str) -> list[dict]:
    params = [("start", since), ("expand", "summary")]
    rows = []
    cursors = set()
    while True:
        page = _platform_get("/models/usage", params)
        rows.extend(page["summary"])
        if not page.get("has_more"):
            return rows
        cursor = page.get("next_cursor")
        if not cursor or cursor in cursors:
            raise ValueError("Invalid usage pagination cursor")
        cursors.add(cursor)
        params = [("start", since), ("expand", "summary"), ("cursor", cursor)]


def month_to_date_spend() -> float | None:
    """Sum current UTC month usage, failing closed on unavailable usage."""
    try:
        return sum(_number(row["cost_total"]) for row in _usage(_month_start()))
    except Exception as exc:
        print(f"Warning: usage lookup failed: {exc}", file=sys.stderr)
        return None


def cmd_spend(args) -> None:
    since = (datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc).isoformat()
             if args.since else _month_start())
    grouped = {}
    for row in _usage(since):
        key = (row["endpoint_id"], row["unit"])
        quantity, cost = grouped.get(key, (0, 0))
        grouped[key] = (quantity + _number(row["quantity"]), cost + _number(row["cost_total"]))
    for (endpoint, unit), (quantity, cost) in sorted(grouped.items(), key=lambda item: -item[1][1]):
        print(f"{endpoint} | {quantity:g} {unit} | ${cost:.4f}")
    print(f"TOTAL ${sum(cost for _, cost in grouped.values()):.4f}")


def _effective_usd(est: Estimate, max_usd: float | None) -> float | None:
    if est.usd is None:
        return max_usd
    return max(est.usd, max_usd) if max_usd is not None else est.usd


def _ledger_path() -> Path:
    return Path.home() / ".cache/nano-banana-multi/fal-ledger.jsonl"


def _ledger(args, kind: str, effective: float, **fields) -> None:
    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = dict(kind=kind, ts=datetime.now(timezone.utc).isoformat(), endpoint=args.endpoint,
                 effective_usd=effective, **fields)
    with path.open("a") as stream:
        stream.write(json.dumps(entry) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _ledger_warn(args, kind: str, effective: float, **fields) -> None:
    try:
        _ledger(args, kind, effective, **fields)
    except Exception as exc:
        print(f"Warning: could not append fal ledger: {exc}", file=sys.stderr)


def _recent_reservations() -> float:
    path = _ledger_path()
    if not path.exists():
        return 0.0
    now = datetime.now(timezone.utc)
    total = 0.0
    for line in path.read_text().splitlines():
        entry = json.loads(line)
        if entry.get("kind") == "reservation":
            age = (now - datetime.fromisoformat(entry["ts"])).total_seconds()
            if age <= 3600:
                total += _number(entry["effective_usd"])
    return total


def _check_and_reserve(args, est: Estimate, threshold: float, cap: float | None) -> tuple[bool, str]:
    def check():
        spend = month_to_date_spend() if cap is not None else None
        if spend is not None:
            spend += _recent_reservations()
        return guard(est, args.max_usd, args.approved, threshold, spend, cap, args.over_cap)

    def reserve():
        _ledger(args, "reservation", _effective_usd(est, args.max_usd),
                estimate_usd=est.usd, lower_bound=est.lower_bound, max_usd=args.max_usd,
                approved=args.approved, pid=os.getpid())

    if cap is not None and not args.dry_run:
        try:
            path = _ledger_path().with_suffix(".lock")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                allowed, message = check()
                if allowed:
                    reserve()
                return allowed, message
        except Exception as exc:
            return False, f"Cannot enforce FAL_MONTHLY_CAP_USD: reservation failed: {exc}"
    try:
        allowed, message = check()
    except Exception as exc:
        return False, f"Cannot enforce FAL_MONTHLY_CAP_USD: ledger lookup failed: {exc}"
    if allowed and not args.dry_run:
        try:
            reserve()
        except Exception as exc:
            print(f"Warning: could not append fal ledger: {exc}", file=sys.stderr)
    return allowed, message


def _input_defaults(endpoint: str) -> dict:
    try:
        data = _platform_get("/models", [("endpoint_id", endpoint), ("expand", "openapi-3.0")])
        schemas = (data["models"][0].get("openapi") or {}).get("components", {}).get("schemas", {})
        return {prop: spec["default"] for name, schema in schemas.items() if name.endswith("Input")
                for prop, spec in schema.get("properties", {}).items() if "default" in spec}
    except Exception as exc:
        print(f"Warning: input defaults lookup failed: {exc}", file=sys.stderr)
        return {}


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
    arguments: dict = {}
    if args.json:
        arguments.update(json.loads(Path(args.json).read_text()))
    for item in args.arg or []:
        key, _, raw = item.partition("=")
        _set_input(arguments, key, _parse_value(raw))
    files = []
    preview = json.loads(json.dumps(arguments))
    for item in args.file or []:
        key, _, path = item.partition("=")
        if not os.path.exists(path):
            print(f"Error: file not found: {path}", file=sys.stderr)
            sys.exit(1)
        files.append((key, path))
        _set_input(preview, key, f"<upload:{path}>")

    prices = _prices([args.endpoint])
    price = next((p for p in prices if p.get("endpoint_id") == args.endpoint), {})
    defaults_used = {key: value for key, value in _input_defaults(args.endpoint).items() if key not in preview}
    est = estimate_cost(price, {**defaults_used, **preview})
    amount = "unknown" if est.usd is None else f"${est.usd:.4f}"
    print(f"Price: {price.get('unit_price', 'unknown')} {price.get('currency', 'USD')} per "
          f"{price.get('unit', 'unknown')}; estimate {amount}"
          f"{' (lower bound)' if est.lower_bound else ''}; {est.note}", file=sys.stderr)
    threshold = _number(_config("FAL_APPROVE_USD", "0.50"))
    cap_value = _config("FAL_MONTHLY_CAP_USD")
    cap = _number(cap_value) if cap_value is not None else None
    allowed, message = _check_and_reserve(args, est, threshold, cap)
    message = message.replace("https://fal.ai/models/<endpoint>", f"https://fal.ai/models/{args.endpoint}")
    print(message, file=sys.stderr)
    if args.dry_run:
        print(json.dumps(dict(arguments=preview, defaults_used=defaults_used, estimate=asdict(est),
                              guard=dict(allowed=allowed, message=message)), indent=2))
    if not allowed:
        sys.exit(3)
    if args.dry_run:
        return

    import fal_client

    effective = _effective_usd(est, args.max_usd)
    try:
        _load_key()
        for key, path in files:
            _set_input(arguments, key, fal_client.upload_file(path))
        handle = fal_client.submit(args.endpoint, arguments=arguments)
    except Exception as exc:
        _ledger_warn(args, "failed", effective, error=str(exc), pid=os.getpid())
        raise
    # Printed before waiting so a killed process can still recover the result.
    print(f"request_id: {handle.request_id}", file=sys.stderr, flush=True)
    _ledger_warn(args, "submitted", effective, request_id=handle.request_id)
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

    p = sub.add_parser("spend", help="Show usage costs since a UTC date")
    p.add_argument("--since", help="YYYY-MM-DD; defaults to the current UTC month")
    p.set_defaults(func=cmd_spend)

    p = sub.add_parser("run", help="Submit a generation, wait, download outputs")
    p.add_argument("endpoint")
    p.add_argument("--arg", action="append", help="key=value (JSON-parsed if valid); key[]=v appends")
    p.add_argument("--file", action="append", help="key=path, uploaded to fal storage; key[]=path appends")
    p.add_argument("--json", help="JSON file with base arguments")
    p.add_argument("--out", required=True, help="Output file (single output) or directory")
    p.add_argument("--max-usd", type=float)
    p.add_argument("--approved", action="store_true")
    p.add_argument("--over-cap", action="store_true")
    p.add_argument("--dry-run", action="store_true")
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
