# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""Offline spend-guard tests."""

import json
import socket
import sys
import types
from datetime import datetime, timedelta, timezone
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
    monkeypatch.setattr(fal, "_input_defaults", lambda endpoint: {})

    def forbidden(*args, **kwargs):
        raise AssertionError("Network forbidden in tests")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(fal.urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(fal, "_platform_get", forbidden)


@pytest.mark.parametrize("unit,args,rate,usd,lower", [
    ("seconds", {"duration": 5}, .1, .5, True),
    (" SECOND ", {"duration": "10"}, .1, 1, True),
    ("seconds", {"duration": "5s"}, .1, .5, True),
    ("seconds", {}, .1, None, True),
    ("seconds", {"duration": "oops"}, .1, None, True),
    ("seconds", {"duration": 5, "resolution": "1080p"}, .1, .5, True),
    ("seconds", {"duration": 5, "resolution": "4K"}, .1, .5, True),
    ("seconds", {"duration": 5, "resolution": "2160p"}, .1, .5, True),
    ("images", {}, .1, .1, True),
    ("images", {"num_images": 4}, .1, .4, True),
    ("megapixels", {"image_size": {"width": 1000, "height": 2000}, "num_images": 2}, .1, .4, True),
    ("megapixels", {"image_size": "landscape_16_9"}, .1, None, False),
    ("units", {}, 1, None, False),
    ("1000 tokens", {}, .1, None, False),
    ("credits", {}, .1, None, False),
    ("generations", {}, .1, .1, True),
    ("requests", {}, .1, .1, True),
    ("videos", {}, .1, .1, True),
    ("images", {"num_images": -1}, .1, None, False),
])
def test_estimate(unit, args, rate, usd, lower):
    result = fal.estimate_cost(dict(unit=unit, unit_price=rate), args)
    assert result.usd == (pytest.approx(usd) if usd is not None else None)
    assert result.lower_bound is lower
    if usd is not None:
        assert "resolution, quality, audio and image count" in result.note
    if unit.strip().lower() in ("second", "seconds"):
        assert "resolution and audio" in result.note
        assert "only a hint" in result.note
    if args.get("resolution") in ("1080p", "4K", "2160p"):
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
    (.2, False, .6, False, None, None, False, False),
    (.2, False, .6, True, .5, 1, False, False),
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


@pytest.mark.parametrize("rate,flags,code", [
    (.1, [], 3), (1, [], 3), (1, ["--approved"], 3),
    (.1, ["--max-usd", "0.1"], 0),
    (1, ["--max-usd", "1"], 3),
    (1, ["--max-usd", "1", "--approved"], 0),
])
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
                                     "--max-usd", "0.1", "--arg", 'images[]="existing"', "--file", f"images[]={source}"])
    fal.main()
    assert calls == [("upload", str(source)), ("submit", "test", {"images": ["existing", "uploaded"]})]
    ledger, submitted = [json.loads(line) for line in fal._ledger_path().read_text().splitlines()]
    assert ledger["kind"] == "reservation"
    assert submitted["kind"] == "submitted"
    assert submitted["request_id"] == "test-id"
    assert submitted["effective_usd"] == .1
    assert ledger["estimate_usd"] == .1
    assert ledger["endpoint"] == "test"
    assert ledger["approved"] is False
    assert "request_id: test-id" in capsys.readouterr().err


