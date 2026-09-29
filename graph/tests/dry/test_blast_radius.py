"""M22: a dry run writes nothing outside its throwaway brain root and its temp workspace.

`the build specification (not in this mirror)` § Deliverable 7 -> *The brain root under test is always a
copy* and *The blast-radius assertion*, and § Directional decisions 17 and 20.

**By construction, then checked anyway.** `protean dry` materializes both trees under one temp
directory and removes it in a `finally`, so the repo cannot be written even if a tick raises.
The before/after tree hash below is not what makes that true -- it is what would catch it
having stopped being true, which is the only job an assertion over a construction has.

M22 is a **builder-verified default**, not a gate (§ DoD, second table). It is kept because it
was paid for: it is the one check that fails if a later change resolves the brain root anywhere
but through the variable, or copies the seed tree by reference, or forgets the teardown.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from protean import cli, config
from tests.conftest import REPO_ROOT
from tests.dry.conftest import DRY_SCENARIO, digest

TRACKED_BRAIN = REPO_ROOT / "brain"

#: The six generated sub-trees of a brain root, as `git ls-files` spells their paths. The same
#: set `protean.runtime.clone.BRAIN_GENERATED_PREFIXES` names, written here as path prefixes
#: because this module reads git's output and not a tree.
GENERATED_PREFIXES = (
    "brain/state/",
    "brain/episodes/",
    "brain/projects/",
    "brain/mailbox/open/",
    "brain/mailbox/orphaned/",
    "brain/archive/",
)


def tracked_brain_files() -> list[str]:
    """`git ls-files -- brain/` — the seed as the repository carries it, not as the disk holds it."""
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "--", "brain/"],
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(line for line in result.stdout.splitlines() if line.strip())


def test_the_repo_tree_hash_is_unchanged_across_a_dry_run(repo_digest, capsys, dry_run) -> None:
    """Row M22, over two runs: this test's own, bracketed by its own baseline, and the shared
    session run, bracketed by itself — so the claim holds whichever of the two ran first."""
    assert cli.main(["dry", DRY_SCENARIO]) == config.EXIT_DONE
    capsys.readouterr()
    after = digest(REPO_ROOT)
    changed = sorted(
        path
        for path in set(repo_digest) | set(after)
        if repo_digest.get(path) != after.get(path)
    )
    assert changed == [], f"a dry run wrote inside the checkout: {changed}"
    shared = sorted(
        path
        for path in set(dry_run.repo_before) | set(dry_run.repo_after)
        if dry_run.repo_before.get(path) != dry_run.repo_after.get(path)
    )
    assert shared == [], f"the shared dry run wrote inside the checkout: {shared}"


def test_the_digest_would_notice_a_write(repo_digest, tmp_path: Path) -> None:
    """The control: a digest that never changes proves nothing about what a run did."""
    planted = REPO_ROOT / "fixtures" / "workspaces" / ".blast-radius-probe"
    planted.write_text("probe\n", encoding="utf-8")
    try:
        assert digest(REPO_ROOT) != repo_digest
    finally:
        planted.unlink()
    assert digest(REPO_ROOT) == repo_digest, "and the probe left nothing behind either"


def test_the_brain_root_is_the_copy_and_never_the_tracked_tree(dry_run) -> None:
    """The root is resolved *through* `$PROTEAN_BRAIN`, the variable points at a temp copy, and
    both throwaway trees and the sandbox that held them are gone when the verb returns.

    Merged (audit rows N1 + N8) from three tests that each paid for their own
    `protean dry dry` and then asked one question of it — this module's
    `test_a_dry_run_leaves_no_temp_directory_behind` and `tests/dry/test_scripted_task.py`'s
    `test_both_throwaway_trees_are_destroyed_when_the_verb_returns`. Every assertion of all
    three is below, against the one shared run; the only line not carried twice is the second,
    byte-identical exit-code assertion, because there is now one run to assert about.

    The **"not under the checkout"** clause is M22's anchor and is kept verbatim.
    """
    assert dry_run.code == config.EXIT_DONE
    printed = dry_run.out
    line = next(item for item in printed.splitlines() if item.startswith("brain root:"))
    root = Path(line.split(": ", 1)[1].split(" — ")[0])

    assert root != TRACKED_BRAIN.resolve()
    assert TRACKED_BRAIN.resolve() not in root.parents
    assert REPO_ROOT not in root.parents, "the copy lives outside the checkout entirely"
    assert not root.exists(), "and it is destroyed when the verb returns"

    named = [item for item in printed.splitlines() if item.startswith(("brain root:", "workspace:"))]
    assert len(named) == 2, printed
    for item in named:
        path = Path(item.split(": ", 1)[1].split(" — ")[0])
        assert not path.exists(), f"{path} outlived the run"

    assert dry_run.temp_after <= dry_run.temp_before, (
        f"a sandbox outlived its run: {sorted(dry_run.temp_after - dry_run.temp_before)}"
    )


def test_the_copy_carries_the_seed_and_starts_its_generated_state_empty(tmp_path: Path) -> None:
    """What `_seed_root` hands the runtime: every node folder, seeded, with empty trace files."""
    root = cli._seed_root(tmp_path / "brain")
    assert sorted(path.name for path in (root / "nodes").iterdir()) == sorted(config.NODE_ORDER)
    for node in config.NODE_ORDER:
        folder = config.node_dir(node, root)
        for entry in config.NODE_FOLDER_ENTRIES:
            assert (folder / entry).exists(), f"{node}/{entry}"
        assert (folder / "trace.jsonl").read_text(encoding="utf-8") == "", node
        assert (folder / "NODE.md").read_bytes() == (
            TRACKED_BRAIN / "nodes" / node / "NODE.md"
        ).read_bytes(), "the seed is copied byte for byte"
    for relative in config.GENERATED_BRAIN_DIRS:
        assert (root / relative).is_dir(), relative


def test_the_tracked_seed_tree_tracks_no_task_state_of_its_own() -> None:
    """The standing consequence: the repo's own brain never *commits* a run's state (S-62).

    Re-based on `git ls-files` from a walk of the working tree (folded: S-62, ruling on
    dispatch-24 ledger D24-9, option 2): the live verb opens on the repo's own brain root by
    design and writes its checkpoints, journals and traces there, all of them gitignored, so the
    working-tree walk asserted the opposite of what the run is for. What must hold — and holds
    after a live run as well as before one — is that none of it is tracked.

    Non-vacuous by construction: the same call must show the node seeds, so a `git ls-files` that
    stopped seeing `brain/` fails here rather than passing on an empty list.
    """
    tracked = tracked_brain_files()
    assert tracked, "git ls-files sees nothing under brain/ at all"
    for node in config.NODE_ORDER:
        assert f"brain/nodes/{node}/NODE.md" in tracked, node
        assert f"brain/nodes/{node}/weights.yaml" in tracked, node

    for prefix in GENERATED_PREFIXES:
        found = [one for one in tracked if one.startswith(prefix)]
        assert found == [], f"{prefix} is tracked: {found}"
    traces = [one for one in tracked if one.endswith("/trace.jsonl")]
    assert traces == [], f"a per-node journal is tracked: {traces}"
