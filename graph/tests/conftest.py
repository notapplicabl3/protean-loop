"""Fixtures shared by the whole battery: the two trees, and the hand-authored envelopes.

`the build specification (not in this mirror)` § Deliverable 7. Everything here is a *path* or a
*hand-authored fixture file*; nothing constructs a contract, because a shared constructor
would let one battery's convenience leak into another's assertions.

`fixtures/envelopes/` is hand-authored to the model, never captured — § Deliverable 6 is
explicit that the first diff of a captured envelope against `SeatEnvelope` is build 2's first
wet row, not something this build can fake.

Three things here are imported rather than requested as fixtures, because their consumers need
them at **collection** time, where no fixture has run yet: the two tree constants, the evidence
printer, and the policy-home prefixes. They are paths, a `print`, and two assembled strings —
still nothing that constructs a contract.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from functools import partial
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The tracked seed tree. Read-only in every test: `protean dry` is what copies it.
BRAIN_SEED = REPO_ROOT / "brain"

#: The two forbidden path prefixes: build 1's M24 (`tests/test_policy_home_clean.py`) and build 2's
#: row W4 (`tests/intake/test_policy_home_license.py`). **Assembled from parts at import time rather
#: than written as literals**, because the claim is that no tracked file under the four trees
#: spells either prefix — a file that spelled one out would be the first to fail the check it
#: serves. Build 1's M24 module keeps its own assembly: it is that build's landed invariant and
#: reads on its own, so the home here is two of the three sites by ruling, not three.
HOME = "~/"
PREFIXES = (HOME + "policy-home", HOME + "." + "claude")


def show(label: str, value: object, *, tag: str) -> None:
    """One piece of evidence beside its claim, tagged with the row it belongs to.

    Print-only — no assertion reads it — so that a `-s` capture of a run is the receipt itself.
    One spelling of this printer stood in sixteen modules, differing in nothing but the bracketed
    tag, so the tag is a keyword and the printer is one. Bind it per module with `tagged_show`.
    """
    print(f"    [{tag}] {label}: {value}")


def tagged_show(tag: str) -> Callable[..., None]:
    """`show` bound to one module's row tag: `show = tagged_show("W9")` beside its constants.

    A module whose evidence spans more than one row overrides the binding at the call site —
    `show(label, value, tag="G2")` — which is what collapsed `tests/cortex/test_kinds.py`'s
    three printers (`show`, `floor`, `kernel`) into one.
    """
    return partial(show, tag=tag)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """The checkout under test."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def brain_seed_root() -> Path:
    """The tracked seed tree. Read-only in every test: `protean dry` is what copies it."""
    return BRAIN_SEED


@pytest.fixture(scope="session")
def envelope_fixtures() -> Path:
    """`fixtures/envelopes/` — the hand-authored `SeatEnvelope` payloads."""
    return REPO_ROOT / "fixtures" / "envelopes"


@pytest.fixture(scope="session")
def load_envelope(envelope_fixtures: Path):
    """Read one envelope fixture by filename, as raw JSON — validation is the test's job."""

    def _load(name: str) -> dict:
        return json.loads((envelope_fixtures / name).read_text(encoding="utf-8"))

    return _load


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Keep `live` deselected when a command-line `-m` replaces the default `-m 'not live'`.

    `-m` is one option and the last value wins, so `uv run pytest -m "not slow"` — the fast
    lane — would otherwise select every `live` case: the ones that spawn the model binary and
    spend. Naming `live` in the expression (`-m live`, `-m "live or slow"`) is the only way
    to select them; every other expression keeps the default's deselection.
    """
    if re.search(r"\blive\b", config.getoption("markexpr") or ""):
        return
    kept = [item for item in items if item.get_closest_marker("live") is None]
    dropped = [item for item in items if item.get_closest_marker("live") is not None]
    if dropped:
        config.hook.pytest_deselected(items=dropped)
        items[:] = kept
