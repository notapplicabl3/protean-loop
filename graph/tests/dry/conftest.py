"""Fixtures for the dry battery: the repo's own tree hash, and the hand-authored trace.

`the build specification (not in this mirror)` § Deliverable 7 -> *The blast-radius assertion*. The digest
below is what "a before/after tree hash of the repo" means concretely: content hashes of every
authored file under the checkout, with the caches that churn on their own excluded, so a run
that wrote one byte anywhere it does not own changes the digest and fails the row.

Nothing here constructs a contract or a scenario -- both are read from the hand-authored files
under `fixtures/`, which is the point of the row: a trace the battery generated would prove
that the run equals itself.

`dry_run` is the second thing here: one session-scoped `protean dry dry`, shared by every
read-only case of this battery (audit row N1). Its own docstring names what does not share it.
"""

from __future__ import annotations

import hashlib
import io
import os
from contextlib import redirect_stdout
from pathlib import Path
from typing import NamedTuple

import pytest
import yaml

from protean import cli
from tests.conftest import REPO_ROOT

#: The scenario `protean dry` runs, and the two fixture files that describe it.
DRY_SCENARIO = "dry"
SCENARIO_DIR = REPO_ROOT / "fixtures" / "scenarios" / DRY_SCENARIO
WORKSPACE_SEED = REPO_ROOT / "fixtures" / "workspaces" / DRY_SCENARIO

#: Directories whose contents change without anyone authoring them. Excluding them is what
#: makes the digest a signal rather than noise; nothing the runtime writes lives in one.
CHURNING_DIRS = frozenset(
    {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "deltas", "handoffs"}
)


def digest(root: Path) -> dict[str, str]:
    """Every authored file under `root`, mapped to the hash of its bytes."""
    tree: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or CHURNING_DIRS.intersection(path.parts):
            continue
        tree[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return tree


@pytest.fixture()
def repo_digest() -> dict[str, str]:
    """The checkout's tree hash, taken before a dry run and compared after it."""
    return digest(REPO_ROOT)


class DryRun(NamedTuple):
    """One whole `protean dry dry`, driven through the operator surface as a shell would."""

    #: The process exit code the verb returned.
    code: int
    #: Everything the verb printed, captured off `sys.stdout`.
    out: str
    #: The `protean-dry-*` sandboxes under the temp root before the run, and after it.
    temp_before: frozenset[str]
    temp_after: frozenset[str]
    #: The checkout's digest before the run, and after it — the shared run brackets itself, so
    #: the blast-radius claim holds whichever test happens to build this fixture first.
    repo_before: dict[str, str]
    repo_after: dict[str, str]


def sandboxes() -> frozenset[str]:
    """The names of every `protean-dry-*` sandbox sitting under the temp root right now."""
    return frozenset(
        path.name for path in Path(os.environ.get("TMPDIR", "/tmp")).glob("protean-dry-*")
    )


@pytest.fixture(scope="session")
def dry_run() -> DryRun:
    """The one scripted run the read-only cases of this battery share.

    Every consumer below reads the run and writes nothing back into it, so eight separate
    `cli.main(["dry", DRY_SCENARIO])` calls bought eight copies of one answer (audit row N1).
    `capsys` is function-scoped and cannot reach here, so stdout is captured with
    `redirect_stdout` instead — the same bytes the shell would see.

    **What does NOT share it, and why.** `test_the_repo_tree_hash_is_unchanged_across_a_dry_run`
    keeps its own run bracketed by its own `repo_digest` baseline: its claim is about what a run
    wrote, so a baseline taken after some earlier run would measure the wrong interval (audit
    row N10). This run brackets itself the same way (`repo_before` / `repo_after`) so that claim
    also covers it, in whatever order the modules are collected. The two cases that monkeypatch
    `$PROTEAN_BRAIN` keep their own runs too, because the environment they borrow is the thing
    under test.
    """
    before = sandboxes()
    repo_before = digest(REPO_ROOT)
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = cli.main(["dry", DRY_SCENARIO])
    return DryRun(
        code=code,
        out=buffer.getvalue(),
        temp_before=before,
        temp_after=sandboxes(),
        repo_before=repo_before,
        repo_after=digest(REPO_ROOT),
    )


@pytest.fixture(scope="session")
def expected_trace() -> dict:
    """`fixtures/scenarios/dry/expected.yaml` -- the hand-authored shape of the climb."""
    return yaml.safe_load((SCENARIO_DIR / "expected.yaml").read_text(encoding="utf-8"))
