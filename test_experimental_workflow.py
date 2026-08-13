import json
from pathlib import Path

import pytest

import experimental_workflow as workflow
from range_guard import RangeEvent, TransferLedger


def record_transfer(ledger, request_range, body_size, total_size=1000, status=206):
    if body_size:
        ledger.reserve(body_size)
        ledger.consume(body_size)
    ledger.record(
        RangeEvent(
            range=request_range,
            status=status,
            content_range=f"bytes 0-{max(body_size - 1, 0)}/{total_size}",
            bytes_transferred=body_size,
            outcome="PASS" if status == 206 else "HTTP_200_ABORT",
        )
    )


def test_build_segment_command_uses_local_guard_and_stream_copy_only(tmp_path):
    command = workflow.build_segment_command(
        "ffmpeg",
        "http://127.0.0.1:4321/media",
        {"start": 12.5, "end": 18.75},
        tmp_path / "part.mp4",
    )

    assert command[command.index("-i") + 1] == "http://127.0.0.1:4321/media"
    assert command[command.index("-map") + 1] == "0"
    assert command[command.index("-c") + 1] == "copy"
    assert not any(
        encoder in command
        for encoder in ("libx264", "h264_nvenc", "h264_qsv", "h264_amf")
    )


def test_identity_sample_ranges_cover_distributed_positions():
    ranges = workflow.identity_sample_ranges(100, chunk_bytes=10)

    assert ranges == [(0, 9), (22, 31), (45, 54), (68, 77), (90, 99)]


def test_distributed_identity_hashes_same_five_exact_ranges(tmp_path, monkeypatch):
    content = bytes(range(100))
    official = tmp_path / "official.mp4"
    official.write_bytes(content)
    requested = []

    def fake_fetch(origin_url, request_range, ledger):
        requested.append(request_range)
        start, end = map(int, request_range.removeprefix("bytes=").split("-"))
        body = content[start : end + 1]
        record_transfer(ledger, request_range, len(body), len(content))
        return body, len(content)

    monkeypatch.setattr(workflow, "IDENTITY_CHUNK_BYTES", 10)
    monkeypatch.setattr(workflow, "fetch_exact_range", fake_fetch)
    ledger = TransferLedger(1000)

    samples = workflow.distributed_identity(
        "https://origin.invalid/private", official, len(content), ledger
    )

    assert [sample["range"] for sample in samples] == requested
    assert len(samples) == 5
    assert all(sample["sha256_identical"] for sample in samples)


def test_packet_mapping_requires_stream_and_monotonic_sequence():
    source = [
        {"data_hash": "A", "stream_index": 0, "codec_type": "video"},
        {"data_hash": "B", "stream_index": 1, "codec_type": "audio"},
        {"data_hash": "A", "stream_index": 0, "codec_type": "video"},
    ]
    output = [
        {"data_hash": "A", "stream_index": 0, "codec_type": "video"},
        {"data_hash": "B", "stream_index": 0, "codec_type": "video"},
        {"data_hash": "A", "stream_index": 0, "codec_type": "video"},
    ]

    for index, packet in enumerate(source):
        packet["pts_time"] = str(index)
    output[0]["pts_time"] = "10"
    output[1]["pts_time"] = "11"
    output[2]["pts_time"] = "12"
    mappings, unmatched, first_video, timestamp_mapped = workflow.map_packet_sequence(
        source, output
    )

    assert mappings == [(0, 0), (2, 2)]
    assert [packet["output_index"] for packet in unmatched] == [1]
    assert unmatched[0]["hash_in_source_window"] is True
    assert first_video == (0, 0)
    assert timestamp_mapped is False


def test_packet_mapping_accepts_stable_per_stream_timestamp_offsets():
    source = [
        {"data_hash": "A", "stream_index": 0, "codec_type": "video", "pts_time": "5.0"},
        {"data_hash": "B", "stream_index": 0, "codec_type": "video", "pts_time": "5.04"},
        {"data_hash": "C", "stream_index": 1, "codec_type": "audio", "pts_time": "5.02"},
    ]
    output = [
        {"data_hash": "A", "stream_index": 0, "codec_type": "video", "pts_time": "0.0"},
        {"data_hash": "B", "stream_index": 0, "codec_type": "video", "pts_time": "0.04"},
        {"data_hash": "C", "stream_index": 1, "codec_type": "audio", "pts_time": "0.0"},
    ]

    mappings, unmatched, _, timestamp_mapped = workflow.map_packet_sequence(source, output)

    assert mappings == [(0, 0), (1, 1), (2, 2)]
    assert unmatched == []
    assert timestamp_mapped is True


