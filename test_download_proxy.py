import subprocess
from types import SimpleNamespace

import download_proxy


def test_encoder_probe_tries_candidates_until_one_really_encodes(monkeypatch):
    attempted = []

    def fake_run(command, **kwargs):
        encoder = command[command.index("-c:v") + 1]
        attempted.append(encoder)
        return SimpleNamespace(returncode=0 if encoder == "h264_qsv" else 1)

    monkeypatch.setattr(download_proxy.subprocess, "run", fake_run)

    assert download_proxy.check_hw_encoder() == "h264_qsv"
    assert attempted == ["h264_nvenc", "h264_qsv"]


def test_encoder_probe_falls_back_to_cpu_after_all_hardware_fails(monkeypatch):
    attempted = []

    def fake_run(command, **kwargs):
        attempted.append(command[command.index("-c:v") + 1])
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(download_proxy.subprocess, "run", fake_run)

    assert download_proxy.check_hw_encoder() == "libx264"
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


def test_encoder_probe_treats_timeout_as_unavailable(monkeypatch):
    monkeypatch.setattr(
        download_proxy.subprocess,
        "run",
        lambda command, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(command, kwargs["timeout"])
        ),
    )

    assert download_proxy.check_hw_encoder() == "libx264"
