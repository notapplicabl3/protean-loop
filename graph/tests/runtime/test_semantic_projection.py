"""The semantic route, end to end: store file → boundary loader → projection → seat → grade.

`the build specification (not in this mirror)` § Deliverable 3 → *How a chunk reaches the seat*, § Directional
decisions 15 and 16, § Named assumptions 9, § Resolutions A1-12, S-2, S-15, S-16, S-25, and DoD
row W5.

**Three things are proven here that neither node battery can prove alone.** The two node batteries
run on constructed input models, which is exactly right for a pure callable and exactly wrong for
the claim W5 makes: that a chunk written to a *file* by `protean intake` comes out the other end
as an `AdmittedItem` a seat can read, and that the thalamus's prediction about it is graded on
`ExecutorSummary.cited_ids`. So this module drives whole ticks against a throwaway brain root.

**Every chunk here is hand-authored** and written into the throwaway root by `write_store()`.
`brain/semantic/` is gitignored and absent on a fresh clone, so a battery that read the repo's
own store would pass only on the machine that ran the intake.

**Where the seam is.** The loader opens the file; the projection assembles the read slice; the
node scores what it is handed. That split is the reason `## Reads` means anything — a projection
that read the store itself would let the runtime hand a node material its input model never
declared — so it is asserted here rather than left to the docstrings that state it.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from protean import config
from protean.brain.folders import load_weights
from protean.brain.jsonl import read_lines
from protean.nodes.thalamus import admitted_id
from protean.runtime import cycle as cycle_module
from protean.runtime import projections
from protean.runtime.cycle import WEIGHT_SEMANTIC_WINDOW, run_tick, windowed_chunks
from protean.runtime.engine import build_context, new_state
from protean.runtime.journal import load as load_journal
from protean.runtime.paths import BrainPaths
from protean.state.enums import CallType, ExpectationKind, NodeName, Tier
from protean.state.primitives import Expectation, WorkUnit, WorkspaceObservation
from protean.state.seats import ExecutorSummary, ManagerPlan, WaveMember
from protean.state.semantic import CHUNK_ID_PREFIX, SemanticChunk, write_store
from tests.runtime import stubs
from tests.runtime.conftest import EXPECTATION_ID, UNIT_ID

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_TREES = (
    REPO_ROOT / "src" / "protean" / "nodes",
    REPO_ROOT / "src" / "protean" / "runtime",
)

#: The task this module runs. Its vocabulary is what every chunk below is written against.
GOAL = "write out.txt in the workspace"
TARGET = "out.txt"

#: The chunk W5 follows from the store file to the seat. Its text names the goal's own words, so
#: it covers the live vocabulary completely and its score needs no threshold to be readable.
SEEDED_TEXT = "To write out.txt in the workspace, name the file and then write it."

#: A second chunk sharing no vocabulary with the task — the floor's job, and the proof that the
#: route admits by relevance rather than by whatever the store happened to hold.
UNRELATED_TEXT = "Migratory patterns of the arctic tern, summarised."


def _chunk(text: str, *, store: str = "docs") -> SemanticChunk:
    return SemanticChunk.of(
        store=store, source=store, text=text, manifest_revision="rev-test"
    )


def _seed_store(brain: Path, *chunks: SemanticChunk, name: str = "docs") -> Path:
    """Write a store file where `protean intake` would have written it, and nowhere else."""
    path = BrainPaths(root=brain).semantic_store(name)
    write_store(path, chunks)
    return path


def _weights(node: str) -> dict[str, Any]:
    return dict(load_weights(config.node_dir(node, REPO_ROOT / "brain") / "weights.yaml"))


# --------------------------------------------------------------------------------------
# The boundary loader — the one thing in this route that opens a file
# --------------------------------------------------------------------------------------


@pytest.fixture()
def state_stub():
    """The two stacks the query is built from, with no runtime behind them."""

    class _Goal:
        text = GOAL

    class _Unit:
        intent = "write the file"

    class _State:
        goals = [_Goal()]
        units = [_Unit()]

    return _State()


def test_a_root_with_no_store_yields_no_chunks(brain: Path, state_stub):
    """A checkout on which `protean intake` has never run is an ordinary shape, not a refusal."""
    assert not BrainPaths(root=brain).semantic.exists()
    assert windowed_chunks(brain, state_stub, 8) == []


def test_an_empty_store_directory_yields_no_chunks(brain: Path, state_stub):
    BrainPaths(root=brain).semantic.mkdir(parents=True)
    assert windowed_chunks(brain, state_stub, 8) == []


def test_a_window_of_zero_reads_nothing_at_all(brain: Path, state_stub):
    _seed_store(brain, _chunk(SEEDED_TEXT))
    assert windowed_chunks(brain, state_stub, 0) == []


def test_the_loader_keeps_the_best_overlapping_chunks(brain: Path, state_stub):
    seeded, unrelated = _chunk(SEEDED_TEXT), _chunk(UNRELATED_TEXT)
    _seed_store(brain, unrelated, seeded)
    assert [chunk.chunk_id for chunk in windowed_chunks(brain, state_stub, 1)] == [
        seeded.chunk_id
    ]


def test_the_window_bounds_what_the_projection_can_carry(brain: Path, state_stub):
    _seed_store(brain, *[_chunk(f"{SEEDED_TEXT} variant {index}") for index in range(6)])
    assert len(windowed_chunks(brain, state_stub, 2)) == 2


def test_the_loader_reads_every_store_file_in_the_directory(brain: Path, state_stub):
    _seed_store(brain, _chunk(SEEDED_TEXT), name="docs")
    _seed_store(brain, _chunk(f"{SEEDED_TEXT} again"), name="memory")
    assert len(windowed_chunks(brain, state_stub, 8)) == 2


def test_the_window_is_deterministic_across_two_reads(brain: Path, state_stub):
    """Ties break on `chunk_id`, so the same store always narrows to the same slice."""
    _seed_store(brain, *[_chunk(f"{SEEDED_TEXT} {index}") for index in range(5)])
    first = [chunk.chunk_id for chunk in windowed_chunks(brain, state_stub, 3)]
    second = [chunk.chunk_id for chunk in windowed_chunks(brain, state_stub, 3)]
    assert first == second


# --------------------------------------------------------------------------------------
# The projection — assembles the read slice, and opens nothing
# --------------------------------------------------------------------------------------


def test_the_projection_carries_the_slice_onto_the_one_new_field(started):
    _context, state, _router, _seat = started
    chunk = _chunk(SEEDED_TEXT)
    payload = projections.hippocampus_input(state, {}, (), [chunk])
    assert [item.chunk_id for item in payload.semantic] == [chunk.chunk_id]
    assert payload.semantic[0].text == chunk.text


def test_the_projection_defaults_the_field_empty(started):
    _context, state, _router, _seat = started
    assert projections.hippocampus_input(state, {}, ()).semantic == []


def test_the_projection_opens_no_file():
    """The store is read at the boundary, never here — the `## Reads` refusal depends on it."""
    source = (REPO_ROOT / "src" / "protean" / "runtime" / "projections.py").read_text(
        encoding="utf-8"
    )
    called = [
        node.func.attr
        for node in ast.walk(ast.parse(source, filename="projections.py"))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    assert not {"glob", "open", "read_text", "iterdir"} & set(called)
    assert "Path" not in {
        node.id for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Name)
    }, "a projection that held a path could grow a read later"


# --------------------------------------------------------------------------------------
# K5's lexical half — the three thresholds arrive on `weights`, and nowhere else
# --------------------------------------------------------------------------------------

NEW_KEYS = {
    "hippocampus": ("semantic_window", "semantic_min_overlap"),
    "thalamus": ("semantic_max_admitted",),
}


@pytest.mark.parametrize("tree", SOURCE_TREES, ids=lambda path: path.name)
def test_no_module_restates_one_of_the_three_seeded_values(tree: Path):
    """The scorer, the quota and the window name no threshold literal (K5).

    The claim's two controls ride here rather than beside it, because all three are readings of
    the same two lists. Each of the three thresholds **is** a seeded `weights.yaml` key — which
    is what makes "the value is on `weights`, and nowhere else" a claim about a key that exists
    — and a vacuous grep proves nothing, so the value set and the tree being walked are both
    asserted non-empty before their absence from it means anything.
    """
    for node, keys in NEW_KEYS.items():
        weights = _weights(node)
        for key in keys:
            assert key in weights, f"{node}/{key}"
    seeded = {
        float(_weights(node)[key]) for node, keys in NEW_KEYS.items() for key in keys
    }
    assert seeded, "the values must exist before their absence from the modules means anything"
    assert list(tree.glob("*.py")), "and the tree must hold modules"
    offenders: list[str] = []
    for path in sorted(tree.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=path.name)):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, (int, float))
                and not isinstance(node.value, bool)
                and float(node.value) in seeded
            ):
                offenders.append(f"{path.name}:{node.lineno} = {node.value}")
    assert offenders == [], offenders


# --------------------------------------------------------------------------------------
# W5 — end to end, on committed artifacts: store file → seat → graded prediction
# --------------------------------------------------------------------------------------


def _unit(request) -> WorkUnit:
    return WorkUnit(
        id=UNIT_ID,
        goal_id=request.workspace.goals[0].id,
        intent="write the file",
        expected=[
            Expectation(
                id=EXPECTATION_ID,
                kind=ExpectationKind.FILE_EXISTS,
                arguments={"path": TARGET},
            )
        ],
    )


#: The subagent kind the wave's one member asks for.
KIND = "writer"

#: What the manager's plan puts on its member's `admitted_ref`. **The member request carries a
#: reference and never the body** (`the build specification (not in this mirror)` § Deliverable 4): the
#: admitted context reaches the *manager*, which sees it on its own compressed workspace, and
#: the runtime is what resolves the reference for a member at the spawn — which is build A.1.i's.
ADMITTED_REF = "admitted"


def _citing_member(admitted_ids: list[str]):
    """A wave member that cites all the tick admitted — the observable the thalamus is graded on.

    **Re-based by build A.1**: the act is a dispatch member rather than a seat, so its request is
    the `WaveMember` — a kind, a unit id and a reference — and it carries neither the tick nor
    the admitted bodies. The ids it cites are the ones the **manager's** own request carried,
    captured on the pass that assembled the wave.
    """

    def _respond(member) -> ExecutorSummary:
        return ExecutorSummary(
            tick=0,
            unit_id=member.unit_id,
            narrative="wrote it",
            observations=[
                WorkspaceObservation(path=TARGET, exists=True, size_bytes=11, content_hash="h1")
            ],
            cited_ids=list(admitted_ids),
        )

    return _respond


@pytest.fixture(scope="module")
def route(tmp_path_factory):
    """Three ticks against a seeded store: plan, execute-and-cite, then the grading boundary.

    **One route for the module.** The five hop tests below are five readings of *one* three-tick
    pass — the projected payload, the journal, the seat's own record of what it was asked, and
    the graded trace — and none of them writes into the root or the store afterwards. The only
    thing patched is `cycle.NODES`, and only for the length of the three passes: the
    `pytest.MonkeyPatch()` context is left before any consumer runs.
    """
    base = tmp_path_factory.mktemp("semantic")
    brain = stubs.seed_brain(REPO_ROOT / "brain", base / "brain")
    workspace = base / "workspace"
    workspace.mkdir()
    seeded, unrelated = _chunk(SEEDED_TEXT), _chunk(UNRELATED_TEXT)
    _seed_store(brain, seeded, unrelated)

    projected: list[Any] = []
    admitted_ids: list[str] = []

    def _manager(request) -> ManagerPlan:
        """Plan the unit, and dispatch its wave on every pass that already names one."""
        admitted = request.workspace.latest.thalamus
        if admitted is not None:
            admitted_ids[:] = [item.admitted_id for item in admitted.admitted]
        wave = (
            [WaveMember(kind=KIND, unit_id=UNIT_ID, admitted_ref=ADMITTED_REF)]
            if request.unit_id
            else []
        )
        return ManagerPlan(tick=request.workspace.tick, units=[_unit(request)], wave=wave)

    responders = {
        str(Tier.MANAGER): _manager,
        str(CallType.DISPATCH): _citing_member(admitted_ids),
        str(Tier.DIRECTOR): lambda request: {"tick": request.workspace.tick},
    }

    def _respond(addressee, request):
        """`stubs.request_keyed`, widened to the wave's member request (§ Deliverable 3)."""
        if isinstance(request, WaveMember):
            return responders[str(addressee)](request)
        return stubs.request_keyed(responders)(addressee, request)

    seat = stubs.StubSeat(responder=_respond)
    with pytest.MonkeyPatch().context() as patch:
        wrapped = dict(cycle_module.NODES)
        inner = wrapped[str(NodeName.HIPPOCAMPUS)]

        def _capture(payload):
            projected.append(payload)
            return inner(payload)

        wrapped[str(NodeName.HIPPOCAMPUS)] = _capture
        patch.setattr(cycle_module, "NODES", wrapped)

        context = build_context(
            brain,
            "task-semantic",
            stubs.layer(stubs.manager_then_dispatch(UNIT_ID), seat),
            workspace_path=str(workspace),
        )
        state = new_state("task-semantic", GOAL, context)
        for _ in range(3):
            state.tick += 1
            run_tick(context, state)
    return seeded, unrelated, projected, context, brain, seat


