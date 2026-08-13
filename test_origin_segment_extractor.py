from pathlib import Path
from types import SimpleNamespace

import pytest

import origin_segment_extractor as extractor


def test_extracts_all_segments_after_range_probe(monkeypatch, tmp_path):
    events = []
    segments = [
        {"start": 1.25, "end": 2.5},
        {"start": 7.0, "end": 9.75},
    ]

    monkeypatch.setattr(extractor, "parse_llc", lambda path: segments)
    monkeypatch.setattr(extractor.shutil, "which", lambda name: "C:/bin/ffmpeg.exe")
    monkeypatch.setattr(
        extractor,
        "get_origin_url",
        lambda url: "https://cdn.example/origin.mp4?sign=secret",
    )

    def fake_probe(url, byte_range, max_bytes):
        events.append(("probe", url, byte_range, max_bytes))
        return b"x" * max_bytes

    def fake_run(command, capture_output, text):
        events.append(("ffmpeg", command))
        Path(command[-1]).touch()
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(extractor, "download_range", fake_probe)
    monkeypatch.setattr(extractor.subprocess, "run", fake_run)

    outputs = extractor.extract_origin_segments(
        "share-token", "cuts.llc", tmp_path
    )

    assert events[0] == (
        "probe",
        "https://cdn.example/origin.mp4?sign=secret",
        "0-65535",
        65536,
    )
    assert [path.name for path in outputs] == ["segment_001.mp4", "segment_002.mp4"]
    ffmpeg_calls = [event[1] for event in events[1:]]
    assert ffmpeg_calls[0][8:12] == [
        "-i",
        "https://cdn.example/origin.mp4?sign=secret",
        "-c",
        "copy",
    ]
    assert ffmpeg_calls[0][6:8] == ["-to", "2.5"]
    assert ffmpeg_calls[1][4:8] == ["-ss", "7", "-to", "9.75"]


def test_does_not_start_ffmpeg_when_range_probe_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(
        extractor, "parse_llc", lambda path: [{"start": 1.0, "end": 2.0}]
    )
    monkeypatch.setattr(extractor.shutil, "which", lambda name: name)
    monkeypatch.setattr(extractor, "get_origin_url", lambda url: "https://cdn/origin")
    monkeypatch.setattr(
        extractor,
        "download_range",
        lambda *args: (_ for _ in ()).throw(ValueError("Server returned 200 OK")),
    )
    monkeypatch.setattr(
        extractor.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("FFmpeg must not run before a safe probe"),
    )

    with pytest.raises(ValueError, match="200 OK"):
        extractor.extract_origin_segments("token", "cuts.llc", tmp_path)

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "segments, message",
    [
        ([], "no cut segments"),
        ([{"start": -1.0, "end": 2.0}], "invalid time range"),
        ([{"start": float("nan"), "end": 2.0}], "non-finite"),
    ],
)
def test_rejects_invalid_segments_before_network(monkeypatch, tmp_path, segments, message):
    monkeypatch.setattr(extractor, "parse_llc", lambda path: segments)
    monkeypatch.setattr(
        extractor,
        "get_origin_url",
        lambda url: pytest.fail("Network discovery must not run for invalid segments"),
    )

    with pytest.raises(ValueError, match=message):
        extractor.extract_origin_segments("token", "cuts.llc", tmp_path)


def test_removes_partial_output_when_ffmpeg_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(
        extractor, "parse_llc", lambda path: [{"start": 1.0, "end": 2.0}]
    )
    monkeypatch.setattr(extractor.shutil, "which", lambda name: name)
    monkeypatch.setattr(extractor, "get_origin_url", lambda url: "https://cdn/origin")
    monkeypatch.setattr(extractor, "download_range", lambda *args: b"x")

    def fake_run(command, **kwargs):
        Path(command[-1]).write_bytes(b"partial")
        return SimpleNamespace(returncode=1, stderr="copy failed")

    monkeypatch.setattr(extractor.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="copy failed"):
        extractor.extract_origin_segments("token", "cuts.llc", tmp_path)

    assert not (tmp_path / "segment_001.mp4").exists()


def test_refuses_to_overwrite_before_network(monkeypatch, tmp_path):
    existing = tmp_path / "segment_001.mp4"
    existing.write_bytes(b"keep me")
    monkeypatch.setattr(
        extractor, "parse_llc", lambda path: [{"start": 1.0, "end": 2.0}]
    )
    monkeypatch.setattr(extractor.shutil, "which", lambda name: name)
    monkeypatch.setattr(
        extractor,
        "get_origin_url",
        lambda url: pytest.fail("Network discovery must not run for output conflicts"),
    )

    with pytest.raises(FileExistsError, match="segment_001.mp4"):
        extractor.extract_origin_segments("token", "cuts.llc", tmp_path)

    assert existing.read_bytes() == b"keep me"
