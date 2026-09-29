"""M1 and M4 — every cheap check is pure, and every `NODE.md` still matches its code.

`the build specification (not in this mirror)` § Deliverable 1 (seam contract C3) and § DoD rows M1 and
M4. Both are **builder-verified defaults**, written here and closed by nobody in this dispatch.

**M1's shape is the SPEC's own.** "Every cheap check is pure: it opens no file, names no binary,
imports nothing from `runtime/`, and is a function of the node's projected input and its weights
alone — proven per node by a **fixture pair whose only difference is one weights value**, with
`basal_ganglia` the stated exemption: its check is structural, it reads no weights key, and
`WEIGHTS_WRITABLE_NODES` is unchanged, so its fixture pair differs by the **presence of the
unit** instead."

The purity half is checked over the source of each check function rather than over its
behaviour, because each clause is a claim about what the function *cannot* do; the module-wide
greps in `tests/nodes/test_purity.py` cover the same three properties for the file as a whole,
and this narrows them to the function M1 names.

**M4's `## Weights` half is parsed here** because `protean.state.reads` parses `## Reads` and
nothing else: `## Reads` is a startup refusal and `## Weights` is a builder's row. The parser is
the same shape — backticked identifiers inside one `##` section — with one named exception,
`window_len`, which `src/protean/state/enums.py` documents as **derived** from five of the trap
keys and never written to the file.

**Zero model calls.** Nothing here constructs a brain root, a seat or a temp directory: a check
is a pure callable, so this battery builds the input model and calls it.
"""

from __future__ import annotations

import ast
import builtins
import functools
import inspect
import re
from typing import get_type_hints

import pytest

from protean import config
from protean.brain.folders import load_weights
from protean.nodes import anterior_cingulate as monitor_node
from protean.nodes import basal_ganglia as gate_node
from protean.nodes import hippocampus as hippocampus_node
from protean.nodes import homeostasis as homeostasis_node
from protean.nodes import thalamus as thalamus_node
from protean.runtime.firing import CONTRACTUAL_BODIES, FIRING_CHECKS, FIRING_KEYS, decide
from protean.state.calls import FiringDecision
from protean.state.enums import NodeName
from protean.state.inputs import (
    BasalGangliaInput,
    HippocampusInput,
    HomeostasisInput,
    MonitorInput,
    ThalamusInput,
)
from protean.state.outputs import RetrievalSet, RetrievedEpisode
from protean.state.reads import check_reads
from protean.state.semantic import SemanticChunk
from tests.conftest import BRAIN_SEED
from tests.nodes.conftest import TASK_ID, cost, overrides, unit
from tests.nodes.test_purity import IO_CALLS

#: The `## Weights` identifier that is **derived and never written** — `src/protean/state/
#: enums.py`'s `WINDOW_LEN_KEYS`: "`window_len` is set once at task start as `max(...) + 1` over
#: exactly these keys ... derived from the weights the detectors read, never a literal".
DERIVED_NOT_WRITTEN = frozenset({"window_len"})

#: The two folders whose `## Weights` list is not its `weights.yaml` keys: the gate's file is the
#: empty mapping by contract, and the cortex is a seat folder rather than a firing outer node.
WEIGHTS_LIST_EXCEPTED = (str(NodeName.BASAL_GANGLIA),)

TICK = 4
BACKTICKED = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")
HEADING = re.compile(r"^##\s+\S")


# --------------------------------------------------------------------------------------
# The fixture pairs: one weights value apart, and the unit apart for the gate
# --------------------------------------------------------------------------------------


@functools.cache
def _parsed_seed_weights(node: str) -> dict:
    """One folder's `weights.yaml`, parsed once per session — the seed tree never changes here."""
    return load_weights(config.node_dir(node, BRAIN_SEED) / "weights.yaml")


def seed_weights_for(node: str) -> dict:
    """A **fresh mutable copy** of one folder's seeded weights.

    The copy is the contract: M1's fixture pair edits one key, so no caller may be handed the
    cached parse itself. Only the parse is shared (audit row N9).
    """
    return dict(_parsed_seed_weights(node))


