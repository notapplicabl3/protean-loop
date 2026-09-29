"""The habit matcher: pure, keyed on `goal_digest`, at most one match per tick.

`the build specification (not in this mirror)` § Deliverable 4 → *Who reads it*, § Directional decisions 13,
19, 21, § Resolutions S-3, S-4, S-18, D16-2, D16-3. Row **L7**'s read half — the boundary half
is `tests/runtime/test_habit_hits_boundary.py`.

**The subject is a file W6 actually writes.** Every procedure below is built through
`protean.state.sleep.Procedure` and dumped with `script_payload()`, the same way
`protean.sleep.habits.write_procedure()` writes one, so a change to P2's shape fails here rather
than at the wet run. Nothing hand-writes a YAML mapping the compiler does not produce.

**Purity is asserted rather than assumed**: `match()` is handed a sequence built in memory and
never a root, and the two rules the matcher enforces beside the compiler — planner and director
only, and a condition that binds `goal_digest` — each get a fixture whose habit *would* have
answered without them.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError
import yaml

from protean import config
from protean.cortex.habits import (
    ANSWERABLE_TIERS,
    HabitBook,
    LoadedProcedure,
    bound_keys,
    load_procedures,
    match,
    open_task,
    seat_models,
)
from protean.cortex.scripts import (
    STAMPED_FIELD,
    ResponseCondition,
    SeatScriptError,
    facts_of,
    goal_digest_of,
)
from protean.runtime.paths import ROOT_PROJECT_SLUG, BrainPaths
from protean.runtime.seat import SeatSelection, decode_seat_result
from protean.state.enums import CallType, Escalation, GoalStatus, Tier
from protean.state.outputs import AdmittedContext
from protean.state.primitives import GoalItem, WorkUnit
from protean.state.sleep import Procedure, ProcedureResponse
from protean.state.seats import WaveMember
from protean.state.workspace import (
    DirectorRequest,
    ManagerRequest,
    Workspace,
)
from tests.cortex.conftest import (
    director_request as build_director_request,
    manager_request,
    one_goal_workspace,
    wave_member as build_wave_member,
)

GOAL_TEXT = "reconcile the ledger and confirm it balances"
GOAL_ID = "task-h-g1"
DIGEST = goal_digest_of(GOAL_TEXT)


def workspace(tick: int = 4, text: str = GOAL_TEXT) -> Workspace:
    return one_goal_workspace("task-h", tick=tick, text=text)


def planner_request(tick: int = 4, text: str = GOAL_TEXT) -> ManagerRequest:
    return manager_request(workspace(tick, text))


def director_request(tick: int = 4) -> DirectorRequest:
    return build_director_request(workspace(tick))


def wave_member() -> WaveMember:
    return build_wave_member(unit_id="u-1")


def compiled(
    procedure_id: str = "habit-manager-" + DIGEST,
    *,
    tier: Tier = Tier.MANAGER,
    when: dict | None = None,
    result: dict | None = None,
    usage: dict | None = None,
) -> Procedure:
    """A habit in the shape `protean.sleep.habits` compiles one, provenance header and all."""
    return Procedure(
        procedure_id=procedure_id,
        name=procedure_id,
        hits_required=3,
        responses=[
            ProcedureResponse(
                tier=tier,
                when={"goal_digest": DIGEST} if when is None else when,
                result={"emitter": str(tier)} if result is None else result,
                usage=usage or {},
            )
        ],
    )


def loaded(*procedures: Procedure) -> tuple[LoadedProcedure, ...]:
    """Compiled procedures → the parsed set, through the one loader P2 is defined against."""
    return load_procedures(
        [(item.procedure_id, item.script_payload()) for item in procedures]
    )


def install(brain: BrainPaths, procedure: Procedure, *, project: str | None = None) -> Path:
    """Write one compiled habit where sleep writes it — node folder, or a project's memory."""
    directory = (
        brain.node_procedures(config.CORTEX_NODE)
        if project is None
        else brain.project_procedures(project)
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{procedure.procedure_id}.yaml"
    path.write_text(
        yaml.safe_dump(procedure.script_payload(), sort_keys=False), encoding="utf-8"
    )
    return path


# --------------------------------------------------------------------------------------
# A habit answers, and the answer is an ordinary envelope
# --------------------------------------------------------------------------------------


def test_a_procedure_bound_to_the_served_goal_answers_the_planner() -> None:
    facts = match(Tier.MANAGER, planner_request(), loaded(compiled()))
    assert facts is not None
    assert facts.procedure_id == "habit-manager-" + DIGEST
    assert facts.tier == str(Tier.MANAGER)


def test_the_answer_decodes_on_the_one_decode_seat_result_path() -> None:
    """§ Directional decisions 3: a habit hit returns through the port's own decode path."""
    facts = match(Tier.MANAGER, planner_request(tick=7), loaded(compiled()))
    assert facts is not None
    decoded = decode_seat_result(Tier.MANAGER, facts.envelope, 7)
    assert decoded.tick == 7 and str(decoded.emitter) == str(Tier.MANAGER)


def test_the_tick_is_stamped_from_the_request_and_never_from_the_file() -> None:
    for tick in (2, 9):
        facts = match(Tier.MANAGER, planner_request(tick=tick), loaded(compiled()))
        assert facts is not None
        assert facts.envelope.parsed_result()[STAMPED_FIELD] == tick


def test_the_goal_placeholder_resolves_through_the_one_substitution() -> None:
    """Ledger `D16-3`: the compiler writes `$goal`; the matcher fills it from the request."""
    habit = compiled(result={"emitter": "manager", "goals_satisfied": ["$goal"]})
    facts = match(Tier.MANAGER, planner_request(), loaded(habit))
    assert facts is not None
    assert facts.envelope.parsed_result()["goals_satisfied"] == [GOAL_ID]


def test_a_habit_costs_nothing_because_the_compiled_usage_is_empty() -> None:
    facts = match(Tier.MANAGER, planner_request(), loaded(compiled()))
    assert facts is not None
    assert facts.envelope.usage == {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
    }


def test_the_director_tier_is_answerable_too() -> None:
    habit = compiled("habit-director-" + DIGEST, tier=Tier.DIRECTOR)
    facts = match(Tier.DIRECTOR, director_request(), loaded(habit))
    assert facts is not None and facts.tier == str(Tier.DIRECTOR)


# --------------------------------------------------------------------------------------
# What does not match
# --------------------------------------------------------------------------------------


def test_a_different_goal_text_does_not_match() -> None:
    request = planner_request(text="something else entirely")
    assert match(Tier.MANAGER, request, loaded(compiled())) is None


def test_the_dispatch_addressee_takes_no_procedure() -> None:
    """Decision 21, folded: S-4, re-based by build A.1 (folded: S-A65).

    The acting tier took no procedure in build 3; A.1 deletes the tier and the property is
    stated of the **addressee** that replaced it. "In A.1 a habit answers a **seat call** and
    nothing else" — not a think, not an escalate, not a delegate, not a dispatch member — which
    is why P3 `HabitHit`'s `(task, tick, tier)` key survives a multi-call tick unwidened.
    """
    # Build 3's P2 `Procedure` is untouched by A.1, and its response is keyed by **`Tier`** —
    # so a dispatch cannot even be written down as a procedure response. That is the property
    # one step stronger than build 3's: not "takes no procedure" but "takes no expressible one".
    with pytest.raises(ValidationError):
        compiled("habit-dispatch-" + DIGEST, tier=CallType.DISPATCH, when={})

    # And the runtime side agrees, one step stronger than a refusal: a member carries no
    # workspace, so it has no `goal_digest` — the one key a compiled habit binds — and a
    # compiled response's condition can therefore never match one.
    facts = facts_of(CallType.DISPATCH, wave_member())
    assert facts.goal_digest is None
    assert not ResponseCondition(goal_digest=DIGEST).matches(facts)
    assert CallType.DISPATCH not in ANSWERABLE_TIERS
    assert tuple(ANSWERABLE_TIERS) == (Tier.DIRECTOR, Tier.MANAGER)


def test_a_response_binding_no_goal_digest_matches_nothing() -> None:
    """Ledger `D19-4`: no everything-matches habit, enforced at read time as well."""
    habit = compiled(when={})
    assert match(Tier.MANAGER, planner_request(), loaded(habit)) is None


def test_a_condition_that_binds_only_unit_id_matches_nothing() -> None:
    """`unit_id` is minted per task and never recurs — a habit keyed on it is not a habit."""
    habit = compiled(when={"unit_id": "u-1"})
    assert match(Tier.MANAGER, planner_request(), loaded(habit)) is None


def test_an_empty_procedure_set_answers_nothing() -> None:
    assert match(Tier.MANAGER, planner_request(), ()) is None


# --------------------------------------------------------------------------------------
# Precedence: lexical by `procedure_id`, first match, one per tick (ledger `D16-2`)
# --------------------------------------------------------------------------------------


def test_precedence_is_lexical_by_procedure_id_and_the_first_match_wins() -> None:
    first = compiled("habit-manager-aaaa", result={"emitter": "manager", "notes": ["a"]})
    second = compiled("habit-manager-bbbb", result={"emitter": "manager", "notes": ["b"]})
    for order in ((first, second), (second, first)):
        facts = match(Tier.MANAGER, planner_request(), loaded(*order))
        assert facts is not None
        assert facts.procedure_id == "habit-manager-aaaa"


def test_the_loader_sorts_lexically_whatever_order_it_is_handed() -> None:
    ids = [item.procedure_id for item in loaded(compiled("z-habit"), compiled("a-habit"))]
    assert ids == ["a-habit", "z-habit"]


def test_at_most_one_match_per_tick_even_with_two_matching_responses() -> None:
    habit = Procedure(
        procedure_id="habit-manager-" + DIGEST,
        name="habit-manager-" + DIGEST,
        responses=[
            ProcedureResponse(
                tier=Tier.MANAGER,
                when={"goal_digest": DIGEST},
                result={"emitter": "manager", "notes": ["first"]},
            ),
            ProcedureResponse(
                tier=Tier.MANAGER,
                when={"goal_digest": DIGEST},
                result={"emitter": "manager", "notes": ["second"]},
            ),
        ],
    )
    facts = match(Tier.MANAGER, planner_request(), loaded(habit))
    assert facts is not None
    assert facts.envelope.parsed_result()["notes"] == ["first"]


# --------------------------------------------------------------------------------------
# What the match reports back — P3's two non-envelope fields
# --------------------------------------------------------------------------------------


def test_matched_condition_carries_the_keys_the_condition_bound() -> None:
    facts = match(Tier.MANAGER, planner_request(), loaded(compiled()))
    assert facts is not None
    assert facts.matched_condition == {"goal_digest": DIGEST}


def test_matched_condition_is_derived_from_the_widened_condition_set() -> None:
    habit = compiled(when={"goal_digest": DIGEST, "escalation": "empty_unit_stack"})
    selection = SeatSelection(tier=Tier.MANAGER, escalation=Escalation.EMPTY_UNIT_STACK)
    facts = match(Tier.MANAGER, planner_request(), loaded(habit), selection)
    assert facts is not None
    assert facts.matched_condition == {
        "escalation": str(Escalation.EMPTY_UNIT_STACK),
        "goal_digest": DIGEST,
    }


def test_bound_keys_names_nothing_a_condition_left_open() -> None:
    parsed = loaded(compiled())[0].script.responses[0].when
    assert bound_keys(parsed) == {"goal_digest": DIGEST}


def test_the_avoided_model_is_carried_through_unchanged() -> None:
    facts = match(
        Tier.MANAGER, planner_request(), loaded(compiled()), avoided_model="a-model"
    )
    assert facts is not None and facts.avoided_model == "a-model"


# --------------------------------------------------------------------------------------
# Purity, and the same answer twice
# --------------------------------------------------------------------------------------


def test_matching_twice_gives_the_same_answer_and_consumes_nothing() -> None:
    procedures = loaded(compiled())
    first = match(Tier.MANAGER, planner_request(), procedures)
    second = match(Tier.MANAGER, planner_request(), procedures)
    assert first is not None and second is not None
    assert first.envelope.result == second.envelope.result
    assert len(procedures) == 1


def test_the_matcher_never_touches_the_filesystem(monkeypatch) -> None:
    """Pure, per § Deliverable 4: the set is resolved by the runtime, never by the matcher."""
    procedures = loaded(compiled())

    def _refuse(*args, **kwargs):
        raise AssertionError("the matcher opened a file")

    monkeypatch.setattr(Path, "open", _refuse)
    monkeypatch.setattr(Path, "read_text", _refuse)
    assert match(Tier.MANAGER, planner_request(), procedures) is not None


# --------------------------------------------------------------------------------------
# Task open: the two folders, the slug, and the roots that have compiled nothing
# --------------------------------------------------------------------------------------


def test_a_root_that_has_compiled_nothing_carries_no_seam(brain: Path) -> None:
    assert open_task(brain, project=ROOT_PROJECT_SLUG) is None


def test_the_node_folders_procedures_are_loaded_at_task_open(brain: Path) -> None:
    install(BrainPaths(root=brain), compiled())
    book = open_task(brain, project=ROOT_PROJECT_SLUG)
    assert isinstance(book, HabitBook)
    assert [item.procedure_id for item in book.procedures] == ["habit-manager-" + DIGEST]
    assert book(Tier.MANAGER, planner_request()) is not None


def test_the_tasks_own_project_procedures_are_loaded_beside_them(brain: Path) -> None:
    paths = BrainPaths(root=brain)
    install(paths, compiled("habit-manager-node"))
    install(paths, compiled("habit-manager-project"), project="workload")
    assert [item.procedure_id for item in open_task(brain, project="workload").procedures] == [
        "habit-manager-node",
        "habit-manager-project",
    ]


def test_another_projects_procedures_are_not_loaded(brain: Path) -> None:
    install(BrainPaths(root=brain), compiled("habit-manager-project"), project="workload")
    assert open_task(brain, project="other") is None
    assert open_task(brain, project="workload") is not None


def test_the_set_is_read_once_and_a_later_file_does_not_join_it(brain: Path) -> None:
    """Held for the life of the task: a sleep run mid-task is refused, so nothing may change."""
    paths = BrainPaths(root=brain)
    install(paths, compiled("habit-manager-first"))
    book = open_task(brain, project=ROOT_PROJECT_SLUG)
    install(paths, compiled("habit-manager-second"))
    assert [item.procedure_id for item in book.procedures] == ["habit-manager-first"]


def test_a_root_with_no_seats_file_avoids_no_named_model(brain: Path) -> None:
    """Ledger `D19-5`: a scripted root avoided no model, so the field stays empty."""
    assert seat_models(brain) == {}
    install(BrainPaths(root=brain), compiled())
    facts = open_task(brain, project=ROOT_PROJECT_SLUG)(Tier.MANAGER, planner_request())
    assert facts is not None and facts.avoided_model == ""


def test_a_live_root_names_the_model_the_habit_stood_in_for(brain: Path) -> None:
    source = Path(config.repo_root()) / "brain" / "seats.yaml"
    # A live seed names its kinds' prefix files, which `parse_kinds()` resolves at load
    # (A.2 § Deliverable 1, `the build specification (not in this mirror)`), so the copied root carries the
    # tracked `seats/` tree beside the file; the assertion below is unchanged.
    shutil.copytree(source.parent / "seats", brain / "seats")
    (brain / "seats.yaml").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    models = seat_models(brain)
    assert set(models) == {str(tier) for tier in ANSWERABLE_TIERS}
    assert all(model for model in models.values())


# --------------------------------------------------------------------------------------
# The file on disk is one `parse_script()` reads, and nothing more exotic
# --------------------------------------------------------------------------------------


def test_the_file_the_compiler_writes_is_what_the_matcher_loads(brain: Path) -> None:
    """Row L6 read from the runtime's end: no second format and no conversion step."""
    path = install(BrainPaths(root=brain), compiled())
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert payload["procedure_id"] == "habit-manager-" + DIGEST
    assert payload["seed"] is False and payload["hits_required"] == 3
    book = open_task(brain, project=ROOT_PROJECT_SLUG)
    assert book.procedures[0].script.name == "habit-manager-" + DIGEST


def test_a_file_that_is_not_a_seat_script_is_refused_rather_than_ignored(brain: Path) -> None:
    directory = BrainPaths(root=brain).node_procedures(config.CORTEX_NODE)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "broken.yaml").write_text("responses: 3\n", encoding="utf-8")
    with pytest.raises(SeatScriptError):
        open_task(brain, project=ROOT_PROJECT_SLUG)
