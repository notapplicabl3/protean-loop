"""The fresh clone every measured session runs on, and the hashes that prove nothing else moved.

`the build specification (not in this mirror)` § Directional decisions 17 (folded: A1-7) — "`git clone
~/workload <tmp>` — local, tracked-content-only, no network, never `~/workload` itself"; § Deliverable 5's
workspace paragraph; § Deliverable 4's K6 receipts.

**One clone per session, destroyed after it.** Not one per task and not one per run: a session
that installed something, edited something or left a stale `.venv` would contaminate the next
repeat's step count, and step count is the whole measurement. The clone's lifetime is the
session's.

**No remote at all.** `git clone` leaves an `origin` pointing at the source, which decision 17's
"never adds a remote" rules out; `remove_remotes()` takes it off before the session opens
(dispatch-14 ledger D14-2). The disallowed set refuses `git fetch`/`pull`/`push`/`remote`
independently, so this is the second of two guards rather than the only one.

**The hash is of the whole tree, computed the same way for every one.** `tree_digest()` walks
real files and hashes relative path plus bytes, so a receipt over the three trees row K6 names —
the workload, this brain root and the policy home — before and after a run is a byte-level claim
rather than an mtime one. Generated caches are excluded by name because they change for reasons
that are not the session's; the exclusion list is short, explicit, and asserted by the tests.

**A symlink is hashed by the string it points at (S-51).** It used to be skipped, and a skipped
symlink is a hole in the receipt exactly where the policy home keeps most of its structure: a
session that re-pointed one changed what every reader of that tree resolves to and moved no
byte this digest was looking at. The target string is what the tree *says*, so following the
link — which would hash the same bytes twice and wander outside the tree — is not what happens.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Final

#: Directories whose contents change for reasons that are not a measured session's, and which
#: are therefore outside every before/after hash. Deliberately short: `.git` is excluded because
#: a clone rewrites its own refs, the three caches because merely importing a module writes
#: them, and `hooks/.logs` because the **orchestrating** session's hook log is appended on every
#: tool call, so the policy home's digest moves during any run for a reason no measured session
#: caused (S-53). Anything not named here is inside the receipt.
#:
#: An entry carrying a `/` is a path of consecutive segments, matched anywhere under the tree; a
#: bare name is matched against any single segment. `hooks/.logs` is written as a path rather
#: than as a bare `.logs` on purpose — a `.logs` directory a measured session created inside the
#: workload must still move the digest (ledger S1-8).
HASH_EXCLUDED_DIRS: Final[frozenset[str]] = frozenset(
    {".git", "__pycache__", ".pytest_cache", ".ruff_cache", "hooks/.logs"}
)

#: What a symlink contributes to the digest, in front of its target string, so a symlink named
#: `x` pointing at `y` can never collide with a regular file `x` whose contents are `y`.
SYMLINK_MARKER: Final[bytes] = b"symlink:"

#: Prefix for the throwaway directory a clone lands in.
CLONE_PREFIX: Final[str] = "protean-oracle-clone-"

#: The provisioning step every session's task begins from (folded: S-29). The oracle does **not**
#: run it — the session does, and the steps it takes to find it are part of the measurement.
#: The constant exists so the tests can assert the oracle never runs it.
PROVISIONING_COMMAND: Final[tuple[str, ...]] = ("uv", "sync", "--offline")


class CloneError(RuntimeError):
    """A clone could not be made, or could not be stripped of its remote."""


def _run(argv: Sequence[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(argv), cwd=None if cwd is None else str(cwd), capture_output=True, text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise CloneError(
            f"{' '.join(argv)} exited {completed.returncode}: "
            f"{(completed.stderr or completed.stdout).strip()[:400]}"
        )
    return completed


def head_sha(tree: Path) -> str:
    """The tree's `HEAD`, which is what `OracleReport.tree_sha` carries."""
    return _run(["git", "-C", str(tree), "rev-parse", "HEAD"]).stdout.strip()


