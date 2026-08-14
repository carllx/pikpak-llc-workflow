"""Automatic hard-fuse estimation for selected Origin segments."""

import math
from dataclasses import dataclass


class BudgetConfirmationRequired(RuntimeError):
    """Raised when partial extraction would approach a full Origin transfer."""


@dataclass(frozen=True)
class OriginBudget:
    estimated_selected_bytes: int
    max_origin_bytes: int
    requires_confirmation: bool = False


def estimate_origin_budget(
    origin_total,
    source_duration,
    selected_duration,
    headroom=2.0,
    seek_overhead=128 * 1024 * 1024,
    rounding=16 * 1024 * 1024,
    confirmation_ratio=0.8,
):
    """Return a rounded hard fuse or fail when it loses partial-transfer value."""
    values = (origin_total, source_duration, selected_duration, headroom, rounding)
    if any(float(value) <= 0 for value in values) or seek_overhead < 0:
        raise ValueError("Origin budget inputs must be positive")
    estimated = int(origin_total * selected_duration / source_duration)
    raw = estimated * headroom + seek_overhead
    maximum = int(math.ceil(raw / rounding) * rounding)
    if maximum >= origin_total * confirmation_ratio:
        raise BudgetConfirmationRequired(
            "Estimated Origin fuse requires explicit high-budget confirmation"
        )
    return OriginBudget(estimated, maximum)
