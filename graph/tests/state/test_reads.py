"""`NODE.md`'s `## Reads` list names exactly its input model's fields — all six folders.

`the build specification (not in this mirror)` § Deliverable 4: "A startup check asserts each `NODE.md`'s
`## Reads` list names exactly the fields its input model declares — no more, no fewer — and a
drift is a refusal, not a warning."

W1 owns both sides, so they are made to agree at authorship rather than reconciled later; this
module is what proves the agreement held, and the drift cases prove the check would have
caught it if it had not. The runtime's startup check calls the same `check_reads()` these
cases call, so there is one parser and one comparison in the build.
"""

from __future__ import annotations

import pytest

from protean import config
from protean.state import NodeName, ReadsDrift, check_reads, declared_reads, parse_reads_section
from protean.state.reads import NODE_INPUT_MODELS

NODES = tuple(NodeName)


def node_md(brain_seed_root, node: NodeName) -> str:
    return (brain_seed_root / "nodes" / str(node) / "NODE.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("node", NODES, ids=str)
def test_the_reads_list_names_exactly_the_input_models_fields(brain_seed_root, node) -> None:
    check_reads(node, node_md(brain_seed_root, node))
    assert sorted(parse_reads_section(node_md(brain_seed_root, node))) == list(
        declared_reads(node)
    )


@pytest.mark.parametrize("node", NODES, ids=str)
def test_a_missing_entry_is_refused(brain_seed_root, node) -> None:
    listed = parse_reads_section(node_md(brain_seed_root, node))
    text = node_md(brain_seed_root, node).replace(f"- `{listed[0]}`\n", "", 1)
    with pytest.raises(ReadsDrift) as raised:
        check_reads(node, text)
    assert listed[0] in raised.value.missing


@pytest.mark.parametrize("node", NODES, ids=str)
def test_an_extra_entry_is_refused(brain_seed_root, node) -> None:
    text = node_md(brain_seed_root, node).replace(
        "\n## Writes", "- `a_field_the_model_does_not_declare`\n\n## Writes", 1
    )
    with pytest.raises(ReadsDrift) as raised:
        check_reads(node, text)
    assert "a_field_the_model_does_not_declare" in raised.value.extra


def test_every_node_folder_in_the_cycle_has_an_input_model() -> None:
    assert sorted(str(n) for n in NODE_INPUT_MODELS) == sorted(config.NODE_ORDER)


def test_the_cortex_folder_reads_the_union_of_the_two_per_seat_requests() -> None:
    """Builder's default, recorded in the dispatch ledger: one folder, two request models.

    Re-based by build A.1: the executor seat is gone and a `WaveMember` is not a seat request,
    so the cortex reads the director's and the manager's requests and nothing else.
    """
    models = NODE_INPUT_MODELS[NodeName.CORTEX]
    assert [m.__name__ for m in models] == [
        "DirectorRequest",
        "ManagerRequest",
    ]
    union = {name for m in models for name in m.model_fields}
    assert set(declared_reads(NodeName.CORTEX)) == union


def test_the_parser_stops_at_the_next_heading() -> None:
    text = "## Reads\n\n- `alpha`\n- `beta`\n\n## Writes\n\n- `gamma`\n"
    assert parse_reads_section(text) == ("alpha", "beta")


def test_the_parser_ignores_prose_and_unbackticked_lines() -> None:
    text = "## Reads\n\nIt reads the slice below and nothing else.\n\n- `alpha`\n- beta\n"
    assert parse_reads_section(text) == ("alpha",)


@pytest.mark.parametrize("node", NODES, ids=str)
def test_weights_is_part_of_every_read_slice(node) -> None:
    """The only entry point a threshold has into a pure node (dispatch ledger D4-3).

    The cortex folder is the exception: its tiers take no weights slice — the ladder counts are
    the router's, and the router is not a seat.
    """
    if node is NodeName.CORTEX:
        assert "weights" not in declared_reads(node)
    else:
        assert "weights" in declared_reads(node)
