"""Row W8's archive half: one directory per terminal, hashed, with the product beside the state.

`the build specification (not in this mirror)` § Deliverable 6 → *The archive*, § Directional decisions 20,
§ Named assumptions 12, § Resolutions A1-17, S-35 and S-41. Builder row **K10** — the builder's
own test list, not a gate.

**Every terminal, driven through the shipping driver.** The five cases below reach `done`,
`interrupted`, `blocked`, `stopped` and `stuck` through `protean.runtime.engine.start()` with
scripted seats — no pre-seeded terminal field and no call into a private — because what S-35
binds is that the *driver* archives, not that a function called `archive_run` works.

**The verification is checked against a control.** A manifest that always verifies would prove
nothing, so three cases tamper with an archive — a changed byte, a deleted file, an extra file —
and each must be caught.

**The product is proven by restoring it.** The bundle is cloned back into a third directory and
the run's commit is read out of it, because "a `git bundle` was written" is a claim about a file
and "the branch survives" is the claim S-35 actually makes.

**Zero model calls.** The seats are hand-written responders and the only binary spawned anywhere
in this module is `git`.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from protean import config
from protean.runtime import engine
from protean.runtime.archive import (
    BUNDLE_FILENAME,
    HASHES_FILENAME,
    MANIFEST_FILENAME,
    NOTES_FILENAME,
    PATCHES_DIRNAME,
    PRODUCT_DIRNAME,
    ArchiveVerificationFailed,
    archive_run,
    archives,
    attach,
    is_repository_root,
    read_manifest,
    run_commits,
    sha256,
    verify,
)
from protean.runtime.paths import BrainPaths
from protean.runtime.report import REPORT_FILENAME
from protean.runtime.seat import SeatSelection
from protean.state.enums import (
    CallType,
    Escalation,
    InterruptKind,
    Raiser,
    TerminalState,
    Tier,
)
from protean.state.interrupts import InterruptRequest
from protean.state.seats import DirectorDirection, ManagerPlan
from tests.conftest import tagged_show
from tests.runtime import stubs
from tests.runtime.conftest import git

REPO_ROOT = Path(__file__).resolve().parents[2]


show = tagged_show("W8-archive")


# --------------------------------------------------------------------------------------
# Five terminals, one driver
# --------------------------------------------------------------------------------------


def _question(text: str) -> InterruptRequest:
    return InterruptRequest(
        kind=InterruptKind.QUESTION, raised_by=Raiser.MANAGER, question=text
    )


def _plans(**fields):
    return lambda request: ManagerPlan(tick=request.workspace.tick, **fields)


def _redirects(request) -> DirectorDirection:
    return DirectorDirection(
        tick=request.workspace.tick, redirect_of=request.workspace.goals[0].id
    )


#: Terminal → (the planner's answer, the director's answer, which tier the router picks).
TERMINALS = {
    TerminalState.DONE: (
        lambda request: ManagerPlan(
            tick=request.workspace.tick, goals_satisfied=[request.workspace.goals[0].id]
        ),
        None,
        Tier.MANAGER,
    ),
    TerminalState.INTERRUPTED: (
        lambda request: ManagerPlan(
            tick=request.workspace.tick, interrupt=_question("which directory?")
        ),
        None,
        Tier.MANAGER,
    ),
    TerminalState.BLOCKED: (
        lambda request: ManagerPlan(
            tick=request.workspace.tick,
            goals_satisfied=[request.workspace.goals[0].id],
            interrupt=_question("is this really done?"),
        ),
        None,
        Tier.MANAGER,
    ),
    TerminalState.STOPPED: (_plans(), None, Tier.MANAGER),
    TerminalState.STUCK: (_plans(), _redirects, Tier.DIRECTOR),
}


def _layer_for(terminal: TerminalState):
    """The router/port pair one terminal's scenario is driven through — the `TERMINALS` row."""
    planner, director, tier = TERMINALS[terminal]
    seat = stubs.StubSeat(
        responder=stubs.request_keyed(
            {
                str(Tier.MANAGER): planner,
                str(CallType.DISPATCH): lambda request: {
                    "tick": 0, "unit_id": request.unit.id, "narrative": "-"
                },
                str(Tier.DIRECTOR): director
                or (lambda request: {"tick": request.workspace.tick}),
            }
        )
    )
    router = stubs.StubRouter(
        rule=lambda _workspace: SeatSelection(
            tier=tier, escalation=Escalation.EMPTY_UNIT_STACK
        )
    )
    return stubs.layer(router, seat)