def remove_remotes(clone: Path) -> tuple[str, ...]:
    """Strip every remote off a fresh clone and return the names removed.

    Decision 17's "never adds a remote", enforced rather than trusted: `git clone` adds `origin`
    unconditionally, so a clone that kept it would carry a fetchable pointer at `~/workload` into a
    tool-bearing session.
    """
    listed = _run(["git", "-C", str(clone), "remote"]).stdout.split()
    for name in listed:
        _run(["git", "-C", str(clone), "remote", "remove", name])
    assert not _run(["git", "-C", str(clone), "remote"]).stdout.split()
    return tuple(listed)


def make_clone(source: Path, into: Path | None = None) -> Path:
    """`git clone <source> <tmp>` — local, no network, branch as it stands, then no remote.

    `source` is a path and never a URL: the whole point of decision 17 is that the measurement
    never reaches the network, and `git clone` over a filesystem path cannot.
    """
    destination = Path(tempfile.mkdtemp(prefix=CLONE_PREFIX)) if into is None else into
    target = destination / "clone" if into is None else destination
    _run(["git", "clone", "--quiet", str(source), str(target)])
    remove_remotes(target)
    return target


def destroy_clone(clone: Path) -> None:
    """Remove the clone whole. Called on every path out of a session, including a failure."""
    shutil.rmtree(clone, ignore_errors=True)


@contextmanager
def fresh_clone(source: Path):
    """One clone for the life of one session, destroyed on the way out however it ends."""
    root = Path(tempfile.mkdtemp(prefix=CLONE_PREFIX))
    clone = root / "clone"
    try:
        _run(["git", "clone", "--quiet", str(source), str(clone)])
        remove_remotes(clone)
        yield clone
    finally:
        destroy_clone(root)


def is_excluded(relative: Path) -> bool:
    """Does this tree-relative path sit under one of the excluded directories?"""
    parts = relative.parts
    for entry in HASH_EXCLUDED_DIRS:
        if "/" not in entry:
            if entry in parts:
                return True
            continue
        needle = tuple(entry.split("/"))
        span = len(needle)
        if any(parts[at : at + span] == needle for at in range(len(parts) - span + 1)):
            return True
    return False


def _hashable_entries(tree: Path) -> Iterable[tuple[Path, bytes]]:
    """Every path inside the receipt, with the bytes it contributes, in sorted order.

    A symlink contributes `symlink:<target>` and is never followed (S-51); a regular file
    contributes its bytes. Directories contribute nothing of their own — their existence is
    already carried by the relative paths beneath them.
    """
    for path in sorted(tree.rglob("*")):
        relative = path.relative_to(tree)
        if is_excluded(relative):
            continue
        if path.is_symlink():
            yield relative, SYMLINK_MARKER + os.readlink(path).encode("utf-8")
        elif path.is_file():
            yield relative, path.read_bytes()


def tree_digest(tree: Path) -> str:
    """A byte-level digest of a whole tree: relative path plus contents, in sorted order.

    K6's receipt. Not a git hash: one of the three witnessed trees is a repo whose policy files
    are untracked, and another holds generated state no index knows about, so the claim has to
    be over the filesystem rather than over what git happens to track.
    """
    digest = hashlib.sha256()
    if not tree.exists():
        return f"absent:{tree}"
    for relative, payload in _hashable_entries(tree):
        digest.update(str(relative).encode("utf-8"))
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
    return digest.hexdigest()


def digests_of(trees: Sequence[Path]) -> dict[str, str]:
    """One digest per named tree, keyed by its absolute path — a before/after receipt."""
    return {str(tree): tree_digest(tree) for tree in trees}


__all__: Sequence[str] = (
    "CLONE_PREFIX",
    "HASH_EXCLUDED_DIRS",
    "PROVISIONING_COMMAND",
    "SYMLINK_MARKER",
    "CloneError",
    "destroy_clone",
    "digests_of",
    "fresh_clone",
    "head_sha",
    "is_excluded",
    "make_clone",
    "remove_remotes",
    "tree_digest",
)
