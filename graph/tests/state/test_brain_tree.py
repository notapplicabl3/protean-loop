"""The seeded brain tree: six folders, four entries each, and one owner per threshold.

`the build specification (not in this mirror)` § Deliverable 1's fenced block, § Deliverable 4 (the uniform
node folder and the trap table's weights keys), § Deliverable 6 (the single-owner rule and the
ladder counts).

Two assertions are the point of the module:

* **`rut_ticks` appears in exactly one *tracked* weights file in the whole brain**, and the
  seeded value is `2` — digest Q2's number, the operator's own, preserved as a *value* while Ruling 16's
  layered shape moved its destination to rung 1. Read off the index rather than the working tree
  from build 3 on (`the build specification (not in this mirror)` § Deliverable 1, folded: A1-12): sleep may
  move the value on disk, and what stays pinned is the *seed*.
* **`brain/nodes/cortex/weights.yaml` carries only the four ladder counts.** A trap threshold
  that appeared there would have two owners, and two owners is how a scenario and the runtime
  come to disagree about what a threshold is.

Everything else here is the shape: every folder present, every entry present, and every
`weights.yaml` a mapping the runtime can load — including the gate's, which is deliberately
empty and must not crash a loader.
"""

from __future__ import annotations

import pytest

from protean import config
from protean.state import (
    ANTERIOR_CINGULATE_WEIGHT_KEYS,
    CORTEX_WEIGHT_KEYS,
    HIPPOCAMPUS_WEIGHT_KEYS,
    TRAP_WEIGHT_KEYS,
    WINDOW_LEN_KEYS,
    window_len,
)
from tests.state.conftest import NODES


@pytest.mark.parametrize("node", NODES)
def test_every_node_folder_carries_all_four_entries(brain_seed_root, node: str) -> None:
    folder = brain_seed_root / "nodes" / node
    assert folder.is_dir()
    assert (folder / "NODE.md").is_file()
    assert (folder / "weights.yaml").is_file()
    assert (folder / "trace.jsonl").is_file()
    assert (folder / "procedures").is_dir()
    assert tuple(config.NODE_FOLDER_ENTRIES) == (
        "NODE.md",
        "weights.yaml",
        "trace.jsonl",
        "procedures",
    )


@pytest.mark.parametrize("node", NODES)
def test_the_tracked_seed_carries_no_trace_file_at_all(tracked_files, node: str) -> None:
    """The seed carries no history. Every record in a trace is the runtime's (folded: S-62).

    Re-based on `git ls-files` from "the seeded trace file is empty": a live run on the repo's
    own brain root fills these files by design and they are gitignored precisely so it may, so
    the claim that holds is the stronger one — the tracked seed carries no `trace.jsonl` at all,
    and the file on disk exists only because the runtime or `cli._seed_root` made it.

    Non-vacuous by construction: the same `git ls-files` call must show this node's `NODE.md` and
    `weights.yaml`, so a command that stopped seeing the tree fails here rather than passing.
    """
    tracked = tracked_files
    assert f"brain/nodes/{node}/NODE.md" in tracked, "the command sees this node's folder"
    assert f"brain/nodes/{node}/weights.yaml" in tracked, "and both of its tracked seeds"
    assert f"brain/nodes/{node}/trace.jsonl" not in tracked
    assert not [one for one in tracked if one.endswith("/trace.jsonl")], (
        f"a trace file is tracked: {[one for one in tracked if one.endswith('/trace.jsonl')]}"
    )


def test_there_are_exactly_six_node_folders(brain_seed_root) -> None:
    """Five deterministic plus the cortex, folded into the same shape (decision 23)."""
    found = sorted(p.name for p in (brain_seed_root / "nodes").iterdir() if p.is_dir())
    assert found == sorted(config.NODE_ORDER)
    assert len(found) == 6


def test_the_rest_of_the_tree_exists(brain_seed_root) -> None:
    for relative in config.GENERATED_BRAIN_DIRS:
        assert (brain_seed_root / relative).is_dir(), relative


@pytest.mark.parametrize("node", NODES)
def test_every_weights_file_loads_as_a_mapping(seed_weights, node: str) -> None:
    """The gate's is deliberately empty; an empty mapping is still a mapping."""
    assert isinstance(seed_weights[node], dict)


