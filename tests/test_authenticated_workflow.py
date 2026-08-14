from contextlib import nullcontext
import json
from pathlib import Path
import pytest

from pikpak_llc import authenticated_workflow as workflow
from pikpak_llc.authenticated_transport import ProfileProvisioningRequired


def prepare_job(tmp_path, project_names):
    workspace = workflow.JobWorkspace(tmp_path / "workspace")
    job = workspace.start_share("private-share")
    for name in project_names:
        (job.projects / name).write_text("{}", encoding="utf-8")
    return workspace, job


class FakeOpened:
    origin_url = "http://127.0.0.1:1234/movie.mp4"
    origin_total = 1_000_000_000


class FakeTransport:
    def __init__(self, fail_for=()):
        self.opened = []
        self.fail_for = set(fail_for)

    def open_for(self, name):
        self.opened.append(name)
        if name in self.fail_for:
            raise ProfileProvisioningRequired("profile invalid")
        return nullcontext(FakeOpened())


def configure_success(monkeypatch, projects, share_files, fail_output_for=()):
    segments = [{"start": 10.0, "end": 20.0}]
    monkeypatch.setattr(
        workflow,
        "parse_llc_project",
        lambda path: {
            "mediaFileName": projects[Path(path).name],
            "cutSegments": segments,
        },
    )
    monkeypatch.setattr(
        workflow.ShareMediaClient,
        "open",
        lambda share: type("Client", (), {"files": share_files})(),
    )

    def fake_probe(url, ledger):
        ledger.reserve(123)
        ledger.consume(123)
        return {
            "format": {"duration": "100", "format_name": "mov,mp4"},
            "streams": [{"index": 0, "codec_type": "video", "codec_name": "h264"}],
        }

    def fake_extract_prog(url, selected, output_dir, ledger, segment_results):
        if Path(output_dir).name in fail_output_for:
            if segment_results:
                segment_results[0].update(
                    STATUS="FAIL",
                    ERROR_CODE="OUTPUT_VALIDATION_FAILED",
                    ERROR_TYPE="WorkflowError",
                )
            raise workflow.WorkflowError("synthetic extraction failure")
        outputs = []
        for i, entry in enumerate(segment_results, 1):
            out_path = Path(output_dir) / f"segment_{i:03d}.mp4"
            entry.update(STATUS="PASS", OUTPUT=str(out_path), ERROR_CODE=None, ERROR_TYPE=None)
            outputs.append(out_path)
        return outputs, [], ["video:h264"]

    monkeypatch.setattr(workflow, "probe_origin", fake_probe)
    monkeypatch.setattr(workflow, "extract_progressive_segments", fake_extract_prog)


def test_one_llc_auto_budgets_without_user_paths_or_budget(monkeypatch, tmp_path):
    workspace, job = prepare_job(tmp_path, ["movie.llc"])
    configure_success(
        monkeypatch,
        {"movie.llc": "movie_h264.mp4"},
        [{"file_id": "one", "filename": "movie.mp4", "candidate_type": "video"}],
    )
    transport = FakeTransport()

    report = workflow.run_latest_job(transport, workspace.root)

    result = report["LLC_RESULTS"][0]
    assert report["STATUS"] == "PASS"
    assert result["SOURCE"] == "movie.mp4"
    assert result["OUTPUTS"] == [str(job.segments / "movie" / "segment_001.mp4")]
    assert result["PREFLIGHT_UPSTREAM_BYTES"] == 123
    assert result["TOTAL_UPSTREAM_BYTES"] == 123
    assert result["MAX_ORIGIN_BYTES"] > result["TOTAL_UPSTREAM_BYTES"]
    assert transport.opened == ["movie.mp4"]


def test_two_llcs_map_to_two_sources_and_do_not_collide(monkeypatch, tmp_path):
    workspace, job = prepare_job(tmp_path, ["b.llc", "a.llc"])
    configure_success(
        monkeypatch,
        {"a.llc": "source-a_h264.mp4", "b.llc": "source-b_h264.mp4"},
        [
            {"file_id": "a", "filename": "source-a.mp4", "candidate_type": "video"},
            {"file_id": "b", "filename": "source-b.mp4", "candidate_type": "video"},
        ],
    )

    report = workflow.run_latest_job(FakeTransport(), workspace.root)

    assert report["STATUS"] == "PASS"
    assert [item["LLC_PROJECT"] for item in report["LLC_RESULTS"]] == ["a.llc", "b.llc"]
    assert [item["OUTPUTS"][0] for item in report["LLC_RESULTS"]] == [
        str(job.segments / "source-a" / "segment_001.mp4"),
        str(job.segments / "source-b" / "segment_001.mp4"),
    ]


