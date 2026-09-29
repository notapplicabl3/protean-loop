"""The advisory instance lock: one process per brain root, reclaimed loudly when it is dead.

`the build specification (not in this mirror)` § Deliverable 3 → *The instance lock*: "An advisory file at
the brain root carrying pid, start time and task id, taken at task start and released on every
exit path — the interrupt path included. A second run exits non-zero naming the holder. **A
dead-pid lock is reclaimed, and the reclamation is printed and written as an `event`
`EpisodeRecord`, never silent.**"

Builder-verified row M19. **The lock is deliberately not a versioned artifact** (decision 12):
it is inspected for a pid, never loaded as a contract, so a corrupt lock is stale rather than a
refusal — the one place in the build where a malformed file does not raise.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from protean import config
from protean.brain.episodes import read_episodes
from protean.runtime import lock
from protean.runtime.cycle import run_tick
from protean.runtime.engine import build_context, new_state, record_lock_reclamation
from protean.runtime.errors import LockHeld
from protean.runtime.paths import BrainPaths
from protean.state.enums import EpisodeKind, EventName

#: A pid no process can hold. `os.kill(0, 0)` is not a lookup, so 0 is never "live" here.
DEAD_PID = 0


@pytest.fixture()
def lock_path(brain: Path) -> Path:
    return BrainPaths(root=brain).lock


def test_the_lock_lands_at_the_config_name_carrying_pid_task_and_start_time(
    brain: Path, lock_path: Path
):
    """Where one acquisition puts the file, and what that same file carries."""
    assert lock_path == brain / config.LOCK_FILENAME
    acquisition = lock.acquire(lock_path, "task-1")
    assert lock_path.exists()

    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    assert payload["pid"] == os.getpid() == acquisition.holder.pid
    assert payload["task_id"] == "task-1"
    assert payload["started_at"] == acquisition.holder.started_at
    assert acquisition.reclaimed is False


def test_a_second_instance_is_refused_by_name_and_leaves_the_holders_file_untouched(
    lock_path: Path
):
    """One refusal, read twice: what it names, and what it did not write."""
    lock.acquire(lock_path, "task-1")
    before = lock_path.read_bytes()
    with pytest.raises(LockHeld) as raised:
        lock.acquire(lock_path, "task-2")

    message = str(raised.value)
    assert str(os.getpid()) in message
    assert "task-1" in message
    assert str(lock_path) in message
    assert raised.value.pid == os.getpid()
    assert raised.value.task_id == "task-1"

    assert lock_path.read_bytes() == before


def test_a_dead_pid_lock_is_reclaimed_and_the_message_names_the_dead_holder(lock_path: Path):
    """One reclamation, read twice: the acquisition it produced, and the message it prints."""
    lock.acquire(lock_path, "task-dead", pid=DEAD_PID)
    acquisition = lock.acquire(lock_path, "task-live")

    assert acquisition.reclaimed is True
    assert acquisition.reclaimed_from is not None
    assert acquisition.reclaimed_from.pid == DEAD_PID
    assert acquisition.reclaimed_from.task_id == "task-dead"
    assert json.loads(lock_path.read_text(encoding="utf-8"))["task_id"] == "task-live"

    message = acquisition.message()
    assert str(DEAD_PID) in message
    assert "task-dead" in message
    assert str(lock_path) in message


def test_a_clean_acquisition_has_no_message(lock_path: Path):
    assert lock.acquire(lock_path, "task-1").message() == ""


#: The three files that do not read as a holder: corrupt bytes, a missing field, and no file.
UNREADABLE = (
    ("corrupt", "{not json"),
    ("missing_a_field", '{"pid": 1}'),
    ("absent", None),
)


@pytest.mark.parametrize(
    "body",
    [body for _id, body in UNREADABLE],
    ids=[identifier for identifier, _body in UNREADABLE],
)
def test_a_lock_that_does_not_read_as_a_holder_is_stale_not_a_refusal(
    lock_path: Path, body: str | None
):
    """Decision 12: the lock is inspected for a pid, never loaded as a contract.

    Corrupt bytes, a lock missing a field and no lock at all are the same case — there is no
    holder — and it is the one place in the build where a malformed file is stale rather than a
    refusal: the acquisition that follows succeeds, reclaims nothing, and writes its own task.
    """
    if body is not None:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(body, encoding="utf-8")
    assert lock.read_holder(lock_path) is None

    acquisition = lock.acquire(lock_path, "task-1")
    assert acquisition.reclaimed is False
    assert json.loads(lock_path.read_text(encoding="utf-8"))["task_id"] == "task-1"


def test_a_lock_that_lands_between_the_check_and_the_write_is_refused_not_clobbered(
    lock_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The check-then-write window (AUDIT 2026-09-19 D2): a holder that appears after the
    absence check must be named, and its file left exactly as it wrote it."""
    rival = json.dumps({"pid": os.getpid(), "task_id": "task-rival", "started_at": "t0"})
    real_read = lock.read_holder
    calls = {"n": 0}

    def rival_wins_inside_the_window(path: Path):
        calls["n"] += 1
        if calls["n"] == 1:
            assert real_read(path) is None, "the window opens on an absent lock"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rival, encoding="utf-8")
            return None
        return real_read(path)

    monkeypatch.setattr(lock, "read_holder", rival_wins_inside_the_window)
    with pytest.raises(LockHeld) as raised:
        lock.acquire(lock_path, "task-late", pid=os.getpid() + 1)
    assert raised.value.task_id == "task-rival"
    assert lock_path.read_text(encoding="utf-8") == rival


