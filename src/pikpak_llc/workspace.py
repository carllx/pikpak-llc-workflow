"""Stable job and output paths for one PikPak Share invocation."""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path


class WorkspaceError(RuntimeError):
    """Raised when the current workspace job cannot be resolved safely."""


@dataclass(frozen=True)
class JobPaths:
    root: Path
    proxies: Path
    projects: Path
    segments: Path
    reports: Path
    temp: Path

    @property
    def directories(self):
        return (
            self.proxies,
            self.projects,
            self.segments,
            self.reports,
            self.temp,
        )


class JobWorkspace:
    """Own job creation, LATEST resolution, and the public output contract."""

    def __init__(self, root="workspace"):
        self.root = Path(root)

    def start_share(self, share_url, now=None):
        if not str(share_url).strip():
            raise WorkspaceError("Share invocation must not be empty")
        current = now or datetime.now(timezone.utc)
        timestamp = current.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        share_key = sha256(str(share_url).encode("utf-8")).hexdigest()[:10]
        job_id = f"{timestamp}-{share_key}"
        job_root = self.root / "jobs" / job_id
        if job_root.exists():
            raise WorkspaceError("Share invocation job already exists")
        paths = self._paths(job_root)
        for directory in paths.directories:
            directory.mkdir(parents=True, exist_ok=False)
        (job_root / "job.json").write_text(
            json.dumps({"share": str(share_url)}, indent=2),
            encoding="utf-8",
        )
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "LATEST.txt").write_text(job_id + "\n", encoding="utf-8")
        return paths

    def _resolve_job(self, job=None):
        if job is not None:
            if isinstance(job, JobPaths):
                return job
            if isinstance(job, (str, Path)):
                job_path = Path(job)
                if not job_path.is_absolute() and job_path.parent == Path("."):
                    job_path = self.root / "jobs" / job_path
                return self._paths(job_path)
            raise WorkspaceError("Invalid job reference")
        return self.latest()

    def latest(self):
        pointer = self.root / "LATEST.txt"
        try:
            job_id = pointer.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise WorkspaceError("LATEST Job is unavailable") from error
        if not job_id or Path(job_id).name != job_id:
            raise WorkspaceError("LATEST Job pointer is invalid")
        jobs_root = (self.root / "jobs").resolve()
        job_root = (jobs_root / job_id).resolve()
        if job_root.parent != jobs_root or not job_root.is_dir():
            raise WorkspaceError("LATEST Job pointer is invalid")
        return self._paths(job_root)

    def find_llcs(self, job=None):
        resolved = self._resolve_job(job)
        projects = resolved.projects
        candidates = sorted(
            projects.glob("*.llc"),
            key=lambda path: (path.name.casefold(), path.name),
        )
        if not candidates:
            raise WorkspaceError(
                "LATEST Job contains no LLC projects"
                if job is None
                else "Job contains no LLC projects"
            )
        return candidates

    def find_llc(self, job=None):
        """Legacy single-project helper; daily workflows must use find_llcs()."""
        candidates = self.find_llcs(job=job)
        if len(candidates) != 1:
            raise WorkspaceError(f"Expected exactly one LLC project, found {len(candidates)}")
        return candidates[0]

    def source_segments(self, media_filename, job=None):
        """Return a collision-free segment directory for one LLC source."""
        filename = Path(media_filename)
        if filename.name != str(media_filename) or not filename.stem:
            raise WorkspaceError("LLC media filename is invalid")
        resolved = self._resolve_job(job)
        return resolved.segments / filename.stem

    def latest_share(self, job=None):
        resolved = self._resolve_job(job)
        metadata = resolved.root / "job.json"
        try:
            share = json.loads(metadata.read_text(encoding="utf-8"))["share"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise WorkspaceError(
                "LATEST Job Share metadata is unavailable"
                if job is None
                else "Job Share metadata is unavailable"
            ) from error
        if not isinstance(share, str) or not share.strip():
            raise WorkspaceError(
                "LATEST Job Share metadata is invalid"
                if job is None
                else "Job Share metadata is invalid"
            )
        return share

    def public_output_paths(self, job=None):
        resolved = self._resolve_job(job)
        return {
            "PROXY_DIR": str(resolved.proxies.resolve()),
            "SEGMENTS_DIR": str(resolved.segments.resolve()),
        }

    def write_cleanup_manifest(
        self, keep_user_output, keep_evidence, discardable, job=None
    ):
        """Persist an explicit cleanup classification before any mutation."""
        resolved = self._resolve_job(job)

        def relative_paths(paths):
            relative = []
            job_root = resolved.root.resolve()
            for value in paths:
                path = Path(value).resolve()
                try:
                    item = path.relative_to(job_root)
                except ValueError as error:
                    raise WorkspaceError(
                        "Cleanup manifest path is outside the LATEST Job"
                        if job is None
                        else "Cleanup manifest path is outside the Job"
                    ) from error
                relative.append(item.as_posix())
            return sorted(relative)

        categories = {
            "KEEP_USER_OUTPUT": relative_paths(keep_user_output),
            "KEEP_EVIDENCE": relative_paths(keep_evidence),
            "DISCARDABLE": relative_paths(discardable),
        }
        classified = [item for values in categories.values() for item in values]
        if len(classified) != len(set(classified)):
            raise WorkspaceError("A path appears in multiple cleanup categories")
        manifest = {
            **categories,
            "cleanup_executed": False,
        }
        destination = resolved.reports / "cleanup-manifest.json"
        destination.write_text(
            json.dumps(manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return destination

    @staticmethod
    def _paths(root):
        return JobPaths(
            root=root,
            proxies=root / "proxies",
            projects=root / "projects",
            segments=root / "segments",
            reports=root / "reports",
            temp=root / "temp",
        )