def test_packet_mapping_tracks_sequence_independently_per_stream():
    source = [
        {"data_hash": "V1", "stream_index": 0, "codec_type": "video", "pts_time": "1"},
        {"data_hash": "A1", "stream_index": 1, "codec_type": "audio", "pts_time": "1"},
        {"data_hash": "V2", "stream_index": 0, "codec_type": "video", "pts_time": "2"},
    ]
    output = [source[1].copy(), source[0].copy(), source[2].copy()]

    mappings, unmatched, _, timestamp_mapped = workflow.map_packet_sequence(source, output)

    assert mappings == [(0, 1), (1, 0), (2, 2)]
    assert unmatched == []
    assert timestamp_mapped is True


def test_safe_range_summary_detects_http_200_fallback():
    ledger = TransferLedger(100)
    record_transfer(ledger, "bytes=0-9", 0, status=200)

    summary = workflow.safe_range_summary(ledger)

    assert summary["RANGE_ONLY"] == "PASS"
    assert summary["UPSTREAM_HTTP_206"] == "FAIL"
    assert summary["HTTP_200_FULL_BODY"] == "DETECTED"


def test_verification_requires_confirmed_keyframe():
    report = {
        "OUTPUT_PLAYABLE": True,
        "PACKET_SEQUENCE_STRICT": True,
        "PACKET_TIMESTAMP_MAPPED": True,
        "KEYFRAME_ALIGNED": None,
        "STREAM_INVENTORY_PRESERVED": True,
    }

    assert workflow.verification_evidence_passes(report) is False
    report["KEYFRAME_ALIGNED"] = True
    assert workflow.verification_evidence_passes(report) is True
    report["STREAM_INVENTORY_PRESERVED"] = False
    assert workflow.verification_evidence_passes(report) is False


class FakeGuard:
    ledgers = []

    def __init__(self, origin_url, ledger):
        self.url = "http://127.0.0.1:4000/media"
        self.ledger = ledger
        self.ledgers.append(ledger)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def raise_if_failed(self):
        return None


def playable_probe(size="12"):
    return {
        "format": {
            "duration": "3.0",
            "size": size,
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
        },
        "streams": [
            {"index": 0, "codec_type": "video", "codec_name": "h264"},
            {"index": 1, "codec_type": "audio", "codec_name": "aac"},
            {"index": 2, "codec_type": "subtitle", "codec_name": "mov_text"},
        ],
    }


def test_non_mp4_origin_is_explicitly_unsupported():
    probe = playable_probe()
    probe["format"]["format_name"] = "matroska,webm"

    with pytest.raises(workflow.WorkflowError, match="Only MP4 Origin"):
        workflow.require_mp4_origin(probe)


