"""The dispatch table: node name → the pure callable that is that node.

`the build specification (not in this mirror)` § Deliverable 3: "The order is a literal in `config.py`,
iterated by the runtime, **never hardcoded inside a node**." `protean.nodes.registry` holds the
callables and `config.NODE_ORDER` holds the order, so a divergence between the two is an
import-time error rather than a silently skipped node.

**The cortex is absent on purpose**: it is the sixth node folder, but its occupant is a seat,
not a deterministic callable, and the runtime reaches it through `protean.runtime.seat`'s port.
"""

from __future__ import annotations

import importlib

import pytest

from protean import config
from protean.nodes.registry import NODES


def test_the_map_is_keyed_by_the_config_literal():
    assert sorted(NODES) == sorted(config.DETERMINISTIC_NODES)


def test_the_cortex_has_no_deterministic_callable():
    assert config.CORTEX_NODE not in NODES
    assert config.CORTEX_NODE in config.NODE_ORDER


def test_the_five_plus_the_seat_are_the_six_folders():
    assert set(NODES) | {config.CORTEX_NODE} == set(config.NODE_ORDER)
    assert len(NODES) == len(config.NODE_ORDER) - 1


@pytest.mark.parametrize("node", list(config.DETERMINISTIC_NODES))
def test_every_node_maps_to_its_own_modules_run(node: str):
    module = importlib.import_module(f"protean.nodes.{node}")
    assert NODES[node] is module.run


def test_the_map_is_immutable():
    """A dispatch table a caller could rebind is a second place the order can be decided."""
    with pytest.raises(TypeError):
        NODES["homeostasis"] = None  # type: ignore[index]


def test_the_registry_holds_the_callables_and_not_the_order():
    """Iteration order here is not the tick order; `config.NODE_ORDER` is the only order."""
    assert tuple(NODES) != config.NODE_ORDER, "the seat is missing from the map by design"
    assert all(callable(item) for item in NODES.values())
