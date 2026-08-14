import pytest

from pikpak_llc.origin_budget import BudgetConfirmationRequired, estimate_origin_budget


def test_origin_budget_uses_selected_average_with_headroom_and_seek_overhead():
    budget = estimate_origin_budget(
        origin_total=4_000_000_000,
        source_duration=2_000,
        selected_duration=100,
        headroom=2.0,
        seek_overhead=128 * 1024 * 1024,
        rounding=16 * 1024 * 1024,
    )

    assert budget.estimated_selected_bytes == 200_000_000
    assert budget.max_origin_bytes == 536_870_912
    assert budget.requires_confirmation is False


def test_origin_budget_requires_confirmation_when_fuse_nears_full_origin():
    with pytest.raises(BudgetConfirmationRequired):
        estimate_origin_budget(
            origin_total=1_000_000_000,
            source_duration=100,
            selected_duration=90,
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"origin_total": 0, "source_duration": 1, "selected_duration": 1},
        {"origin_total": 1, "source_duration": 0, "selected_duration": 1},
        {"origin_total": 1, "source_duration": 1, "selected_duration": 0},
    ],
)
def test_origin_budget_rejects_non_positive_inputs(kwargs):
    with pytest.raises(ValueError):
        estimate_origin_budget(**kwargs)
