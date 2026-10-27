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

import numpy as np
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
    assert qa.expected_frame_count({"nb_frames": "289"}, 99.0, 24) == (289, "nb_frames")
    # a music bed longer than the picture must not inflate the expectation
    assert qa.expected_frame_count({"duration": "12.0", "avg_frame_rate": "24/1"}, 15.0, 24) == (pytest.approx(288), "duration × rate")
    # variable-rate phone footage: the average rate, not r_frame_rate
    assert qa.expected_frame_count({"duration": "10.0", "avg_frame_rate": "2950/100"}, 10.0, 30) == (pytest.approx(295), "duration × rate")
    # nothing in the stream: container duration × nominal rate
    assert qa.expected_frame_count({}, 2.0, 24) == (pytest.approx(48), "duration × rate")


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


def sheet_pixels(path: Path):
    stream = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
                                       capture_output=True, text=True, timeout=15).stdout)["streams"][0]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, timeout=15).stdout
    return np.frombuffer(raw, np.uint8).reshape(stream["height"], stream["width"], 3).astype(int)


def sheet_message(findings):
    return next(f["message"] for f in findings if f["check"] == "sheet")


def test_contact_sheet_prints_each_timestamp(tmp_path):
    video = tmp_path / "green.mp4"
    sheet = tmp_path / "labelled.jpg"
    make_video(video, "color=c=green:s=320x240:r=24:d=2", 2)
    proc = run_cli(video, "--sheet", str(sheet), "--sheet-frames", "4")
    assert proc.returncode == 0, proc.stdout
    assert "timestamps printed on each tile" in sheet_message(result_json(proc)["findings"])
    pixels = sheet_pixels(sheet)
    # white text only exists in the label box at each tile's top-left; pure green has no channel near 255
    white = pixels.min(axis=2) > 180
    for left in (8, 8 + 328, 8 + 2 * 328, 8 + 3 * 328):
        assert white[8 + 6:8 + 34, left + 6:left + 70].any()
        assert not white[8 + 60:8 + 240, left:left + 320].any()


def test_contact_sheet_without_a_usable_font_is_made_unlabelled(tmp_path, monkeypatch, capsys):
    video = tmp_path / "no-font.mp4"
    sheet = tmp_path / "unlabelled.jpg"
    make_video(video, "color=c=green:s=320x240:r=24:d=2", 2)
    labelled_attempts = []
    original_run = qa._run

    def no_font(command, *args, **kwargs):
        if any("drawtext" in part for part in command):
            labelled_attempts.append(command)
            # what ffmpeg 6.1 prints with an empty fontconfig
            return subprocess.CompletedProcess(command, 254, "", (
                "[Parsed_drawtext_1 @ 0x5f0d405b5ec0] Cannot find a valid font for the family Sans\n"
                "[AVFilterGraph @ 0x5f0d405b6140] Error initializing filters\n"
                "Failed to set value 'scale=320:-2,drawtext=text=0.00s:x=6:y=6' for option 'vf': No such file or directory\n"
                "Error opening output files: No such file or directory\n"))
        return original_run(command, *args, **kwargs)

    monkeypatch.setattr(qa, "_run", no_font)
    assert qa.main([str(video), "--sheet", str(sheet), "--sheet-frames", "4", "--json"]) == 0
    message = sheet_message(json.loads(capsys.readouterr().out)["findings"])
    assert ("timestamps not printed on the tiles (drawtext: [Parsed_drawtext_1 @ 0x5f0d405b5ec0] "
            "Cannot find a valid font for the family Sans);") in message
    assert message.endswith("frames at 0.00s, 0.50s, 1.00s, 1.50s")
    assert len(labelled_attempts) == 1   # one failed try, then the whole sheet without labels
    assert not (sheet_pixels(sheet).min(axis=2) > 180).any()


