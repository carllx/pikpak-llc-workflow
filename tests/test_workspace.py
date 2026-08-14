from datetime import datetime, timezone
from pathlib import Path

import pytest

from pikpak_llc.workspace import JobWorkspace, WorkspaceError


NOW = datetime(2026, 8, 14, 1, 2, 3, tzinfo=timezone.utc)


def test_share_invocation_creates_one_job_with_public_output_contract(tmp_path):
    workspace = JobWorkspace(tmp_path / "workspace")

    job = workspace.start_share("https://example.invalid/private-share", now=NOW)

    assert job.root.name.startswith("20260814T010203Z-")
    assert job.proxies == job.root / "proxies"
    assert job.projects == job.root / "projects"
    assert job.segments == job.root / "segments"
    assert job.reports == job.root / "reports"
    assert job.temp == job.root / "temp"
    assert all(path.is_dir() for path in job.directories)
    assert workspace.latest().root == job.root
    assert workspace.public_output_paths() == {
        "PROXY_DIR": str(job.proxies.resolve()),
        "SEGMENTS_DIR": str(job.segments.resolve()),
    }
    assert "private-share" not in (workspace.root / "LATEST.txt").read_text()
    assert workspace.latest_share() == "https://example.invalid/private-share"


def test_latest_job_locates_one_llc_project_without_more_user_paths(tmp_path):
    workspace = JobWorkspace(tmp_path / "workspace")
    job = workspace.start_share("share", now=NOW)
    expected = job.projects / "cut.llc"
    expected.write_text("{}", encoding="utf-8")

    assert workspace.find_llcs() == [expected]
    assert workspace.find_llc() == expected


def test_latest_job_rejects_missing_llc_projects(tmp_path):
    workspace = JobWorkspace(tmp_path / "workspace")
    workspace.start_share("share", now=NOW)

    with pytest.raises(WorkspaceError, match="LLC"):
        workspace.find_llcs()


def test_one_share_two_video_proxies_discovers_two_llcs_and_ignores_other_files(tmp_path):
    workspace = JobWorkspace(tmp_path / "workspace")
    job = workspace.start_share("share", now=NOW)
    (job.proxies / "source-b_h264.mp4").touch()
    (job.proxies / "source-a_h264.mp4").touch()
    project_b = job.projects / "source-b.llc"
    project_a = job.projects / "source-a.llc"
    project_b.write_text("{}", encoding="utf-8")
    project_a.write_text("{}", encoding="utf-8")
    (job.projects / "notes.txt").write_text("ignore", encoding="utf-8")

    assert workspace.find_llcs() == [project_a, project_b]
    assert workspace.source_segments("source-a.mp4") == job.segments / "source-a"
    assert workspace.source_segments("source-b.mp4") == job.segments / "source-b"


def test_legacy_find_llc_still_rejects_multiple_projects(tmp_path):
    workspace = JobWorkspace(tmp_path / "workspace")
    job = workspace.start_share("share", now=NOW)
    for name in ("a.llc", "b.llc"):
        (job.projects / name).write_text("{}", encoding="utf-8")

    with pytest.raises(WorkspaceError, match="exactly one"):
        workspace.find_llc()


def test_find_llcs_has_total_order_when_casefold_keys_tie(tmp_path):
    workspace = JobWorkspace(tmp_path / "workspace")
    job = workspace.start_share("share", now=NOW)
    upper = job.projects / "SS.llc"
    folded = job.projects / "ß.llc"
    upper.write_text("{}", encoding="utf-8")
    folded.write_text("{}", encoding="utf-8")

    assert workspace.find_llcs() == [upper, folded]


def test_latest_fails_closed_when_pointer_escapes_workspace(tmp_path):
    workspace = JobWorkspace(tmp_path / "workspace")
    workspace.root.mkdir(parents=True)
    (workspace.root / "LATEST.txt").write_text("../../outside", encoding="utf-8")

    with pytest.raises(WorkspaceError, match="LATEST"):
        workspace.latest()


def test_cleanup_manifest_records_all_categories_before_cleanup(tmp_path):
    workspace = JobWorkspace(tmp_path / "workspace")
    job = workspace.start_share("share", now=NOW)

    manifest_path = workspace.write_cleanup_manifest(
        keep_user_output=[job.proxies / "proxy.mp4"],
        keep_evidence=[job.reports / "acceptance.json"],
        discardable=[job.temp / "failed-shell.mp4"],
    )

    manifest = __import__("json").loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_path.parent == job.reports
    assert manifest["KEEP_USER_OUTPUT"] == ["proxies/proxy.mp4"]
    assert manifest["KEEP_EVIDENCE"] == ["reports/acceptance.json"]
    assert manifest["DISCARDABLE"] == ["temp/failed-shell.mp4"]
    assert manifest["cleanup_executed"] is False


def test_cleanup_manifest_rejects_paths_outside_latest_job(tmp_path):
    workspace = JobWorkspace(tmp_path / "workspace")
    workspace.start_share("share", now=NOW)

    with pytest.raises(WorkspaceError, match="outside"):
        workspace.write_cleanup_manifest(
            keep_user_output=[tmp_path / "outside.mp4"],
            keep_evidence=[],
            discardable=[],
        )


def test_cleanup_manifest_rejects_conflicting_classification(tmp_path):
    workspace = JobWorkspace(tmp_path / "workspace")
    job = workspace.start_share("share", now=NOW)
    final = job.segments / "final.mp4"

    with pytest.raises(WorkspaceError, match="multiple cleanup categories"):
        workspace.write_cleanup_manifest(
            keep_user_output=[final],
            keep_evidence=[],
            discardable=[final],
        )
