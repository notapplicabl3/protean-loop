"""The task workspace: a local clone of the workload, and the witness digest the run hashes.

`the build specification (not in this mirror)` § Deliverable 5's *workspace* paragraph, § Directional
decisions 17 (folded: A1-7, folded: A1-15), § Resolutions S-41 and S-59; order W8 of
`the work orders (not in this mirror)`, builder row K8.

**`git clone <source> <tmp>` — local, branch `main`, no network, never the workload itself.**
`source` is a filesystem path and never a URL, which is what makes "no network" a property of
the call rather than a promise about it. The clone supplies the task workspace used by dispatch workers, and it is destroyed after the archive has taken the bundle and the patch series.

**The origin stays.** This is the one place this build's two clone modules differ, and the
difference is deliberate. `protean.oracle.clone` strips every remote off a measured session's
clone, because a measured session is a stranger and a fetchable pointer at the workload is one
capability more than it needs. Here the origin is *evidence*: DoD row W7 closes on a captured
`git remote -v` "naming only the local origin", and `protean.runtime.archive.run_commits()`
derives the run's own commits as `rev-list HEAD --not --remotes`, which answers nothing at all
in a repository with no remote (folded: D16-6). A local-path origin cannot reach the network,
and a dispatch kind's closed grant licenses none of `git remote`, `fetch`, `pull` or `push`.
The interpreter limitations of that grant remain documented in `cortex/live/invoke.py`;
the origin itself is not a containment boundary.

**The witness digest is `tree_digest` with a caller-side exclusion** (folded: S-59). Row W7's
second witness is `~/protean/brain/` *outside the task's own generated state*: a run writes its
checkpoints, journals, episodes, traces, mailbox and archive by design, and a digest of the
whole brain root would move on every run for the one reason that is not a breach. So the
generated sub-trees are named here and excluded at the caller, and
`protean.oracle.clone.HASH_EXCLUDED_DIRS` — which speaks about caches, not about the runtime —
is left alone. `brain/semantic/` stays **inside** the receipt: it is a seed the run must not
write.

**And the same exclusion, once more, for the run's own interrupt** (folded: S-61, ruling on
dispatch-24 ledger D24-7, option 1). The open mailbox directory is witnessed *whole*, so the one
item a terminal of `interrupted` is contractually required to write moves it. `exclude_task`
grades that witness modulo the files the run's own task named — the presence of that item being
itself a receipt (decision 11, contract 4) — and leaves every other write inside it.

**No model is called and no binary but `git` is named.** `tests/test_zero_calls.py`'s static
half greps this module like every other one outside the two licensed packages.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from protean.oracle.clone import SYMLINK_MARKER, is_excluded, tree_digest
from protean.runtime.archive import GIT, GIT_TIMEOUT_SECONDS, run_git

#: The workload § Deliverable 5 names, resolved from the home directory rather than written as
#: one absolute literal — the same resolution `tests/oracle/test_live_clone.py` uses, so this
#: module says "the sibling checkout" rather than "this disk".
DEFAULT_WORKLOAD: Final[Path] = Path("~/workload").expanduser()

#: The branch decision 17 fixes. A clone that landed on some other default would measure a tree
#: the baselines were never taken over.
DEFAULT_BRANCH: Final[str] = "main"

#: Prefix for the throwaway directory the workspace lands in. Distinct from the oracle's, so a
#: leftover directory says which of the two made it.
WORKSPACE_PREFIX: Final[str] = "protean-workspace-"

#: The one remote a workspace clone may carry, and the only name `git clone` creates.
ORIGIN: Final[str] = "origin"

#: The generated sub-trees of a brain root, relative to it and **anchored at it** — a `state`
#: directory a seed grew under `semantic/` must still move the digest. Order matches S-59's own
#: list: the task state, the episodes, the project memories, the two mailbox halves the runtime
#: writes, and the archive the terminal step mints.
BRAIN_GENERATED_PREFIXES: Final[tuple[str, ...]] = (
    "state",
    "episodes",
    "projects",
    "mailbox/open",
    "mailbox/orphaned",
    "archive",
)

#: The per-node journal the runtime appends to every tick. Excluded by shape rather than by
#: name, because the node set is `config.NODE_ORDER`'s and this module does not own it.
BRAIN_GENERATED_GLOBS: Final[tuple[str, ...]] = ("nodes/*/trace.jsonl",)


class WorkspaceError(RuntimeError):
    """A workspace clone could not be made, or came back carrying something it must not."""


def _git(*arguments: str) -> subprocess.CompletedProcess[str]:
    """One bounded `git` call **outside** any repository — the clone itself, and nothing else.

    Every read *inside* a clone goes through `protean.runtime.archive.run_git`, which is this
    package's one git seam. `git clone` is the single call that has no `-C <workspace>` to make,
    because the workspace does not exist yet.
    """
    completed = subprocess.run(  # noqa: S603 - a fixed binary and a fixed argument list
        [GIT, *arguments],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0:
        raise WorkspaceError(
            f"git {' '.join(arguments)} exited {completed.returncode}: "
            f"{(completed.stderr or completed.stdout).strip()[:400]}"
        )
    return completed


def remotes(clone: Path) -> tuple[tuple[str, str, str], ...]:
    """`git remote -v` as `(name, url, kind)` triples — row W7's first capture, parsed.

    Returned rather than printed: the row closes on captured output, and the driver writes that
    output down verbatim beside this.
    """
    result = run_git(clone, "remote", "-v")
    if not result.ok:
        return ()
    rows: list[tuple[str, str, str]] = []
    for line in result.out.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            rows.append((parts[0], parts[1], parts[2].strip("()")))
    return tuple(rows)


#: The reads that make up a clone's own account of what happened to it — row W7's "no push and
#: no merge" half. `ORIG_HEAD` and `FETCH_HEAD` are `rev-parse`d rather than read as files, so an
#: absent one comes back as a recorded refusal rather than as a missing key: `ORIG_HEAD` is what a
#: merge, rebase or reset writes and `FETCH_HEAD` is what a fetch writes, so both being absent is
#: the positive evidence that neither happened.
AUDIT_READS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("remote_verbose", ("remote", "-v")),
    ("reflog", ("reflog", "--date=iso")),
    ("orig_head", ("rev-parse", "--verify", "--quiet", "ORIG_HEAD")),
    ("fetch_head", ("rev-parse", "--verify", "--quiet", "FETCH_HEAD")),
    ("head", ("rev-parse", "HEAD")),
    ("branch", ("rev-parse", "--abbrev-ref", "HEAD")),
    ("branches", ("branch", "--all")),
    ("status", ("status", "--porcelain")),
)


def audit(clone: Path) -> dict[str, dict[str, object]]:
    """Every read of `AUDIT_READS`, captured as `(ok, out, error)` — row W7's HYBRID receipt.

    Captured rather than asserted: the row closes on command output, and a function that decided
    "no push happened" would be substituting its own verdict for the output the row asks for.
    """
    return {
        name: {"ok": result.ok, "out": result.out, "error": result.error}
        for name, result in (
            (name, run_git(clone, *arguments)) for name, arguments in AUDIT_READS
        )
    }


def clone_workload(
    source: Path | None = None,
    *,
    into: Path | None = None,
    branch: str = DEFAULT_BRANCH,
) -> Path:
    """`git clone --branch <branch> <source> <tmp>` — local, no network, origin kept.

    Refuses on the way out rather than trusting the call: a clone whose origin is anything but
    the local source path would be a network-reachable pointer inside a tool-bearing session,
    and that is the one thing decision 17 exists to prevent.
    """
    workload = (source or DEFAULT_WORKLOAD).expanduser()
    if not (workload / ".git").is_dir():
        raise WorkspaceError(f"{workload} is not a git checkout: there is nothing to clone")
    destination = Path(tempfile.mkdtemp(prefix=WORKSPACE_PREFIX)) if into is None else into
    target = destination / "clone" if into is None else destination
    _git("clone", "--quiet", "--branch", branch, str(workload), str(target))

    named = remotes(target)
    unexpected = [row for row in named if row[0] != ORIGIN or Path(row[1]) != workload]
    if unexpected:
        destroy(target)
        raise WorkspaceError(f"the clone carries a remote that is not the local origin: {named}")
    return target


def destroy(clone: Path) -> None:
    """Remove the workspace whole. Called on every path out, including a failure."""
    shutil.rmtree(clone, ignore_errors=True)


@contextmanager
def workspace(
    source: Path | None = None, *, branch: str = DEFAULT_BRANCH
) -> Iterator[Path]:
    """One clone for the life of one block, destroyed on the way out however it ends.

    **The run does not use this.** Its clone has to outlive `engine.start()` — the archive takes
    the bundle at the terminal step and the post-change oracle then clones *from* it — so the
    driver owns that lifetime explicitly. This is here for everything shorter than a run: the
    S-40 refusal probe, and any test that wants a real clone and no leftovers.
    """
    root = Path(tempfile.mkdtemp(prefix=WORKSPACE_PREFIX))
    try:
        yield clone_workload(source, into=root / "clone", branch=branch)
    finally:
        destroy(root)


# --------------------------------------------------------------------------------------
# The witness digest — `tree_digest` minus the runtime's own generated state (S-59)
# --------------------------------------------------------------------------------------


def is_generated(
    relative: Path,
    *,
    prefixes: Sequence[str] = BRAIN_GENERATED_PREFIXES,
    globs: Sequence[str] = BRAIN_GENERATED_GLOBS,
) -> bool:
    """Is this tree-relative path part of what the runtime writes rather than what it reads?

    Prefixes are **anchored at the tree root**, unlike `protean.oracle.clone.is_excluded`'s
    bare-name matching: `state` means `brain/state/`, and a `state` directory anywhere else is
    inside the receipt.
    """
    parts = relative.parts
    for entry in prefixes:
        needle = tuple(entry.split("/"))
        if parts[: len(needle)] == needle:
            return True
    return any(relative.match(pattern) for pattern in globs)


def witness_digest(
    tree: Path,
    *,
    prefixes: Sequence[str] = (),
    globs: Sequence[str] = (),
) -> str:
    """`protean.oracle.clone.tree_digest`'s protocol, with a caller-side exclusion on top.

    Byte-for-byte the same walk, the same sort, the same `symlink:<target>` marker and the same
    `path\\0payload\\0` framing — so with an empty exclusion this returns exactly what
    `tree_digest()` returns, which is the equality `tests/runtime/test_clone.py` asserts rather
    than this docstring claiming it. What the exclusion adds is S-59's second witness: the brain
    root outside the task's own generated state.
    """
    digest = hashlib.sha256()
    if not tree.exists():
        return f"absent:{tree}"
    for path in sorted(tree.rglob("*")):
        relative = path.relative_to(tree)
        if is_excluded(relative) or is_generated(relative, prefixes=prefixes, globs=globs):
            continue
        if path.is_symlink():
            payload = SYMLINK_MARKER + os.readlink(path).encode("utf-8")
        elif path.is_file():
            payload = path.read_bytes()
        else:
            continue
        digest.update(str(relative).encode("utf-8"))
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
    return digest.hexdigest()


def brain_witness_digest(brain_root: Path) -> str:
    """Row W7's second witness: `brain/` outside the task's own state (folded: S-59).

    `brain/semantic/` is deliberately **in**: it is a seed the run must not write, and a digest
    that excused it would excuse the one write there that would matter.
    """
    return witness_digest(
        brain_root, prefixes=BRAIN_GENERATED_PREFIXES, globs=BRAIN_GENERATED_GLOBS
    )


def own_task_globs(task_id: str) -> tuple[str, ...]:
    """The one glob that matches every file this task itself named (folded: S-61).

    The mailbox contract writes its items as `<task_id>-t<tick>-<seat>.md`, so a task's own
    files are identified by the prefix on their *name* and by nothing else. `PurePath.match`
    matches from the right, so one bare pattern reaches every depth of the tree.
    """
    return (f"{task_id}*",)


def own_task_items(
    tree: Path,
    task_id: str,
    *,
    prefixes: Sequence[str] = (),
    globs: Sequence[str] = (),
) -> list[str]:
    """The tree-relative names, **inside this tree's witness**, that this task itself wrote.

    `prefixes` and `globs` are the exclusions the tree's own digest already applies, and passing
    them is what keeps this from double-counting: the brain root's `state/`, `mailbox/open/` and
    `archive/` are outside `brain_witness_digest` to begin with, so the brain root reports the
    empty list here and its digest needs no modulo view at all. The open mailbox directory,
    digested whole, reports the run's interrupt item.
    """
    if not tree.exists():
        return []
    found: list[str] = []
    for path in sorted(tree.rglob("*")):
        if not (path.is_file() or path.is_symlink()):
            continue
        relative = path.relative_to(tree)
        if is_excluded(relative) or is_generated(relative, prefixes=prefixes, globs=globs):
            continue
        if path.name.startswith(task_id):
            found.append(str(relative))
    return found


def witnessed_digests(
    trees: Sequence[Path], brain_root: Path, *, exclude_task: str | None = None
) -> dict[str, str]:
    """One digest per witnessed tree, keyed by absolute path — the before/after receipt.

    The brain root takes the witness digest; every other tree takes `tree_digest` whole. Four
    trees, before the first tick and after the terminal (folded: S-41).

    **`exclude_task` is S-61's modulo view.** A run that ends `interrupted` writes one mailbox
    item by contract (decision 11, contract 4), so the open-mailbox witness moves for the one
    reason that is not a breach — the same shape S-59 already gives the brain root. Passing the
    run's own task id drops the files *that task* named and leaves every other write inside the
    receipt. With `exclude_task=None` this returns exactly what it always did: `witness_digest`
    with an empty exclusion **is** `tree_digest`, which `tests/runtime/test_clone.py` asserts as
    an equality rather than claiming here.
    """
    globs = own_task_globs(exclude_task) if exclude_task else ()
    return {
        str(tree): (
            brain_witness_digest(tree)
            if tree.resolve() == brain_root.resolve()
            else witness_digest(tree, globs=globs)
        )
        for tree in trees
    }


def moved(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """The trees whose digests changed. An empty list is row W7's containment receipt."""
    return sorted(key for key in before if before[key] != after.get(key))


__all__: Sequence[str] = (
    "BRAIN_GENERATED_GLOBS",
    "BRAIN_GENERATED_PREFIXES",
    "DEFAULT_BRANCH",
    "DEFAULT_WORKLOAD",
    "AUDIT_READS",
    "ORIGIN",
    "WORKSPACE_PREFIX",
    "WorkspaceError",
    "audit",
    "brain_witness_digest",
    "clone_workload",
    "destroy",
    "is_generated",
    "moved",
    "own_task_globs",
    "own_task_items",
    "remotes",
    "witness_digest",
    "witnessed_digests",
    "workspace",
)
