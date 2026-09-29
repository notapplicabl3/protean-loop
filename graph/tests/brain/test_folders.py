"""The node-folder read, the `## Reads` drift refusal, and the seed hashes.

`the build specification (not in this mirror)` § Deliverable 4 → *`NODE.md` is prose, and the model is the
contract*: "A startup check asserts each `NODE.md`'s `## Reads` list names exactly the fields
its input model declares — no more, no fewer — and **a drift is a refusal, not a warning**."
§ Deliverable 2 adds `Checkpoint.seed_hashes`: "`{relative path: sha256}` for every
`weights.yaml` and `NODE.md` the run loaded".

Builder-verified row M10 — the builder's own test list, not a gate. **The runtime writes
`trace.jsonl` and nothing else under a node folder**, which is asserted here by hashing the
seed files across a three-tick run rather than by reading the source for `open()` calls.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from protean import config
from protean.brain.folders import (
    SEED_FILES,
    SEED_INDEX_KEY,
    changed_seed_files,
    file_sha256,
    inventory_seed_files,
    load_weights,
    read_all_folders,
    read_node_folder,
    seed_hashes,
    seed_index,
    seed_reader,
    seed_relative_path,
    widened_seed_files,
)
from protean.state.enums import NodeName
from protean.state.errors import ReadsDrift
from protean.state.reads import READS_HEADING, declared_reads
from tests.brain.conftest import advance

FOLDERS = list(config.NODE_ORDER)


def _node_md(brain: Path, node: str) -> Path:
    return config.node_dir(node, brain) / "NODE.md"


# --------------------------------------------------------------------------------------
# Reading a folder
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("node", FOLDERS)
def test_a_folder_reads_back_its_prose_and_its_weights(brain: Path, node: str):
    folder = read_node_folder(node, brain)
    assert folder.node is NodeName(node)
    assert folder.path == config.node_dir(node, brain)
    assert folder.node_md.startswith(f"# {node}")
    assert folder.trace_path == folder.path / "trace.jsonl"
    assert folder.procedures_path == folder.path / "procedures"
    assert isinstance(folder.weights, dict)


def test_read_all_folders_covers_the_six_and_only_the_six(brain: Path):
    folders = read_all_folders(brain)
    assert sorted(str(name) for name in folders) == sorted(config.NODE_ORDER)


def test_the_gates_weights_file_is_the_empty_mapping(brain: Path):
    """A tunable on a catastrophic-only gate is an invitation to loosen it."""
    assert read_node_folder("basal_ganglia", brain).weights == {}


def test_a_comments_only_weights_file_reads_as_the_empty_mapping(tmp_path: Path):
    path = tmp_path / "weights.yaml"
    path.write_text("# nothing here\n", encoding="utf-8")
    assert load_weights(path) == {}


def test_a_weights_file_that_is_not_a_mapping_is_refused(tmp_path: Path):
    path = tmp_path / "weights.yaml"
    path.write_text("- one\n- two\n", encoding="utf-8")
    with pytest.raises(ValueError) as raised:
        load_weights(path)
    assert "mapping" in str(raised.value)


# --------------------------------------------------------------------------------------
# The `## Reads` drift refusal
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("node", FOLDERS)
def test_every_seed_folder_declares_exactly_its_input_models_fields(brain: Path, node: str):
    read_node_folder(node, brain)  # raises ReadsDrift on drift
    assert declared_reads(node), "a folder with no declared reads would pass vacuously"


@pytest.mark.parametrize("node", FOLDERS)
def test_an_extra_entry_in_the_reads_list_is_refused_by_name(brain: Path, node: str):
    path = _node_md(brain, node)
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace(READS_HEADING, f"{READS_HEADING}\n\n- `not_a_field`", 1), encoding="utf-8"
    )
    with pytest.raises(ReadsDrift) as raised:
        read_node_folder(node, brain)
    assert "not_a_field" in str(raised.value)


@pytest.mark.parametrize("node", FOLDERS)
def test_a_missing_entry_in_the_reads_list_is_refused_by_name(brain: Path, node: str):
    path = _node_md(brain, node)
    dropped = declared_reads(node)[0]
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() != f"- `{dropped}`"
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ReadsDrift) as raised:
        read_node_folder(node, brain)
    assert dropped in str(raised.value)


def test_a_drift_in_one_folder_refuses_the_whole_startup_check(brain: Path):
    path = _node_md(brain, "thalamus")
    path.write_text(
        path.read_text(encoding="utf-8").replace(READS_HEADING, f"{READS_HEADING}\n\n- `drift`", 1),
        encoding="utf-8",
    )
    with pytest.raises(ReadsDrift):
        read_all_folders(brain)


# --------------------------------------------------------------------------------------
# Seed hashing
# --------------------------------------------------------------------------------------


def test_seed_hashes_covers_every_node_md_and_weights_file(brain: Path):
    hashes = seed_hashes(brain)
    expected = {
        seed_relative_path(node, filename)
        for node in config.NODE_ORDER
        for filename in SEED_FILES
    }
    assert set(hashes) == expected
    assert len(hashes) == len(config.NODE_ORDER) * len(SEED_FILES)


def test_a_seed_hash_is_the_sha256_of_the_files_bytes(brain: Path):
    path = _node_md(brain, "cortex")
    assert file_sha256(path) == hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_key_is_brain_root_relative_so_a_copy_hashes_the_same(brain: Path, tmp_path: Path):
    """`protean dry` runs against a copy; an absolute key would make its checkpoint unrepeatable."""
    import shutil

    other = tmp_path / "second-brain"
    shutil.copytree(brain, other)
    assert seed_hashes(brain) == seed_hashes(other)
    assert all(key.startswith("nodes/") for key in seed_hashes(brain))


def test_seed_reader_hashes_a_root_relative_path(brain: Path):
    read = seed_reader(brain)
    key = seed_relative_path("homeostasis", "weights.yaml")
    assert read(key) == file_sha256(brain / key)


def test_changed_seed_files_reports_both_sides_of_every_edit(brain: Path):
    recorded = seed_hashes(brain)
    path = config.node_dir("homeostasis", brain) / "weights.yaml"
    weights = yaml.safe_load(path.read_text(encoding="utf-8"))
    weights["max_ticks"] = 7
    path.write_text(yaml.safe_dump(weights), encoding="utf-8")

    changed = changed_seed_files(brain, recorded)
    key = seed_relative_path("homeostasis", "weights.yaml")
    assert list(changed) == [key]
    was, now = changed[key]
    assert was == recorded[key]
    assert now == file_sha256(path)


def test_an_untouched_tree_reports_no_changed_seed_file(brain: Path):
    assert changed_seed_files(brain, seed_hashes(brain)) == {}


# --------------------------------------------------------------------------------------
# The widened ladder, and build 3's one seed with no tick-time reader
# --------------------------------------------------------------------------------------

SEEDS_MAP = "feedback_fixture:\n  - node: hippocampus\n    key: candidate_window\n    value: 20\n"


def test_the_seeding_map_joins_the_widened_ladder_and_is_hashed(brain: Path):
    """`the build specification (not in this mirror)` § Deliverable 3: hashed like every other seed."""
    assert "seeds.yaml" not in widened_seed_files(brain)
    (brain / "seeds.yaml").write_text(SEEDS_MAP, encoding="utf-8")
    assert "seeds.yaml" in widened_seed_files(brain)
    assert seed_hashes(brain)["seeds.yaml"] == file_sha256(brain / "seeds.yaml")


def test_an_edit_to_a_recorded_seeding_map_is_a_drift(brain: Path):
    """The per-file arm is what makes editing it between two ticks a refusal, not a silence."""
    (brain / "seeds.yaml").write_text(SEEDS_MAP, encoding="utf-8")
    recorded = seed_hashes(brain)
    (brain / "seeds.yaml").write_text(SEEDS_MAP + "\n# a hand edit\n", encoding="utf-8")
    assert list(changed_seed_files(brain, recorded)) == ["seeds.yaml"]
    assert seed_reader(brain)("seeds.yaml") != recorded["seeds.yaml"]


def test_the_seeding_map_is_the_one_widened_seed_outside_the_inventory(brain: Path):
    """Ledger `D14-4`: it has no tick-time reader, so its *appearance* refuses nothing.

    The inventory key exists to catch a seed whose appearance changes what a running tick sees.
    `brain/seeds.yaml` is read only by `seeded_keys()` and by the intake verb, both of which
    refuse an occupied root — so a checkpoint written before build 3 authored the file still
    loads, while every other widened seed keeps the appearance detector it had.
    """
    (brain / "seats.yaml").write_text("# a seat seed\n", encoding="utf-8")
    before = seed_hashes(brain)[SEED_INDEX_KEY]

    (brain / "seeds.yaml").write_text(SEEDS_MAP, encoding="utf-8")
    assert "seeds.yaml" not in inventory_seed_files(brain)
    assert seed_hashes(brain)[SEED_INDEX_KEY] == before
    assert seed_reader(brain)(SEED_INDEX_KEY) == before

    (brain / "intake").mkdir()
    (brain / "intake" / "manifest.yaml").write_text("# appeared\n", encoding="utf-8")
    assert seed_hashes(brain)[SEED_INDEX_KEY] != before, "every other seed still refuses"


def test_the_inventory_key_is_written_only_when_its_own_set_is_non_empty(brain: Path):
    """A root whose only widened seed is the map carries the twelve node keys plus it."""
    (brain / "seeds.yaml").write_text(SEEDS_MAP, encoding="utf-8")
    hashes = seed_hashes(brain)
    assert inventory_seed_files(brain) == []
    assert SEED_INDEX_KEY not in hashes
    assert set(hashes) == {
        seed_relative_path(node, filename)
        for node in config.NODE_ORDER
        for filename in SEED_FILES
    } | {"seeds.yaml"}


def test_a_root_with_no_seeding_map_hashes_exactly_as_before(brain: Path):
    """The carve-out is inert on every root that carries no map — build 2's behaviour, intact."""
    (brain / "seats.yaml").write_text("# a seat seed\n", encoding="utf-8")
    assert inventory_seed_files(brain) == widened_seed_files(brain)
    assert seed_hashes(brain)[SEED_INDEX_KEY] == seed_index(widened_seed_files(brain))


# --------------------------------------------------------------------------------------
# The runtime writes `trace.jsonl` and nothing else under a node folder
# --------------------------------------------------------------------------------------


def test_a_run_leaves_every_seed_file_and_every_procedures_dir_untouched(started, brain: Path):
    context, state, _router, _seat = started
    before = seed_hashes(brain)
    procedures = {
        node: sorted(p.name for p in (config.node_dir(node, brain) / "procedures").iterdir())
        for node in config.NODE_ORDER
    }

    advance(context, state, 3)

    assert seed_hashes(brain) == before
    assert {
        node: sorted(p.name for p in (config.node_dir(node, brain) / "procedures").iterdir())
        for node in config.NODE_ORDER
    } == procedures
    assert (config.node_dir("thalamus", brain) / "trace.jsonl").read_text(
        encoding="utf-8"
    ), "the one file the runtime does write"


def test_every_folder_carries_all_four_entries(brain: Path):
    for node in config.NODE_ORDER:
        folder = config.node_dir(node, brain)
        assert sorted(entry.name for entry in folder.iterdir()) == sorted(
            config.NODE_FOLDER_ENTRIES
        ), node
