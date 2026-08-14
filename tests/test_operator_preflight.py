import subprocess
from pathlib import Path

import pytest

from pikpak_llc.operator_preflight import (
    OperatorPreflightError,
    run_operator_preflight,
)
from pikpak_llc import download_proxy


def git(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    )


def canonical_fixture(tmp_path):
    root = tmp_path / "pikpak-llc-workflow"
    required = [
        "AGENTS.md",
        ".agents/skills/pikpak-llc/SKILL.md",
        "src/pikpak_llc/authenticated_workflow.py",
        "src/pikpak_llc/download_proxy.py",
        "src/pikpak_llc/workspace.py",
    ]
    for relative in required:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("required", encoding="utf-8")
    git(root, "init", "-b", "master")
    git(root, "add", ".")
    git(root, "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture")
    return root


def test_canonical_master_with_clean_production_files_passes(tmp_path):
    root = canonical_fixture(tmp_path)

    report = run_operator_preflight(root, canonical_root=root)

    assert report["branch"] == "master"
    assert len(report["head"]) == 40
    assert report["workflow_source_clean"] is True
    assert report["skill_present"] is True


def test_legacy_operator_file_stops_with_fixed_incident_code(tmp_path):
    root = canonical_fixture(tmp_path)
    (root / "origin_segment_extractor.py").write_text("legacy", encoding="utf-8")

    with pytest.raises(OperatorPreflightError) as caught:
        run_operator_preflight(root, canonical_root=root)

    assert caught.value.code == "LEGACY_OPERATOR_FILE_DETECTED"


def test_tracked_workflow_source_modification_fails_closed(tmp_path):
    root = canonical_fixture(tmp_path)
    (root / "src/pikpak_llc/workspace.py").write_text("dirty", encoding="utf-8")

    with pytest.raises(OperatorPreflightError) as caught:
        run_operator_preflight(root, canonical_root=root)

    assert caught.value.code == "OPERATOR_WORKFLOW_SOURCE_DIRTY"


def test_untracked_workflow_source_also_fails_closed(tmp_path):
    root = canonical_fixture(tmp_path)
    (root / "src/pikpak_llc/loose_extractor.py").write_text("unsafe", encoding="utf-8")

    with pytest.raises(OperatorPreflightError) as caught:
        run_operator_preflight(root, canonical_root=root)

    assert caught.value.code == "OPERATOR_WORKFLOW_SOURCE_DIRTY"


def test_non_master_or_missing_production_module_fails_closed(tmp_path):
    root = canonical_fixture(tmp_path)
    git(root, "switch", "-c", "prototype")

    with pytest.raises(OperatorPreflightError) as caught:
        run_operator_preflight(root, canonical_root=root)
    assert caught.value.code == "OPERATOR_BRANCH_NOT_MASTER"

    git(root, "switch", "master")
    (root / "src/pikpak_llc/authenticated_workflow.py").unlink()
    with pytest.raises(OperatorPreflightError) as caught:
        run_operator_preflight(root, canonical_root=root)
    assert caught.value.code == "OPERATOR_PRODUCTION_MODULE_MISSING"


def test_feature_worktree_cannot_impersonate_canonical_operator(tmp_path):
    root = canonical_fixture(tmp_path)

    with pytest.raises(OperatorPreflightError) as caught:
        run_operator_preflight(root, canonical_root=tmp_path / "canonical")

    assert caught.value.code == "OPERATOR_WORKTREE_NOT_CANONICAL"


def test_proxy_cli_stops_before_share_access_when_preflight_fails(monkeypatch, capsys):
    def blocked():
        raise OperatorPreflightError("LEGACY_OPERATOR_FILE_DETECTED")

    monkeypatch.setattr(download_proxy, "run_operator_preflight", blocked)
    monkeypatch.setattr(
        download_proxy,
        "prepare_share_proxies",
        lambda share: pytest.fail("Share must not be accessed after failed preflight"),
    )

    assert download_proxy.main(["private-share"]) == 1
    assert "LEGACY_OPERATOR_FILE_DETECTED" in capsys.readouterr().out
