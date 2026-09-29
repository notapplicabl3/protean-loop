"""G8 — homeostasis sees every call, and a multi-call tick is bounded at the boundary.

`the build specification (not in this mirror)` § Deliverable 7 (the measured under-count, the one spend
path, the derived counters, the two inhibitions' mid-tick effects, and what in-tick suppression
cannot do), § Directional decisions 13 and 14, § Rulings 6, § Resolutions A1-4.

**Measured before it was changed.** The built arithmetic initialised `tokens_this_tick` to zero,
incremented it **once** inside the seat branch and added it at the boundary, so a tick holding N
calls under-counted by N−1. Against `fixtures/calls/four_cold_calls.yaml` that was a recorded
110 against a true 192 on the five-call tick, and a recorded **0** against a true 82 on the
four-call one. Those two numbers are the baseline this module is read against; they are what
`test_the_tick_cost_is_the_sum_of_every_call_in_the_tick` fails by if the accumulation ever
moves back inside the seat branch.

**The counters are derived, never tallied.** Calls per type and wave members are read off the
journal's own call keys, so the runtime holds one account of what a tick called rather than two
that can disagree.

**Zero model calls.** Every answer is `fixtures/calls/*.yaml` through order W2's scripted
transport; the delegate and dispatch answers have no process behind them, and no fixture here
creates a tier-three process at all (row G12). The receipt for that claim is the recording
shim's log at zero bytes across this module, captured from the command line.

**What this module does not assert.** No wave width is bounded, stated or implied — that is
build A.1.i's (§ Out of scope), and in this battery every return is scripted, so no member is
ever *away* for suppression to fail to recall. The firing checks that decide whether a node runs
at all are order W6's.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from protean import config
from protean.runtime import cycle as cycle_module
from protean.runtime.cycle import run_tick
from protean.runtime.engine import build_context
from protean.state.enums import CallType, NodeName, SelectionDecision, TerminalState, Tier
from protean.state.seat_calls import cache_reads, spend_tokens
from tests.runtime import stubs
from tests.runtime.conftest import REPO_ROOT, call_entries_of

GOAL = "drop the table the goal names"

#: `fixtures/calls/four_cold_calls.yaml`'s declared counters, as spend: a think is
#: 7 + 11 + 3 and an escalate is 13 + 2 + 5, with `cache_read_input_tokens` left out of both.
#: Mirrored here so the expectation is hand-computed rather than read back off the run, and
#: asserted against the fixture's own envelopes below so the mirror cannot drift.
THINK_SPEND = 21
ESCALATE_SPEND = 20
#: The seat call of the opening tick: 40 + 60 + 10.
MANAGER_SPEND = 110
#: The measured tick's four calls — think, think, escalate, escalate.
FOUR_COLD_SPEND = 2 * THINK_SPEND + 2 * ESCALATE_SPEND

#: `fixtures/calls/ceiling_crossing.yaml`: four calls, none of which crosses anything alone.
CHEAP_THINK_SPEND = 6
CHEAP_ESCALATE_SPEND = 8
FOUR_CHEAP_SPEND = 2 * CHEAP_THINK_SPEND + 2 * CHEAP_ESCALATE_SPEND


def journal_counters(context, tick: int) -> dict[str, int]:
    """The tick's per-type counters, read straight off the journal file on disk."""
    counters: dict[str, int] = {}
    for entry in call_entries_of(context, tick):
        counters[str(entry.tier)] = counters.get(str(entry.tier), 0) + 1
    return counters


@pytest.fixture()
def ceiling_readings(monkeypatch):
    """Every reading homeostasis's ceiling function took, in the order it took them.

    **One function, reached two ways, so the shim is installed at both** — the registry the
    node's own step dispatches through, and the module the boundary reads directly because a
    call through the registry would be a seventh node step in contract 5's recorded sequence.
    That the two are the same callable is asserted here rather than assumed, so "run twice"
    cannot quietly become two ceiling arithmetics.

    What is recorded is the cost *as read*: `HomeostasisInput.cost` is the live counter object,
    so a payload kept for later would show the boundary's number at both sites.
    """
    readings: list[int] = []
    real = cycle_module.NODES[str(NodeName.HOMEOSTASIS)]
    assert cycle_module.homeostasis_node.run is real, "the boundary reads the node's own function"

    def recording(payload):
        readings.append(payload.cost.tokens)
        return real(payload)

    monkeypatch.setattr(
        cycle_module,
        "NODES",
        {**cycle_module.NODES, str(NodeName.HOMEOSTASIS): recording},
    )
    monkeypatch.setattr(cycle_module.homeostasis_node, "run", recording)
    return readings


