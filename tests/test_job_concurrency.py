"""Regression tests for Job identity vs LATEST concurrency bug."""
from contextlib import nullcontext
from pathlib import Path
import pytest

from pikpak_llc import download_proxy
from pikpak_llc import authenticated_workflow as workflow
from pikpak_llc.workspace import JobWorkspace, WorkspaceError


class FakeShareClient:
    def __init__(self, files, proxies):
        self.files = files
        self.proxies = proxies
        self.requested = []

    def proxy_for_file(self, file_id):
        self.requested.append(file_id)
        return self.proxies[file_id]


def video(file_id, filename):
    return {"file_id": file_id, "filename": filename, "candidate_type": "video"}


class FakeOpened:
    origin_url = "http://127.0.0.1:1234/movie.mp4"
    origin_total = 1_000_000_000


class FakeTransport:
    def __init__(self):
        self.opened = []

    def open_for(self, name):
        self.opened.append(name)
        return nullcontext(FakeOpened())


def test_proxy_interleaving_maintains_job_a_identity_and_paths(monkeypatch, tmp_path):
    """Test A: Job A starts, Job B starts & overwrites LATEST, Job A finishes."""
    workspace = JobWorkspace(tmp_path / "workspace")

    client_a = FakeShareClient([video("v1", "video_a.mp4")], {"v1": "proxy-url-a"})
    client_b = FakeShareClient([video("v2", "video_b.mp4")], {"v2": "proxy-url-b"})

    def fake_open(share_url):
        if "share-a" in str(share_url):
            return client_a
        if "share-b" in str(share_url):
            return client_b
        raise ValueError(f"Unknown share {share_url}")

    monkeypatch.setattr(download_proxy.ShareMediaClient, "open", fake_open)
    monkeypatch.setattr(download_proxy.shutil, "which", lambda cmd: cmd)
    monkeypatch.setattr(download_proxy, "check_hw_encoder", lambda: "libx264")

    def fake_download_and_transcode(url, raw, compatible, encoder):
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.touch()
        compatible.touch()
        if "video_a" in raw.name:
            # While Job A is in flight, Job B starts and overwrites LATEST.txt
            workspace.start_share("https://mypikpak.com/s/share-b")

    monkeypatch.setattr(
        download_proxy, "_download_and_transcode", fake_download_and_transcode
    )

    result_a = download_proxy.prepare_share_proxies(
        "https://mypikpak.com/s/share-a", workspace_root=workspace.root
    )

    job_a_root = Path(result_a["files"][0]["raw_proxy"]).parent.parent

    # Assert that PROXY_DIR and SEGMENTS_DIR belong to Job A, NOT Job B
    assert Path(result_a["PROXY_DIR"]).parent == job_a_root
    assert Path(result_a["SEGMENTS_DIR"]).parent == job_a_root
    assert Path(result_a["files"][0]["raw_proxy"]).parent == job_a_root / "proxies"
    assert Path(result_a["files"][0]["compatible_proxy"]).parent == job_a_root / "proxies"


def test_origin_identity_stability_when_latest_changes(monkeypatch, tmp_path):
    """Test B: Origin run resolves Job A, Job B subsequently changes LATEST, Origin A continues."""
    workspace = JobWorkspace(tmp_path / "workspace")

    job_a = workspace.start_share("https://mypikpak.com/s/share-a")
    (job_a.projects / "video_a.llc").write_text("{}", encoding="utf-8")

    def fake_parse_llc(path):
        if "video_a" in Path(path).name:
            return {"mediaFileName": "video_a_h264.mp4", "cutSegments": [{"start": 1.0, "end": 2.0}]}
        if "video_b" in Path(path).name:
            return {"mediaFileName": "video_b_h264.mp4", "cutSegments": [{"start": 1.0, "end": 2.0}]}
        raise ValueError(f"Unknown LLC {path}")

    def fake_open(share_url):
        if "share-a" in str(share_url):
            return type("Client", (), {"files": [video("a", "video_a.mp4")]})()
        if "share-b" in str(share_url):
            return type("Client", (), {"files": [video("b", "video_b.mp4")]})()
        raise ValueError(f"Unknown share {share_url}")

    def fake_probe(url, ledger):
        ledger.reserve(100)
        ledger.consume(100)
        return {
            "format": {"duration": "100", "format_name": "mov,mp4"},
            "streams": [{"index": 0, "codec_type": "video", "codec_name": "h264"}],
        }

    def fake_extract(url, segments, output_dir, ledger, segment_results):
        # While Origin is running for Job A, Job B is created in background and overwrites LATEST
        workspace.start_share("https://mypikpak.com/s/share-b")
        outputs = []
        for i, entry in enumerate(segment_results, 1):
            out_path = Path(output_dir) / f"segment_{i:03d}.mp4"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.touch()
            entry.update(STATUS="PASS", OUTPUT=str(out_path), ERROR_CODE=None, ERROR_TYPE=None)
            outputs.append(out_path)
        return outputs, [], ["video:h264"]

    monkeypatch.setattr(workflow, "parse_llc_project", fake_parse_llc)
    monkeypatch.setattr(workflow.ShareMediaClient, "open", fake_open)
    monkeypatch.setattr(workflow, "probe_origin", fake_probe)
    monkeypatch.setattr(workflow, "extract_progressive_segments", fake_extract)

    transport = FakeTransport()
    # Execute Origin for Job A
    report = workflow.run_latest_job(transport, workspace_root=workspace.root)

    assert report["STATUS"] == "PASS"
    # Result must belong to Job A, not Job B
    assert report["CUT_PROJECTS"] == 1
    assert report["LLC_RESULTS"][0]["LLC_PROJECT"] == "video_a.llc"
    assert report["LLC_RESULTS"][0]["SOURCE"] == "video_a.mp4"
    assert Path(report["PROXY_DIR"]).parent == job_a.root
    assert Path(report["SEGMENTS_DIR"]).parent == job_a.root
    assert Path(report["LLC_RESULTS"][0]["OUTPUTS"][0]).parent == job_a.segments / "video_a"
    assert transport.opened == ["video_a.mp4"]


