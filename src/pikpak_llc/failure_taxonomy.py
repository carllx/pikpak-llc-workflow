"""Deterministic error codes and failure classification for authenticated jobs."""

from .authenticated_transport import ProfileProvisioningRequired
from .operator_preflight import OperatorPreflightError
from .origin_budget import BudgetConfirmationRequired
from .range_guard import RangeGuardError
from .rclone_adapter import RcloneTargetError
from .experimental_workflow import WorkflowError


class ErrorCode:
    OPERATOR_PREFLIGHT_FAILED = "OPERATOR_PREFLIGHT_FAILED"
    PROFILE_REQUIRED = "PROFILE_REQUIRED"
    AUTH_TARGET_NOT_FOUND = "AUTH_TARGET_NOT_FOUND"
    PROJECT_BUDGET_BLOCKED = "PROJECT_BUDGET_BLOCKED"
    HARD_FUSE_HIT = "HARD_FUSE_HIT"
    AUTH_ORIGINAL_RANGE_FAILED = "AUTH_ORIGINAL_RANGE_FAILED"
    SOURCE_MATCH_FAILED = "SOURCE_MATCH_FAILED"
    FFMPEG_FAILED = "FFMPEG_FAILED"
    OUTPUT_VALIDATION_FAILED = "OUTPUT_VALIDATION_FAILED"
    UNCLASSIFIED_FAILURE = "UNCLASSIFIED_FAILURE"


def classify_error(error):
    """Map a caught exception to a deterministic ERROR_CODE."""
    if isinstance(error, OperatorPreflightError):
        return ErrorCode.OPERATOR_PREFLIGHT_FAILED
    if isinstance(error, ProfileProvisioningRequired):
        return ErrorCode.PROFILE_REQUIRED
    if isinstance(error, RcloneTargetError):
        return ErrorCode.AUTH_TARGET_NOT_FOUND
    if isinstance(error, BudgetConfirmationRequired):
        return ErrorCode.PROJECT_BUDGET_BLOCKED
    if isinstance(error, RangeGuardError):
        detail = str(error).casefold()
        if "exceeded limit" in detail or "budget" in detail or "fuse" in detail:
            return ErrorCode.HARD_FUSE_HIT
        return ErrorCode.AUTH_ORIGINAL_RANGE_FAILED
    if isinstance(error, WorkflowError):
        detail = str(error).casefold()
        if any(marker in detail for marker in ("stream", "probeable", "playable", "inventory")):
            return ErrorCode.OUTPUT_VALIDATION_FAILED
        if "ffmpeg" in detail:
            return ErrorCode.FFMPEG_FAILED
        return ErrorCode.OUTPUT_VALIDATION_FAILED
    if isinstance(error, (ValueError, KeyError)):
        return ErrorCode.SOURCE_MATCH_FAILED
    return ErrorCode.UNCLASSIFIED_FAILURE