@pytest.fixture()
def scripted(brain: Path, workspace: Path, mailbox):
    """A scripted run against a throwaway brain root, driven to whichever terminal is asked."""

    def _run(terminal: TerminalState, *, workspace_path: str | None = None):
        if terminal is TerminalState.STOPPED:
            stubs.set_weight(brain, "homeostasis", max_ticks=1)
        return engine.start(
            brain,
            f"reach {terminal}",
            _layer_for(terminal),
            mailbox=mailbox,
            workspace_path=str(workspace) if workspace_path is None else workspace_path,
            max_ticks=30,
        )

    return _run


@pytest.mark.parametrize("terminal", sorted(TERMINALS, key=str))
def test_the_archive_lands_on_every_one_of_the_five_terminals(
    scripted, brain: Path, terminal: TerminalState
) -> None:
    """S-35, the whole clause: `done` is not special and a partial run is archived too."""
    outcome = scripted(terminal)
    landed = archives(brain)
    show(f"{terminal} archives", [path.name for path in landed])

    assert outcome.terminal is terminal, "the scenario reached the terminal it was written for"
    assert len(landed) == 1, "one terminal, one archive directory"
    assert landed[0].name.startswith("workload-run-")
    assert landed[0].parent == BrainPaths(root=brain).archive
    notes = json.loads((landed[0] / NOTES_FILENAME).read_text(encoding="utf-8"))
    assert notes["terminal"] == str(terminal), "and it records which terminal it fired on"
    assert any(str(landed[0]) in message for message in outcome.messages)


def test_the_archive_carries_everything_deliverable_6_names(scripted, brain: Path) -> None:
    outcome = scripted(TerminalState.DONE)
    directory = archives(brain)[0]
    held = sorted(
        str(path.relative_to(directory)) for path in directory.rglob("*") if path.is_file()
    )
    show("archived files", held)

    paths = BrainPaths(root=brain).task(outcome.task_id)
    assert f"state/{paths.checkpoint.name}" in held, "the checkpoints"
    assert any(name.startswith("state/journal-") for name in held), "the journals"
    assert f"state/{REPORT_FILENAME}" in held, "the WorkloadRunReport"
    assert "episodes/episodes.jsonl" in held, "the task's episodes"
    for node in config.NODE_ORDER:
        assert f"nodes/{node}/trace.jsonl" in held, f"all six trace.jsonl — {node}"
    assert (directory / MANIFEST_FILENAME).is_file(), "and the manifest sits at the root"


def test_the_seat_call_record_is_archived_with_the_rest_of_the_state(
    brain: Path, scripted
) -> None:
    """§ Deliverable 6 names `seat_calls.jsonl` among the archive's contents.

    The scripted seats above have no `calls()` seam, so the run writes none; the file is written
    here as the boundary would write it and the archive is re-taken over it.
    """
    outcome = scripted(TerminalState.DONE)
    paths = BrainPaths(root=brain).task(outcome.task_id)
    paths.seat_calls.write_text('{"schema_version":1}\n', encoding="utf-8")
    result = archive_run(brain, outcome.task_id, terminal=outcome.terminal)
    archived = result.directory / "state" / paths.seat_calls.name
    show("archived seat calls", str(archived.relative_to(result.directory)))
    assert archived.read_bytes() == paths.seat_calls.read_bytes()
    assert str(archived.relative_to(result.directory)) in result.manifest
    assert not any("no seat_calls" in note for note in result.notes)


