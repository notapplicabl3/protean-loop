"""Fixtures for the mailbox battery: a throwaway brain root, a file mailbox, a scripted layer.

`the build specification (not in this mirror)` § Deliverable 5 and § Deliverable 7. Every test here runs
against a **copy** of the tracked seed tree in a temp directory — the repo's own `brain/` is
read-only to this battery, the same rule `protean dry` enforces by construction for a scenario
run — and every assertion about a mailbox item is made against the file on disk rather than
against the model that produced it.

Two helpers live here because two modules each had their own copy: `item()`, the `Interrupt`
both the format and the port batteries assert against, and `committed_prediction_keys()`, the
comprehension that makes a `ref` assertion non-vacuous by pinning it to a prediction the folder
actually committed.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

from protean import config
from protean.cortex.layer import build_layer
from protean.cortex.scenario import script_path
from protean.cortex.scripts import load_script
from protean.mailbox.files import FileMailbox, build
from protean.runtime.engine import build_context, new_state
from protean.state.enums import InterruptKind, Raiser
from protean.state.interrupts import Interrupt
from tests.runtime.stubs import seed_brain

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The seat script this battery drives: a run whose executor asks the operator one question.
QUESTION_SCRIPT = "asks_a_question"

#: The unit and predicate that script mints, so a test can name them without minting an id.
UNIT_ID = "u-q1"
EXPECTATION_ID = "e-q1"


@pytest.fixture()
def brain(tmp_path: Path) -> Path:
    """A throwaway brain root seeded from the tracked tree."""
    return seed_brain(REPO_ROOT / "brain", tmp_path / "brain")


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """The task's throwaway workspace — created and destroyed with the test."""
    path = tmp_path / "workspace"
    path.mkdir()
    return path


@pytest.fixture()
def mailbox(brain: Path) -> FileMailbox:
    """The mailbox layer under test, over the throwaway root."""
    return build(brain)


@pytest.fixture()
def layer(brain: Path):
    """A scripted seat layer whose executor raises one `question` interrupt."""
    return build_layer(root=brain, script=load_script(script_path(QUESTION_SCRIPT)))


@pytest.fixture()
def started(brain: Path, workspace: Path, layer, mailbox: FileMailbox):
    """A task opened at tick 0: its context and its state, before any tick has run."""
    context = build_context(
        brain, "task-mailbox", layer, mailbox=mailbox, workspace_path=str(workspace)
    )
    state = new_state("task-mailbox", "settle the ledger question", context)
    return context, state


@pytest.fixture()
def open_dir(brain: Path) -> Path:
    """`brain/mailbox/open/` — the directory M12's listings are taken of."""
    return brain / "mailbox" / "open"


def listing(directory: Path) -> list[str]:
    """The directory listing M12's check reads: filenames, sorted, or nothing at all."""
    if not directory.exists():
        return []
    return sorted(path.name for path in directory.iterdir())


def item(**overrides) -> Interrupt:
    """One `Interrupt` in the shape this battery asserts against; every field is overridable.

    The seven front-matter keys are spelled once, here, so a schema move lands in one place
    rather than in each module's own copy of the payload.
    """
    payload = {
        "schema_version": config.MAILBOX_SCHEMA_VERSION,
        "id": "task-x-t1-planner",
        "kind": InterruptKind.QUESTION,
        "raised_by": Raiser.MANAGER,
        "task": "task-x",
        "tick": 1,
        "raised_at": "2026-09-06T21:23:00+00:00",
        "question": "which ledger?",
    }
    payload.update(overrides)
    return Interrupt(**payload)


def committed_prediction_keys(records: Iterable[dict]) -> set[str]:
    """The `ref` keys a folder actually committed — what makes a `ref` assertion non-vacuous.

    `append_trace()` refuses an outcome whose `ref` names no committed key, so a test that
    asserts a landed answer's `ref` has to read the predictions back to say the assertion could
    have failed.
    """
    return {
        f"{record['task']}:{record['tick']}:{record['node']}:{record['tier']}:prediction"
        for record in records
        if record["kind"] == "prediction"
    }