def test_compare_sheet_puts_the_reference_beside_each_tile(tmp_path):
    video = tmp_path / "ours.mp4"
    reference = tmp_path / "reference.mp4"   # shorter, vertical, another frame rate
    sheet = tmp_path / "compare.jpg"
    make_video(video, "color=c=red:s=320x240:r=24:d=2", 2)
    make_video(reference, "color=c=blue:s=180x320:r=30:d=1", 1, audio=False)
    proc = run_cli(video, "--sheet", str(sheet), "--sheet-frames", "4", "--compare", str(reference))
    assert proc.returncode == 0, proc.stdout
    message = sheet_message(result_json(proc)["findings"])
    assert f"each tile beside {reference} at the same moment" in message
    assert message.endswith("frames at 0.00s, 0.50s, 1.00s, 1.50s")
    pixels = sheet_pixels(sheet)
    # each pair is 320 high: ours 426 wide, the reference 180; two pairs a row, 8 px margin and padding.
    # The frames at 1.00s and 1.50s exist only because the reference is clamped to its last frame.
    assert pixels.shape == (8 + 320 + 8 + 320 + 8, 8 + 606 + 8 + 606 + 8, 3)
    for top in (8, 8 + 328):
        for left in (8, 8 + 614):
            ours, theirs = pixels[top + 200, left + 200], pixels[top + 200, left + 426 + 90]
            assert ours[0] > 180 and ours[2] < 80
            assert theirs[2] > 180 and theirs[0] < 80