def test_the_archived_bytes_are_the_bytes_the_run_wrote(scripted, brain: Path) -> None:
    """A copy, not a summary (§ Named assumptions 12): byte for byte, live against archived."""
    outcome = scripted(TerminalState.INTERRUPTED)
    directory = archives(brain)[0]
    paths = BrainPaths(root=brain).task(outcome.task_id)
    for live, archived in (
        (paths.checkpoint, directory / "state" / paths.checkpoint.name),
        (paths.episodes, directory / "episodes" / paths.episodes.name),
        (paths.trace(config.CORTEX_NODE), directory / "nodes" / config.CORTEX_NODE / "trace.jsonl"),
    ):
        show(f"{archived.name} digest", sha256(archived))
        assert archived.read_bytes() == live.read_bytes()


def test_a_second_terminal_adds_a_directory_and_deletes_nothing(
    scripted, brain: Path, mailbox
) -> None:
    """"never delete a previous one" (§ Named assumptions 12): a second terminal is a second
    directory, and the first one's bytes are untouched."""
    scripted(TerminalState.INTERRUPTED)
    first = archives(brain)[0]
    first_manifest = read_manifest(first)

    mailbox.answer(mailbox.open_ids()[0], "put it in docs/")
    outcome = engine.resume(
        brain, _layer_for(TerminalState.DONE), mailbox=mailbox, max_ticks=3
    )
    landed = archives(brain)
    show("archives after two terminals", [path.name for path in landed])

    assert outcome.terminal is TerminalState.DONE
    assert len(landed) == 2, "one directory per terminal, never one replaced"
    assert first.exists(), "the first archive survives the second run"
    assert read_manifest(first) == first_manifest, "byte for byte"
    assert verify(landed[1]), "and the second verifies on its own"


# --------------------------------------------------------------------------------------
# The manifest, and the control that proves the verification is not vacuous
# --------------------------------------------------------------------------------------


def test_the_manifest_names_every_file_and_every_digest_re_computes(
    scripted, brain: Path
) -> None:
    """Row K10: the archive verifies. Both directions — nothing missing, nothing unlisted."""
    scripted(TerminalState.DONE)
    directory = archives(brain)[0]
    manifest = read_manifest(directory)
    show("manifest entries", len(manifest))

    assert manifest, "a manifest with no entries would verify vacuously"
    assert MANIFEST_FILENAME not in manifest, "the manifest does not hash itself"
    for name, digest in manifest.items():
        assert (directory / name).exists(), name
        assert sha256(directory / name) == digest, name
    assert verify(directory) == manifest, "and the shipping verifier agrees"


def _change_a_byte(directory: Path) -> None:
    target = directory / "state" / "checkpoint.json"
    target.write_text(target.read_text(encoding="utf-8") + " ", encoding="utf-8")


def _delete_a_file(directory: Path) -> None:
    (directory / "episodes" / "episodes.jsonl").unlink()


def _plant_an_unlisted_file(directory: Path) -> None:
    (directory / "planted.txt").write_text("not in the manifest\n", encoding="utf-8")


#: The three ways an archive can stop verifying, and the word the refusal names each by.
TAMPERS = (
    ("a_changed_byte", _change_a_byte, "re-compute"),
    ("a_deleted_file", _delete_a_file, "missing"),
    ("a_file_the_manifest_never_named", _plant_an_unlisted_file, "unmanifested"),
)


@pytest.mark.parametrize(
    ("tamper", "expected"),
    [(tamper, expected) for _id, tamper, expected in TAMPERS],
    ids=[identifier for identifier, _tamper, _expected in TAMPERS],
)
def test_verification_catches(scripted, brain: Path, tamper, expected: str) -> None:
    """The control that proves row K10's verification is not vacuous — each arm its own archive."""
    scripted(TerminalState.DONE)
    directory = archives(brain)[0]
    tamper(directory)
    with pytest.raises(ArchiveVerificationFailed) as raised:
        verify(directory)
    show(f"{expected} refusal", str(raised.value)[:120])
    assert expected in str(raised.value)


