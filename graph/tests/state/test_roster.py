"""The gate that makes M7's "every contract" true: a contract added without a test fails.

`the work orders (not in this mirror)` § W1 Process step 9 — "Add a roster test asserting the
tested-model set equals the model set `src/protean/state/` exports, so a contract added
without a test fails."

The battery parametrizes over `protean.state.MODELS`. That is a hand-kept tuple, so on its own
it proves nothing: the failure it cannot see is a new contract exported and forgotten. This
module closes that by discovering the exported models independently — by scanning the package
namespace — and asserting the two sets are equal in both directions.

The abstract bases are excluded by name and the exclusion is itself asserted, so "we forgot to
export it" and "it is deliberately a base" stay different states.
"""

from __future__ import annotations

import inspect

from pydantic import BaseModel

import protean.state as state
from protean.state import MODELS
from protean.state.base import ExtraTolerantModel, ProteanModel
from protean.state.inputs import NodeInput
from protean.state.outputs import NodeOutput
from protean.state.seats import SeatResult

#: Shapes, not contracts. Never instantiated, and deliberately not exported by the package.
ABSTRACT_BASES = (BaseModel, ProteanModel, ExtraTolerantModel, NodeOutput, SeatResult, NodeInput)


def exported_models() -> set[type]:
    """Every pydantic model reachable through `protean.state`'s public namespace."""
    found: set[type] = set()
    for name, obj in vars(state).items():
        if name.startswith("_"):
            continue
        if inspect.isclass(obj) and issubclass(obj, BaseModel) and obj not in ABSTRACT_BASES:
            found.add(obj)
    return found


def test_the_roster_is_exactly_what_the_package_exports() -> None:
    exported = exported_models()
    roster = set(MODELS)
    assert sorted(m.__name__ for m in exported - roster) == [], (
        "a contract is exported but absent from MODELS, so nothing tests it"
    )
    assert sorted(m.__name__ for m in roster - exported) == [], (
        "MODELS names a contract the package does not export"
    )


def test_the_roster_has_no_duplicates() -> None:
    assert len(MODELS) == len(set(MODELS))


def test_the_abstract_bases_are_not_exported() -> None:
    """They are shapes. Exporting one would put an uninstantiable class in the battery."""
    exported_names = {name for name in vars(state) if not name.startswith("_")}
    for base in (NodeOutput, SeatResult, NodeInput):
        assert base.__name__ not in exported_names


def test_every_roster_entry_is_a_pydantic_model() -> None:
    for model in MODELS:
        assert issubclass(model, BaseModel), model