def test_compare_sheet_keeps_each_moment_when_the_reference_is_slower(tmp_path):
    video = tmp_path / "cut.mp4"   # 10 fps, red until 1s, then blue
    reference = tmp_path / "slow.mp4"   # 1 fps: after a seek to 0.5s its first frame is 0.5s later
    sheet = tmp_path / "slow-compare.jpg"
    made = subprocess.run(["ffmpeg", "-threads", "1", "-hide_banner", "-loglevel", "error", "-y",
                           "-f", "lavfi", "-i", "color=c=red:s=320x240:r=10:d=1",
                           "-f", "lavfi", "-i", "color=c=blue:s=320x240:r=10:d=1",
                           "-filter_complex", "[0:v][1:v]concat=n=2:v=1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                           str(video)], capture_output=True, text=True, timeout=15)
    assert made.returncode == 0, made.stderr
    make_video(reference, "color=c=gray:s=320x240:r=1:d=2", 2, audio=False)
    proc = subprocess.run([sys.executable, str(SCRIPT), str(video), "--sheet", str(sheet), "--sheet-frames", "4",
                           "--compare", str(reference), "--json"], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout
    assert sheet_message(result_json(proc)["findings"]).endswith("frames at 0.00s, 0.50s, 1.00s, 1.50s")
    pixels = sheet_pixels(sheet)
    # pairs are 852 wide (426 + 426), two a row: 0.00s and 0.50s on top, 1.00s and 1.50s below
    for (top, left), red in (((8, 8), True), ((8, 868), True), ((336, 8), False), ((336, 868), False)):
        ours = pixels[top + 200, left + 200]
        assert (ours[0] > 180 and ours[2] < 80) if red else (ours[2] > 180 and ours[0] < 80), (top, left, ours)


def make_cut(path: Path, rate: int):
    """2 s at `rate` fps: red until 1s, then blue."""
    made = subprocess.run(["ffmpeg", "-threads", "1", "-hide_banner", "-loglevel", "error", "-y",
                           "-f", "lavfi", "-i", f"color=c=red:s=320x240:r={rate}:d=1",
                           "-f", "lavfi", "-i", f"color=c=blue:s=320x240:r={rate}:d=1",
                           "-filter_complex", "[0:v][1:v]concat=n=2:v=1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                           str(path)], capture_output=True, text=True, timeout=15)
    assert made.returncode == 0, made.stderr


def test_on_screen_picks_the_frame_shown_at_a_moment():
    frames = [0.0, 0.5, 1.0, 1.5]
    assert [qa._on_screen(frames, t) for t in (0.0, 0.49, 0.5, 0.667, 1.0, 9.0)] == [0.0, 0.0, 0.5, 0.5, 1.0, 1.5]
    assert qa._on_screen([0.2, 0.4], 0.1) == 0.2   # before the first frame: the first one
    assert qa._on_screen([0.0, 1 / 3, 2 / 3], 1 / 3) == pytest.approx(1 / 3)   # a float sum of the same moment


def test_compare_sheet_shows_the_frames_on_screen_between_frames(tmp_path):
    video, reference, sheet = tmp_path / "draft.mp4", tmp_path / "reference.mp4", tmp_path / "between.jpg"
    make_cut(video, 2)
    make_cut(reference, 1)
    proc = subprocess.run([sys.executable, str(SCRIPT), str(video), "--sheet", str(sheet), "--sheet-frames", "3",
                           "--compare", str(reference), "--json"], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout
    assert sheet_message(result_json(proc)["findings"]).endswith("frames at 0.00s, 0.67s, 1.33s")
    pixels = sheet_pixels(sheet)
    # 0.67s falls between frames of both: each shows the frame on screen (red), not the next one (blue)
    for (top, left), red in (((8, 8), True), ((8, 868), True), ((336, 8), False)):
        for side in (left + 200, left + 426 + 200):
            pixel = pixels[top + 200, side]
            assert (pixel[0] > 180 and pixel[2] < 80) if red else (pixel[2] > 180 and pixel[0] < 80), (top, side, pixel)


def test_compare_needs_a_sheet(tmp_path):
    proc = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path / "any.mp4"), "--compare", str(tmp_path / "ref.mp4")],
                          capture_output=True, text=True, timeout=15)
    assert proc.returncode == 2 and "--compare needs --sheet" in proc.stderr


def test_compare_with_a_missing_reference_fails_naming_it(tmp_path):
    video = tmp_path / "ours.mp4"
    make_video(video, "color=c=red:s=320x240:r=24:d=2", 2)
    proc = run_cli(video, "--sheet", str(tmp_path / "sheet.jpg"), "--compare", str(tmp_path / "missing.mp4"))
    assert proc.returncode == 1
    assert any(f["level"] == "FAIL" and f"reference {tmp_path / 'missing.mp4'}: ffprobe failed" in f["message"]
               for f in result_json(proc)["findings"])


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


def test_count_shortfall_on_a_complete_timeline_only_warns(monkeypatch, tmp_path, capsys):
    video = tmp_path / "normal.mp4"
    make_video(video, "color=c=green:s=320x240:r=24:d=2", 2, audio=False)
    monkeypatch.setattr(qa, "_jump_indices", lambda *args: ([], 46, 1.875, None))
    assert qa.main([str(video), "--json"]) == 0
    findings = json.loads(capsys.readouterr().out)["findings"]
    assert any(f["check"] == "decode" and f["level"] == "PASS" for f in findings)
    assert any(f["check"] == "frames" and f["level"] == "WARN" and "decoded 46 of ~48" in f["message"] for f in findings)


def test_playback_ending_early_fails_without_decode_errors(monkeypatch, tmp_path, capsys):
    video = tmp_path / "normal.mp4"
    make_video(video, "color=c=green:s=320x240:r=24:d=2", 2, audio=False)
    monkeypatch.setattr(qa, "_jump_indices", lambda *args: ([], 24, 0.958, None))
    assert qa.main([str(video), "--json"]) == 1
    findings = json.loads(capsys.readouterr().out)["findings"]
    assert any(f["check"] == "frames" and f["level"] == "FAIL" and "playback ends at 1.000s of 2.000s" in f["message"]
               for f in findings)


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
    jumps, count, last, held = qa._jump_indices(str(video))
    assert count == 90
    assert last == pytest.approx(3.967, abs=.05)
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


@pytest.mark.parametrize("noise", [
    "[null] Application provided invalid, non monotonically increasing dts to muxer: 2 >= 2",
    "[vost] Non-monotonic DTS; previous: 2, current: 2",
    "Non-Monotonically increasing PTS in output stream",
])
def test_decode_error_filter_retains_real_errors(noise):
    error = "[h264] Invalid NAL unit size"
    assert qa.decode_error_lines(noise + "\n" + error) == [error]
    assert qa.decode_error_lines(error) == [error]
    assert qa.decode_error_lines("unrelated muxer error") == ["unrelated muxer error"]


def test_select_video_stream_skips_cover_art():
    cover = {"index": 0, "codec_type": "video", "disposition": {"attached_pic": 1}}
    audio = {"index": 1, "codec_type": "audio"}
    video = {"index": 2, "codec_type": "video", "r_frame_rate": "24/1"}
    default = {"index": 3, "codec_type": "video", "disposition": {"default": 1}}
    probe = {"streams": [cover, audio, video, default]}
    assert qa.select_video_stream(probe) is video
    assert qa.select_video_stream({"streams": [cover, audio]}) is None
    assert any(f.check == "probe" and "index=2" in f.message for f in qa.parse_probe(probe))


@pytest.mark.parametrize("rates", [(30, 15), (15, 30)])
def test_vfr_matroska_does_not_fail_decode_or_estimated_frames(tmp_path, rates):
    video = tmp_path / "vfr.mkv"
    graph = (f"testsrc2=s=320x240:r=30:d=1.5,select=not(mod(n\\,{30 // rates[0]}))[a];"
             f"testsrc2=s=320x240:r=30:d=1.5,select=not(mod(n\\,{30 // rates[1]}))[b];"
             "[a][b]concat=n=2:v=1:a=0[out]")
    made = subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error",
                           "-filter_threads", "1", "-f", "lavfi", "-i", graph,
                           "-t", "3", "-fps_mode", "passthrough", "-c:v", "libx264",
                           "-threads", "1", "-pix_fmt", "yuv420p", str(video)],
                          capture_output=True, text=True, timeout=15)
    assert made.returncode == 0, made.stderr
    proc = subprocess.run([sys.executable, str(SCRIPT), str(video), "--json"],
                          capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = result_json(proc)
    assert not any(f["level"] == "FAIL" and f["check"] in {"decode", "frames"}
                   for f in data["findings"])
    stream = qa.select_video_stream(data["probe"])
    assert "nb_frames" not in stream
    assert any(f["level"] == "WARN" and f["check"] == "frames"
               and "the timeline is complete" in f["message"] for f in data["findings"])


def test_two_video_tracks_analyse_first_even_when_second_is_default(tmp_path, monkeypatch):
    video = tmp_path / "two-tracks.mp4"
    sheet = tmp_path / "two-tracks.jpg"
    made = subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error",
                           "-filter_threads", "1", "-f", "lavfi", "-i",
                           "testsrc2=s=320x240:r=24:d=2", "-f", "lavfi", "-i",
                           "color=c=blue:s=320x240:r=12:d=2", "-f", "lavfi", "-i",
                           "sine=frequency=440:duration=2", "-map", "2:a", "-map", "0:v", "-map", "1:v",
                           "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p", "-c:a", "aac",
                           "-disposition:v:1", "default", "-disposition:v:0", "0", str(video)],
                          capture_output=True, text=True, timeout=15)
    assert made.returncode == 0, made.stderr
    proc = run_cli(video, "--sheet", str(sheet), "--sheet-frames", "2")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = result_json(proc)
    streams = [s for s in data["probe"]["streams"] if s["codec_type"] == "video"]
    assert [int(s["nb_frames"]) for s in streams] == [48, 24]
    assert streams[1]["disposition"]["default"] == 1
    selected = qa.select_video_stream(data["probe"])
    assert selected is streams[0]
    assert selected["index"] == 1  # absolute index, not the ordinal video index
    assert qa._jump_indices(str(video), video_index=selected["index"])[1] == 48
    assert not any(f["check"] == "frames" and f["level"] == "FAIL" for f in data["findings"])
    assert any(f["check"] == "probe" and "index=1" in f["message"] for f in data["findings"])
    assert any(f["check"] == "freeze" and f["level"] == "PASS" for f in data["findings"])
    assert sheet.is_file() and sheet.stat().st_size > 0

    # Record the real commands to cover every pass, including each sheet extraction.
    commands = []
    original_run = qa._run

    def record(command, *args, **kwargs):
        commands.append(command)
        return original_run(command, *args, **kwargs)

    monkeypatch.setattr(qa, "_run", record)
    assert qa.main([str(video), "--sheet", str(sheet), "--sheet-frames", "2", "--json"]) == 0
    source_commands = [c for c in commands if c[0] == "ffmpeg" and str(video) in c]
    assert len(source_commands) == 7  # decode, black, freeze, silence, loudness, two images
    for command in source_commands:
        maps = [command[i + 1] for i, arg in enumerate(command) if arg == "-map"]
        if "-af" in command:
            assert maps == ["0:a:0"]
        elif "-v" in command:
            assert maps == ["0:1", "0:a:0?"]
        else:
            assert maps == ["0:1"]