def test_cleanup_identity_stability_when_latest_changes(tmp_path):
    """Test C: Cleanup manifest for Job A succeeds with Job A paths even when LATEST is Job B."""
    workspace = JobWorkspace(tmp_path / "workspace")

    job_a = workspace.start_share("https://mypikpak.com/s/share-a")
    job_b = workspace.start_share("https://mypikpak.com/s/share-b")

    # LATEST is now Job B.
    # Creating cleanup manifest for explicit Job A must validate against Job A
    manifest_path = workspace.write_cleanup_manifest(
        keep_user_output=[job_a.proxies / "proxy.mp4"],
        keep_evidence=[job_a.reports / "report.json"],
        discardable=[job_a.temp / "temp.mp4"],
        job=job_a,
    )
    assert manifest_path.parent == job_a.reports

    # And attempting to classify Job B paths under Job A must be rejected
    with pytest.raises(WorkspaceError, match="outside"):
        workspace.write_cleanup_manifest(
            keep_user_output=[job_b.proxies / "proxy.mp4"],
            keep_evidence=[],
            discardable=[],
            job=job_a,
        )


def test_latest_convenience_behavior_preserved(tmp_path):
    """Test D: When no explicit job is provided, workspace methods fallback to LATEST."""
    workspace = JobWorkspace(tmp_path / "workspace")

    job_a = workspace.start_share("https://mypikpak.com/s/share-a")
    (job_a.projects / "cut_a.llc").write_text("{}", encoding="utf-8")

    job_b = workspace.start_share("https://mypikpak.com/s/share-b")
    (job_b.projects / "cut_b.llc").write_text("{}", encoding="utf-8")

    # When called without explicit job, resolves to current LATEST (Job B)
    assert workspace.latest().root == job_b.root
    assert workspace.latest_share() == "https://mypikpak.com/s/share-b"
    assert [p.name for p in workspace.find_llcs()] == ["cut_b.llc"]
    assert workspace.public_output_paths() == {
        "PROXY_DIR": str(job_b.proxies.resolve()),
        "SEGMENTS_DIR": str(job_b.segments.resolve()),
    }
    assert workspace.source_segments("movie.mp4") == job_b.segments / "movie"


def test_prepare_share_proxies_fails_closed_if_output_outside_job_proxies(monkeypatch, tmp_path):
    """Ensure fail-closed invariant if a proxy output somehow targets an outside directory."""
    workspace = JobWorkspace(tmp_path / "workspace")
    client = FakeShareClient([video("v1", "video.mp4")], {"v1": "proxy-url"})

    monkeypatch.setattr(download_proxy.ShareMediaClient, "open", lambda url: client)
    monkeypatch.setattr(download_proxy.shutil, "which", lambda cmd: cmd)
    monkeypatch.setattr(download_proxy, "check_hw_encoder", lambda: "libx264")

    # Simulate an anomaly where raw/compatible proxy was written to outside path
    def fake_download_and_transcode(url, raw, compatible, encoder):
        outside_raw = tmp_path / "outside.mp4"
        outside_comp = tmp_path / "outside_h264.mp4"
        outside_raw.touch()
        outside_comp.touch()
        # Modifying the output path pointers in-place isn't directly done by transcode,
        # but if download_proxy returns outside paths:

    monkeypatch.setattr(
        download_proxy, "_download_and_transcode", fake_download_and_transcode
    )

    # If download_proxy mock returns an item pointing outside job.proxies:
    def fake_download_proxy(share_url, output_dir):
        return [
            {
                "file_id": "v1",
                "filename": "video.mp4",
                "status": "PASS",
                "raw_proxy": str(tmp_path / "outside.mp4"),
                "compatible_proxy": str(tmp_path / "outside_h264.mp4"),
            }
        ]

    monkeypatch.setattr(download_proxy, "download_proxy", fake_download_proxy)

    result = download_proxy.prepare_share_proxies(
        "https://mypikpak.com/s/share", workspace_root=workspace.root
    )

    assert result["files"][0]["status"] == "FAIL"
    assert result["files"][0]["error_type"] == "WorkspaceJobMismatch"