def test_monthly_cap_failure_blocks_dry_run(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("FAL_MONTHLY_CAP_USD", "1")
    monkeypatch.setattr(fal, "_prices", lambda endpoints: [dict(endpoint_id="test", unit="images", unit_price=.1)])
    monkeypatch.setitem(sys.modules, "fal_client", None)
    monkeypatch.setattr(sys, "argv", ["fal.py", "run", "test", "--out", str(tmp_path), "--dry-run", "--max-usd", "0.1"])
    with pytest.raises(SystemExit) as exc:
        fal.main()
    assert exc.value.code == 3
    output = json.loads(capsys.readouterr().out)
    assert "FAL_MONTHLY_CAP_USD" in output["guard"]["message"]
    assert output["guard"]["allowed"] is False


@pytest.fixture
def run_stub(monkeypatch, tmp_path):
    calls = []

    def submit(endpoint, arguments):
        entries = [json.loads(line) for line in fal._ledger_path().read_text().splitlines()]
        assert entries[-1]["kind"] == "reservation"
        calls.append(arguments.copy())
        return types.SimpleNamespace(request_id="stub-id", get=lambda: {})

    monkeypatch.setitem(sys.modules, "fal_client", types.SimpleNamespace(submit=submit))
    monkeypatch.setattr(fal, "_save_outputs", lambda *args: None)
    monkeypatch.setattr(fal, "_prices", lambda endpoints: [dict(endpoint_id="test", unit="images", unit_price=.4)])
    monkeypatch.setattr(sys, "argv", ["fal.py", "run", "test", "--out", str(tmp_path)])
    return calls


@pytest.mark.parametrize("flags", [[], ["--max-usd", "0.504"]])
def test_seconds_require_ceiling_and_audio_approval(monkeypatch, run_stub, flags):
    monkeypatch.setattr(fal, "_prices", lambda endpoints: [dict(endpoint_id="test", unit="seconds", unit_price=.14)])
    monkeypatch.setattr(sys, "argv", sys.argv + ["--arg", "duration=3"] + flags)
    with pytest.raises(SystemExit) as exc:
        fal.main()
    assert exc.value.code == 3
    assert run_stub == []
    assert not fal._ledger_path().exists()


def test_defaults_are_only_used_for_estimate(monkeypatch, run_stub, capsys):
    monkeypatch.setattr(fal, "_input_defaults", lambda endpoint: {"resolution": "1080p", "duration": "5", "prompt": "default"})
    monkeypatch.setattr(fal, "_prices", lambda endpoints: [dict(endpoint_id="test", unit="seconds", unit_price=.1)])
    argv = sys.argv + ["--max-usd", "0.5", "--arg", "prompt=explicit"]
    monkeypatch.setattr(sys, "argv", argv + ["--dry-run"])
    fal.main()
    output = json.loads(capsys.readouterr().out)
    assert output["defaults_used"] == {"resolution": "1080p", "duration": "5"}
    assert output["estimate"]["usd"] == .5
    assert output["estimate"]["lower_bound"] is True
    assert "720p" in output["estimate"]["note"]
    assert output["arguments"] == {"prompt": "explicit"}
    assert not fal._ledger_path().exists()
    monkeypatch.setattr(sys, "argv", argv)
    fal.main()
    assert run_stub == [{"prompt": "explicit"}]


def test_cap_counts_recent_reservation(monkeypatch, run_stub):
    monkeypatch.setattr(sys, "argv", sys.argv + ["--max-usd", "0.4"])
    monkeypatch.setenv("FAL_MONTHLY_CAP_USD", "1")
    monkeypatch.setattr(fal, "month_to_date_spend", lambda: .4)
    fal.main()
    with pytest.raises(SystemExit) as exc:
        fal.main()
    assert exc.value.code == 3
    assert len(run_stub) == 1
    entries = [json.loads(line) for line in fal._ledger_path().read_text().splitlines()]
    assert [entry["kind"] for entry in entries] == ["reservation", "submitted"]
    assert entries[0]["effective_usd"] == .4
    assert entries[0]["pid"] == fal.os.getpid()


def test_cap_ignores_old_reservations(monkeypatch, run_stub):
    monkeypatch.setattr(sys, "argv", sys.argv + ["--max-usd", "0.4"])
    monkeypatch.setenv("FAL_MONTHLY_CAP_USD", "1")
    monkeypatch.setattr(fal, "month_to_date_spend", lambda: .4)
    path = fal._ledger_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(dict(kind="reservation", effective_usd=10,
                                   ts=(datetime.now(timezone.utc) - timedelta(minutes=61)).isoformat())) + "\n")
    fal.main()
    assert len(run_stub) == 1


def test_capped_dry_run_never_locks_or_writes(monkeypatch, run_stub):
    monkeypatch.setattr(sys, "argv", sys.argv + ["--max-usd", "0.4"])
    monkeypatch.setenv("FAL_MONTHLY_CAP_USD", "1")
    monkeypatch.setattr(fal, "month_to_date_spend", lambda: .4)
    monkeypatch.setattr(sys, "argv", sys.argv + ["--dry-run"])

    def forbidden(*args):
        raise AssertionError("dry-run must not lock")

    monkeypatch.setattr(fal.fcntl, "flock", forbidden)
    fal.main()
    assert not fal._ledger_path().parent.exists()
    assert run_stub == []