def test_extract_with_guard_processes_every_segment(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(workflow, "RangeGuard", FakeGuard)
    monkeypatch.setattr(workflow.shutil, "which", lambda name: name)
    monkeypatch.setattr(workflow, "probe_media", lambda path: playable_probe())

    def fake_run(command, expect_json=False):
        commands.append(command)
        Path(command[-1]).write_bytes(b"segment")

    monkeypatch.setattr(workflow, "run_command", fake_run)
    segments = [{"start": 1.0, "end": 2.0}, {"start": 3.0, "end": 4.0}]

    outputs, probes, source_inventory = workflow.extract_with_guard(
        "https://origin.invalid/private",
        segments,
        tmp_path / "out",
        TransferLedger(1000),
    )

    assert len(outputs) == len(probes) == len(commands) == 2
    assert [stream["codec_type"] for stream in source_inventory] == [
        "video", "audio", "subtitle"
    ]
    assert all(command[command.index("-c") + 1] == "copy" for command in commands)


def test_verify_mode_emits_one_safe_acceptance_report(monkeypatch, tmp_path):
    share = "PRIVATE_SHARE_TOKEN"
    origin = "https://origin.invalid/file?token=SIGNED_SECRET"
    segment = {"start": 399.0, "end": 409.0}
    monkeypatch.setattr(
        workflow, "resolve_llc_origin", lambda share_value, path: ([segment], origin)
    )
    monkeypatch.setattr(workflow, "RangeGuard", FakeGuard)
    monkeypatch.setattr(workflow.shutil, "which", lambda name: name)
    monkeypatch.setattr(workflow, "probe_media", lambda path: playable_probe("64"))
    monkeypatch.setattr(
        workflow,
        "packet_acceptance",
        lambda guard, selected, output: {
            "SOURCE_PACKET_COUNT": 1352,
            "SEGMENT_PACKET_COUNT": 1352,
            "PACKET_MATCH": "1352/1352",
            "PACKET_SEQUENCE_STRICT": True,
            "PACKET_TIMESTAMP_MAPPED": True,
            "PACKET_MAPPINGS": [
                {
                    "output_index": 0,
                    "source_index": 0,
                    "stream_index": 0,
                    "codec_type": "video",
                    "output_pts": "0",
                    "source_pts": "395.098",
                    "data_hash": "SHA256:safehash",
                }
            ],
            "UNMATCHED_PACKETS": [],
            "FIRST_SOURCE_PACKET": {
                "stream_index": 0,
                "codec_type": "video",
                "pts_time": "395.098",
                "dts_time": "395.098",
                "duration_time": "0.04",
                "size": "100",
                "flags": "K__",
                "data_hash": "SHA256:safehash",
            },
            "KEYFRAME_ALIGNED": True,
            "PREROLL_SECONDS": 3.902,
        },
    )

    def fake_fetch(origin_url, request_range, ledger):
        record_transfer(ledger, request_range, 64, total_size=10000)
        return b"x" * 64, 10000

    def fake_run(command, expect_json=False):
        Path(command[-1]).write_bytes(b"segment")
        record_transfer(FakeGuard.ledgers[-1], "bytes=100-199", 100, total_size=10000)

    FakeGuard.ledgers.clear()
    monkeypatch.setattr(workflow, "fetch_exact_range", fake_fetch)
    monkeypatch.setattr(workflow, "run_command", fake_run)

    report = workflow.verify_mode(
        share,
        tmp_path / "project.llc",
        tmp_path / "verify",
        max_origin_bytes=1000,
    )

    serialized = json.dumps(report)
    assert report["STATUS"] == "PASS"
    assert report["RANGE_ONLY"] == "PASS"
    assert report["UPSTREAM_HTTP_206"] == "PASS"
    assert report["HTTP_200_FULL_BODY"] == "NONE"
    assert report["UPSTREAM_TRANSFERRED"] == 164
    assert report["TRANSFER_RATIO"] == pytest.approx(0.0164)
    assert "TRANSFER_SAVING" not in report
    assert report["STREAM_COPY"] == "PASS"
    assert report["STREAM_INVENTORY_PRESERVED"] is True
    assert report["OUTPUT_PLAYABLE"] is True
    assert share not in serialized
    assert "SIGNED_SECRET" not in serialized


def test_segments_mode_preserves_range_telemetry_when_extraction_fails(
    monkeypatch, tmp_path
):
    segment = {"start": 1.0, "end": 2.0}
    monkeypatch.setattr(
        workflow,
        "resolve_llc_origin",
        lambda share, path: ([segment], "https://origin.invalid/private"),
    )

    def fake_fetch(origin_url, request_range, ledger):
        record_transfer(ledger, request_range, 64, total_size=1000)
        return b"x" * 64, 1000

    def failing_extract(origin_url, segments, output_dir, ledger):
        record_transfer(ledger, "bytes=100-199", 100, total_size=1000)
        raise ConnectionError("simulated extraction failure")

    monkeypatch.setattr(workflow, "fetch_exact_range", fake_fetch)
    monkeypatch.setattr(workflow, "extract_with_guard", failing_extract)

    report = workflow.segments_mode(
        "PRIVATE_SHARE_TOKEN",
        tmp_path / "project.llc",
        tmp_path / "segments",
        max_origin_bytes=1000,
    )

    assert report["STATUS"] == "FAIL"
    assert report["ERROR_TYPE"] == "ConnectionError"
    assert report["TOTAL_UPSTREAM_BYTES"] == 164
    assert report["UPSTREAM_TRANSFERRED"] == 164
    assert [event["status"] for event in report["RANGE_EVENTS"]] == [206, 206]
    assert [event["content_range"] for event in report["RANGE_EVENTS"]] == [
        "bytes 0-63/1000",
        "bytes 0-99/1000",
    ]
    assert [event["outcome"] for event in report["RANGE_EVENTS"]] == [
        "PASS",
        "PASS",
    ]
