"""Builder row K8: the workspace clone carries only the local origin and only the tracked surface.

`the build specification (not in this mirror)` § Deliverable 5's *workspace* and *surface* paragraphs,
§ Directional decisions 17 (folded: A1-7, folded: A1-15), § Resolutions S-41 and S-59. Order W8
of `the work orders (not in this mirror)`, process step 11.

**K8 is the builder's own test list, never a gate** (the orders file's header). Row W7 is the
gate, and it closes on captured command output from the real run, not on anything here.

**The mechanism is proven on a synthetic checkout; the real workload gets one `live` case.**
A repository built in `tmp_path` with `~/workload`'s own gitignore shape is what makes "the clone
carries none of the maintainer-local paths" a claim about *cloning* rather than about one
machine's disk — and it costs nothing on every `uv run pytest`. The one case that clones
`~/workload` itself reaches outside the checkout, so it carries order W1's `live`
marker, which is the rule `tests/oracle/test_live_clone.py` already follows for the same reason.

**Zero model calls.** The only binary spawned in this module is `git`.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from protean.oracle.clone import tree_digest
from protean.runtime.clone import (
    BRAIN_GENERATED_GLOBS,
    BRAIN_GENERATED_PREFIXES,
    DEFAULT_BRANCH,
    DEFAULT_WORKLOAD,
    ORIGIN,
    WorkspaceError,
    brain_witness_digest,
    clone_workload,
    destroy,
    is_generated,
    moved,
    own_task_globs,
    own_task_items,
    remotes,
    witness_digest,
    witnessed_digests,
    workspace,
)
from tests.conftest import tagged_show
from tests.runtime.conftest import git

#: The five paths `~/workload/.gitignore:26-33` makes maintainer-local (folded: A1-15). A clone
#: carries none of them, which is what makes the workload's surface the tracked surface *by
#: construction* rather than by the executor being asked to leave them alone.
MAINTAINER_LOCAL = ("CLAUDE.md", "architecture-logic.md", "docs", "plans", "tools")


show = tagged_show("W8-clone")


@pytest.fixture(scope="module")
def source(tmp_path_factory) -> Path:
    """A checkout shaped like the workload: a tracked surface, and five ignored paths.

    **Read-only to every consumer**, and asserted so: each test clones it into a temp directory
    of its own, and `test_the_clone_is_a_copy_and_the_source_head_is_unmoved` re-reads the
    source's `HEAD` after the clone. Three git spawns for the module rather than per test.
    """
    root = tmp_path_factory.mktemp("workload") / "source"
    root.mkdir()
    git(root, "init", "--quiet", "--initial-branch", DEFAULT_BRANCH)

    (root / "README.md").write_text("# tracked\n", encoding="utf-8")
    (root / "architecture.md").write_text("# tracked\n", encoding="utf-8")
    (root / "setup").mkdir()
    (root / "setup" / "install.sh").write_text("echo tracked\n", encoding="utf-8")
    (root / ".gitignore").write_text(
        "\n".join(MAINTAINER_LOCAL[:2]) + "\n" + "\n".join(f"{one}/" for one in MAINTAINER_LOCAL[2:])
        + "\n",
        encoding="utf-8",
    )
    for name in MAINTAINER_LOCAL[:2]:
        (root / name).write_text("maintainer only\n", encoding="utf-8")
    for name in MAINTAINER_LOCAL[2:]:
        (root / name).mkdir()
        (root / name / "note.md").write_text("maintainer only\n", encoding="utf-8")

    git(root, "add", "-A")
    git(root, "commit", "--quiet", "-m", "the tracked surface")
    return root


# --------------------------------------------------------------------------------------
# K8, first half: only the local origin
# --------------------------------------------------------------------------------------


def test_the_clone_carries_exactly_one_remote_and_it_is_the_local_origin(
    source: Path, tmp_path: Path
) -> None:
    clone = clone_workload(source, into=tmp_path / "clone")
    named = remotes(clone)
    show("git remote -v", named)
    assert {row[0] for row in named} == {ORIGIN}, "one remote, and it is origin"
    assert {row[2] for row in named} == {"fetch", "push"}
    for _, url, _ in named:
        assert Path(url) == source, "the origin is the local source path"
        assert Path(url).is_dir(), "a filesystem path, so the clone cannot have used the network"
        assert "://" not in url, "no URL scheme anywhere in the remote"


def test_the_clone_is_on_the_branch_decision_17_fixes(source: Path, tmp_path: Path) -> None:
    clone = clone_workload(source, into=tmp_path / "clone")
    branch = git(clone, "rev-parse", "--abbrev-ref", "HEAD")
    show("branch", branch)
    assert branch == DEFAULT_BRANCH


def test_the_clone_is_a_copy_and_the_source_head_is_unmoved(source: Path, tmp_path: Path) -> None:
    before = git(source, "rev-parse", "HEAD")
    clone = clone_workload(source, into=tmp_path / "clone")
    assert git(clone, "rev-parse", "HEAD") == before
    assert git(source, "rev-parse", "HEAD") == before, "cloning wrote nothing into the source"
    assert clone.resolve() != source.resolve(), "never the workload itself"


def test_a_clone_that_came_back_with_a_foreign_remote_is_refused(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control: the refusal is real, and it takes the bad clone with it."""
    import protean.runtime.clone as module

    made: list[Path] = []
    real = module.remotes

    def lying(clone: Path):
        made.append(clone)
        return (*real(clone), ("upstream", "https://example.invalid/workload.git", "fetch"))

    monkeypatch.setattr(module, "remotes", lying)
    with pytest.raises(WorkspaceError, match="not the local origin"):
        module.clone_workload(source, into=tmp_path / "clone")
    assert made, "the check ran"
    assert not made[0].exists(), "and the refused clone was destroyed rather than left behind"


