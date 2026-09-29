"""The responder: keyed by the request, never by the call order, and never by a number.

`the build specification (not in this mirror)` § Deliverable 6 → *Seat scripts are request-keyed responders,
never turn lists* (folded: A1-10). The claim these tests make is a negative one — that nothing
about the *sequence* of calls changes the answer — so the shape of most of them is: ask twice,
ask out of order, and get the same answer both times.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from protean.cortex.scripts import (
    CONDITION_KEYS,
    STAMPED_FIELD,
    RequestFacts,
    ResponseCondition,
    SeatScriptError,
    facts_of,
    goal_digest_of,
    parse_script,
    substitute,
)
from protean.runtime.seat import SeatSelection, decode_seat_result
from protean.state.enums import CallType, Escalation, GoalStatus, Tier, TrapDetector
from protean.state.outputs import AdmittedContext
from protean.state.primitives import GoalItem, TrapScalar, WorkUnit
from protean.state.seats import WaveMember
from protean.state.workspace import (
    DirectorRequest,
    ManagerRequest,
    Workspace,
)
from tests.cortex.conftest import (
    manager_request,
    one_goal_workspace,
    trap_scalar,
    wave_member,
)


def _workspace(tick: int = 4) -> Workspace:
    return one_goal_workspace("task-s", tick=tick)


def _planner_request(**overrides) -> ManagerRequest:
    named = overrides.pop("workspace", None)
    return manager_request(_workspace() if named is None else named, **overrides)


def _wave_member(unit_id: str = "u-stuck-1") -> WaveMember:
    return wave_member(unit_id=unit_id)


def _scalar(detector: TrapDetector, unit_id: str = "u-stuck-1") -> TrapScalar:
    return trap_scalar(detector, unit_id=unit_id)


# --------------------------------------------------------------------------------------
# The format the loader accepts, and what it refuses
# --------------------------------------------------------------------------------------


def test_every_shipped_script_loads_and_names_only_tiers_that_exist(script_for):
    for stem in ("plan_and_execute", "stuck_ladder", "asks_a_question"):
        script = script_for(stem)
        assert script.responses, f"{stem} carries responses"
        assert {response.tier for response in script.responses} <= set(Tier) | set(CallType)


def test_a_response_that_writes_its_own_tick_is_refused_at_load():
    """The responder stamps it from the request, so no fixture may carry a turn number."""
    with pytest.raises(SeatScriptError, match=STAMPED_FIELD):
        parse_script(
            {"responses": [{"tier": "manager", "result": {STAMPED_FIELD: 3}}]},
            name="bad",
        )


def test_a_condition_key_that_is_not_a_request_field_is_refused():
    with pytest.raises(SeatScriptError, match="request fields"):
        parse_script(
            {"responses": [{"tier": "manager", "when": {"call": 2}, "result": {}}]},
            name="bad",
        )


def test_a_response_with_no_result_mapping_is_refused():
    with pytest.raises(SeatScriptError, match="result"):
        parse_script({"responses": [{"tier": "manager"}]}, name="bad")


def test_a_script_with_no_responses_list_is_refused():
    with pytest.raises(SeatScriptError, match="responses"):
        parse_script({"name": "bad"}, name="bad")


# --------------------------------------------------------------------------------------
# Matching is on the request, and only on the request
# --------------------------------------------------------------------------------------


def test_an_empty_condition_matches_every_request_for_its_tier():
    condition = ResponseCondition()
    assert condition.matches(RequestFacts(tier=CallType.DISPATCH, tick=1))
    assert condition.matches(
        RequestFacts(tier=Tier.MANAGER, tick=9, escalation=Escalation.VETO)
    )


def test_a_condition_matches_on_the_unit_id_the_escalation_and_the_trap():
    facts = RequestFacts(
        tier=Tier.MANAGER,
        tick=5,
        unit_id="u-stuck-1",
        escalation=Escalation.TRAP_SIGNAL,
        traps=frozenset({"dislodging"}),
    )
    assert ResponseCondition(unit_id="u-stuck-1").matches(facts)
    assert ResponseCondition(escalation=Escalation.TRAP_SIGNAL).matches(facts)
    assert ResponseCondition(trap=TrapDetector.DISLODGING).matches(facts)
    assert not ResponseCondition(unit_id="u-other").matches(facts)
    assert not ResponseCondition(escalation=Escalation.VETO).matches(facts)
    assert not ResponseCondition(trap=TrapDetector.FORMING).matches(facts)


def test_the_planner_reads_its_escalation_and_evidence_off_its_own_request():
    request = _planner_request(
        escalation=Escalation.TRAP_SIGNAL,
        unit_id="u-stuck-1",
        trap_evidence=[_scalar(TrapDetector.DISLODGING)],
    )
    facts = facts_of(Tier.MANAGER, request)
    assert facts.escalation is Escalation.TRAP_SIGNAL
    assert facts.unit_id == "u-stuck-1"
    assert facts.traps == frozenset({"dislodging"})
    assert facts.goal_id == "task-s-g1"


def test_the_director_reads_its_escalation_off_the_selection_because_its_request_has_none():
    """`DirectorRequest` carries only the compressed workspace; the reason rides the selection."""
    request = DirectorRequest(workspace=_workspace())
    assert facts_of(Tier.DIRECTOR, request).escalation is None
    selected = facts_of(
        Tier.DIRECTOR,
        request,
        SeatSelection(tier=Tier.DIRECTOR, escalation=Escalation.REPLAN_EXHAUSTED),
    )
    assert selected.escalation is Escalation.REPLAN_EXHAUSTED


def test_a_dispatch_member_is_answered_on_its_own_facts_and_carries_no_path():
    """Re-based by build A.1 order W8: the member request **is** the `WaveMember`.

    § Deliverable 3's model table makes it the dispatch member's request model, so the scripted
    responder reads its own facts off it — the **kind**, which is the one thing that tells two
    members of one wave apart, and the unit the wave is about. It still carries no path and no
    tick: the workspace is the runtime's to fill and the decoder stamps the tick.

    Folded: S-A68 — a `WaveMember` carries no goal digest because it carries no workspace. The
    acting tier took no procedure in build 3 because its request carried no workspace text to
    digest (folded: S-4); A.1 removes the request model altogether, so the property holds a
    fortiori — the field-set equality below leaves a member no field a digest could come from.
    """
    member = _wave_member()
    assert sorted(type(member).model_fields) == ["admitted_ref", "kind", "unit_id"]
    facts = facts_of(CallType.DISPATCH, member)
    assert facts.tier is CallType.DISPATCH
    assert (facts.kind, facts.unit_id) == (member.kind, member.unit_id)
    assert facts.goal_digest is None, "a member carries no workspace to digest"


# --------------------------------------------------------------------------------------
# The fifth key — build 3's one addition (folded: S-3)
# --------------------------------------------------------------------------------------


def test_the_sixth_condition_key_is_the_member_s_kind_and_it_is_optional(script_for):
    """Build 3 added `goal_digest` (folded: S-3); build A.1 order W8 adds `kind`, the member
    request's own field, `None` for every request that is not a wave member — so every
    hand-authored script and every landed condition still loads unchanged."""
    assert CONDITION_KEYS == ("unit_id", "escalation", "trap", "resolved", "goal_digest", "kind")
    for stem in ("plan_and_execute", "stuck_ladder", "asks_a_question"):
        assert script_for(stem).responses, f"{stem} still loads with the widened set"
    parse_script({"responses": [{"tier": "manager", "result": {}}]}, name="empty")


def test_the_goal_digest_is_the_sha256_of_the_served_goal_s_text_not_its_id():
    """`sha256[:16]` of the TEXT — an id is minted per task and would never recur."""
    request = _planner_request()
    facts = facts_of(Tier.MANAGER, request)
    assert facts.goal_id == "task-s-g1"
    assert facts.goal_digest == goal_digest_of("reconcile")
    assert facts.goal_digest == hashlib.sha256(b"reconcile").hexdigest()[:16]
    assert facts.goal_digest != "task-s-g1"


def test_two_tasks_with_the_same_goal_text_draw_the_same_digest():
    """The whole point of the key: a repeated goal is the same condition in a different task."""
    first = _workspace()
    second = Workspace(
        task_id="task-other",
        tick=9,
        goals=[
            GoalItem(
                id="task-other-g1",
                text="reconcile",
                status=GoalStatus.OPEN,
                opened_at_tick=0,
                last_progress_tick=0,
            )
        ],
    )
    digests = {
        facts_of(Tier.DIRECTOR, DirectorRequest(workspace=workspace)).goal_digest
        for workspace in (first, second)
    }
    assert len(digests) == 1


def test_a_goal_digest_condition_matches_only_its_own_goal():
    facts = RequestFacts(tier=Tier.MANAGER, tick=1, goal_digest="abc123")
    assert ResponseCondition(goal_digest="abc123").matches(facts)
    assert not ResponseCondition(goal_digest="def456").matches(facts)
    assert ResponseCondition().matches(facts), "an empty condition still matches everything"


def test_a_request_with_no_open_goal_carries_no_digest():
    """No goal, no digest — and a condition binding one then matches nothing, rather than all."""
    empty = Workspace(task_id="task-s", tick=1)
    facts = facts_of(Tier.DIRECTOR, DirectorRequest(workspace=empty))
    assert facts.goal_digest is None and facts.goal_id is None
    assert not ResponseCondition(goal_digest="abc123").matches(facts)


def test_an_unrecognised_request_is_refused_rather_than_answered():
    with pytest.raises(SeatScriptError, match="unrecognised"):
        facts_of(Tier.MANAGER, object())


def test_the_first_matching_response_wins_and_the_queue_is_not_consumed(script_for):
    """Ask the same thing twice, in any order, and get the same answer — no call counter."""
    script = script_for("stuck_ladder")
    request = _planner_request(
        escalation=Escalation.TRAP_SIGNAL,
        unit_id="u-stuck-1",
        trap_evidence=[_scalar(TrapDetector.DISLODGING)],
    )
    first = script.respond(Tier.MANAGER, request)
    opening = script.respond(Tier.MANAGER, _planner_request())
    again = script.respond(Tier.MANAGER, request)
    assert first == again
    assert first != opening, "a different request draws a different response"


def test_an_unmatched_request_refuses_by_naming_what_it_was_asked(script_for):
    script = script_for("stuck_ladder")
    with pytest.raises(SeatScriptError, match="no director response matching"):
        script.respond(Tier.DIRECTOR, DirectorRequest(workspace=_workspace()))


# --------------------------------------------------------------------------------------
# Stamping and substitution
# --------------------------------------------------------------------------------------


def test_the_tick_is_stamped_from_the_request_and_never_from_the_file(script_for):
    script = script_for("stuck_ladder")
    for value in (2, 11):
        payload = script.respond(Tier.MANAGER, _planner_request(workspace=_workspace(value)))
        assert payload[STAMPED_FIELD] == value


def test_the_goal_and_unit_placeholders_are_filled_from_the_request(script_for):
    plan = script_for("stuck_ladder").respond(Tier.MANAGER, _planner_request())
    assert plan["units"][0]["goal_id"] == "task-s-g1"

    # The acting half of this claim — `$unit` filled from a dispatch member's own request — is
    # order W8's: a dispatch is not a seat call and its scripted returns arrive with the wave.


def test_substitution_reaches_nested_lists_and_mappings():
    facts = RequestFacts(tier=Tier.MANAGER, tick=1, unit_id="u-x", goal_id="g-x")
    assert substitute({"a": ["$goal", {"b": "$unit"}], "c": "plain"}, facts) == {
        "a": ["g-x", {"b": "u-x"}],
        "c": "plain",
    }


def test_a_scripted_payload_decodes_against_its_tier_s_result_model(script_for):
    """The script cannot be tidier than the contract: every response validates as its model."""
    from protean.cortex.adapters import build_envelope

    script = script_for("stuck_ladder")
    payload = script.respond(Tier.MANAGER, _planner_request())
    envelope = build_envelope(Tier.MANAGER, payload, session_id="s-1")
    decoded = decode_seat_result(Tier.MANAGER, envelope)
    assert decoded.emitter == "manager"
    assert [unit.id for unit in decoded.units] == ["u-stuck-1"]


# --------------------------------------------------------------------------------------
# M16's fixture clauses, as a property of the files rather than of a comment
# --------------------------------------------------------------------------------------


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
AUTHORED = ("seat_scripts", "scenarios")


def _authored_files() -> list[Path]:
    return sorted(
        path
        for directory in AUTHORED
        for path in (FIXTURES / directory).rglob("*.yaml")
    )


def _leaves(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _leaves(value)
    elif isinstance(node, list):
        for item in node:
            yield from _leaves(item)
    else:
        yield node


def test_no_authored_fixture_indexes_by_tick_number():
    """Not one key, one value or one raw byte of a scenario names a turn number."""
    for path in _authored_files():
        source = path.read_text(encoding="utf-8")
        assert "tick" not in source.lower(), f"{path} names a tick"
        loaded = yaml.safe_load(source)
        assert STAMPED_FIELD not in list(_leaves(loaded))


def test_no_authored_fixture_restates_a_threshold_the_weights_files_own(
    cortex_weights, monitor_weights
):
    """Scenario and runtime read the same number, so no scenario carries a copy of one."""
    owned_keys = set(cortex_weights) | set(monitor_weights)
    #: An index, an empty default, a unit step carry no threshold meaning (the exclusion
    #: `tests/nodes/test_purity.py` carries); A.1 seeds `firing_threshold` at 0.0.
    trivial = {0, 1}
    # A.2.i's trigger key ships off as `null`; skip non-numeric values as `test_purity.py` does (E33).
    owned_values = {
        float(value)
        for value in {**cortex_weights, **monitor_weights}.values()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    } - {float(t) for t in trivial}

    for path in _authored_files():
        source = path.read_text(encoding="utf-8")
        for key in owned_keys:
            assert key not in source, f"{path} names the weights key {key!r}"
        for leaf in _leaves(yaml.safe_load(source)):
            if isinstance(leaf, bool) or not isinstance(leaf, (int, float)):
                continue
            assert float(leaf) not in owned_values, f"{path} restates {leaf!r}"