# --------------------------------------------------------------------------------------
# The product: a bundle and a patch series, out of a real clone
# --------------------------------------------------------------------------------------


def test_the_run_s_own_commits_are_the_ones_no_remote_carries(shared_clone: Path) -> None:
    clone = shared_clone
    commits = run_commits(clone)
    show("run commits", commits)
    assert len(commits) == 1, "the upstream commit is on a remote-tracking ref, not the run's"
    assert git(clone, "log", "-1", "--format=%s", commits[0]) == "the run's work"


def test_a_work_tree_with_no_remote_and_no_base_claims_nothing(tmp_path: Path) -> None:
    """The control for the reading above: no base, no claim — never the whole history."""
    lonely = tmp_path / "lonely"
    lonely.mkdir()
    subprocess.run(["git", "init", "-q", str(lonely)], check=True)
    (lonely / "a.txt").write_text("a\n", encoding="utf-8")
    git(lonely, "add", "-A")
    git(lonely, "commit", "-qm", "only commit")
    show("no-remote commits", run_commits(lonely))
    assert run_commits(lonely) == ()
    assert len(run_commits(lonely, base_ref="HEAD~0")) == 0


def test_a_directory_that_is_not_a_work_tree_root_is_refused(tmp_path: Path, clone: Path) -> None:
    """A sub-directory of a checkout would otherwise report that checkout's changes as the run's."""
    inside = clone / "sub"
    inside.mkdir()
    assert is_repository_root(clone)
    assert not is_repository_root(inside)
    assert not is_repository_root(tmp_path / "nothing-here")


def test_the_bundle_restores_the_branch_and_the_series_carries_the_diff(
    scripted, brain: Path, shared_clone: Path, tmp_path: Path
) -> None:
    """S-35's actual claim: the branch survives the clone being thrown away."""
    clone = shared_clone
    scripted(TerminalState.DONE, workspace_path=str(clone))
    directory = archives(brain)[0]
    bundle = directory / PRODUCT_DIRNAME / BUNDLE_FILENAME
    patches = sorted((directory / PRODUCT_DIRNAME / PATCHES_DIRNAME).glob("*.patch"))
    show("bundle bytes", bundle.stat().st_size)
    show("patch series", [path.name for path in patches])

    assert bundle.exists(), "the product is bundled"
    assert len(patches) == 1, "one commit, one patch"
    assert "answer.txt" in patches[0].read_text(encoding="utf-8")

    restored = tmp_path / "restored"
    subprocess.run(["git", "clone", "-q", str(bundle), str(restored)], check=True)
    log = git(restored, "log", "--oneline", "--all")
    show("restored log", log)
    assert "the run's work" in log, "the branch is readable on a machine that never saw the clone"

    manifest = read_manifest(directory)
    assert str(bundle.relative_to(directory)) in manifest, "and both are hashed"
    assert str(patches[0].relative_to(directory)) in manifest


def test_a_run_with_no_clone_archives_the_rest_and_says_so(scripted, brain: Path) -> None:
    """A dry or scripted run has no product; that is an ordinary shape, not a refusal."""
    scripted(TerminalState.DONE, workspace_path="")
    directory = archives(brain)[0]
    notes = json.loads((directory / NOTES_FILENAME).read_text(encoding="utf-8"))
    show("no-workspace notes", notes["notes"])
    assert any("no workspace" in note for note in notes["notes"])
    assert not (directory / PRODUCT_DIRNAME).exists()
    assert verify(directory), "the rest is still archived and still verifies"


# --------------------------------------------------------------------------------------
# The two places another order fills
# --------------------------------------------------------------------------------------


def test_the_hashes_file_is_the_place_order_w8_writes_s41_s_four_hashes(
    brain: Path, scripted
) -> None:
    """S-41: the run driver captures the four before/after hashes; this module holds the place."""
    outcome = scripted(TerminalState.DONE)
    taken = {"workload": "a" * 64, "brain": "b" * 64, "mailbox": "c" * 64, "policy": "d" * 64}
    result = archive_run(brain, outcome.task_id, terminal=outcome.terminal, hashes=taken)
    written = json.loads((result.directory / HASHES_FILENAME).read_text(encoding="utf-8"))
    show("hashes.json", sorted(written))
    assert written == taken
    assert HASHES_FILENAME in result.manifest, "and it is hashed like everything else"