def test_a_source_that_is_not_a_checkout_is_refused(tmp_path: Path) -> None:
    (tmp_path / "not-a-repo").mkdir()
    with pytest.raises(WorkspaceError, match="not a git checkout"):
        clone_workload(tmp_path / "not-a-repo", into=tmp_path / "clone")


# --------------------------------------------------------------------------------------
# K8, second half: none of the maintainer-local paths
# --------------------------------------------------------------------------------------


def test_the_clone_carries_the_tracked_surface_and_none_of_the_maintainer_local_paths(
    source: Path, tmp_path: Path
) -> None:
    clone = clone_workload(source, into=tmp_path / "clone")
    present = sorted(one.name for one in clone.iterdir() if one.name != ".git")
    show("the clone's top level", present)
    for name in MAINTAINER_LOCAL:
        assert not (clone / name).exists(), f"{name} is maintainer-local and is not in a clone"
        assert (source / name).exists(), "and the control: it IS in the source"
    assert (clone / "README.md").exists() and (clone / "setup" / "install.sh").exists()


def test_the_executor_cannot_edit_a_maintainer_file_because_it_is_not_there(
    source: Path, tmp_path: Path
) -> None:
    """§ Deliverable 5's *by construction*, stated as the property it actually is."""
    clone = clone_workload(source, into=tmp_path / "clone")
    tracked = set(git(clone, "ls-files").splitlines())
    show("tracked in the clone", sorted(tracked))
    assert not tracked & {"CLAUDE.md", "architecture-logic.md"}
    assert not any(one.startswith(("docs/", "plans/", "tools/")) for one in tracked)


# --------------------------------------------------------------------------------------
# Lifetime
# --------------------------------------------------------------------------------------


def test_destroy_removes_the_workspace_whole(source: Path, tmp_path: Path) -> None:
    clone = clone_workload(source, into=tmp_path / "clone")
    assert clone.exists()
    destroy(clone)
    assert not clone.exists()
    destroy(clone), "and destroying a gone clone is not an error"


def test_the_context_manager_destroys_the_clone_even_when_the_block_raises(
    source: Path,
) -> None:
    seen: list[Path] = []
    with pytest.raises(ZeroDivisionError):
        with workspace(source) as clone:
            seen.append(clone)
            assert clone.exists()
            1 / 0
    assert seen and not seen[0].exists()
    assert not seen[0].parent.exists(), "the temp root goes too"


