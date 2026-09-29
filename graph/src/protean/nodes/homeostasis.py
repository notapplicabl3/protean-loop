"""Homeostasis — hypothalamus + insula. It measures, and it raises the one stop it is allowed.

`the build specification (not in this mirror)` § Deliverable 3's `stopped` terminal ("homeostasis's
contractual stop, including the tick ceiling from its weights"), § Deliverable 2's
`HomeostasisReport` row, and `brain/nodes/homeostasis/NODE.md`.

**Pure, like every node**: `HomeostasisInput` in, `HomeostasisReport` out, no file opened and
no persistent effect. Every ceiling arrives on `weights`, which the runtime projected from
`brain/nodes/homeostasis/weights.yaml`, so this module names no number.

From build A.1.i a tick may hold a bounded wave of tier-three processes. This module gains no
counter and no ceiling for them: every spawn is a call the journal keys and the landed per-type
counters already count, and the wave's width and dollar sum are refused before the first spawn by
the spawn desk, never here (`the build specification (not in this mirror)` § Deliverable 5).

**`stop` is inhibition, not advice**, and it is one of the build's only two contractual
inhibitions. It is still committed at the boundary like any other terminal: crossing a ceiling
does not shorten the tick, it sets a flag the runtime commits after the cycle finishes.

**Build A.1 measures a tick that may hold several calls** (`the build specification (not in this mirror)`
§ Deliverable 7, route R17). A tick is no longer one seat call: every outer node may think,
escalate and delegate, and the manager dispatches a wave — and the counters see **every one of
them**, because the cost is counted **per call**: each call's spend accumulates on the one
`spend_tokens()` path (cache reads excluded, exactly as before), and the tick's per-call and
per-type counters are derived from the journal's own call keys. Nothing here changed to make
that true: the ceilings, the `budget` narrowing rule and the arithmetic below are untouched, and
this function is simply run **twice** in a tick — once at this node's own step and once at the
boundary, against the spend the tick accumulated — yielding **one** stop. That stop is
**contractual and still committed at the boundary**, never mid-tick; what a crossing suppresses
for the rest of the tick is the *spending*, while every remaining node still runs. A model at
this node adds nuance to the signal it reports and can neither raise the stop nor suppress it.

**A `budget` constraint narrows a ceiling; it never widens one.** The effective limit is the
lower of the weights ceiling and any budget the director set, and `ceiling_overrides` — what
`resume --extend` writes — is added to the weights ceiling before that comparison, so an extend
cannot be quietly undone by a stale budget and a budget cannot be escaped by an extend.
"""

from __future__ import annotations

from typing import Any, Mapping

from protean.state.calls import FiringDecision
from protean.state.enums import CallType, ConstraintKind, NodeName
from protean.state.inputs import HomeostasisInput
from protean.state.outputs import HomeostasisReport

#: The ceiling names shared by `homeostasis/weights.yaml` and a `budget` constraint.
CEILING_TICKS = "max_ticks"
CEILING_TOKENS = "max_tokens"
CEILING_WALL_SECONDS = "max_wall_seconds"
CEILING_ERROR_RATE = "max_error_rate"

CEILING_KEYS: tuple[str, ...] = (
    CEILING_TICKS,
    CEILING_TOKENS,
    CEILING_WALL_SECONDS,
    CEILING_ERROR_RATE,
)

#: This node's firing threshold, and the name of the check it gates
#: (`the build specification (not in this mirror)` § Deliverable 1). The key is a `weights.yaml` name like
#: every other threshold here, so *which* nodes fire is adaptation in data.
WEIGHT_FIRING = "firing_threshold"
CHECK_CEILING_PRESSURE = "ceiling_pressure"

#: This node's **think trigger** (`the build specification (not in this mirror)` § Deliverable 1, the
#: homeostasis rule): the call check below plans one think when `ceiling_pressure` is **>=** this
#: key's value. **Off is `null` or the key absent**, which is how the shipping seed carries it. The
#: key is **static** — no sleep rule names it and no learner moves it — and it sits in series
#: behind `firing_threshold`, which reads the same score.
WEIGHT_THINK_TRIGGER = "think_threshold"


def _budget_floor(constraints, key: str) -> float | None:
    """The tightest `budget` constraint on one ceiling, or `None` if none names it."""
    values = [
        float(constraint.arguments[key])
        for constraint in constraints
        if constraint.kind is ConstraintKind.BUDGET and key in constraint.arguments
    ]
    return min(values) if values else None


