"""The argument keys the open `Constraint` and `Expectation` maps are read under.

`the build specification (not in this mirror)` § Deliverable 2 fixes both `kind` sets as closed enums and
leaves `arguments` an open `dict[str, JsonValue]`. An open map still needs **one** vocabulary,
or the gate reads a key the planner never wrote and a catastrophic-only veto silently never
fires — which is why the names live in one module read by every node and every fixture
(dispatch ledger D5-10).

**Nothing here is a threshold.** These are key names; the numbers they select live in
`brain/nodes/*/weights.yaml`.
"""

from __future__ import annotations

import pytest

from protean.nodes import vocabulary
from protean.nodes.homeostasis import CEILING_KEYS
from protean.state.enums import ConstraintKind, ExpectationKind

#: Every kind whose payload the build reads under a named key, and the keys it reads.
CONSTRAINT_KEYS = {
    ConstraintKind.PATH_SCOPE: (vocabulary.PATH_SCOPE_PATHS,),
    ConstraintKind.ALLOW_IRREVERSIBLE: (vocabulary.ALLOW_IRREVERSIBLE_UNIT_IDS,),
}

EXPECTATION_KEYS = {
    ExpectationKind.FILE_EXISTS: (vocabulary.EXPECTATION_PATH,),
    ExpectationKind.FILE_ABSENT: (vocabulary.EXPECTATION_PATH,),
    ExpectationKind.FILE_CONTAINS: (vocabulary.EXPECTATION_PATH, vocabulary.EXPECTATION_VALUE),
    ExpectationKind.SUMMARY_FIELD_EQUALS: (
        vocabulary.EXPECTATION_FIELD,
        vocabulary.EXPECTATION_VALUE,
    ),
    ExpectationKind.EXIT_CODE: (vocabulary.EXPECTATION_CODE,),
}


def test_every_expectation_kind_has_a_named_key_set():
    assert set(EXPECTATION_KEYS) == set(ExpectationKind)


def test_the_two_veto_reading_constraint_kinds_have_named_keys():
    assert set(CONSTRAINT_KEYS) == set(ConstraintKind) - {ConstraintKind.BUDGET}


def test_a_budget_constraint_reuses_homeostasis_own_ceiling_names():
    """A budget narrows a *named* ceiling rather than introducing a second name for it."""
    assert not hasattr(vocabulary, "BUDGET_LIMIT")
    assert CEILING_KEYS, "the ceiling names are the budget's keys"


@pytest.mark.parametrize("key", sorted({k for keys in EXPECTATION_KEYS.values() for k in keys}))
def test_every_expectation_key_is_a_plain_identifier(key: str):
    assert key.isidentifier()
    assert key == key.lower()


@pytest.mark.parametrize("key", sorted({k for keys in CONSTRAINT_KEYS.values() for k in keys}))
def test_every_constraint_key_is_a_plain_identifier(key: str):
    assert key.isidentifier()
    assert key == key.lower()


def test_the_path_bearing_key_set_is_exactly_the_path_key():
    """Arm (a) of the veto walks this set; `intent` is prose and is not in it."""
    assert vocabulary.PATH_BEARING_KEYS == (vocabulary.EXPECTATION_PATH,)


def test_no_two_keys_collide_on_one_kind():
    for kind, keys in EXPECTATION_KEYS.items():
        assert len(set(keys)) == len(keys), kind


def test_nothing_in_the_vocabulary_is_a_number():
    """The module names keys; every value it selects lives in a weights file."""
    public = {
        name: getattr(vocabulary, name)
        for name in dir(vocabulary)
        if name.isupper() and not name.startswith("_")
    }
    assert public, "a vacuous scan proves nothing"
    for name, value in public.items():
        assert isinstance(value, (str, tuple)), name
        if isinstance(value, tuple):
            assert all(isinstance(item, str) for item in value), name