# --------------------------------------------------------------------------------------
# S-59: the witness digest is `tree_digest` with a caller-side exclusion
# --------------------------------------------------------------------------------------


@pytest.fixture()
def brain_root(tmp_path: Path) -> Path:
    """A brain root with one file in every generated sub-tree S-59 names, and seeds beside them."""
    root = tmp_path / "brain"
    for relative in (
        "seats.yaml",
        "seats/executor.md",
        "nodes/homeostasis/weights.yaml",
        "nodes/homeostasis/NODE.md",
        "semantic/policy_home.jsonl",
        "intake/manifest.yaml",
        "state/task-1/checkpoint.json",
        "episodes/task-1/episodes.jsonl",
        "projects/workload/notes.md",
        "mailbox/open/item.md",
        "mailbox/orphaned/old.md",
        "archive/workload-run-1/manifest.json",
        "nodes/homeostasis/trace.jsonl",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"seed for {relative}\n", encoding="utf-8")
    return root


def test_the_witness_digest_is_tree_digest_when_nothing_extra_is_excluded(
    brain_root: Path,
) -> None:
    """The reuse claim, as an equality rather than as a docstring."""
    assert witness_digest(brain_root) == tree_digest(brain_root)


def test_an_absent_tree_answers_the_same_way_tree_digest_does(tmp_path: Path) -> None:
    gone = tmp_path / "never-existed"
    assert witness_digest(gone) == tree_digest(gone) == f"absent:{gone}"


@pytest.mark.parametrize(
    "relative",
    [
        "state/task-1/new.json",
        "episodes/task-1/new.jsonl",
        "projects/workload/new.md",
        "mailbox/open/new.md",
        "mailbox/orphaned/new.md",
        "archive/workload-run-2/manifest.json",
        "nodes/homeostasis/trace.jsonl",
    ],
)
def test_the_run_s_own_generated_state_does_not_move_the_witness(
    brain_root: Path, relative: str
) -> None:
    before = brain_witness_digest(brain_root)
    path = brain_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("the runtime wrote this\n", encoding="utf-8")
    after = brain_witness_digest(brain_root)
    show(f"{relative} moved the whole-tree digest", tree_digest(brain_root) != before)
    assert after == before, f"{relative} is generated state and is outside the witness"


@pytest.mark.parametrize(
    "relative",
    [
        "seats.yaml",
        "seats/executor.md",
        "nodes/homeostasis/weights.yaml",
        "nodes/homeostasis/NODE.md",
        "semantic/policy_home.jsonl",
        "intake/manifest.yaml",
        "state-of-the-art.md",
        "semantic/state/nested.jsonl",
    ],
)
def test_a_write_to_a_seed_moves_the_witness(brain_root: Path, relative: str) -> None:
    """The control, and the reason the exclusion is anchored: `semantic/state/` is still a seed."""
    before = brain_witness_digest(brain_root)
    path = brain_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("something wrote here\n", encoding="utf-8")
    assert brain_witness_digest(brain_root) != before, f"{relative} is inside the witness"


def test_a_repointed_symlink_moves_the_witness(brain_root: Path) -> None:
    """S-51's hole, inherited: a symlink is hashed by the string it points at."""
    link = brain_root / "seats" / "current.md"
    link.symlink_to("executor.md")
    before = brain_witness_digest(brain_root)
    link.unlink()
    link.symlink_to("planner.md")
    assert brain_witness_digest(brain_root) != before


def test_is_generated_is_anchored_at_the_tree_root() -> None:
    assert is_generated(Path("state/task-1/checkpoint.json"), prefixes=BRAIN_GENERATED_PREFIXES)
    assert is_generated(Path("mailbox/open/item.md"), prefixes=BRAIN_GENERATED_PREFIXES)
    assert is_generated(Path("nodes/cortex/trace.jsonl"), globs=BRAIN_GENERATED_GLOBS)
    assert not is_generated(Path("semantic/state/x.jsonl"), prefixes=BRAIN_GENERATED_PREFIXES)
    assert not is_generated(Path("mailbox/answered/item.md"), prefixes=BRAIN_GENERATED_PREFIXES)
    assert not is_generated(Path("nodes/cortex/weights.yaml"), globs=BRAIN_GENERATED_GLOBS)


