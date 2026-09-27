"""Ceilings and spend: the caps, the stop test, and the dollar cost of one call's receipt."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, fields

from protean.state import Root, Task


@dataclass
class Caps:
    """Per-task ceilings and per-call limits. `max_usd` is the task's hard dollar cap."""

    max_usd: float = 10.0
    max_ticks: int = 30
    director_call_usd: float = 2.0
    worker_call_usd: float = 4.0
    director_wall_seconds: int = 300
    worker_wall_seconds: int = 900
    max_attempts_per_unit: int = 2
    max_replans: int = 3


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def load_caps(root: Root) -> Caps:
    """Caps from `config.json`; a missing file or key keeps the default, an unknown key raises."""
    try:
        data = json.loads(root.config_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Caps()
    if not isinstance(data, dict):
        raise ValueError(f"{root.config_file}: expected a JSON object")
    for suffix in ("call_usd", "wall_seconds"):
        old, new = f"manager_{suffix}", f"director_{suffix}"
        if old in data:  # Accept existing custom configs without changing their limits.
            if new in data and data[new] != data[old]:
                raise ValueError(f"{root.config_file}: conflicting keys {old} and {new}")
            data[new] = data.pop(old)
    known = {f.name: f for f in fields(Caps)}
    unknown = sorted(data.keys() - known.keys())
    if unknown:
        raise ValueError(f"{root.config_file}: unknown key(s) {', '.join(unknown)}")
    for name, value in data.items():
        wants_int = isinstance(known[name].default, int)
        if not _is_number(value) or (wants_int and not isinstance(value, int)):
            kind = "an integer" if wants_int else "a number"
            raise ValueError(f"{root.config_file}: {name} must be {kind}, got {value!r}")
    return Caps(**data)


def stop_reason(task: Task, caps: Caps) -> str | None:
    """The ceiling the task has reached, named with its numbers, or None while under every one."""
    max_usd, max_ticks = caps.max_usd + task.extra_usd, caps.max_ticks + task.extra_ticks
    if task.cost_usd >= max_usd:
        return f"max_usd: {task.cost_usd:.2f} >= {max_usd}"
    if task.tick >= max_ticks:
        return f"max_ticks: {task.tick} >= {max_ticks}"
    return None


def _dollars(value: object) -> float | None:
    """A usable dollar amount: a finite, non-negative number that is not a bool."""
    if _is_number(value) and math.isfinite(value) and value >= 0:
        return float(value)
    return None


def cost_of(receipt: dict) -> float:
    """Dollars one call spent: `total_cost_usd`, else the sum of `modelUsage[*].costUSD`, else 0.

    Capped calls report their dollars but zero tokens, so cost is never estimated from tokens.
    """
    total = _dollars(receipt.get("total_cost_usd"))
    if total is not None:
        return total
    usage = receipt.get("modelUsage")
    if not isinstance(usage, dict):
        return 0.0
    costs = [_dollars(m.get("costUSD")) for m in usage.values() if isinstance(m, dict)]
    return float(sum(c for c in costs if c is not None))