def homeostasis_payload(weights: dict) -> HomeostasisInput:
    """A task half way to one ceiling and nowhere near the others."""
    ceiling = float(weights[homeostasis_node.CEILING_TOKENS])
    return HomeostasisInput(
        task_id=TASK_ID,
        tick=TICK,
        weights=weights,
        cost=cost(tokens=int(ceiling / 2)),
        ceiling_overrides=overrides(),
    )


def hippocampus_payload(weights: dict) -> HippocampusInput:
    return HippocampusInput(
        task_id=TASK_ID,
        tick=TICK,
        weights=weights,
        semantic=[
            SemanticChunk(
                schema_version=config.SEMANTIC_CHUNK_SCHEMA_VERSION,
                chunk_id="semantic:aa",
                store="notes",
                source="s.md",
                text="the note the goal names",
                terms=["note", "goal"],
                manifest_revision="r1",
            )
        ],
    )


#: "no argument given" is not "the slot was withheld", and the second is the case under test.
UNSET = object()


def thalamus_payload(weights: dict, *, retrieval=UNSET) -> ThalamusInput:
    if retrieval is UNSET:
        retrieval = RetrievalSet(
            tick=TICK, candidates=[RetrievedEpisode(episode_id="ep-1", score=1.0)]
        )
    return ThalamusInput(task_id=TASK_ID, tick=TICK, weights=weights, retrieval=retrieval)


def monitor_payload(weights: dict) -> MonitorInput:
    return MonitorInput(task_id=TASK_ID, tick=TICK, weights=weights, units=[unit()])


def gate_payload(weights: dict, *, pending) -> BasalGangliaInput:
    return BasalGangliaInput(
        task_id=TASK_ID,
        tick=TICK,
        weights=weights,
        pending_unit=pending,
        workspace_root="/tmp/workspace",
    )


#: node -> (a payload builder, the check, the node name) for the four threshold-bearing checks.
THRESHOLD_PAIRS = (
    (str(NodeName.HOMEOSTASIS), homeostasis_payload, homeostasis_node.firing_check),
    (str(NodeName.HIPPOCAMPUS), hippocampus_payload, hippocampus_node.firing_check),
    (str(NodeName.THALAMUS), thalamus_payload, thalamus_node.firing_check),
    (str(NodeName.ANTERIOR_CINGULATE), monitor_payload, monitor_node.firing_check),
)


@pytest.mark.parametrize(
    "node,build,check", THRESHOLD_PAIRS, ids=[row[0] for row in THRESHOLD_PAIRS]
)
def test_one_weights_value_apart_flips_the_decision(node, build, check):
    """M1's fixture pair: the same projection twice, one number different, and nothing else."""
    weights = seed_weights_for(node)
    key = FIRING_KEYS[node]
    fires = check(build({**weights, key: 0.0}))
    scored = fires.value
    skips = check(build({**weights, key: scored + 1.0}))

    print(f"    [W6-M1] {node}: value={scored} fires@{fires.threshold} skips@{skips.threshold}")
    assert fires.fired is True
    assert skips.fired is False
    assert fires.value == skips.value, "one weights value apart, and nothing else"
    assert fires.key == skips.key == key
    assert fires.check == skips.check


@pytest.mark.parametrize(
    "node,build,check", THRESHOLD_PAIRS, ids=[row[0] for row in THRESHOLD_PAIRS]
)
def test_a_check_fires_at_exactly_its_threshold(node, build, check):
    """The comparison sense § Deliverable 1 states: `value >= threshold`, so `==` fires."""
    weights = seed_weights_for(node)
    key = FIRING_KEYS[node]
    scored = check(build({**weights, key: 0.0})).value
    assert check(build({**weights, key: scored})).fired is True, "at the threshold, it fires"
    assert check(build({**weights, key: scored + 1.0})).fired is False, "above it, it does not"


