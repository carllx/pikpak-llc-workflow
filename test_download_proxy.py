import subprocess
from types import SimpleNamespace

import download_proxy


def encoder_from(command):
    return command[command.index("-c:v") + 1]


def test_encoder_probe_tries_candidates_until_one_really_encodes(monkeypatch):
    attempted = []

    def fake_run(command, **kwargs):
        encoder = encoder_from(command)
        attempted.append(encoder)
        return SimpleNamespace(returncode=0 if encoder == "h264_qsv" else 1)

    monkeypatch.setattr(download_proxy.subprocess, "run", fake_run)

    assert download_proxy.check_hw_encoder() == "h264_qsv"
    assert attempted == ["h264_nvenc", "h264_qsv"]


def test_encoder_probe_falls_back_to_cpu_after_all_hardware_fails(monkeypatch):
    attempted = []

    def fake_run(command, **kwargs):
        attempted.append(encoder_from(command))
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(download_proxy.subprocess, "run", fake_run)

    assert download_proxy.check_hw_encoder() == "libx264"
    assert attempted == ["h264_nvenc", "h264_qsv", "h264_amf"]


def test_encoder_probe_tries_amf_after_nvenc_and_qsv_profiles_fail(monkeypatch):
    attempted = []

    def fake_run(command, **kwargs):
        encoder = encoder_from(command)
        attempted.append(encoder)
        return SimpleNamespace(returncode=0 if encoder == "h264_amf" else 1)

    monkeypatch.setattr(download_proxy.subprocess, "run", fake_run)

    assert download_proxy.check_hw_encoder() == "h264_amf"
    assert attempted == ["h264_nvenc", "h264_qsv", "h264_amf"]


def test_encoder_probe_uses_tiny_real_encode_not_encoder_listing(monkeypatch):
    captured = []

    def fake_run(command, **kwargs):
        captured.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(download_proxy.subprocess, "run", fake_run)

    assert download_proxy.check_hw_encoder() == "h264_nvenc"
    command, kwargs = captured[0]
    assert "-encoders" not in command
    assert command[command.index("-frames:v") + 1] == "1"
    assert command[-3:] == ["-f", "null", "-"]
    assert kwargs["timeout"] == 15


def test_probe_and_production_command_share_each_encoder_profile(monkeypatch):
    original_builder = download_proxy.build_encoder_args
    calls = []

    def recording_builder(encoder):
        calls.append(encoder)
        return original_builder(encoder)

    monkeypatch.setattr(download_proxy, "build_encoder_args", recording_builder)
    monkeypatch.setattr(
        download_proxy.subprocess,
        "run",
        lambda command, **kwargs: SimpleNamespace(returncode=0),
    )

    for encoder in ("h264_nvenc", "h264_qsv", "h264_amf", "libx264"):
        calls.clear()
        assert download_proxy._can_encode_with(encoder)
        production = download_proxy.build_transcode_command(
            "input.ts", "output.mp4", encoder
        )
        assert calls == [encoder, encoder]
        profile = original_builder(encoder)
        start = production.index("-c:v")
        assert production[start:start + len(profile)] == profile


def test_encoder_profiles_use_compatible_encoder_specific_options():
    assert download_proxy.build_encoder_args("h264_nvenc") == [
        "-c:v", "h264_nvenc", "-preset", "p4",
        "-rc", "vbr", "-cq", "23", "-b:v", "0",
    ]
    assert download_proxy.build_encoder_args("h264_qsv") == [
        "-c:v", "h264_qsv", "-preset", "fast", "-global_quality", "23",
    ]
    assert download_proxy.build_encoder_args("h264_amf") == [
        "-c:v", "h264_amf", "-quality", "balanced",
        "-rc", "cqp", "-qp_i", "23", "-qp_p", "23",
    ]
    assert download_proxy.build_encoder_args("libx264") == [
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
    ]


def test_encoder_probe_treats_timeout_as_unavailable(monkeypatch):
    monkeypatch.setattr(
        download_proxy.subprocess,
        "run",
        lambda command, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(command, kwargs["timeout"])
        ),
    )

    assert download_proxy.check_hw_encoder() == "libx264"


def test_encoder_probe_treats_process_error_as_unavailable(monkeypatch):
    attempted = []

    def fake_run(command, **kwargs):
        encoder = encoder_from(command)
        attempted.append(encoder)
        if encoder == "h264_nvenc":
            raise OSError("encoder device unavailable")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(download_proxy.subprocess, "run", fake_run)

    assert download_proxy.check_hw_encoder() == "h264_qsv"
    assert attempted == ["h264_nvenc", "h264_qsv"]