def test_the_oracle_report_is_copied_when_the_run_has_one(
    brain: Path, scripted, tmp_path: Path
) -> None:
    outcome = scripted(TerminalState.DONE)
    report = tmp_path / "oracle-report.json"
    report.write_text(json.dumps({"run_id": "r1"}), encoding="utf-8")
    result = archive_run(
        brain, outcome.task_id, terminal=outcome.terminal, oracle_report=report
    )
    copied = result.directory / "oracle" / report.name
    show("archived oracle report", copied.relative_to(result.directory))
    assert copied.read_bytes() == report.read_bytes()
    assert str(copied.relative_to(result.directory)) in result.manifest


def test_attach_puts_the_post_terminal_facts_in_and_the_archive_still_verifies(
    brain: Path, scripted, tmp_path: Path
) -> None:
    """S-58: `close_out()` runs before the after-hashes and the grading exist, so they arrive later.

    The archive is minted with neither — the shape `engine._drive()` actually produces, which
    passes no `hashes` and no `oracle_report` — and the driver attaches all three afterwards.
    The manifest is **rewritten**, because `verify()` refuses a file it never named.
    """
    outcome = scripted(TerminalState.DONE)
    result = archive_run(brain, outcome.task_id, terminal=outcome.terminal)
    assert HASHES_FILENAME not in result.manifest, "the terminal step could not have had them"

    hashes = tmp_path / HASHES_FILENAME
    hashes.write_text(json.dumps({"trees_that_moved": []}), encoding="utf-8")
    report = tmp_path / "oracle-20260101-000000Z.json"
    report.write_text(json.dumps({"run_id": "post"}), encoding="utf-8")
    summary = tmp_path / "oracle-summary.json"
    summary.write_text(json.dumps({"accepted": False}), encoding="utf-8")

    manifest = attach(
        result.directory,
        {
            HASHES_FILENAME: hashes,
            f"oracle/{report.name}": report,
            "oracle-summary.json": summary,
        },
    )
    show("attached", sorted(set(manifest) - set(result.manifest)))
    assert set(manifest) - set(result.manifest) == {
        HASHES_FILENAME, f"oracle/{report.name}", "oracle-summary.json"
    }
    assert (result.directory / f"oracle/{report.name}").read_bytes() == report.read_bytes()
    assert verify(result.directory) == manifest, "and the re-manifested archive re-verifies"
    for name, digest in result.manifest.items():
        assert manifest[name] == digest, f"attach changed nothing already archived: {name}"


def test_attach_refuses_a_source_that_is_not_there(brain: Path, scripted, tmp_path: Path) -> None:
    """A short manifest is not a shape the driver should learn about from a missing line."""
    outcome = scripted(TerminalState.DONE)
    result = archive_run(brain, outcome.task_id, terminal=outcome.terminal)
    with pytest.raises(FileNotFoundError):
        attach(result.directory, {HASHES_FILENAME: tmp_path / "never-written.json"})
    assert verify(result.directory) == result.manifest, "and the archive is untouched"


def test_attach_refuses_a_directory_that_is_not_an_archive(tmp_path: Path) -> None:
    with pytest.raises(ArchiveVerificationFailed, match="no archive to attach to"):
        attach(tmp_path / "not-there", {})


def test_the_archive_directory_is_gitignored_in_this_checkout(brain: Path) -> None:
    """"It stays gitignored — it carries `~/workload` content and real cost numbers"."""
    probe = "brain/archive/workload-run-probe/manifest.json"
    ignored = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "-v", probe],
        capture_output=True, text=True, check=False,
    )
    show("check-ignore", ignored.stdout.strip())
    assert ignored.returncode == 0, "brain/archive/ is not ignored in this checkout"