def test_the_gates_pair_differs_by_the_presence_of_the_unit(gate_weights):
    """M1's stated exemption: structural, threshold-free, and the gate's file stays empty."""
    present = gate_node.firing_check(gate_payload(gate_weights, pending=unit()))
    absent = gate_node.firing_check(gate_payload(gate_weights, pending=None))
    print(f"    [W6-M1] gate: present={present.fired} absent={absent.fired}")
    assert present.fired is True and absent.fired is False
    assert present.key == absent.key == "", "it reads no weights key at all"
    assert present.threshold is absent.threshold is None
    assert gate_weights == {}, "and its `weights.yaml` is the empty mapping, still"
    assert str(NodeName.BASAL_GANGLIA) not in config.WEIGHTS_WRITABLE_NODES
    assert str(NodeName.BASAL_GANGLIA) not in FIRING_KEYS


def test_the_cortex_is_not_a_firing_node():
    """A seat folder, not an outer node: it gains no check and no firing key (folded: S-A63)."""
    assert config.CORTEX_NODE not in FIRING_CHECKS
    assert config.CORTEX_NODE not in FIRING_KEYS
    cortex_keys = load_weights(config.node_dir(config.CORTEX_NODE, BRAIN_SEED) / "weights.yaml")
    assert "firing_threshold" not in cortex_keys


def test_the_weights_writable_set_is_unchanged():
    """`WEIGHTS_WRITABLE_NODES` is `NODE_ORDER` less the gate, exactly as build 3 left it."""
    assert config.WEIGHTS_WRITABLE_NODES == tuple(
        node for node in config.NODE_ORDER if node != str(NodeName.BASAL_GANGLIA)
    )


def test_a_withheld_slot_scores_the_bottom_of_the_thalamuss_scale():
    """An absent required input is the consumer's own "nothing for me" condition."""
    weights = seed_weights_for(str(NodeName.THALAMUS))
    decision = thalamus_node.firing_check(thalamus_payload(weights, retrieval=None))
    print(f"    [W6-M1] thalamus on a withheld slot: value={decision.value}")
    assert decision.value == 0.0
    assert decision.fired is True, "whether that skips the node is the seeded number's business"


# --------------------------------------------------------------------------------------
# M1's purity half, over the check functions themselves
# --------------------------------------------------------------------------------------


def check_tree(node: str) -> ast.AST:
    return ast.parse(inspect.getsource(FIRING_CHECKS[node]).strip())


@pytest.mark.parametrize("node", list(config.DETERMINISTIC_NODES))
def test_every_check_is_one_callable_from_the_nodes_own_projection(node):
    """Projected input in, a `FiringDecision` out — one parameter, named like the body's."""
    signature = inspect.signature(FIRING_CHECKS[node])
    assert list(signature.parameters) == ["payload"], node
    hints = get_type_hints(FIRING_CHECKS[node])
    assert hints["return"] is FiringDecision, node


@pytest.mark.parametrize("node", list(config.DETERMINISTIC_NODES))
def test_no_check_opens_a_file_or_names_a_binary(node):
    called = [
        item.attr if isinstance(item, ast.Attribute) else getattr(item, "id", "")
        for element in ast.walk(check_tree(node))
        if isinstance(element, ast.Call)
        for item in [element.func]
    ]
    assert not (set(called) & IO_CALLS), f"{node}'s check touches the filesystem: {called}"
    assert "claude" not in inspect.getsource(FIRING_CHECKS[node]).lower()


# DoD row M1's prover is `tests/nodes/test_purity.py::test_no_node_module_imports_an_io_module_or_the_writer`
# — `test_no_check_reaches_the_runtime_or_an_io_module` was removed here as its subset (audit row N4).


@pytest.mark.parametrize("node", list(config.DETERMINISTIC_NODES))
def test_a_check_reads_nothing_but_its_payload(node):
    """A function of the projection and its weights alone: no free name but its own module's."""
    tree = check_tree(node)
    module = inspect.getmodule(FIRING_CHECKS[node])
    bound = {
        element.id
        for element in ast.walk(tree)
        if isinstance(element, ast.Name) and isinstance(element.ctx, ast.Store)
    } | {argument.arg for element in ast.walk(tree)
         if isinstance(element, ast.FunctionDef) for argument in element.args.args}
    for element in ast.walk(tree):
        if not isinstance(element, ast.Name) or not isinstance(element.ctx, ast.Load):
            continue
        assert (
            element.id in bound or element.id in dir(module) or element.id in dir(builtins)
        ), f"{node}'s check reads the free name {element.id!r}"
    assert "payload" in bound, f"{node}'s check takes the projection as its one argument"