def test_missing_or_ambiguous_source_is_explicit_per_llc_failure(monkeypatch, tmp_path):
    workspace, _ = prepare_job(tmp_path, ["missing.llc", "ambiguous.llc"])
    configure_success(
        monkeypatch,
        {"missing.llc": "missing_h264.mp4", "ambiguous.llc": "same_h264.mp4"},
        [
            {"file_id": "1", "filename": "same.mp4", "candidate_type": "video"},
            {"file_id": "2", "filename": "same.mkv", "candidate_type": "video"},
        ],
    )

    report = workflow.run_latest_job(FakeTransport(), workspace.root)

    assert report["STATUS"] == "FAIL"
    assert [item["STATUS"] for item in report["LLC_RESULTS"]] == ["FAIL", "FAIL"]
    assert all(item["ERROR_TYPE"] == "SourceSelectionError" for item in report["LLC_RESULTS"])
    assert all(item["ERROR_CODE"] == "SOURCE_MATCH_FAILED" for item in report["LLC_RESULTS"])
    assert [item["SOURCE"] for item in report["LLC_RESULTS"]] == [
        "same_h264.mp4",
        "missing_h264.mp4",
    ]


def test_invalid_llc_structure_classifies_as_unclassified_failure(monkeypatch, tmp_path):
    workspace, job = prepare_job(tmp_path, ["bad.llc"])
    (job.projects / "bad.llc").write_text("{ not valid json5", encoding="utf-8")
    monkeypatch.setattr(
        workflow.ShareMediaClient,
        "open",
        lambda share: type("Client", (), {"files": [{"file_id": "1", "filename": "movie.mp4", "candidate_type": "video"}]})(),
    )

    report = workflow.run_latest_job(FakeTransport(), workspace.root)

    assert report["STATUS"] == "FAIL"
    result = report["LLC_RESULTS"][0]
    assert result["STATUS"] == "FAIL"
    assert result["ERROR_CODE"] != "SOURCE_MATCH_FAILED"
    assert result["ERROR_CODE"] == "UNCLASSIFIED_FAILURE"
    assert result["ERROR_TYPE"] == "ValueError"
    assert result["ROOT_CAUSE"] == "UNVERIFIED"


def test_one_llc_failure_does_not_silently_skip_other_projects(monkeypatch, tmp_path):
    workspace, _ = prepare_job(tmp_path, ["a.llc", "b.llc"])
    configure_success(
        monkeypatch,
        {"a.llc": "a.mp4", "b.llc": "b.mp4"},
        [
            {"file_id": "a", "filename": "a.mp4", "candidate_type": "video"},
            {"file_id": "b", "filename": "b.mp4", "candidate_type": "video"},
        ],
        fail_output_for={"a"},
    )

    report = workflow.run_latest_job(FakeTransport(), workspace.root)

    failed, passed = report["LLC_RESULTS"]
    assert [failed["STATUS"], passed["STATUS"]] == ["FAIL", "PASS"]
    assert failed["SOURCE"] == "a.mp4"
    assert failed["OUTPUTS"] == []
    assert failed["MAX_ORIGIN_BYTES"] is not None
    assert failed["TOTAL_UPSTREAM_BYTES"] == 123


def test_missing_or_expired_profile_is_explicit_failure(monkeypatch, tmp_path):
    workspace, _ = prepare_job(tmp_path, ["movie.llc"])
    configure_success(
        monkeypatch,
        {"movie.llc": "movie.mp4"},
        [{"file_id": "one", "filename": "movie.mp4", "candidate_type": "video"}],
    )

    report = workflow.run_latest_job(FakeTransport(fail_for={"movie.mp4"}), workspace.root)

    assert report["STATUS"] == "FAIL"
    assert report["LLC_RESULTS"][0]["ERROR_TYPE"] == "ProfileProvisioningRequired"
    assert report["LLC_RESULTS"][0]["ERROR_CODE"] == "PROFILE_REQUIRED"
    assert report["ROOT_CAUSE"] == "UNVERIFIED"