def test_release_is_idempotent(lock_path: Path):
    lock.acquire(lock_path, "task-1")
    lock.release(lock_path)
    lock.release(lock_path)
    assert not lock_path.exists()


def test_the_context_manager_releases_on_a_clean_exit(lock_path: Path):
    with lock.held(lock_path, "task-1") as acquisition:
        assert acquisition.holder.task_id == "task-1"
        assert lock_path.exists()
    assert not lock_path.exists()


def test_the_context_manager_releases_on_a_raise(lock_path: Path):
    """"released on every exit path — the interrupt path included"."""
    with pytest.raises(RuntimeError):
        with lock.held(lock_path, "task-1"):
            raise RuntimeError("the interrupt path")
    assert not lock_path.exists()


def test_a_second_context_manager_over_a_live_lock_refuses(lock_path: Path):
    with lock.held(lock_path, "task-1"):
        with pytest.raises(LockHeld):
            with lock.held(lock_path, "task-2"):
                pass
    assert not lock_path.exists()


# --------------------------------------------------------------------------------------
# The reclamation is written, not only printed
# --------------------------------------------------------------------------------------


def test_a_reclamation_lands_as_an_event_episode_record(brain: Path, lock_path: Path):
    lock.acquire(lock_path, "task-dead", pid=DEAD_PID)
    acquisition = lock.acquire(lock_path, "task-live")

    record = record_lock_reclamation(brain, "task-live", acquisition)
    assert record is not None
    assert record.kind is EpisodeKind.EVENT
    assert record.event_name is EventName.LOCK_RECLAIMED
    assert record.detail["from_pid"] == DEAD_PID
    assert record.detail["from_task"] == "task-dead"
    assert record.detail["message"] == acquisition.message()

    on_disk = read_episodes(BrainPaths(root=brain).task("task-live").episodes)
    assert [item.event_name for item in on_disk] == [EventName.LOCK_RECLAIMED]


def test_a_clean_acquisition_writes_no_event(brain: Path, lock_path: Path):
    acquisition = lock.acquire(lock_path, "task-live")
    assert record_lock_reclamation(brain, "task-live", acquisition) is None
    assert not BrainPaths(root=brain).task("task-live").episodes.exists()


def test_the_reclamation_is_keyed_to_the_committed_tick(brain: Path, workspace: Path, layer):
    """A reclaimed `resume` records the event at the tick the task actually reached."""
    seat_layer, _router, _seat = layer
    context = build_context(
        brain, "task-live", seat_layer, workspace_path=str(workspace)
    )
    state = new_state("task-live", "write out.txt", context)
    for _ in range(2):
        state.tick += 1
        run_tick(context, state)

    path = BrainPaths(root=brain).lock
    lock.acquire(path, "task-live", pid=DEAD_PID)
    record = record_lock_reclamation(brain, "task-live", lock.acquire(path, "task-live"))
    assert record is not None
    assert record.tick == 2
    assert record.episode_id == "task-live:2"


def test_the_reclamation_event_does_not_collide_with_the_ticks_own_record(
    brain: Path, workspace: Path, layer
):
    """Its key carries the event name, so it lands beside the tick record at the same tick."""
    seat_layer, _router, _seat = layer
    context = build_context(brain, "task-live", seat_layer, workspace_path=str(workspace))
    state = new_state("task-live", "write out.txt", context)
    state.tick += 1
    run_tick(context, state)

    path = BrainPaths(root=brain).lock
    lock.acquire(path, "task-live", pid=DEAD_PID)
    record_lock_reclamation(brain, "task-live", lock.acquire(path, "task-live"))

    records = read_episodes(context.paths.episodes)
    at_tick_one = [item for item in records if item.tick == 1]
    assert {item.kind for item in at_tick_one} == {EpisodeKind.TICK, EpisodeKind.EVENT}


def test_the_lock_is_outside_the_versioned_artifact_set(lock_path: Path):
    """Decision 12: no loader parses it as a contract, so it carries no `schema_version`."""
    lock.acquire(lock_path, "task-1")
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    assert "schema_version" not in payload
    assert config.LOCK_FILENAME not in config.ARTIFACT_SCHEMA_VERSIONS
