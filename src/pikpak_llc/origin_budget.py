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
    values = (
        origin_total,
        source_duration,
        selected_duration,
        headroom,
        rounding,
        confirmation_ratio,
    )
    if any(float(value) <= 0 for value in values) or seek_overhead < 0:
        raise ValueError("Origin budget inputs must be positive")
    if confirmation_ratio >= 1.0:
        raise ValueError("Confirmation ratio must be less than 1.0")

    estimated = int(origin_total * selected_duration / source_duration)
    hard_cap = origin_total * confirmation_ratio
    if estimated >= hard_cap:
        raise BudgetConfirmationRequired(
            "Estimated Origin fuse requires explicit high-budget confirmation"
        )

    raw = estimated * headroom + seek_overhead
    desired = math.ceil(raw / rounding) * rounding
    if desired > hard_cap:
        floored_cap = int(math.floor(hard_cap / rounding) * rounding)
        maximum = floored_cap if floored_cap >= estimated else int(hard_cap)
    else:
        maximum = int(desired)

    return OriginBudget(estimated, maximum)