def test_contact_sheet_on_a_clip_shorter_than_the_sample_count(tmp_path):
    video = tmp_path / "six-frames.mp4"
    make_video(video, "color=c=green:s=320x240:r=24:d=0.25", 0.25, audio=False)
    sheet = tmp_path / "six-frames.jpg"
    proc = subprocess.run([sys.executable, str(SCRIPT), str(video), "--sheet", str(sheet), "--json"],
                          capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert sheet.is_file() and sheet.read_bytes().startswith(b"\xff\xd8")


def test_short_silent_audio_track_fails_and_is_flagged(tmp_path):
    video = tmp_path / "short-silent-audio.mp4"
    command = ["ffmpeg", "-threads", "1", "-filter_threads", "1", "-hide_banner", "-loglevel", "error", "-y",
               "-f", "lavfi", "-i", "color=c=green:s=320x240:r=24:d=3",
               "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:d=1",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)]
    made = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert made.returncode == 0, made.stderr
    proc = run_cli(video, "--expect-audio", expect_duration="3")
    assert proc.returncode == 1
    findings = result_json(proc)["findings"]
    assert any(f["check"] == "silence" and f["level"] == "FAIL" for f in findings)
    assert any(f["check"] == "audio" and f["level"] == "WARN" and "audio ends at" in f["message"] for f in findings)


