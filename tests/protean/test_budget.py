"""Budget: caps from config, the stop test at >=, and dollars from receipts only."""

from __future__ import annotations

import json

import pytest

from protean.budget import Caps, cost_of, load_caps, stop_reason
from protean.state import Root, Task, from_json, to_json

CONFIG = {
    "max_usd": 10.0, "max_ticks": 30, "director_call_usd": 2.0, "worker_call_usd": 4.0,
    "director_wall_seconds": 300, "worker_wall_seconds": 900, "max_attempts_per_unit": 2, "max_replans": 3,
}


def _load(root: Root, data: object) -> Caps:
    root.path.mkdir(parents=True, exist_ok=True)
    root.config_file.write_text(json.dumps(data))
    return load_caps(root)


def test_config_loading_defaults(root: Root):
    assert load_caps(root) == Caps()
    assert _load(root, CONFIG) == Caps()
    caps = _load(root, {"max_usd": 5, "max_ticks": 12})
    assert (caps.max_usd, caps.max_ticks, caps.worker_call_usd) == (5, 12, 4.0)


@pytest.mark.parametrize(
    "data", [{"max_usd": 10.0, "max_dollars": 5}, {"max_ticks": 3.5}, {"max_usd": "10"}, {"max_usd": True}, [1]]
)
def test_a_bad_config_raises(root: Root, data: object):
    with pytest.raises(ValueError):
        _load(root, data)


def test_legacy_director_limits_are_preserved(root: Root):
    caps = _load(root, {"manager_call_usd": 1.25, "manager_wall_seconds": 42})
    assert (caps.director_call_usd, caps.director_wall_seconds) == (1.25, 42)
    with pytest.raises(ValueError, match="conflicting keys"):
        _load(root, {"manager_call_usd": 1.25, "director_call_usd": 2.0})


def test_stop_reason_crosses_at_greater_or_equal():
    assert stop_reason(Task("t", "g", "/w", tick=29, cost_usd=9.99), Caps()) is None
    assert stop_reason(Task("t", "g", "/w", cost_usd=10.0), Caps()) == "max_usd: 10.00 >= 10.0"
    assert stop_reason(Task("t", "g", "/w", cost_usd=10.36), Caps()) == "max_usd: 10.36 >= 10.0"
    assert stop_reason(Task("t", "g", "/w", tick=30), Caps()) == "max_ticks: 30 >= 30"
    assert stop_reason(Task("t", "g", "/w", tick=3), Caps(max_ticks=3)) == "max_ticks: 3 >= 3"


def test_task_extras_default_to_zero_and_round_trip():
    task = Task("t", "g", "/w")
    assert (task.extra_usd, task.extra_ticks) == (0.0, 0)
    task.extra_usd, task.extra_ticks = 2.5, 4
    assert from_json(to_json(task)) == task
    older = json.loads(to_json(Task("t", "g", "/w")))
    del older["extra_usd"], older["extra_ticks"]
    assert from_json(json.dumps(older)) == Task("t", "g", "/w")


def test_stop_reason_widens_by_the_task_extras():
    assert stop_reason(Task("t", "g", "/w", cost_usd=10.36, extra_usd=5.0), Caps()) is None
    assert stop_reason(Task("t", "g", "/w", cost_usd=15.0, extra_usd=5.0), Caps()) == "max_usd: 15.00 >= 15.0"
    assert stop_reason(Task("t", "g", "/w", tick=30, extra_ticks=5), Caps()) is None
    assert stop_reason(Task("t", "g", "/w", tick=35, extra_ticks=5), Caps()) == "max_ticks: 35 >= 35"


def test_cost_of_a_capped_call_is_its_receipt_not_its_tokens():
    capped = {
        "is_error": True,
        "total_cost_usd": 2.51,
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "modelUsage": {"claude-opus-5": {"inputTokens": 0, "outputTokens": 0, "costUSD": 2.51}},
    }
    assert cost_of(capped) == 2.51


def test_cost_of_falls_back_to_the_model_usage_sum():
    receipt = {"modelUsage": {"a": {"costUSD": 1.25}, "b": {"costUSD": 0.5}, "c": {"inputTokens": 900}}}
    assert cost_of(receipt) == 1.75
    assert cost_of({"total_cost_usd": None, **receipt}) == 1.75


@pytest.mark.parametrize("total", [float("nan"), float("inf"), -1.0, True, "2.51"])
def test_cost_of_ignores_a_total_that_is_not_a_real_amount(total: object):
    assert cost_of({"total_cost_usd": total, "modelUsage": {"m": {"costUSD": 0.25}}}) == 0.25


def test_cost_of_with_no_dollar_figure_is_zero_never_estimated():
    assert cost_of({}) == 0.0
    assert cost_of({"usage": {"input_tokens": 50_000, "output_tokens": 8_000}}) == 0.0
    assert cost_of({"modelUsage": "garbled"}) == 0.0
