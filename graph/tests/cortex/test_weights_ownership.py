"""Every threshold has exactly one owner, and the router reads all three seats out of signals.

`the build specification (not in this mirror)` § Deliverable 6 → *The seat router* (folded: S-5): "the streak
and trap thresholds live in `brain/nodes/anterior_cingulate/weights.yaml` beside the detectors
that compute them, and `brain/nodes/cortex/weights.yaml` carries only the ladder counts —
`k_replan`, `k_redirect`, `manager_horizon`, `progress_window`. **`rut_ticks` exists in exactly
one file in the whole brain.**"

Builder-verified row M17, this order's half of it. `brain/` is read-only here — the seed tree is
W1's — so these are assertions about the tracked files rather than edits to them.
"""

from __future__ import annotations

from pathlib import Path

from protean import config
from protean.brain.folders import load_weights
from protean.cortex.layer import build_layer
from protean.cortex.scenario import script_path
from protean.cortex.scripts import load_script
from protean.mailbox.files import build as build_mailbox
from protean.runtime import engine
from protean.state.enums import (
    ANTERIOR_CINGULATE_WEIGHT_KEYS,
    CORTEX_WEIGHT_KEYS,
    TRAP_WEIGHT_KEYS,
    NodeName,
    Tier,
    TrapDetector,
)
from tests.runtime.stubs import seed_brain

TRACKED_BRAIN = Path(__file__).resolve().parents[2] / "brain"

#: The one key the SPEC singles out as existing in exactly one file in the whole brain.
RUT_TICKS = TRAP_WEIGHT_KEYS[TrapDetector.DISLODGING][0]


def _all_weights(root: Path) -> dict[str, dict]:
    return {
        node: dict(load_weights(config.node_dir(node, root) / "weights.yaml"))
        for node in config.NODE_ORDER
    }


def test_rut_ticks_exists_in_exactly_one_weights_file_in_the_whole_brain():
    owners = [
        node for node, weights in _all_weights(TRACKED_BRAIN).items() if RUT_TICKS in weights
    ]
    assert owners == [str(NodeName.ANTERIOR_CINGULATE)]


def test_the_cortex_weights_file_carries_only_the_four_ladder_counts():
    weights = load_weights(
        config.node_dir(str(NodeName.CORTEX), TRACKED_BRAIN) / "weights.yaml"
    )
    assert sorted(weights) == sorted(CORTEX_WEIGHT_KEYS)


def test_no_ladder_count_is_duplicated_into_the_monitors_file_or_the_other_way():
    all_weights = _all_weights(TRACKED_BRAIN)
    cortex = set(all_weights[str(NodeName.CORTEX)])
    monitor = set(all_weights[str(NodeName.ANTERIOR_CINGULATE)])
    assert cortex.isdisjoint(monitor), "one owner per threshold, never two"
    # `firing_threshold` is A.1's per-node key, owned by every firing-bearing folder and read by
    # no router, so it sits outside the trap-and-streak tuple by design (folded: D15-7).
    # `think_threshold` is A.2.i's static trigger key, outside the tuple the same way (E33).
    assert monitor - {"firing_threshold", "think_threshold"} == set(ANTERIOR_CINGULATE_WEIGHT_KEYS)


def test_every_key_the_router_reads_is_owned_by_exactly_one_file():
    all_weights = _all_weights(TRACKED_BRAIN)
    for key in (*CORTEX_WEIGHT_KEYS, *ANTERIOR_CINGULATE_WEIGHT_KEYS):
        owners = [node for node, weights in all_weights.items() if key in weights]
        assert len(owners) == 1, f"{key} is carried by {owners}"


def test_the_router_fires_all_three_seats_across_the_batterys_scenarios(
    tmp_path: Path, workspace: Path
):
    """Workspace signals alone reach every tier — no scenario names a tier and none counts calls.

    One task per brain root, so each scenario gets its own throwaway copy of the seed tree.
    """
    fired: set[str] = set()
    for index, (stem, goal) in enumerate(
        (
            ("stuck_ladder", "reconcile the ledger against the statement"),
            ("plan_and_execute", "write notes.md"),
        )
    ):
        root = seed_brain(TRACKED_BRAIN, tmp_path / f"brain-{index}")
        layer = build_layer(root=root, script=load_script(script_path(stem)))
        engine.start(
            root,
            goal,
            layer,
            mailbox=build_mailbox(root),
            workspace_path=str(workspace),
            task_id=f"task-m17-{index}",
            max_ticks=60,
        )
        fired.update(str(item.tier) for item in layer.router.selections)

    print(f"    [M17] tiers the router fired: {sorted(fired)}")
    assert fired == {str(tier) for tier in Tier}