def test_display_size_applies_rotation_metadata():
    assert qa.display_size({"width": 320, "height": 240}) == (320, 240)
    assert qa.display_size({"width": 320, "height": 240, "side_data_list": [{"rotation": -90}]}) == (240, 320)
    assert qa.display_size({"width": 320, "height": 240, "side_data_list": [{"rotation": 180}]}) == (320, 240)
    assert qa.display_size({"width": 320, "height": 240, "tags": {"rotate": "270"}}) == (240, 320)


def test_rotated_portrait_video_passes_expected_display_size(tmp_path):
    plain = tmp_path / "landscape.mp4"
    rotated = tmp_path / "portrait.mp4"
    make_video(plain, "color=c=green:s=320x240:r=24:d=2", 2, audio=False)
    made = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-display_rotation", "90",
                           "-i", str(plain), "-c", "copy", str(rotated)],
                          capture_output=True, text=True, timeout=15)
    assert made.returncode == 0, made.stderr
    proc = subprocess.run([sys.executable, str(SCRIPT), str(rotated), "--expect-size", "240x320", "--json"],
                          capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_contact_sheet_on_a_five_frame_clip(tmp_path):
    video = tmp_path / "five-frames.mp4"
    make_video(video, "color=c=green:s=320x240:r=24:d=0.2083", 0.2083, audio=False)
    sheet = tmp_path / "five-frames.jpg"
    proc = subprocess.run([sys.executable, str(SCRIPT), str(video), "--sheet", str(sheet), "--json"],
                          capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert sheet.is_file()


def test_stream_copied_trim_with_edit_list_preroll_passes(tmp_path):
    source = tmp_path / "source.mp4"
    trimmed = tmp_path / "trimmed.mp4"
    made = subprocess.run(["ffmpeg", "-threads", "1", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                           "-i", "testsrc=s=320x240:r=24:d=4", "-c:v", "libx264", "-g", "48", "-pix_fmt", "yuv420p",
                           str(source)], capture_output=True, text=True, timeout=15)
    assert made.returncode == 0, made.stderr
    made = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", "1", "-i", str(source),
                           "-t", "2", "-c", "copy", str(trimmed)], capture_output=True, text=True, timeout=15)
    assert made.returncode == 0, made.stderr
    proc = subprocess.run([sys.executable, str(SCRIPT), str(trimmed), "--json"], capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0, proc.stdout
    assert not any(f["check"] == "frames" and f["level"] == "FAIL" for f in result_json(proc)["findings"])


def test_half_second_silent_track_fails(tmp_path):
    video = tmp_path / "tiny-silent-audio.mp4"
    made = subprocess.run(["ffmpeg", "-threads", "1", "-hide_banner", "-loglevel", "error", "-y",
                           "-f", "lavfi", "-i", "color=c=green:s=320x240:r=24:d=3",
                           "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:d=0.5",
                           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)],
                          capture_output=True, text=True, timeout=15)
    assert made.returncode == 0, made.stderr
    proc = run_cli(video, "--expect-audio", expect_duration="3")
    assert proc.returncode == 1
    assert any(f["check"] == "silence" and f["level"] == "FAIL" for f in result_json(proc)["findings"])


