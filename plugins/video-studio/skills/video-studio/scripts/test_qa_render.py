# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest>=8", "numpy>=1.24"]
# ///
"""Focused parser and short-media integration tests for qa_render.py."""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).with_name("qa_render.py")
if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
    pytest.skip("ffmpeg/ffprobe not installed", allow_module_level=True)
SPEC = importlib.util.spec_from_file_location("qa_render", SCRIPT)
qa = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["qa_render"] = qa
SPEC.loader.exec_module(qa)


def test_parse_rate_handles_rational_and_invalid_values():
    assert qa.parse_rate("30000/1001") == pytest.approx(29.97003)
    assert qa.parse_rate("24/1") == 24
    assert qa.parse_rate("0/0") is None
    assert qa.parse_rate("bad") is None


def test_parse_probe_reports_missing_video_and_pixel_format_warning():
    assert qa.parse_probe({"streams": []})[0].level == "FAIL"
    findings = qa.parse_probe({
        "streams": [{"codec_type": "video", "codec_name": "h264", "width": 640,
                     "height": 360, "r_frame_rate": "24/1", "pix_fmt": "yuv444p"}],
        "format": {"duration": "2.0"},
    })
    assert any(f.check == "pix_fmt" and f.level == "WARN" for f in findings)
    assert any(f.check == "duration" and "2.000" in f.message for f in findings)


def test_filter_parsers_keep_intervals_and_trailing_events():
    black = qa.parse_blackdetect("black_start:0.200 black_end:0.700 black_duration:0.5")
    assert black == [(0.2, 0.7)]
    frozen = qa.parse_freezedetect("freeze_start: 1.0\nfreeze_end: 2.0\nfreeze_start: 3.0", 4)
    assert frozen == [(1.0, 2.0), (3.0, 4)]
    silence = qa.parse_silencedetect("silence_start:0.5\nsilence_end:1.7", 2)
    assert silence == [(0.5, 1.7)]


def test_ebur128_parser_reads_final_summary():
    stderr = "momentary: -13.2\nSummary:\n  I: -14.1 LUFS\n  Peak: -0.8 dBFS\n"
    assert qa.parse_ebur128(stderr) == (-14.1, -0.8)


def test_jump_detection_uses_absolute_differences():
    assert qa.jump_indices([0, 255, 0, 0]) == [2]


def test_expected_frames_prefer_the_video_stream_over_the_container():
    # the stream's own frame count wins
    assert qa.expected_frame_count({"nb_frames": "289"}, 99.0, 24) == 289
    # a music bed longer than the picture must not inflate the expectation
    assert qa.expected_frame_count({"duration": "12.0", "avg_frame_rate": "24/1"}, 15.0, 24) == pytest.approx(288)
    # variable-rate phone footage: the average rate, not r_frame_rate
    assert qa.expected_frame_count({"duration": "10.0", "avg_frame_rate": "2950/100"}, 10.0, 30) == pytest.approx(295)
    # nothing in the stream: container duration × nominal rate
    assert qa.expected_frame_count({}, 2.0, 24) == pytest.approx(48)


def test_pass_timeout_grows_with_duration():
    assert qa.pass_timeout(None) == 60
    assert qa.pass_timeout(10) == 60
    assert qa.pass_timeout(300) == 1200