def test_budget_blocked_before_extraction_records_not_run_not_fail(monkeypatch, tmp_path):
    workspace, _ = prepare_job(tmp_path, ["movie.llc"])
    configure_success(
        monkeypatch,
        {"movie.llc": "movie.mp4"},
        [{"file_id": "one", "filename": "movie.mp4", "candidate_type": "video"}],
    )
    # 90s out of 100s will exceed hard_cap and trigger BudgetConfirmationRequired
    monkeypatch.setattr(
        workflow,
        "parse_llc_project",
        lambda path: {
            "mediaFileName": "movie.mp4",
            "cutSegments": [{"start": 0.0, "end": 90.0}],
        },
    )

    report = workflow.run_latest_job(FakeTransport(), workspace.root)

    assert report["STATUS"] == "FAIL"
    assert report["SEGMENTS_TOTAL"] == 1
    assert report["SEGMENTS_PASS"] == 0
    assert report["SEGMENTS_FAIL"] == 0
    assert report["SEGMENTS_NOT_RUN"] == 1
    result = report["LLC_RESULTS"][0]
    assert result["STATUS"] == "FAIL"
    assert result["ERROR_CODE"] == "PROJECT_BUDGET_BLOCKED"
    assert result["SEGMENTS_FAIL"] == 0
    assert result["SEGMENTS_NOT_RUN"] == 1


def test_extraction_failure_records_failed_segments(monkeypatch, tmp_path):
    workspace, _ = prepare_job(tmp_path, ["movie.llc"])
    configure_success(
        monkeypatch,
        {"movie.llc": "movie.mp4"},
        [{"file_id": "one", "filename": "movie.mp4", "candidate_type": "video"}],
        fail_output_for={"movie"},
    )

    report = workflow.run_latest_job(FakeTransport(), workspace.root)

    assert report["STATUS"] == "FAIL"
    assert report["SEGMENTS_TOTAL"] == 1
    assert report["SEGMENTS_PASS"] == 0
    assert report["SEGMENTS_FAIL"] == 1
    assert report["SEGMENTS_NOT_RUN"] == 0
    result = report["LLC_RESULTS"][0]
    assert result["STATUS"] == "FAIL"
    assert result["ERROR_CODE"] == "OUTPUT_VALIDATION_FAILED"
    assert result["SEGMENTS_FAIL"] == 1
    assert result["SEGMENTS_NOT_RUN"] == 0


def test_mid_batch_segment_failure_accounting(monkeypatch, tmp_path):
    workspace, _ = prepare_job(tmp_path, ["movie.llc"])
    segments = [
        {"start": 10.0, "end": 20.0},
        {"start": 30.0, "end": 40.0},
        {"start": 50.0, "end": 60.0},
    ]
    monkeypatch.setattr(
        workflow,
        "parse_llc_project",
        lambda path: {
            "mediaFileName": "movie.mp4",
            "cutSegments": segments,
        },
    )
    monkeypatch.setattr(
        workflow.ShareMediaClient,
        "open",
        lambda share: type("Client", (), {"files": [{"file_id": "one", "filename": "movie.mp4", "candidate_type": "video"}]})(),
    )

    def fake_probe(url, ledger):
        return {
            "format": {"duration": "100", "format_name": "mov,mp4"},
            "streams": [{"index": 0, "codec_type": "video", "codec_name": "h264"}],
        }

    def fake_extract_prog(url, selected, output_dir, ledger, segment_results):
        # Segment 1 PASS
        segment_results[0].update(STATUS="PASS", OUTPUT=str(Path(output_dir) / "segment_001.mp4"))
        # Segment 2 FAIL
        segment_results[1].update(STATUS="FAIL", ERROR_CODE="FFMPEG_FAILED", ERROR_TYPE="WorkflowError")
        # Segment 3 remains NOT_RUN
        raise workflow.WorkflowError("ffmpeg mid-batch failure")

    monkeypatch.setattr(workflow, "probe_origin", fake_probe)
    monkeypatch.setattr(workflow, "extract_progressive_segments", fake_extract_prog)

    report = workflow.run_latest_job(FakeTransport(), workspace.root)

    assert report["STATUS"] == "FAIL"
    assert report["SEGMENTS_TOTAL"] == 3
    assert report["SEGMENTS_PASS"] == 1
    assert report["SEGMENTS_FAIL"] == 1
    assert report["SEGMENTS_NOT_RUN"] == 1

    result = report["LLC_RESULTS"][0]
    assert result["STATUS"] == "FAIL"
    assert result["ERROR_CODE"] == "FFMPEG_FAILED"
    assert result["SEGMENTS_TOTAL"] == 3
    assert result["SEGMENTS_PASS"] == 1
    assert result["SEGMENTS_FAIL"] == 1
    assert result["SEGMENTS_NOT_RUN"] == 1
    assert len(result["SEGMENT_RESULTS"]) == 3
    assert result["SEGMENT_RESULTS"][0]["STATUS"] == "PASS"
    assert result["SEGMENT_RESULTS"][1]["STATUS"] == "FAIL"
    assert result["SEGMENT_RESULTS"][2]["STATUS"] == "NOT_RUN"