def test_cap_reservation_write_failure_refuses(monkeypatch, run_stub):
    monkeypatch.setattr(sys, "argv", sys.argv + ["--max-usd", "0.4"])
    monkeypatch.setenv("FAL_MONTHLY_CAP_USD", "1")
    monkeypatch.setattr(fal, "month_to_date_spend", lambda: .4)

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(fal, "_ledger", broken)
    with pytest.raises(SystemExit) as exc:
        fal.main()
    assert exc.value.code == 3
    assert run_stub == []


@pytest.mark.parametrize("stage", ["upload", "submit"])
def test_failed_run_retains_reservation(monkeypatch, run_stub, tmp_path, stage):
    monkeypatch.setattr(sys, "argv", sys.argv + ["--max-usd", "0.4"])
    def broken(*args, **kwargs):
        raise RuntimeError("stub failure")

    client = sys.modules["fal_client"]
    if stage == "upload":
        source = tmp_path / "input.png"
        source.write_bytes(b"fake")
        monkeypatch.setattr(sys, "argv", sys.argv + ["--file", f"image={source}"])
        client.upload_file = broken
    else:
        client.submit = broken
    with pytest.raises(SystemExit) as exc:
        fal.main()
    assert exc.value.code == 1
    entries = [json.loads(line) for line in fal._ledger_path().read_text().splitlines()]
    assert [entry["kind"] for entry in entries] == ["reservation", "failed"]
    assert entries[1]["effective_usd"] == .4


def test_cap_holds_lock_through_check_and_reservation(monkeypatch, run_stub):
    monkeypatch.setattr(sys, "argv", sys.argv + ["--max-usd", "0.4"])
    monkeypatch.setenv("FAL_MONTHLY_CAP_USD", "1")
    original_ledger = fal._ledger
    checked = []

    def assert_locked(stage):
        with fal._ledger_path().with_suffix(".lock").open("a") as contender:
            with pytest.raises(BlockingIOError):
                fal.fcntl.flock(contender, fal.fcntl.LOCK_EX | fal.fcntl.LOCK_NB)
        checked.append(stage)

    def usage():
        assert_locked("usage")
        return .4

    def ledger(args, kind, effective, **fields):
        if kind == "reservation":
            assert_locked("reservation")
        original_ledger(args, kind, effective, **fields)

    monkeypatch.setattr(fal, "month_to_date_spend", usage)
    monkeypatch.setattr(fal, "_ledger", ledger)
    fal.main()
    assert checked == ["usage", "reservation"]
    with fal._ledger_path().with_suffix(".lock").open("a") as contender:
        fal.fcntl.flock(contender, fal.fcntl.LOCK_EX | fal.fcntl.LOCK_NB)
    assert len(run_stub) == 1


@pytest.mark.parametrize("flags", [[], ["--max-usd", "0.60"]])
def test_nano_banana_pro_4k_requires_budget_and_approval(monkeypatch, run_stub, capsys, flags):
    endpoint = "fal-ai/nano-banana-pro/edit"
    monkeypatch.setattr(fal, "_prices", lambda endpoints: [
        dict(endpoint_id=endpoint, unit="images", unit_price=.15)])
    argv = sys.argv.copy()
    argv[2] = endpoint
    monkeypatch.setattr(sys, "argv", argv + ["--arg", "num_images=2", "--arg",
                                            'resolution="4K"', "--dry-run"] + flags)
    with pytest.raises(SystemExit) as exc:
        fal.main()
    assert exc.value.code == 3
    output = json.loads(capsys.readouterr().out)
    assert output["estimate"]["usd"] == pytest.approx(.30)
    assert output["estimate"]["lower_bound"] is True
    assert output["guard"]["allowed"] is False
    if flags:
        assert "$0.6000" in output["guard"]["message"]
        assert "$0.5000" in output["guard"]["message"]
        assert "--approved" in output["guard"]["message"]
    else:
        assert "--max-usd" in output["guard"]["message"]
    assert run_stub == []
    assert not fal._ledger_path().exists()