def make_video(path: Path, video_filter: str, duration: float, audio: bool | str = True):
    command = ["ffmpeg", "-threads", "1", "-filter_threads", "1", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", video_filter]
    if audio:
        audio_source = f"anullsrc=r=48000:cl=stereo:d={duration}" if audio == "silent" else f"sine=frequency=440:sample_rate=48000:duration={duration}"
        command += ["-f", "lavfi", "-i", audio_source]
    command += ["-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio:
        command += ["-c:a", "aac", "-shortest"]
    command += ["-movflags", "+faststart", str(path)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def run_cli(path: Path, *options: str, expect_duration: str = "2"):
    command = [sys.executable, str(SCRIPT), str(path), "--expect-size", "320x240",
               "--expect-fps", "24", "--expect-duration", expect_duration, "--json", *options]
    return subprocess.run(command, capture_output=True, text=True, timeout=15)


def result_json(proc):
    return json.loads(proc.stdout)


def test_normal_clip_has_expected_size_fps_and_audio(tmp_path):
    video = tmp_path / "normal.mp4"
    make_video(video, "color=c=green:s=320x240:r=24:d=2", 2)
    proc = run_cli(video, "--expect-audio")
    data = result_json(proc)
    assert proc.returncode == 0
    stream = next(s for s in data["probe"]["streams"] if s["codec_type"] == "video")
    assert (stream["width"], stream["height"]) == (320, 240)
    assert qa.parse_rate(stream["r_frame_rate"]) == 24
    assert any(f["check"] == "freeze" and f["level"] == "WARN" for f in data["findings"])
    assert any(f["check"] == "loudness" and "LUFS" in f["message"] for f in data["findings"])
    assert any(f["check"] == "peak" and "dBFS" in f["message"] for f in data["findings"])
    assert not any(f["level"] == "FAIL" for f in data["findings"])
    assert any(f["check"] == "fps" and f["level"] == "PASS" for f in data["findings"])
    bare = subprocess.run([sys.executable, str(SCRIPT), str(video), "--json"], capture_output=True, text=True, timeout=15)
    assert bare.returncode == 0


def test_black_middle_is_warned_near_one_second(tmp_path):
    video = tmp_path / "black-middle.mp4"
    graph = ("color=c=red:s=320x240:r=24:d=1[a];"
             "color=c=black:s=320x240:r=24:d=1[b];"
             "color=c=blue:s=320x240:r=24:d=1[c];"
             "[a][b][c]concat=n=3:v=1:a=0[out]")
    make_video(video, graph, 3, audio=False)
    proc = run_cli(video, expect_duration="3")
    data = result_json(proc)
    black = [f for f in data["findings"] if f["check"] == "black"]
    assert any(f["level"] == "WARN" and abs((f["t"] or 0) - 1) <= 0.15 for f in black)


def test_color_cut_jump_warns_for_clip_and_is_info_for_edit(tmp_path):
    video = tmp_path / "color-cut.mp4"
    graph = ("color=c=red:s=320x240:r=24:d=1[a];"
             "color=c=blue:s=320x240:r=24:d=1[b];"
             "[a][b]concat=n=2:v=1:a=0[out]")
    make_video(video, graph, 2, audio=False)
    clip = result_json(run_cli(video, "--mode", "clip"))
    edit = result_json(run_cli(video, "--mode", "edit"))
    clip_spikes = [f for f in clip["findings"] if f["check"] == "jump"]
    edit_spikes = [f for f in edit["findings"] if f["check"] == "jump"]
    assert len(clip_spikes) == len(edit_spikes) == 1
    assert clip_spikes[0]["t"] == pytest.approx(1, abs=.05)
    assert edit_spikes[0]["t"] == pytest.approx(1, abs=.05)
    assert clip_spikes[0]["level"] == "WARN" and edit_spikes[0]["level"] == "INFO"
    assert "cut" in edit_spikes[0]["message"] and "frame 24" in edit_spikes[0]["message"]


def test_missing_expected_audio_and_wrong_size_fail(tmp_path):
    video = tmp_path / "silent.mp4"
    make_video(video, "color=c=green:s=320x240:r=24:d=2", 2, audio=False)
    audio_proc = run_cli(video, "--expect-audio")
    assert audio_proc.returncode == 1
    assert any(f["check"] == "audio" and f["level"] == "FAIL" for f in result_json(audio_proc)["findings"])
    wrong_size = subprocess.run([sys.executable, str(SCRIPT), str(video), "--expect-size", "640x360",
                                 "--expect-fps", "24", "--expect-duration", "2", "--json"],
                                capture_output=True, text=True, timeout=15)
    assert wrong_size.returncode == 1
    assert any(f["check"] == "size" and f["level"] == "FAIL" for f in result_json(wrong_size)["findings"])


def test_contact_sheet_is_written(tmp_path):
    video = tmp_path / "sheet-source.mp4"
    sheet = tmp_path / "contact.jpg"
    make_video(video, "color=c=green:s=320x240:r=24:d=2", 2)
    proc = run_cli(video, "--sheet", str(sheet), "--sheet-frames", "4")
    assert proc.returncode == 0
    assert sheet.is_file() and sheet.stat().st_size > 0
    assert sheet.read_bytes().startswith(b"\xff\xd8")
    data = result_json(proc)
    assert any(f["check"] == "sheet" and all(x in f["message"] for x in ("0.00s", "1.50s")) for f in data["findings"])


def test_nearly_all_silent_audio_fails_and_keeps_interval_warning(tmp_path):
    video = tmp_path / "silent-audio.mp4"
    make_video(video, "color=c=green:s=320x240:r=24:d=2", 2, audio="silent")
    data = result_json(run_cli(video, "--expect-audio"))
    assert any(f["check"] == "silence" and f["level"] == "FAIL" for f in data["findings"])
    assert any(f["check"] == "silence" and f["level"] == "WARN" for f in data["findings"])


def test_truncated_faststart_clip_fails(tmp_path):
    video = tmp_path / "complete.mp4"
    truncated = tmp_path / "truncated.mp4"
    make_video(video, "testsrc2=s=320x240:r=24:d=3", 3)
    contents = video.read_bytes()
    truncated.write_bytes(contents[:int(len(contents) * .65)])
    proc = run_cli(truncated, expect_duration="3")
    assert proc.returncode == 1
    assert any(f["level"] == "FAIL" and f["check"] in {"decode", "frames"}
               for f in result_json(proc)["findings"])


def test_frame_shortfall_fails_without_decode_errors(monkeypatch, tmp_path, capsys):
    video = tmp_path / "normal.mp4"
    make_video(video, "color=c=green:s=320x240:r=24:d=2", 2, audio=False)
    monkeypatch.setattr(qa, "_jump_indices", lambda *args: ([], 46))
    assert qa.main([str(video), "--json"]) == 1
    findings = json.loads(capsys.readouterr().out)["findings"]
    assert any(f["check"] == "decode" and f["level"] == "PASS" for f in findings)
    assert any(f["check"] == "frames" and f["level"] == "FAIL" and
               f["message"] == "decoded 46 of ~48 expected frames" for f in findings)


def test_contact_sheet_samples_picture_when_audio_is_longer(tmp_path):
    video = tmp_path / "long-audio.mp4"
    sheet = tmp_path / "long-audio.jpg"
    command = ["ffmpeg", "-threads", "1", "-filter_threads", "1", "-hide_banner",
               "-loglevel", "error", "-y", "-f", "lavfi", "-i",
               "color=c=green:s=320x240:r=24:d=2", "-f", "lavfi", "-i",
               "sine=frequency=440:sample_rate=48000:duration=4",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)]
    made = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert made.returncode == 0, made.stderr
    proc = run_cli(video, "--sheet", str(sheet), "--sheet-frames", "4", expect_duration="4")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = result_json(proc)
    stream = next(s for s in data["probe"]["streams"] if s["codec_type"] == "video")
    assert float(stream["duration"]) == pytest.approx(2)
    assert float(data["probe"]["format"]["duration"]) == pytest.approx(4, abs=.1)
    assert sheet.is_file() and sheet.stat().st_size > 0
    assert sheet.read_bytes().startswith(b"\xff\xd8")
    assert any(f["check"] == "sheet" and "1.50s" in f["message"] for f in data["findings"])


def test_variable_rate_jump_uses_presentation_time(tmp_path):
    video = tmp_path / "variable-rate.mp4"
    graph = ("color=c=red:s=320x240:r=15:d=2[a];"
             "color=c=blue:s=320x240:r=30:d=2[b];"
             "[a][b]concat=n=2:v=1:a=0[out]")
    command = ["ffmpeg", "-threads", "1", "-filter_threads", "1", "-hide_banner",
               "-loglevel", "error", "-y", "-f", "lavfi", "-i", graph,
               "-fps_mode", "passthrough", "-enc_time_base", "1:30", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)]
    made = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert made.returncode == 0, made.stderr
    jumps, count = qa._jump_indices(str(video))
    assert count == 90
    assert len(jumps) == 1
    assert jumps[0][0] == 30
    assert jumps[0][1] == pytest.approx(2, abs=.05)
    proc = subprocess.run([sys.executable, str(SCRIPT), str(video), "--json"],
                          capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    findings = [f for f in result_json(proc)["findings"] if f["check"] == "jump"]
    assert len(findings) == 1
    assert findings[0]["t"] == pytest.approx(2, abs=.05)
    assert "frame 30 (2.000s)" in findings[0]["message"]