def test_stream_duration_reads_matroska_tags_and_ebur128_reads_inf_peak():
    assert qa.stream_duration({"duration": "2.5"}) == 2.5
    assert qa.stream_duration({"tags": {"DURATION": "00:00:02.021000000"}}) == pytest.approx(2.021)
    assert qa.stream_duration({"tags": {"DURATION-eng": "00:01:03.5"}}) == pytest.approx(63.5)
    assert qa.stream_duration({}) is None
    integrated, peak = qa.parse_ebur128("Summary:\n  I: -70.0 LUFS\n  True peak:\n    Peak: -inf dBFS\n")
    assert integrated == -70.0 and peak == float("-inf")


def test_complete_matroska_video_with_longer_soundtrack_passes(tmp_path):
    video = tmp_path / "long-audio.mkv"
    made = subprocess.run(["ffmpeg", "-threads", "1", "-hide_banner", "-loglevel", "error", "-y",
                           "-f", "lavfi", "-i", "testsrc=s=320x240:r=24:d=2",
                           "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4",
                           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)],
                          capture_output=True, text=True, timeout=15)
    assert made.returncode == 0, made.stderr
    proc = subprocess.run([sys.executable, str(SCRIPT), str(video), "--json"], capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0, proc.stdout
    assert not any(f["check"] == "frames" and f["level"] == "FAIL" for f in result_json(proc)["findings"])


def test_audible_tone_shorter_than_the_loudness_window_is_not_silent(tmp_path):
    video = tmp_path / "short-tone.mp4"
    made = subprocess.run(["ffmpeg", "-threads", "1", "-hide_banner", "-loglevel", "error", "-y",
                           "-f", "lavfi", "-i", "color=c=green:s=320x240:r=24:d=1",
                           "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=0.25",
                           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)],
                          capture_output=True, text=True, timeout=15)
    assert made.returncode == 0, made.stderr
    proc = subprocess.run([sys.executable, str(SCRIPT), str(video), "--expect-audio", "--json"],
                          capture_output=True, text=True, timeout=15)
    findings = result_json(proc)["findings"]
    assert not any(f["check"] == "silence" and f["level"] == "FAIL" for f in findings), findings
    assert any(f["check"] == "loudness" and "too short" in f["message"] for f in findings)