def test_unknown_exception_maps_to_unclassified_failure(monkeypatch, tmp_path):
    workspace, _ = prepare_job(tmp_path, ["movie.llc"])
    configure_success(
        monkeypatch,
        {"movie.llc": "movie.mp4"},
        [{"file_id": "one", "filename": "movie.mp4", "candidate_type": "video"}],
    )

    def fake_probe_error(url, ledger):
        raise TypeError("completely unexpected python error")

    monkeypatch.setattr(workflow, "probe_origin", fake_probe_error)

    report = workflow.run_latest_job(FakeTransport(), workspace.root)

    assert report["STATUS"] == "FAIL"
    result = report["LLC_RESULTS"][0]
    assert result["STATUS"] == "FAIL"
    assert result["ERROR_CODE"] == "UNCLASSIFIED_FAILURE"
    assert result["ERROR_TYPE"] == "TypeError"
    assert result["ROOT_CAUSE"] == "UNVERIFIED"


def test_extract_progressive_segments_direct(monkeypatch, tmp_path):
    segments = [
        {"start": 0.0, "end": 10.0},
        {"start": 10.0, "end": 20.0},
        {"start": 20.0, "end": 30.0},
    ]
    segment_results = [
        {
            "INDEX": idx,
            "STATUS": "NOT_RUN",
            "OUTPUT": str(tmp_path / f"segment_{idx:03d}.mp4"),
            "ERROR_CODE": None,
            "ERROR_TYPE": None,
        }
        for idx in range(1, 4)
    ]
    ledger = workflow.TransferLedger(1000)

    def fake_run_command(cmd, expect_json=False):
        out = Path(cmd[-1])
        out.write_bytes(b"data")
        return None

    def fake_probe(path_or_url):
        if "segment_002.mp4" in str(path_or_url):
            raise workflow.WorkflowError("Extracted Origin segment is not probeable")
        return {
            "format": {"duration": "10", "format_name": "mov,mp4"},
            "streams": [{"index": 0, "codec_type": "video", "codec_name": "h264"}],
        }

    monkeypatch.setattr(workflow, "probe_media", fake_probe)
    monkeypatch.setattr(workflow, "run_command", fake_run_command)

    with pytest.raises(workflow.WorkflowError):
        workflow.extract_progressive_segments(
            "http://dummy", segments, tmp_path, ledger, segment_results
        )

    assert segment_results[0]["STATUS"] == "PASS"
    assert segment_results[1]["STATUS"] == "FAIL"
    assert segment_results[1]["ERROR_CODE"] == "OUTPUT_VALIDATION_FAILED"
    assert segment_results[1]["ERROR_TYPE"] == "WorkflowError"
    assert segment_results[2]["STATUS"] == "NOT_RUN"


def test_daily_entrypoint_needs_no_user_arguments(monkeypatch, capsys):
    expected = {"STATUS": "PASS", "SEGMENTS_DIR": "C:/output"}
    monkeypatch.setattr(workflow, "run_operator_preflight", lambda: {})
    monkeypatch.setattr(workflow, "run_default_latest_job", lambda: expected)

    assert workflow.main() == 0

    assert json.loads(capsys.readouterr().out) == expected