def effective_ceilings(payload: HomeostasisInput) -> dict[str, float]:
    """Every ceiling in force this tick: weights, plus the extend, narrowed by any budget."""
    weights: Mapping[str, Any] = payload.weights
    ceilings: dict[str, float] = {}
    for key in CEILING_KEYS:
        if key not in weights:
            continue
        ceiling = float(weights[key])
        if key == CEILING_TICKS:
            ceiling += payload.ceiling_overrides.extra_ticks
        elif key == CEILING_WALL_SECONDS:
            ceiling += payload.ceiling_overrides.extra_seconds
        budget = _budget_floor(payload.constraints, key)
        ceilings[key] = ceiling if budget is None else min(ceiling, budget)
    return ceilings


def error_rate(errors: int, ticks: int) -> float:
    """Errors per tick. A task that has run no tick has no rate rather than a division."""
    return 0.0 if ticks <= 0 else errors / ticks


def ceiling_pressure(payload: HomeostasisInput) -> float:
    """The largest fraction of any ceiling in force this task has already consumed.

    The cheap check's score, and a pure function of the same projection `run()` reads: nothing to
    say about a task with acres of headroom, everything to say about one approaching a wall. A
    ceiling of zero or less contributes nothing rather than a division — it is a stop that has
    already fired, which `run()` reports on its own account.
    """
    ceilings = effective_ceilings(payload)
    cost = payload.cost
    observed = {
        CEILING_TICKS: float(cost.ticks),
        CEILING_TOKENS: float(cost.tokens),
        CEILING_WALL_SECONDS: cost.wall_seconds,
        CEILING_ERROR_RATE: error_rate(cost.errors, cost.ticks),
    }
    pressures = [
        observed[key] / ceiling for key, ceiling in ceilings.items() if ceiling > 0
    ]
    return max(pressures) if pressures else 0.0


def firing_check(payload: HomeostasisInput) -> FiringDecision:
    """The cheap check, beside the body (§ Deliverable 1, seam contract C3).

    **What it gates here is the think call, and never the body.** Homeostasis is one of the two
    contractual inhibitions: the ceiling evaluation and the `stop` flag always run and this node
    always produces its **full** `HomeostasisReport`, so a tick that declines still commits
    `stopped` when a ceiling was crossed — only the nuance call this node may make is skipped
    (decision 14, folded: A1-5, folded: S-A16). The runtime holds that rule; this function only
    answers the question.

    It **fires when the score is ≥ its threshold**, exactly as `nodes/detectors.py` scores a trap
    scalar, so **raising** the threshold makes the node skip more (folded: S-A91).
    """
    threshold = float(payload.weights.get(WEIGHT_FIRING, 0.0))
    value = ceiling_pressure(payload)
    return FiringDecision(
        tick=payload.tick,
        node=NodeName.HOMEOSTASIS,
        check=CHECK_CEILING_PRESSURE,
        key=WEIGHT_FIRING,
        value=value,
        threshold=threshold,
        fired=value >= threshold,
    )


def call_check(payload: HomeostasisInput) -> tuple[CallType, ...]:
    """The call check, beside the cheap check (build A.2.i, § Deliverable 1).

    **It decides that this node thinks, and never makes the call.** The answer is the tuple of
    call types the node plans this tick — one `think` when its trigger key is on and
    `ceiling_pressure` is **>= that key's value**, the firing checks' own sense; nothing when the
    key is off (`null` or absent) or the pressure is below it. The runtime asks only when
    `firing_check` fired, so the two gates sit in series over the one score and the larger
    threshold wins. Whether the key's value is a legal one is the policy's refusal at task start,
    never this function's.
    """
    trigger = payload.weights.get(WEIGHT_THINK_TRIGGER)
    if trigger is None:
        return ()
    return (CallType.THINK,) if ceiling_pressure(payload) >= float(trigger) else ()


def run(payload: HomeostasisInput) -> HomeostasisReport:
    """Measure the task's spend, report the ceilings in force, and stop when one is crossed."""
    ceilings = effective_ceilings(payload)
    cost = payload.cost
    rate = error_rate(cost.errors, cost.ticks)

    crossed: list[str] = []
    observed = {
        CEILING_TICKS: float(cost.ticks),
        CEILING_TOKENS: float(cost.tokens),
        CEILING_WALL_SECONDS: cost.wall_seconds,
        CEILING_ERROR_RATE: rate,
    }
    for key, ceiling in ceilings.items():
        if observed[key] >= ceiling:
            crossed.append(key)

    return HomeostasisReport(
        tick=payload.tick,
        tokens=cost.tokens,
        wall_seconds=cost.wall_seconds,
        error_rate=rate,
        ticks=cost.ticks,
        ceilings=ceilings,
        stop=bool(crossed),
        stop_reason=(
            None
            if not crossed
            else "ceiling crossed: " + ", ".join(f"{k}={observed[k]}>={ceilings[k]}" for k in crossed)
        ),
    )
