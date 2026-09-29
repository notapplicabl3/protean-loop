"""M8 — the two raising refusals, append-only, and the dedupe key, on all six node folders.

`the build specification (not in this mirror)` § Deliverable 4 → *The prediction is enforced at trace-append,
not by convention*: "`brain/`'s append path refuses a `prediction`-kind `TraceRecord` with no
`prediction`, and an `outcome`-kind record whose `ref` names no committed prediction — **it
raises and writes nothing**." § Deliverable 2 fixes the dedupe key
`(task, tick, node, tier, kind, source)`.

**"Writes nothing" is proven by a byte hash, not by a line count.** Every refusal case below
hashes `trace.jsonl` before the call and after it: a rollback that rewrote the file with the
same records would pass a count and fail this.

**Every case is parametrized over the six folders**, because the row says "proven for each of
the six node folders" and the five deterministic folders and the cortex folder are different
shapes — `tier` is the cortex folder's key and only the cortex folder's.

**The root here is the six trace files and nothing else** (`trace_root`, audit row N2). Every
case below touches `node_dir(node, root)/trace.jsonl` and no other entry, so copying the whole
seeded tree per case proved nothing it did not already assume; the one claim that *is* about the
seeded tree — `test_every_folder_starts_with_a_trace_file` — keeps the real `brain` fixture.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from protean import config
from protean.brain.jsonl import read_lines
from protean.brain.trace import append_trace, committed_prediction_keys
from protean.state.enums import Tier, TraceSource
from protean.state.errors import TraceAppendRefused
from tests.brain import factories
from tests.brain.conftest import trace_path

FOLDERS = list(config.NODE_ORDER)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tier(node: str) -> Tier | None:
    return factories.DEFAULT_TIER[node]


@pytest.mark.parametrize("node", FOLDERS)
def test_every_folder_starts_with_a_trace_file(brain: Path, node: str):
    """The six folders each carry one, so a hash before the first append is a real hash.

    **This one case keeps the real seeded tree** (audit row N2): it is the claim about what the
    tracked seed ships, so the lean `trace_root` the rest of the module runs on — which builds
    those six files itself — could only assert its own construction here.
    """
    assert trace_path(brain, node).exists()
    assert read_lines(trace_path(brain, node)) == []


# --------------------------------------------------------------------------------------
# Refusal 1 — a `prediction` record with no prediction
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("node", FOLDERS)
def test_a_prediction_with_no_prediction_raises_and_leaves_the_file_byte_unchanged(
    trace_root: Path, node: str
):
    path = trace_path(trace_root, node)
    record = factories.prediction(node, _tier(node))
    assert append_trace(path, record) is not None, "the well-formed record lands first"
    before = _hash(path)

    with pytest.raises(TraceAppendRefused) as raised:
        append_trace(path, factories.without_prediction(factories.prediction(node, _tier(node), tick=2)))

    assert _hash(path) == before
    assert "prediction" in str(raised.value)


@pytest.mark.parametrize("node", FOLDERS)
def test_the_refusal_fires_on_an_empty_file_too(trace_root: Path, node: str):
    """Validation runs before the file is opened, so "unchanged" holds with nothing on disk."""
    path = trace_path(trace_root, node)
    before = _hash(path)
    with pytest.raises(TraceAppendRefused):
        append_trace(path, factories.without_prediction(factories.prediction(node, _tier(node))))
    assert _hash(path) == before
    assert read_lines(path) == []


# --------------------------------------------------------------------------------------
# Refusal 2 — an `outcome` whose `ref` names no committed prediction
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("node", FOLDERS)
def test_an_outcome_whose_ref_names_no_committed_prediction_raises_and_writes_nothing(
    trace_root: Path, node: str
):
    path = trace_path(trace_root, node)
    tier = _tier(node)
    assert append_trace(path, factories.prediction(node, tier)) is not None
    before = _hash(path)

    orphan = factories.outcome(factories.unknown_ref(), node, tier)
    with pytest.raises(TraceAppendRefused) as raised:
        append_trace(path, orphan)

    assert _hash(path) == before
    message = str(raised.value)
    assert orphan.ref in message, "the refusal names the ref it could not find"
    assert path.name in message, "and the file it looked in"


@pytest.mark.parametrize("node", FOLDERS)
def test_an_outcome_lands_once_its_prediction_is_committed(trace_root: Path, node: str):
    path = trace_path(trace_root, node)
    tier = _tier(node)
    record = factories.prediction(node, tier)
    append_trace(path, record)
    assert committed_prediction_keys(path) == {record.prediction_key()}

    landed = append_trace(path, factories.outcome(record.prediction_key(), node, tier))
    assert landed is not None
    assert len(read_lines(path)) == 2


@pytest.mark.parametrize("node", FOLDERS)
def test_a_prediction_in_another_folder_does_not_satisfy_this_folders_ref(
    trace_root: Path, node: str
):
    """The committed set is per file: `ref` names a prediction *in this folder*."""
    other = next(name for name in FOLDERS if name != node)
    append_trace(trace_path(trace_root, other), factories.prediction(other, _tier(other)))
    foreign_key = factories.prediction(other, _tier(other)).prediction_key()

    path = trace_path(trace_root, node)
    before = _hash(path)
    with pytest.raises(TraceAppendRefused):
        append_trace(path, factories.outcome(foreign_key, node, _tier(node)))
    assert _hash(path) == before


# --------------------------------------------------------------------------------------
# Append-only, and outcomes as appended records
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("node", FOLDERS)
def test_the_existing_bytes_are_a_prefix_of_the_new_file(trace_root: Path, node: str):
    path = trace_path(trace_root, node)
    tier = _tier(node)
    append_trace(path, factories.prediction(node, tier, tick=1))
    first = path.read_bytes()

    append_trace(path, factories.prediction(node, tier, tick=2))
    second = path.read_bytes()
    assert second.startswith(first)

    record = factories.prediction(node, tier, tick=1)
    append_trace(path, factories.outcome(record.prediction_key(), node, tier, tick=2))
    third = path.read_bytes()
    assert third.startswith(second)


@pytest.mark.parametrize("node", FOLDERS)
def test_an_outcome_is_an_appended_record_never_an_in_place_edit(trace_root: Path, node: str):
    path = trace_path(trace_root, node)
    tier = _tier(node)
    record = factories.prediction(node, tier)
    append_trace(path, record)
    prediction_line = path.read_text(encoding="utf-8").splitlines()[0]

    append_trace(path, factories.outcome(record.prediction_key(), node, tier))

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == prediction_line, "the graded record is untouched"
    assert len(lines) == 2
    kinds = [line["kind"] for line in read_lines(path)]
    assert kinds == ["prediction", "outcome"]


# --------------------------------------------------------------------------------------
# The dedupe key
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("node", FOLDERS)
def test_the_dedupe_key_rejects_a_duplicate(trace_root: Path, node: str):
    path = trace_path(trace_root, node)
    tier = _tier(node)
    record = factories.prediction(node, tier)
    assert append_trace(path, record) is not None

    before = _hash(path)
    assert append_trace(path, record) is None, "a key collision is a silent no-op"
    assert _hash(path) == before
    assert len(read_lines(path)) == 1


@pytest.mark.parametrize("node", FOLDERS)
def test_every_component_of_the_key_is_load_bearing(trace_root: Path, node: str):
    """Change any one of `(task, tick, node, tier, kind, source)` and the record lands."""
    path = trace_path(trace_root, node)
    tier = _tier(node)
    base = factories.prediction(node, tier, task="task-f", tick=1)
    append_trace(path, base)

    assert append_trace(path, factories.prediction(node, tier, task="task-g", tick=1)) is not None
    assert append_trace(path, factories.prediction(node, tier, tick=2)) is not None
    assert len(read_lines(path)) == 3


@pytest.mark.parametrize("node", FOLDERS)
def test_a_operator_answer_and_a_runtime_grade_coexist_at_one_tick(trace_root: Path, node: str):
    """`source` is the component that lets a resolution and a grading land at the same tick."""
    path = trace_path(trace_root, node)
    tier = _tier(node)
    record = factories.prediction(node, tier, tick=1)
    append_trace(path, record)
    key = record.prediction_key()

    graded = append_trace(path, factories.outcome(key, node, tier, tick=2))
    answered = append_trace(
        path,
        factories.outcome(key, node, tier, tick=2, source=TraceSource.OPERATOR_ANSWER),
    )
    assert graded is not None and answered is not None
    sources = [line["source"] for line in read_lines(path) if line["kind"] == "outcome"]
    assert sources == ["runtime_grade", "operator_answer"]


def test_the_cortex_folder_is_keyed_by_addressee(trace_root: Path):
    """One folder, three keys at one tick — and only the cortex folder carries an addressee.

    Re-based by build A.1 (contract 3's third amendment, folded: S-A61): the column is the
    **addressee**, so the cortex folder's three keys are the two seats plus `dispatch`.
    """
    path = trace_path(trace_root, config.CORTEX_NODE)
    for tier in factories.FOLDER_TIERS[config.CORTEX_NODE]:
        assert append_trace(path, factories.prediction(config.CORTEX_NODE, tier, tick=1)) is not None

    records = read_lines(path)
    assert [line["tier"] for line in records] == [
        str(key) for key in factories.FOLDER_TIERS[config.CORTEX_NODE]
    ]
    assert len({line["tier"] for line in records}) == len(
        factories.FOLDER_TIERS[config.CORTEX_NODE]
    )

    duplicate = factories.prediction(config.CORTEX_NODE, Tier.DIRECTOR, tick=1)
    assert append_trace(path, duplicate) is None, "the same tier at the same tick is a no-op"
    assert len(read_lines(path)) == len(factories.FOLDER_TIERS[config.CORTEX_NODE])


@pytest.mark.parametrize("node", [name for name in FOLDERS if name != config.CORTEX_NODE])
def test_a_deterministic_folder_refuses_a_tier(trace_root: Path, node: str):
    """`TraceRecord`'s own validator — a tier outside the cortex folder is unconstructible."""
    payload = factories.prediction(node).model_dump(mode="json")
    payload["tier"] = str(Tier.MANAGER)
    path = trace_path(trace_root, node)
    before = _hash(path)
    with pytest.raises(TraceAppendRefused):
        append_trace(path, payload)
    assert _hash(path) == before