def _journalled(context, tick: int, node: NodeName):
    entries = load_journal(context.paths.journal(tick))
    return next(entry.output for entry in entries if entry.node is node)


def _executor_tick(context) -> int:
    """The tick the wave ran on — read off the journal's own call entries, never assumed.

    **Re-based by build A.1**: a `WaveMember` carries no tick, so the pass is read from the
    artifact that keys every call by one — the journal, `(task, tick, node, call#[, member#])`.
    """
    for tick in range(1, 4):
        path = context.paths.journal(tick)
        if not path.exists():
            continue
        if any(entry.tier is CallType.DISPATCH for entry in load_journal(path)):
            return tick
    raise AssertionError("no dispatch member was journalled on any pass")


def test_hop_one_the_chunk_is_projected_onto_the_input_model(route):
    seeded, unrelated, projected, _context, _brain, _seat = route
    assert projected, "the hippocampus ran"
    latest = projected[-1]
    assert latest.semantic, "the projected `semantic` list is non-empty"
    assert seeded.chunk_id in {chunk.chunk_id for chunk in latest.semantic}
    assert latest.semantic[0].text == seeded.text


def test_hop_two_the_retrieval_set_carries_a_semantic_id(route):
    seeded, _unrelated, _projected, context, _brain, seat = route
    retrieval = _journalled(context, _executor_tick(context), NodeName.HIPPOCAMPUS)
    ids = [item.episode_id for item in retrieval.candidates]
    assert seeded.chunk_id in ids
    assert any(item.startswith(CHUNK_ID_PREFIX) for item in ids)