def test_only_homeostasis_has_a_contractual_body():
    """The gate needs no exception: its check fires exactly when a unit is pending."""
    assert CONTRACTUAL_BODIES == (str(NodeName.HOMEOSTASIS),)


@pytest.mark.parametrize("node", list(config.DETERMINISTIC_NODES))
def test_the_runtimes_one_reading_is_the_nodes_own_check(node):
    """`firing.decide()` dispatches to the function beside the body, and to nothing else."""
    payload = {
        str(NodeName.HOMEOSTASIS): lambda: homeostasis_payload(seed_weights_for(node)),
        str(NodeName.HIPPOCAMPUS): lambda: hippocampus_payload(seed_weights_for(node)),
        str(NodeName.THALAMUS): lambda: thalamus_payload(seed_weights_for(node)),
        str(NodeName.BASAL_GANGLIA): lambda: gate_payload(seed_weights_for(node), pending=unit()),
        str(NodeName.ANTERIOR_CINGULATE): lambda: monitor_payload(seed_weights_for(node)),
    }[node]()
    assert decide(node, payload) == FIRING_CHECKS[node](payload)


# --------------------------------------------------------------------------------------
# M4 — every `NODE.md` still matches its code
# --------------------------------------------------------------------------------------


def section(text: str, heading: str) -> str:
    """One `## <heading>` section's body, ending at the next `##` heading."""
    lines = text.splitlines()
    out: list[str] = []
    inside = False
    for line in lines:
        if line.strip() == f"## {heading}":
            inside = True
            continue
        if inside and HEADING.match(line):
            break
        if inside:
            out.append(line)
    assert inside, f"no `## {heading}` section"
    return "\n".join(out)


def node_md(node: str) -> str:
    return (config.node_dir(node, BRAIN_SEED) / "NODE.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("node", list(config.NODE_ORDER))
def test_the_weights_list_equals_the_weights_file(node):
    """M4: including the new firing key — the gate and the cortex excepted by name."""
    listed = set(BACKTICKED.findall(section(node_md(node), "Weights"))) - DERIVED_NOT_WRITTEN
    keys = set(load_weights(config.node_dir(node, BRAIN_SEED) / "weights.yaml"))
    print(f"    [W6-M4] {node}: listed={sorted(listed)} file={sorted(keys)}")
    if node in WEIGHTS_LIST_EXCEPTED:
        assert keys == set(), "the gate's file is the empty mapping, by contract"
        assert listed == set(), "and its `## Weights` gains no firing key"
        return
    assert listed == keys
    if node in FIRING_KEYS:
        assert FIRING_KEYS[node] in listed, "the firing key is in the list"
        assert FIRING_KEYS[node] in keys, "and in the file"
    else:
        assert "firing_threshold" not in keys, f"{node} is not a firing-key-bearing node"


@pytest.mark.parametrize("node", list(config.DETERMINISTIC_NODES))
def test_the_predicts_section_names_the_skip_prediction(node):
    """M4: every outer node's `## Predicts` says what its skip records and what checks it."""
    predicts = section(node_md(node), "Predicts")
    print(f"    [W6-M4] {node} predicts names: {'FiringDecision' in predicts}")
    assert "skip prediction" in predicts
    assert "FiringDecision" in predicts
    assert "`call# = 0`" in predicts
    check_name = FIRING_CHECKS[node].__module__.rsplit(".", 1)[1]
    assert check_name == node, "the check lives in the node's own module"


@pytest.mark.parametrize("node", list(config.NODE_ORDER))
def test_startup_does_not_refuse_on_drift(node):
    """M4's last clause: `## Reads` still names exactly its input model's fields."""
    check_reads(node, node_md(node))