def test_playback_end_uses_the_last_frames_real_duration():
    assert qa.playback_end(1.958, 2.0, 24) == pytest.approx(3.958)      # end card held 2 s
    assert qa.playback_end(1.958, None, 24) == pytest.approx(2.0, abs=.01)  # no duration reported
    assert qa.playback_end(None, None, 24) == 0.0


def test_jump_pass_reports_the_last_frames_duration(tmp_path):
    video = tmp_path / "normal.mp4"
    make_video(video, "color=c=green:s=320x240:r=24:d=1", 1, audio=False)
    _, count, last, held = qa._jump_indices(str(video))
    assert count == 24
    assert last == pytest.approx(23 / 24, abs=.01)
    assert held == pytest.approx(1 / 24, abs=.01)


def test_delayed_audio_ending_with_the_picture_is_not_flagged(tmp_path):
    video = tmp_path / "delayed-audio.mp4"
    made = subprocess.run(["ffmpeg", "-threads", "1", "-hide_banner", "-loglevel", "error", "-y",
                           "-f", "lavfi", "-i", "testsrc=s=320x240:r=24:d=4",
                           "-itsoffset", "2", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
                           "-map", "0:v", "-map", "1:a",
                           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)],
                          capture_output=True, text=True, timeout=15)
    assert made.returncode == 0, made.stderr
    audio = next(s for s in json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(video)],
                 capture_output=True, text=True).stdout)["streams"] if s["codec_type"] == "audio")
    assert float(audio["start_time"]) == pytest.approx(2, abs=.1)   # the fixture really is delayed
    proc = subprocess.run([sys.executable, str(SCRIPT), str(video), "--json"], capture_output=True, text=True, timeout=15)
    assert not any(f["check"] == "audio" and "audio ends at" in f["message"] for f in result_json(proc)["findings"])


def test_matroska_with_a_timestamp_offset_passes(tmp_path):
    video = tmp_path / "offset.mkv"
    made = subprocess.run(["ffmpeg", "-threads", "1", "-hide_banner", "-loglevel", "error", "-y",
                           "-f", "lavfi", "-i", "testsrc=s=320x240:r=24:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                           "-output_ts_offset", "2", str(video)], capture_output=True, text=True, timeout=15)
    assert made.returncode == 0, made.stderr
    stream = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(video)],
                                       capture_output=True, text=True).stdout)["streams"][0]
    assert float(stream["start_time"]) == pytest.approx(2, abs=.05)   # the fixture really is offset
    assert qa.stream_duration(stream) == pytest.approx(2, abs=.05)
    proc = subprocess.run([sys.executable, str(SCRIPT), str(video), "--json"], capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0, proc.stdout


def test_contact_sheet_starts_where_a_delayed_picture_starts(tmp_path):
    video = tmp_path / "delayed-video.mkv"   # MP4/MOV muxers normalise a delayed video start to 0
    made = subprocess.run(["ffmpeg", "-threads", "1", "-hide_banner", "-loglevel", "error", "-y",
                           "-itsoffset", "2", "-f", "lavfi", "-i", "testsrc=s=320x240:r=24:d=2",
                           "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4",
                           "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                           str(video)], capture_output=True, text=True, timeout=15)
    assert made.returncode == 0, made.stderr
    streams = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(video)],
                                        capture_output=True, text=True).stdout)["streams"]
    assert float(next(s for s in streams if s["codec_type"] == "video")["start_time"]) == pytest.approx(2, abs=.1)
    sheet = tmp_path / "delayed.jpg"
    proc = subprocess.run([sys.executable, str(SCRIPT), str(video), "--sheet", str(sheet), "--sheet-frames", "4", "--json"],
                          capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0, proc.stdout
    message = next(f["message"] for f in result_json(proc)["findings"] if f["check"] == "sheet")
    times = [float(x.rstrip("s")) for x in message.split("frames at ")[1].split(", ")]
    assert len(set(times)) == 4 and all(2.0 <= x < 4.0 for x in times), message
