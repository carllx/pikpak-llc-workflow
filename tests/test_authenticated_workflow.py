from contextlib import nullcontext
import json
from pathlib import Path

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

    def fake_extract(url, selected, output, ledger):
        if Path(output).name in fail_output_for:
            raise RuntimeError("synthetic extraction failure")
        return [Path(output) / "segment_001.mp4"], [], ["video:h264"]

    monkeypatch.setattr(workflow, "probe_origin", fake_probe)
    monkeypatch.setattr(workflow, "extract_with_guard", fake_extract)


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
    assert all(item["ERROR_TYPE"] == "ValueError" for item in report["LLC_RESULTS"])
    assert [item["SOURCE"] for item in report["LLC_RESULTS"]] == [
        "same_h264.mp4",
        "missing_h264.mp4",
    ]


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


def test_daily_entrypoint_needs_no_user_arguments(monkeypatch, capsys):
    expected = {"STATUS": "PASS", "SEGMENTS_DIR": "C:/output"}
    monkeypatch.setattr(workflow, "run_operator_preflight", lambda: {})
    monkeypatch.setattr(workflow, "run_default_latest_job", lambda: expected)

    assert workflow.main() == 0

    assert json.loads(capsys.readouterr().out) == expected
