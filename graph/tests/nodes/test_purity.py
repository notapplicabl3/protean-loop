"""Decision 25 and M11's grep, as a structural test rather than a promise in a docstring.

`the build specification (not in this mirror)` § Directional decision 25 — a node is "a pure callable from a
typed input model to a typed output model" — and § Deliverable 4: "every threshold is a named
key in `brain/nodes/anterior_cingulate/weights.yaml`, **never a literal**", "**no node opens a
trace file**".

Builder-verified row M11's grep half. Three properties are checked over the source itself,
because each is a claim about what the module *cannot* do and no behavioural test can prove an
absence:

* **no threshold literal** — no numeric constant anywhere in `src/protean/nodes/` equals a
  non-trivial value in any of the six seeded `weights.yaml` files;
* **no file is opened** — no node module imports an I/O module or calls a filesystem method;
* **no coupling to the writer** — no node imports `protean.brain` or `protean.runtime`, so a
  node cannot reach `trace.jsonl` even indirectly.

The fourth check is the veto's reach (B3's machine half): the runtime's cycle inhibits the seat
in exactly **two** places, and both read one of the two contractual inhibition fields.
"""

from __future__ import annotations

import ast
import functools
import inspect
from pathlib import Path
from typing import get_type_hints

import pytest

from protean import config
from protean.brain.folders import load_weights
from protean.nodes.registry import NODES
from protean.state.outputs import NodeOutput
from protean.state.reads import NODE_INPUT_MODELS
from tests.conftest import BRAIN_SEED, REPO_ROOT

NODES_DIR = REPO_ROOT / "src" / "protean" / "nodes"

#: Constants that carry no threshold meaning: an index, an empty default, a unit step. Every
#: other number in a weights file is a tuning knob and must not appear in a node module.
TRIVIAL = {0, 1}

#: Names whose call would mean the node touched the filesystem.
IO_CALLS = frozenset(
    {
        "open",
        "read_text",
        "read_bytes",
        "write_text",
        "write_bytes",
        "iterdir",
        "glob",
        "rglob",
        "mkdir",
        "unlink",
        "rename",
        "replace",
        "stat",
        "exists",
        "resolve",
        "touch",
        "chmod",
        "walk",
        "listdir",
    }
)

#: Modules a pure callable has no business importing.
FORBIDDEN_IMPORTS = frozenset(
    {"os", "io", "shutil", "json", "yaml", "sqlite3", "tempfile", "subprocess", "socket"}
)

MODULES = sorted(path for path in NODES_DIR.glob("*.py") if path.name != "__init__.py")


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


@functools.cache
def _seeded_thresholds() -> frozenset[float]:
    """Every non-trivial seeded value, parsed once: the six files are read-only to this battery.

    Cached because one call parses all six `weights.yaml` files and every parametrized case
    below asks the same question of the same unchanged tree (audit row N9). The return is a
    `frozenset` so a cached answer cannot be edited by one caller on behalf of the rest.
    """
    values: set[float] = set()
    for node in config.NODE_ORDER:
        weights = load_weights(config.node_dir(node, BRAIN_SEED) / "weights.yaml")
        for value in weights.values():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if value in TRIVIAL:
                continue
            values.add(float(value))
    return frozenset(values)


def test_the_module_list_is_not_empty():
    assert MODULES, "a vacuous grep proves nothing"
    assert {path.stem for path in MODULES} >= set(config.DETERMINISTIC_NODES)


def test_the_seeded_threshold_set_is_not_empty():
    assert len(_seeded_thresholds()) >= 10


@pytest.mark.parametrize("path", MODULES, ids=lambda path: path.name)
def test_no_node_module_contains_a_threshold_literal(path: Path):
    thresholds = _seeded_thresholds()
    offenders = [
        node.value
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
        and float(node.value) in thresholds
    ]
    assert offenders == [], f"{path.name} restates a seeded weights value: {offenders}"


@pytest.mark.parametrize("path", MODULES, ids=lambda path: path.name)
def test_no_node_module_opens_a_file(path: Path):
    called: list[str] = []
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
        if name in IO_CALLS:
            called.append(name)
    assert called == [], f"{path.name} touches the filesystem: {called}"


@pytest.mark.parametrize("path", MODULES, ids=lambda path: path.name)
def test_no_node_module_imports_an_io_module_or_the_writer(path: Path):
    """DoD row M1's prover: no node module imports an I/O module or the writer.

    Absorbs `tests/nodes/test_firing_checks.py::test_no_check_reaches_the_runtime_or_an_io_module`
    (audit row N4) — the same `FORBIDDEN_IMPORTS` set and the same runtime/brain prefix
    predicate over the same bytes, its five check modules a subset of these eight. The
    narrower sibling that walks the check's own function AST stays there.
    """
    imported: list[str] = []
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    roots = {name.split(".")[0] for name in imported}
    assert not (roots & FORBIDDEN_IMPORTS), f"{path.name} imports {roots & FORBIDDEN_IMPORTS}"
    assert not any(
        name.startswith("protean.brain") or name.startswith("protean.runtime")
        for name in imported
    ), f"{path.name} reaches the writer: {imported}"


@pytest.mark.parametrize("node", list(config.DETERMINISTIC_NODES))
def test_every_node_is_one_callable_from_one_typed_input(node: str):
    callable_ = NODES[node]
    signature = inspect.signature(callable_)
    assert len(signature.parameters) == 1, node

    hints = get_type_hints(callable_)
    parameter = next(iter(signature.parameters))
    assert hints[parameter] is NODE_INPUT_MODELS[node][0]
    assert issubclass(hints["return"], NodeOutput)


@pytest.mark.parametrize("node", list(config.DETERMINISTIC_NODES))
def test_no_node_takes_a_path_a_root_or_a_port(node: str):
    """The read slice is the input model; nothing else reaches a node."""
    parameter = next(iter(inspect.signature(NODES[node]).parameters))
    assert parameter == "payload", node


def test_the_seat_is_the_only_thing_the_cycle_inhibits_on():
    """B3's machine half: exactly two contractual inhibitions, and they are the named two."""
    source = (REPO_ROOT / "src" / "protean" / "runtime" / "cycle.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source, filename="cycle.py")
    guards: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        assigns = [
            child
            for child in node.body
            if isinstance(child, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "skip_seat"
                for target in child.targets
            )
        ]
        if assigns:
            guards.append(ast.unparse(node.test))

    assert len(guards) == 2, guards
    assert any("stop" in guard for guard in guards), guards
    assert any("decision" in guard and "NO_GO" in guard for guard in guards), guards


@pytest.mark.parametrize("path", MODULES, ids=lambda path: path.name)
def test_no_node_module_names_a_binary(path: Path):
    """M21's node half: the `claude` binary is named nowhere outside `src/protean/cortex/`."""
    assert "claude" not in path.read_text(encoding="utf-8").lower(), path.name