def test_hop_two_the_unrelated_chunk_is_below_the_floor(route):
    _seeded, unrelated, _projected, context, _brain, seat = route
    retrieval = _journalled(context, _executor_tick(context), NodeName.HIPPOCAMPUS)
    assert unrelated.chunk_id not in [item.episode_id for item in retrieval.candidates]


def test_hop_three_the_seat_is_admitted_the_body_and_not_the_id(route):
    seeded, _unrelated, _projected, context, _brain, seat = route
    admitted = _journalled(context, _executor_tick(context), NodeName.THALAMUS)
    item = next(
        entry for entry in admitted.admitted if entry.episode_id == seeded.chunk_id
    )
    assert item.summary == seeded.text
    assert item.summary != item.episode_id
    assert item.admitted_id == admitted_id(seeded.chunk_id)


def test_hop_three_the_request_the_seat_received_carries_the_body(route):
    """**Re-based by build A.1**: the seat that is admitted the body is the **manager**.

    The admitted context reaches it on its own compressed workspace, and the member it
    dispatches carries a **reference** rather than the body (§ Deliverable 4) — resolving that
    reference at the spawn is build A.1.i's. Both halves are asserted here, because the second
    is the shape half of the audit's riskiest finding.
    """
    seeded, _unrelated, _projected, _context, _brain, seat = route
    request = next(
        request for tier, request in seat.calls if tier == str(Tier.MANAGER)
    )
    admitted = request.workspace.admitted
    assert seeded.text in [item.summary for item in admitted.admitted]

    member = next(
        request for tier, request in seat.calls if tier == str(CallType.DISPATCH)
    )
    assert member.admitted_ref == ADMITTED_REF
    assert not hasattr(member, "admitted"), "a member carries the reference, never the body"


def test_hop_four_cited_ids_grade_the_thalamus_prediction_on_the_chunk(route):
    seeded, _unrelated, _projected, context, brain, seat = route
    tick = _executor_tick(context)
    path = config.node_dir(str(NodeName.THALAMUS), brain) / "trace.jsonl"
    key = f":{tick}:{NodeName.THALAMUS}:-:prediction"
    graded = [
        record
        for record in read_lines(path)
        if record["kind"] == "outcome" and record["ref"].endswith(key)
    ]
    assert len(graded) == 1, [record["ref"] for record in graded]
    outcome = graded[0]["outcome"]
    assert admitted_id(seeded.chunk_id) in outcome["cited_admitted_ids"]
    assert outcome["matched"] is True


def test_the_seed_files_and_the_input_model_still_agree(brain: Path):
    """W5's second half: the `## Reads` list matches, so startup does not refuse."""
    from protean.brain.folders import read_all_folders

    folders = read_all_folders(brain)
    assert set(folders) == {NodeName(name) for name in config.NODE_ORDER}