def test_the_four_witnesses_are_keyed_by_path_and_only_the_brain_root_is_filtered(
    brain_root: Path, tmp_path: Path
) -> None:
    other = tmp_path / "other"
    (other / "sub").mkdir(parents=True)
    (other / "sub" / "file.txt").write_text("x\n", encoding="utf-8")
    trees = [other, brain_root]

    before = witnessed_digests(trees, brain_root)
    assert set(before) == {str(other), str(brain_root)}
    assert before[str(other)] == tree_digest(other), "every tree but the brain root is whole"
    assert before[str(brain_root)] == brain_witness_digest(brain_root)

    (brain_root / "state" / "task-1" / "tick.json").write_text("{}\n", encoding="utf-8")
    assert moved(before, witnessed_digests(trees, brain_root)) == []

    (other / "sub" / "file.txt").write_text("y\n", encoding="utf-8")
    assert moved(before, witnessed_digests(trees, brain_root)) == [str(other)]


# --------------------------------------------------------------------------------------
# S-61: the witness modulo the run's own task's items
# --------------------------------------------------------------------------------------

#: The shape `protean.runtime.interrupts` writes: `<task_id>-t<tick>-<seat>.md`.
OWN_TASK = "task-20260907T152905915343"
OWN_ITEM = f"{OWN_TASK}-t4-executor.md"
FOREIGN_ITEM = "task-20260101T000000000000-t1-executor.md"


@pytest.fixture()
def mailbox_dir(tmp_path: Path) -> Path:
    """One open mailbox holding two items: this run's own interrupt, and a stranger's."""
    directory = tmp_path / "mailbox" / "open"
    directory.mkdir(parents=True)
    (directory / OWN_ITEM).write_text("## Question\nthe run's own\n", encoding="utf-8")
    (directory / FOREIGN_ITEM).write_text("## Question\nsomebody else's\n", encoding="utf-8")
    return directory


def test_excluding_the_runs_own_task_leaves_exactly_the_foreign_items_digest(
    mailbox_dir: Path,
) -> None:
    """D24-7's ruling, as the equality it rests on rather than as a claim about one run.

    The modulo digest is asserted against the digest of the directory *with the run's own item
    physically gone* — so "excluded" means the same thing here that it means to `tree_digest`,
    and an exclusion that silently swallowed the foreign item too would fail.
    """
    excluded = witness_digest(mailbox_dir, globs=own_task_globs(OWN_TASK))
    show("digest excluding the run's own item", excluded)
    assert excluded != tree_digest(mailbox_dir), "the whole-tree digest sees both items"

    (mailbox_dir / OWN_ITEM).unlink()
    show("digest of the foreign item alone   ", tree_digest(mailbox_dir))
    assert excluded == tree_digest(mailbox_dir)


def test_a_foreign_item_still_moves_the_witness_modulo_the_runs_own_task(
    mailbox_dir: Path,
) -> None:
    """The control: the exclusion is one task wide, and a stranger's write is still a breach."""
    globs = own_task_globs(OWN_TASK)
    before = witness_digest(mailbox_dir, globs=globs)
    (mailbox_dir / "task-20260101T000000000000-t2-executor.md").write_text(
        "x\n", encoding="utf-8"
    )
    assert witness_digest(mailbox_dir, globs=globs) != before

    another = mailbox_dir / f"{OWN_TASK}-t9-executor.md"
    another.write_text("y\n", encoding="utf-8")
    assert witness_digest(mailbox_dir, globs=globs) != before, (
        "the stranger's write is still inside the witness, whatever else was excluded"
    )


def test_own_task_items_names_the_files_the_run_itself_wrote(mailbox_dir: Path) -> None:
    assert own_task_items(mailbox_dir, OWN_TASK) == [OWN_ITEM]
    assert own_task_items(mailbox_dir, "task-20260101T000000000000") == [FOREIGN_ITEM]
    assert own_task_items(mailbox_dir, "task-nothing-matches-this") == []
    assert own_task_items(mailbox_dir.parent / "never-existed", OWN_TASK) == []


