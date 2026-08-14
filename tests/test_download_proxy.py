import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from pikpak_llc import download_proxy


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


class FakeShareClient:
    def __init__(self, files, proxies):
        self.files = files
        self.proxies = proxies
        self.requested = []

    def proxy_for_file(self, file_id):
        self.requested.append(file_id)
        value = self.proxies[file_id]
        if isinstance(value, Exception):
            raise value
        return value


def install_proxy_batch(monkeypatch, client):
    processed = []
    monkeypatch.setattr(
        download_proxy.ShareMediaClient, "open", lambda share_url: client
    )
    monkeypatch.setattr(download_proxy.shutil, "which", lambda command: command)
    monkeypatch.setattr(download_proxy, "check_hw_encoder", lambda: "libx264")
    monkeypatch.setattr(
        download_proxy,
        "_download_and_transcode",
        lambda url, raw, compatible, encoder: processed.append(
            (url, raw.name, compatible.name, encoder)
        ),
    )
    return processed


def video(file_id, filename):
    return {"file_id": file_id, "filename": filename, "candidate_type": "video"}


def test_single_file_share_processes_its_only_video(monkeypatch, tmp_path):
    client = FakeShareClient([video("one", "one.mp4")], {"one": "proxy-one"})
    processed = install_proxy_batch(monkeypatch, client)

    report = download_proxy.download_proxy("private-share", tmp_path)

    assert [item["status"] for item in report] == ["PASS"]
    assert client.requested == ["one"]
    assert processed == [("proxy-one", "one.mp4", "one_h264.mp4", "libx264")]


def test_normal_proxy_invocation_uses_one_workspace_job(monkeypatch, tmp_path):
    client = FakeShareClient([video("one", "one.mp4")], {"one": "proxy-one"})
    processed = install_proxy_batch(monkeypatch, client)

    result = download_proxy.prepare_share_proxies(
        "private-share", workspace_root=tmp_path / "workspace"
    )

    proxy_dir = Path(result["PROXY_DIR"])
    segment_dir = Path(result["SEGMENTS_DIR"])
    assert proxy_dir.name == "proxies"
    assert segment_dir.name == "segments"
    assert proxy_dir.parent == segment_dir.parent
    assert result["files"][0]["status"] == "PASS"
    assert processed[0][1:] == ("one.mp4", "one_h264.mp4", "libx264")


def test_folder_share_processes_all_video_candidates(monkeypatch, tmp_path):
    client = FakeShareClient(
        [video("a", "a.mp4"), video("b", "b.mkv")],
        {"a": "proxy-a", "b": "proxy-b"},
    )
    processed = install_proxy_batch(monkeypatch, client)

    report = download_proxy.download_proxy("private-share", tmp_path)

    assert [item["status"] for item in report] == ["PASS", "PASS"]
    assert client.requested == ["a", "b"]
    assert [item[0] for item in processed] == ["proxy-a", "proxy-b"]


def test_folder_ignores_non_video_candidates(monkeypatch, tmp_path):
    client = FakeShareClient(
        [
            video("video", "movie.mp4"),
            {"file_id": "text", "filename": "notes.txt", "candidate_type": "non_video"},
        ],
        {"video": "proxy-video"},
    )
    install_proxy_batch(monkeypatch, client)

    report = download_proxy.download_proxy("private-share", tmp_path)

    assert [item["file_id"] for item in report] == ["video"]
    assert client.requested == ["video"]


def test_folder_with_zero_videos_fails_explicitly(monkeypatch):
    client = FakeShareClient(
        [{"file_id": "text", "filename": "notes.txt", "candidate_type": "non_video"}],
        {},
    )
    install_proxy_batch(monkeypatch, client)

    with pytest.raises(ValueError, match="zero video candidates"):
        download_proxy.download_proxy("private-share")


def test_legacy_proxy_function_requires_an_explicit_output_path(monkeypatch):
    client = FakeShareClient([video("one", "one.mp4")], {"one": "proxy-one"})
    install_proxy_batch(monkeypatch, client)

    with pytest.raises(ValueError, match="explicit output path"):
        download_proxy.download_proxy("private-share")


def test_legacy_proxy_function_rejects_repo_root_output(monkeypatch, tmp_path):
    client = FakeShareClient([video("one", "one.mp4")], {"one": "proxy-one"})
    install_proxy_batch(monkeypatch, client)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="repository root"):
        download_proxy.download_proxy("private-share", "one.mp4")


def test_missing_480p_fails_only_that_file_explicitly(monkeypatch, tmp_path):
    client = FakeShareClient(
        [video("ok", "ok.mp4"), video("missing", "missing.mp4")],
        {
            "ok": "proxy-ok",
            "missing": download_proxy.ProxyVariantNotFound("480P proxy not found"),
        },
    )
    install_proxy_batch(monkeypatch, client)

    report = download_proxy.download_proxy("private-share", tmp_path)

    assert report[0]["status"] == "PASS"
    assert report[1]["status"] == "FAIL"
    assert report[1]["file_id"] == "missing"
    assert report[1]["error_type"] == "ProxyVariantNotFound"