def test_rut_ticks_exists_in_exactly_one_tracked_weights_file_and_is_the_operators_number(
    tracked_files, tracked_weights
) -> None:
    """the operator's number stays pinned as the *seed* while the working tree may carry a learned value.

    Re-based on the tracked blob from "the file on disk" (`the build specification (not in this mirror)`
    § Deliverable 1, folded: A1-12). Build 3's sleep graph is the sole rewriter of `weights.yaml`
    and it writes the working tree, so the claim that survives the layer is the one about the
    index — and that distinction is the whole layer in one assertion. It still fails if the
    tracked seed itself is edited, which is the point.

    Non-vacuous by construction: `git ls-files` must still list every node's `weights.yaml`, so a
    command that stopped seeing the tree fails here rather than passing on an empty read.
    """
    tracked = tracked_files
    for node in NODES:
        assert f"brain/nodes/{node}/weights.yaml" in tracked, "the command sees every seed file"

    owners = [n for n in NODES if "rut_ticks" in tracked_weights[n]]
    assert owners == ["anterior_cingulate"]
    assert tracked_weights["anterior_cingulate"]["rut_ticks"] == 2


def test_the_cortex_weights_carry_only_the_four_ladder_counts(seed_weights) -> None:
    assert sorted(seed_weights["cortex"]) == sorted(CORTEX_WEIGHT_KEYS)


def test_the_anterior_cingulate_owns_every_trap_and_streak_threshold(seed_weights) -> None:
    loaded = seed_weights["anterior_cingulate"]
    # `firing_threshold` is A.1's per-node key, outside the trap-and-streak tuple (folded: D15-7).
    # `think_threshold` is A.2.i's static trigger key, outside the tuple the same way (E33).
    assert sorted(set(loaded) - {"firing_threshold", "think_threshold"}) == sorted(
        ANTERIOR_CINGULATE_WEIGHT_KEYS
    )
    # Each trap key's presence *here* is the other half of
    # `test_no_trap_threshold_leaks_into_another_weights_file`, one parametrized case per key.


@pytest.mark.parametrize("key", sorted({k for ks in TRAP_WEIGHT_KEYS.values() for k in ks}))
def test_no_trap_threshold_leaks_into_another_weights_file(seed_weights, key: str) -> None:
    owners = [n for n in NODES if key in seed_weights[n]]
    assert owners == ["anterior_cingulate"]


def test_the_hippocampus_owns_the_candidate_window(seed_weights) -> None:
    for key in HIPPOCAMPUS_WEIGHT_KEYS:
        owners = [n for n in NODES if key in seed_weights[n]]
        assert owners == ["hippocampus"]


def test_the_window_length_is_derived_from_the_thresholds_and_never_seeded(
    seed_weights,
) -> None:
    """§ Deliverable 2: `max(...) + 1` over five keys — retuning a threshold retunes it."""
    loaded = seed_weights["anterior_cingulate"]
    assert "window_len" not in loaded
    assert window_len(loaded) == max(loaded[k] for k in WINDOW_LEN_KEYS) + 1


def test_the_gate_carries_no_tunable(seed_weights) -> None:
    """Both arms of the veto are contractual; a weights key would invite loosening one."""
    assert seed_weights["basal_ganglia"] == {}


@pytest.mark.parametrize("node", NODES)
def test_every_threshold_defaults_high_enough_to_need_persistence(
    seed_weights, node: str
) -> None:
    """Ruling 16 (b): no detector may trip on a single tick."""
    loaded = seed_weights[node]
    for key in ("rut_ticks", "forming_ticks", "rework_window", "abandon_window", "mislead_window"):
        if key in loaded:
            assert loaded[key] >= 2, f"{node}.{key} would fire on one tick"


def test_the_tracked_seed_carries_no_project_memory_file_at_all(tracked_files) -> None:
    """The digest's project-memory ruling, re-based: the *tracked* seed writes nothing in it.

    Was "the tree exists and is empty on disk" (`the build specification (not in this mirror)` § Deliverable 1,
    folded: A1-12). Build 3's sleep graph writes `brain/projects/<slug>/memory/<node>/` on every
    run and the tree is gitignored precisely so it may, so a walk of the working tree reads a
    sleep run's state and a walk of the *index* cannot. The directory's existence is still
    asserted, by `test_the_rest_of_the_tree_exists` over `config.GENERATED_BRAIN_DIRS`.

    Non-vacuous by construction: the same `git ls-files` must still see `brain/nodes/*/weights.yaml`,
    so a command that stopped seeing the tree fails here rather than passing on an empty read.
    """
    assert [one for one in tracked_files if one.startswith("brain/projects/")] == []

    tracked = tracked_files
    seeds = [one for one in tracked if one.endswith("/weights.yaml")]
    assert len(seeds) == len(NODES), f"the command sees every seeded weights file: {seeds}"
    assert not [one for one in tracked if one.startswith("brain/projects/")]