def test_the_brain_roots_own_items_are_already_outside_its_witness(brain_root: Path) -> None:
    """No double counting: S-59's exclusions drop these before S-61 is ever consulted.

    And the identification is by **file name**, never by containing directory — a task's
    `state/<task_id>/checkpoint.json` is its own state and is already outside the brain
    witness, but nothing about it is called "an item this task wrote into the mailbox".
    """
    for relative in (
        f"state/{OWN_TASK}/checkpoint.json",
        f"mailbox/open/{OWN_ITEM}",
        f"archive/{OWN_TASK}/manifest.json",
    ):
        path = brain_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("the runtime wrote this\n", encoding="utf-8")
    assert (
        own_task_items(
            brain_root,
            OWN_TASK,
            prefixes=BRAIN_GENERATED_PREFIXES,
            globs=BRAIN_GENERATED_GLOBS,
        )
        == []
    )
    assert own_task_items(brain_root, OWN_TASK) == [f"mailbox/open/{OWN_ITEM}"], (
        "the control: without S-59's exclusions the mailbox item IS found under the brain root"
    )


def test_witnessed_digests_grades_the_mailbox_modulo_the_runs_own_task(
    brain_root: Path, mailbox_dir: Path
) -> None:
    """The driver's call, both ways: raw is `tree_digest`, modulo drops this task's items."""
    trees = [mailbox_dir, brain_root]
    raw = witnessed_digests(trees, brain_root)
    modulo = witnessed_digests(trees, brain_root, exclude_task=OWN_TASK)

    assert raw[str(mailbox_dir)] == tree_digest(mailbox_dir), "nothing named, nothing excluded"
    assert modulo[str(mailbox_dir)] != raw[str(mailbox_dir)]
    assert modulo[str(mailbox_dir)] == witness_digest(
        mailbox_dir, globs=own_task_globs(OWN_TASK)
    )
    assert modulo[str(brain_root)] == raw[str(brain_root)] == brain_witness_digest(brain_root)


# --------------------------------------------------------------------------------------
# The real workload — outside the checkout, so it carries order W1's marker
# --------------------------------------------------------------------------------------


@pytest.mark.live
def test_a_real_clone_of_the_workload_holds_k8(tmp_path: Path) -> None:
    """K8 against `~/workload` itself. `live`-marked because it reaches outside the checkout."""
    if not (DEFAULT_WORKLOAD / ".git").is_dir():
        pytest.skip(f"{DEFAULT_WORKLOAD} is not a checkout on this machine")
    clone = clone_workload(DEFAULT_WORKLOAD, into=tmp_path / "clone")
    named = remotes(clone)
    show("git remote -v", named)
    assert {row[0] for row in named} == {ORIGIN}
    assert all(Path(url) == DEFAULT_WORKLOAD for _, url, _ in named)
    assert git(clone, "rev-parse", "--abbrev-ref", "HEAD") == DEFAULT_BRANCH
    for name in MAINTAINER_LOCAL:
        assert not (clone / name).exists(), f"{name} is maintainer-local"
    show("the clone's top level", sorted(one.name for one in clone.iterdir()))
    assert (clone / "README.md").exists(), "and the tracked surface IS there"


@pytest.mark.live
def test_cloning_the_workload_leaves_it_byte_unchanged(tmp_path: Path) -> None:
    """The receipt row W7 takes around the whole run, taken around the clone alone."""
    if not (DEFAULT_WORKLOAD / ".git").is_dir():
        pytest.skip(f"{DEFAULT_WORKLOAD} is not a checkout on this machine")
    before = tree_digest(DEFAULT_WORKLOAD)
    clone = clone_workload(DEFAULT_WORKLOAD, into=tmp_path / "clone")
    after = tree_digest(DEFAULT_WORKLOAD)
    show("workload digest before", before)
    show("workload digest after ", after)
    assert after == before
    assert os.access(clone, os.W_OK), "the clone is the writable one"