@pytest.fixture(scope="module")
def four_cold(tmp_path_factory):
    """Ticks 1 and 2 of `four_cold_calls.yaml`, run once and read by every consumer.

    The tick cost, the spend path over the journalled envelopes, the cache reads and the
    per-type counters are four readings of the *same* two passes — the opening tick whose five
    calls include the seat's, and the vetoed tick whose four are the `calls:` plan's alone — and
    none of them writes into the root or makes a further call. Returns `(context, state, first,
    second, opening_cost)`, where `opening_cost` is `state.cost.tokens` as it stood between the
    two passes. A test that needs the seat's own record at the mid-point, or a different
    fixture, drives its own pair.
    """
    base = tmp_path_factory.mktemp("four_cold")
    brain = stubs.seed_brain(REPO_ROOT / "brain", base / "brain")
    workspace = base / "workspace"
    workspace.mkdir()
    context, state, _port, _seat = stubs.open_task(
        brain, workspace, "four_cold_calls.yaml", "task-cost", goal=GOAL
    )
    state.tick += 1
    first = run_tick(context, state)
    opening_cost = state.cost.tokens
    state.tick += 1
    second = run_tick(context, state)
    return context, state, first, second, opening_cost


# --------------------------------------------------------------------------------------
# The cost: every call in the tick, on the one spend path, cache reads excluded
# --------------------------------------------------------------------------------------


def test_the_tick_cost_is_the_sum_of_every_call_in_the_tick(four_cold) -> None:
    """§ Deliverable 7's change, against its own measurement.

    Tick 1 makes five calls — four the `calls:` plan names and the seat's — and tick 2 makes the
    four alone, because the unit the manager minted is irreversible and the gate vetoes it. The
    landed arithmetic recorded 110 and 0 for those two ticks; the sums are 192 and 82.
    """
    context, state, first, second, opening_cost = four_cold

    assert state.latest.basal_ganglia.decision is SelectionDecision.NO_GO
    assert second.seat_skipped is True, "the vetoed tick's calls are exactly the planned four"
    assert [str(entry.tier) for entry in call_entries_of(context, 2)] == [
        str(CallType.THINK),
        str(CallType.THINK),
        str(CallType.ESCALATE),
        str(CallType.ESCALATE),
    ]

    assert opening_cost == MANAGER_SPEND + FOUR_COLD_SPEND == 192
    assert first.tokens == 192, "five calls, not the seat's one: the landed sum was 110"
    assert second.tokens == FOUR_COLD_SPEND == 82, "the landed sum for this tick was 0"
    assert state.cost.tokens - opening_cost == FOUR_COLD_SPEND
    assert state.cost.tokens == first.tokens + second.tokens


def test_the_sum_is_the_one_spend_path_over_the_journalled_envelopes(four_cold) -> None:
    """The hand-computed sum and `spend_tokens()` over the tick's own envelopes agree."""
    context, _state, _first, result, _opening = four_cold

    envelopes = [entry.envelope for entry in call_entries_of(context, 2)]
    assert all(envelope is not None for envelope in envelopes)
    assert sum(spend_tokens(envelope.usage) for envelope in envelopes) == result.tokens
    assert [spend_tokens(envelope.usage) for envelope in envelopes] == [
        THINK_SPEND,
        THINK_SPEND,
        ESCALATE_SPEND,
        ESCALATE_SPEND,
    ]


def test_cache_reads_are_recorded_and_are_not_spend(four_cold) -> None:
    """Build 2's rule, unchanged by the multiplication of callers (folded: S-19)."""
    context, _state, _first, result, _opening = four_cold

    envelopes = [entry.envelope for entry in call_entries_of(context, 2)]
    reads = sum(cache_reads(envelope.usage) for envelope in envelopes)
    assert reads == 28_000, "the reads are on the envelopes"
    assert result.tokens == FOUR_COLD_SPEND, "and not one of them is in the tick's spend"


# --------------------------------------------------------------------------------------
# The counters: derived from the journal's call keys, never tallied beside them
# --------------------------------------------------------------------------------------


def test_the_per_type_counters_are_the_journals_own_call_keys(four_cold) -> None:
    context, _state, first, second, _opening = four_cold

    assert dict(first.calls_by_type) == journal_counters(context, 1)
    assert dict(first.calls_by_type) == {
        str(CallType.THINK): 2,
        str(CallType.ESCALATE): 2,
        str(Tier.MANAGER): 1,
    }
    assert dict(second.calls_by_type) == journal_counters(context, 2)
    assert dict(second.calls_by_type) == {
        str(CallType.THINK): 2,
        str(CallType.ESCALATE): 2,
    }
    assert (first.wave_members, second.wave_members) == (0, 0), "no wave on either tick"


def test_the_counters_count_a_waves_members_under_the_waves_one_call(brain, workspace) -> None:
    """Non-vacuity: a tick that dispatches counts its members off the same `member#` keys."""
    context, state, _port, _seat = stubs.open_task(
        brain, workspace, "dispatch_wave.yaml", "task-wave", goal=GOAL
    )
    state.tick += 1
    run_tick(context, state)
    state.tick += 1
    result = run_tick(context, state)

    assert dict(result.calls_by_type) == journal_counters(context, 2)
    assert dict(result.calls_by_type) == {str(Tier.MANAGER): 1, str(CallType.DISPATCH): 2}
    assert result.wave_members == 2 == len(result.wave)


# --------------------------------------------------------------------------------------
# Four session-less calls are four cold calls
# --------------------------------------------------------------------------------------


