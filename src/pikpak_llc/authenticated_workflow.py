"""Daily authenticated Origin workflow for the current workspace Job."""

import json

from .experimental_workflow import (
    extract_with_guard,
    output_is_playable,
    probe_media,
    require_mp4_origin,
    safe_range_summary,
    validate_segments,
)
from .llc_parser import parse_llc_project
from .origin_budget import estimate_origin_budget
from .operator_preflight import OperatorPreflightError, run_operator_preflight
from .pikpak_api import ShareMediaClient, select_share_video
from .range_guard import RangeGuard, TransferLedger
from .workspace import JobWorkspace
from .authenticated_transport import build_default_authenticated_transport


def probe_origin(origin_url, ledger):
    with RangeGuard(origin_url, ledger) as guard:
        probe = probe_media(guard.url)
        guard.raise_if_failed()
        require_mp4_origin(probe)
        return probe


def _result_base(llc_path):
    return {
        "LLC_PROJECT": llc_path.name,
        "SOURCE": None,
        "OUTPUTS": [],
        "MAX_ORIGIN_BYTES": None,
        "TOTAL_UPSTREAM_BYTES": 0,
        "RANGE_EVENTS": [],
    }


def _run_project(transport, workspace, llc_path, share_files):
    result = _result_base(llc_path)
    ledger = None
    try:
        project = parse_llc_project(llc_path)
        segments = project["cutSegments"]
        validate_segments(segments)
        selected_duration = sum(item["end"] - item["start"] for item in segments)
        result["SOURCE"] = project["mediaFileName"]
        source = select_share_video(share_files, project["mediaFileName"])
        result["SOURCE"] = source["filename"]
        output_dir = workspace.source_segments(source["filename"])

        with transport.open_for(source["filename"]) as opened:
            ledger = TransferLedger(128 * 1024 * 1024)
            source_probe = probe_origin(opened.origin_url, ledger)
            preflight_bytes = ledger.total_upstream_bytes
            budget = estimate_origin_budget(
                opened.origin_total,
                float(source_probe["format"]["duration"]),
                selected_duration,
            )
            ledger.increase_max_bytes(budget.max_origin_bytes)
            result["MAX_ORIGIN_BYTES"] = budget.max_origin_bytes
            outputs, probes, source_inventory = extract_with_guard(
                opened.origin_url, segments, output_dir, ledger
            )
    except Exception as error:
        result.update(STATUS="FAIL", ERROR_TYPE=type(error).__name__)
        if ledger is not None:
            result.update(safe_range_summary(ledger))
        return result

    result.update(
        STATUS="PASS",
        ORIGIN_TOTAL=opened.origin_total,
        SELECTED_DURATION=selected_duration,
        ESTIMATED_SELECTED_BYTES=budget.estimated_selected_bytes,
        PREFLIGHT_UPSTREAM_BYTES=preflight_bytes,
        OUTPUTS=[str(path) for path in outputs],
        OUTPUT_PLAYABLE=all(output_is_playable(probe) for probe in probes),
        SOURCE_STREAM_INVENTORY=source_inventory,
        STREAM_INVENTORY_PRESERVED=True,
        **safe_range_summary(ledger),
    )
    return result


def run_latest_job(transport, workspace_root="workspace"):
    """Process every LLC in LATEST without user-facing transport details."""
    workspace = JobWorkspace(workspace_root)
    llc_paths = workspace.find_llcs()
    try:
        share_files = ShareMediaClient.open(workspace.latest_share()).files
    except Exception as error:
        results = []
        for path in llc_paths:
            result = _result_base(path)
            result.update(STATUS="FAIL", ERROR_TYPE=type(error).__name__)
            results.append(result)
    else:
        results = [
            _run_project(transport, workspace, path, share_files) for path in llc_paths
        ]
    return {
        "STATUS": "PASS" if all(item["STATUS"] == "PASS" for item in results) else "FAIL",
        "CUT_PROJECTS": len(results),
        "LLC_RESULTS": results,
        **workspace.public_output_paths(),
    }


def run_default_latest_job(workspace_root="workspace"):
    """Daily entrypoint: use the saved local profile and current Job."""
    return run_latest_job(build_default_authenticated_transport(), workspace_root)


def main():
    """Execute the current Job without asking for transport implementation details."""
    try:
        run_operator_preflight()
        report = run_default_latest_job()
    except OperatorPreflightError as error:
        report = {"STATUS": "FAIL", "ERROR": error.code}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["STATUS"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
