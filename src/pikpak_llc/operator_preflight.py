"""Fail-closed checks for daily media operations in the canonical worktree."""

import subprocess
from pathlib import Path


CANONICAL_OPERATOR_ROOT = Path(r"E:\PROJECTS\pikpak-llc-workflow")
LEGACY_EXTRACTOR = "origin_segment_extractor.py"
REQUIRED_PRODUCTION_FILES = (
    "AGENTS.md",
    ".agents/skills/pikpak-llc/SKILL.md",
    "src/pikpak_llc/authenticated_workflow.py",
    "src/pikpak_llc/download_proxy.py",
    "src/pikpak_llc/workspace.py",
)
WORKFLOW_TRACKED_PATHS = (
    "AGENTS.md",
    ".agents/skills/pikpak-llc",
    "src/pikpak_llc",
    "download_proxy.py",
    "experimental_workflow.py",
)


class OperatorPreflightError(RuntimeError):
    """A safe, stable reason daily workflow execution was blocked."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _git(root, *arguments):
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def run_operator_preflight(repo_root=None, canonical_root=None):
    """Validate and return safe operator identity without exposing user inputs."""
    root = Path(repo_root or Path.cwd()).resolve()
    canonical = Path(canonical_root or CANONICAL_OPERATOR_ROOT).resolve()
    if root != canonical:
        raise OperatorPreflightError("OPERATOR_WORKTREE_NOT_CANONICAL")
    if (root / LEGACY_EXTRACTOR).exists():
        raise OperatorPreflightError("LEGACY_OPERATOR_FILE_DETECTED")

    branch = _git(root, "branch", "--show-current")
    if branch != "master":
        raise OperatorPreflightError("OPERATOR_BRANCH_NOT_MASTER")
    head = _git(root, "rev-parse", "HEAD")

    if any(not (root / relative).is_file() for relative in REQUIRED_PRODUCTION_FILES):
        raise OperatorPreflightError("OPERATOR_PRODUCTION_MODULE_MISSING")
    status = _git(
        root,
        "status",
        "--short",
        "--untracked-files=all",
        "--",
        *WORKFLOW_TRACKED_PATHS,
    )
    if status:
        raise OperatorPreflightError("OPERATOR_WORKFLOW_SOURCE_DIRTY")

    return {
        "branch": branch,
        "head": head,
        "workflow_source_clean": True,
        "production_modules_present": True,
        "skill_present": True,
    }
