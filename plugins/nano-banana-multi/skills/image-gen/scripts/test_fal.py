# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""Offline spend-guard tests."""

import json
import socket
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest
import fal


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("FAL_KEY", "dummy-test-key")
    monkeypatch.delenv("FAL_APPROVE_USD", raising=False)
    monkeypatch.delenv("FAL_MONTHLY_CAP_USD", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("Network forbidden in tests")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(fal.urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(fal, "_platform_get", forbidden)


@pytest.mark.parametrize("unit,args,rate,usd,lower", [
    ("seconds", {"duration": 5}, .1, .5, False),
    (" SECOND ", {"duration": "10"}, .1, 1, False),
    ("seconds", {"duration": "5s"}, .1, .5, False),
    ("seconds", {}, .1, None, False),
    ("seconds", {"duration": "oops"}, .1, None, False),
    ("seconds", {"duration": 5, "resolution": "1080p"}, .1, .5, True),
    ("seconds", {"duration": 5, "resolution": "4K"}, .1, .5, True),
    ("seconds", {"duration": 5, "resolution": "2160p"}, .1, .5, True),
    ("images", {}, .1, .1, False),
    ("images", {"num_images": 4}, .1, .4, False),
    ("megapixels", {"image_size": {"width": 1000, "height": 2000}, "num_images": 2}, .1, .4, False),
    ("megapixels", {"image_size": "landscape_16_9"}, .1, None, False),
    ("units", {}, 1, None, False),
    ("1000 tokens", {}, .1, None, False),
    ("credits", {}, .1, None, False),
    ("generations", {}, .1, .1, False),
    ("requests", {}, .1, .1, False),
    ("videos", {}, .1, .1, False),
    ("images", {"num_images": -1}, .1, None, False),
])
def test_estimate(unit, args, rate, usd, lower):
    result = fal.estimate_cost(dict(unit=unit, unit_price=rate), args)
    assert result.usd == (pytest.approx(usd) if usd is not None else None)
    assert result.lower_bound is lower
    if lower:
        assert "720p" in result.note
    if unit == "seconds" and usd is None:
        assert "duration is unknown" in result.note.lower()
    if unit == "units":
        assert "placeholder" in result.note.lower()
    if unit == "1000 tokens":
        assert unit in result.note


@pytest.mark.parametrize("usd,lower,maximum,approved,spend,cap,over,allowed", [
    (None, False, None, False, None, None, False, False),
    (None, False, .4, False, None, None, False, True),
    (1, False, None, False, None, None, False, False),
    (1, False, None, True, None, None, False, True),
    (1, False, .5, True, None, None, False, False),
    (.2, True, None, True, None, None, False, False),
    (.2, True, .6, False, None, None, False, False),
    (.6, True, .2, False, None, None, False, False),
    (.6, True, .2, True, None, None, False, True),
    (.4, False, None, False, .8, 1, False, False),
    (.4, False, None, False, .8, 1, True, True),
    (.4, False, None, False, None, 1, False, False),
    (.4, False, None, False, None, 1, True, True),
    (None, False, float("nan"), True, None, None, False, False),
])
def test_guard(usd, lower, maximum, approved, spend, cap, over, allowed):
    result, message = fal.guard(fal.Estimate(usd, lower, ""), maximum, approved, .5, spend, cap, over)
    assert result is allowed
    assert message
    if allowed:
        assert "estimated $" in message


def test_usage_pagination(monkeypatch):
    calls = []

    def page(path, params):
        calls.append((path, params))
        return {"summary": [{"cost_total": .2 if len(calls) == 1 else .3}],
                "has_more": len(calls) == 1, "next_cursor": "page2"}

    monkeypatch.setattr(fal, "_platform_get", page)
    assert fal.month_to_date_spend() == pytest.approx(.5)
    assert calls[0][0] == "/models/usage"
    assert ("expand", "summary") in calls[0][1]
    assert ("cursor", "page2") in calls[1][1]
    assert dict(calls[0][1])["start"].endswith("01T00:00:00+00:00")


def test_usage_failure(capsys):
    assert fal.month_to_date_spend() is None
    assert "Warning" in capsys.readouterr().err


@pytest.mark.parametrize("rate,flags,code", [(.1, [], 0), (1, [], 3), (1, ["--approved"], 0)])
def test_dry_run(monkeypatch, tmp_path, capsys, rate, flags, code):
    stub = types.ModuleType("fal_client")

    def forbidden(name):
        raise AssertionError(f"fal_client attribute accessed: {name}")

    stub.__getattr__ = forbidden
    monkeypatch.setitem(sys.modules, "fal_client", stub)
    monkeypatch.setattr(fal, "_prices", lambda endpoints: [dict(endpoint_id="test", unit="images", unit_price=rate)])
    source = tmp_path / "image.png"
    source.write_bytes(b"fake")
    base = tmp_path / "args.json"
    base.write_text(json.dumps({"image_urls": ["existing"], "prompt": "base"}))
    monkeypatch.setattr(sys, "argv", ["fal.py", "run", "test", "--out", str(tmp_path), "--dry-run",
                                     "--json", str(base), "--arg", "prompt=override",
                                     "--file", f"image_urls[]={source}", "--file", f"image_urls[]={source}"] + flags)
    if code:
        with pytest.raises(SystemExit) as exc:
            fal.main()
        assert exc.value.code == code
    else:
        fal.main()
    output = json.loads(capsys.readouterr().out)
    assert output["arguments"]["prompt"] == "override"
    assert output["arguments"]["image_urls"] == ["existing", f"<upload:{source}>", f"<upload:{source}>"]
    assert output["guard"]["allowed"] is (code == 0)
    assert output["estimate"]["usd"] == rate
    assert not (tmp_path / ".cache").exists()


def test_refused_real_run_never_imports_client(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "fal_client", None)
    monkeypatch.setattr(fal, "_prices", lambda endpoints: [])
    monkeypatch.setattr(sys, "argv", ["fal.py", "run", "test", "--out", str(tmp_path)])
    with pytest.raises(SystemExit) as exc:
        fal.main()
    assert exc.value.code == 3


def test_config_precedence(monkeypatch, tmp_path):
    secrets = tmp_path / ".secrets"
    secrets.mkdir()
    (secrets / "fal.env").write_text("FAL_KEY='fake-file-key'\nFAL_APPROVE_USD=0.25\n")
    assert fal._load_key() == "dummy-test-key"
    assert fal._config("FAL_APPROVE_USD") == "0.25"
    monkeypatch.setenv("FAL_APPROVE_USD", "0.75")
    assert fal._config("FAL_APPROVE_USD") == "0.75"


def test_spend_sorted(monkeypatch, capsys):
    monkeypatch.setattr(fal, "_platform_get", lambda path, params: {
        "summary": [dict(endpoint_id="cheap", unit="images", quantity=2, cost_total=.2),
                    dict(endpoint_id="costly", unit="seconds", quantity=3, cost_total=1)], "has_more": False})
    monkeypatch.setattr(sys, "argv", ["fal.py", "spend", "--since", "2026-10-01"])
    fal.main()
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "costly | 3 seconds | $1.0000"
    assert lines[1] == "cheap | 2 images | $0.2000"
    assert lines[2] == "TOTAL $1.2000"


def test_allowed_upload_submit_and_ledger(monkeypatch, tmp_path, capsys):
    calls = []
    client = types.ModuleType("fal_client")
    client.upload_file = lambda path: calls.append(("upload", path)) or "uploaded"

    def submit(endpoint, arguments):
        calls.append(("submit", endpoint, arguments))
        return types.SimpleNamespace(request_id="test-id", get=lambda: {})

    client.submit = submit
    monkeypatch.setitem(sys.modules, "fal_client", client)
    monkeypatch.setattr(fal, "_prices", lambda endpoints: [dict(endpoint_id="test", unit="images", unit_price=.1)])
    monkeypatch.setattr(fal, "_save_outputs", lambda *args: None)
    source = tmp_path / "input.png"
    source.write_bytes(b"fake")
    monkeypatch.setattr(sys, "argv", ["fal.py", "run", "test", "--out", str(tmp_path),
                                     "--arg", 'images[]="existing"', "--file", f"images[]={source}"])
    fal.main()
    assert calls == [("upload", str(source)), ("submit", "test", {"images": ["existing", "uploaded"]})]
    ledger = json.loads((tmp_path / ".cache/nano-banana-multi/fal-ledger.jsonl").read_text())
    assert ledger["request_id"] == "test-id"
    assert ledger["estimate_usd"] == .1
    assert ledger["endpoint"] == "test"
    assert ledger["approved"] is False
    assert "request_id: test-id" in capsys.readouterr().err


def test_monthly_cap_failure_blocks_dry_run(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("FAL_MONTHLY_CAP_USD", "1")
    monkeypatch.setattr(fal, "_prices", lambda endpoints: [dict(endpoint_id="test", unit="images", unit_price=.1)])
    monkeypatch.setitem(sys.modules, "fal_client", None)
    monkeypatch.setattr(sys, "argv", ["fal.py", "run", "test", "--out", str(tmp_path), "--dry-run"])
    with pytest.raises(SystemExit) as exc:
        fal.main()
    assert exc.value.code == 3
    output = json.loads(capsys.readouterr().out)
    assert "FAL_MONTHLY_CAP_USD" in output["guard"]["message"]
    assert output["guard"]["allowed"] is False