def test_the_four_calls_are_four_cold_sessions_and_none_is_checkpointed(
    brain, workspace
) -> None:
    """§ Deliverable 2 (folded: S-A31) — a fresh `--session-id` per invocation, discarded.

    It is what makes the tick's arithmetic the plain sum of its calls: four cold calls share no
    cache, so there is no cross-call read discount to assume.
    """
    context, state, _port, seat = stubs.open_task(
        brain, workspace, "four_cold_calls.yaml", "task-cold", goal=GOAL
    )
    state.tick += 1
    run_tick(context, state)
    before = len(seat.calls)
    state.tick += 1
    run_tick(context, state)

    handles = [handle for _addressee, handle in seat.calls[before:]]
    assert len(handles) == 4
    assert len(set(handles)) == 4, "minted per invocation, never reused"
    assert set(state.seat_sessions) <= set(config.TIERS), "the book is keyed by tier"
    assert not set(handles) & set(state.seat_sessions.values()), "none is checkpointed"


# --------------------------------------------------------------------------------------
# The ceiling: run twice in the tick, one stop, committed at the boundary
# --------------------------------------------------------------------------------------


def crossing_task(brain: Path, workspace: Path, ceiling_readings):
    """Run the opening tick, then set a ceiling the *next* tick's four cheap calls cross.

    The ceiling is written between the two ticks and the context rebuilt, because the boundary
    loader reads a node's weights when the task's folders are opened. It is set one token below
    what the tick will have spent by its boundary, so the first reading of the tick is under it
    and the second is over: the crossing belongs to the tick's own calls and to nothing else.
    """
    context, state, port, seat = stubs.open_task(
        brain, workspace, "ceiling_crossing.yaml", "task-ceiling", goal=GOAL
    )
    state.tick += 1
    run_tick(context, state)
    opening = state.cost.tokens

    stubs.set_weight(brain, "homeostasis", max_tokens=opening + FOUR_CHEAP_SPEND - 1)
    context = build_context(
        brain, "task-ceiling", context.layer, workspace_path=str(workspace)
    )
    return context, state, port, seat, opening


def test_the_ceiling_runs_twice_in_the_tick_and_yields_exactly_one_stop(
    brain, workspace, ceiling_readings
) -> None:
    """§ Deliverable 7's first inhibition bullet, and row G8's "exactly one stop"."""
    context, state, port, _seat, opening = crossing_task(brain, workspace, ceiling_readings)
    before = len(ceiling_readings)

    state.tick += 1
    result = run_tick(context, state)

    assert ceiling_readings[before:] == [opening, opening + FOUR_CHEAP_SPEND], (
        "twice in the tick: the node's own step against the cost it opened on, and the "
        "boundary against the spend the tick accumulated"
    )
    assert state.latest.homeostasis.stop is False, "the step could not see what had not happened"
    assert result.committed_terminal is TerminalState.STOPPED
    assert TerminalState.STOPPED not in result.losing_terminals, "one stop, not two"
    assert result.receipt.checkpoint.state.terminal is TerminalState.STOPPED
    assert result.receipt.checkpoint_is_last(), "committed at the boundary and nowhere else"
    assert list(result.order) == list(config.NODE_ORDER), "every node after homeostasis ran"
    assert port.addressees[-4:] == ["think", "think", "escalate", "escalate"], (
        "the four cheap calls were made: the crossing is theirs"
    )


def test_a_crossed_ceiling_suppresses_every_further_call_and_the_nodes_still_run(
    brain, workspace, ceiling_readings
) -> None:
    """§ Deliverable 7's second bullet: the spending is suppressed, the pass is not.

    The tick after the crossing plans the same four calls and issues none of them, while all six
    nodes run and the tick commits. No call sits on homeostasis in this fixture, so "after the
    crossing" is the whole tick rather than the part of it that follows the node's own step.

    This also covers the stub layer's skip: `test_seat_skip.py`'s crossed-ceiling test (removed)
    drove the same `max_ticks` ceiling through a stub seat and asserted the same stop flag, empty
    call list, full node pass and `STOPPED` commit at the boundary.
    """
    context, state, port, _seat, _opening = crossing_task(brain, workspace, ceiling_readings)
    state.tick += 1
    run_tick(context, state)

    made_before_the_crossing = list(port.addressees)
    state.tick += 1
    result = run_tick(context, state)

    assert state.latest.homeostasis.stop is True, "this tick opened over the ceiling"
    assert port.addressees == made_before_the_crossing, "no further model call was issued"
    assert result.seat_skipped is True, "the seat was skipped, not merely uncalled (carried from test_seat_skip.py)"
    assert call_entries_of(context, state.tick) == [], "no call, so no call entry"
    assert list(result.order) == list(config.NODE_ORDER), "and every node still ran"
    assert result.journal_entries == len(config.NODE_ORDER)
    assert result.tokens == 0
    assert dict(result.calls_by_type) == {}
    assert result.committed_terminal is TerminalState.STOPPED
    assert result.receipt.checkpoint_is_last()
