"""The episode writer: one file per task, `tick` records and runtime-authored `event` records.

`the build specification (not in this mirror)` § Deliverable 2's `EpisodeRecord` row — "One FILE per task
holding many records", `episode_id` is `<task_id>:<tick>`, dedupe key
`(task, tick, kind, event_name)` — and § Deliverable 3, which names every `event` the runtime
writes.

Builder-verified row M4's episode half. **The event name is half the key**, which is what lets
two different events at the same tick both land while a replayed tick's re-emission of one is
the silent no-op every appended artifact gets.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from protean import config
from protean.brain.episodes import (
    EPISODES_FILENAME,
    append_episode,
    dedupe_key,
    episode_id,
    read_episodes,
    recent_episodes,
)
from protean.state.enums import EpisodeKind, EventName
from protean.state.records import EpisodeRecord
from tests.brain.conftest import advance


def _tick_record(task: str = "task-e", tick: int = 1) -> EpisodeRecord:
    return EpisodeRecord(
        schema_version=config.EPISODE_SCHEMA_VERSION,
        episode_id=episode_id(task, tick),
        task=task,
        tick=tick,
        kind=EpisodeKind.TICK,
    )


def _event_record(name: EventName, task: str = "task-e", tick: int = 1) -> EpisodeRecord:
    return EpisodeRecord(
        schema_version=config.EPISODE_SCHEMA_VERSION,
        episode_id=episode_id(task, tick),
        task=task,
        tick=tick,
        kind=EpisodeKind.EVENT,
        event_name=name,
        detail={"why": str(name)},
    )


@pytest.fixture()
def episodes(tmp_path: Path) -> Path:
    return tmp_path / "episodes" / "task-e" / EPISODES_FILENAME


def test_the_episode_id_is_task_and_tick():
    assert episode_id("task-e", 4) == "task-e:4"


def test_the_dedupe_key_is_task_tick_kind_and_event_name():
    tick = _tick_record()
    event = _event_record(EventName.TERMINAL)
    assert dedupe_key(tick.model_dump(mode="json")) == ("task-e", 1, "tick", None)
    assert dedupe_key(event.model_dump(mode="json")) == ("task-e", 1, "event", "terminal")
    assert dedupe_key(event.model_dump(mode="json")) == event.dedupe_key()


def test_the_directory_is_created_on_demand(episodes: Path):
    assert not episodes.parent.exists()
    assert append_episode(episodes, _tick_record()) is not None
    assert episodes.exists()


def test_a_record_round_trips(episodes: Path):
    record = _tick_record()
    append_episode(episodes, record)
    assert read_episodes(episodes) == [record]


def test_one_file_holds_many_records(episodes: Path):
    for tick in (1, 2, 3):
        append_episode(episodes, _tick_record(tick=tick))
    assert [record.tick for record in read_episodes(episodes)] == [1, 2, 3]
    assert len(list(episodes.parent.iterdir())) == 1


def test_two_different_events_at_one_tick_both_land(episodes: Path):
    assert append_episode(episodes, _event_record(EventName.TERMINAL)) is not None
    assert append_episode(episodes, _event_record(EventName.TERMINAL_LOSER)) is not None
    assert [record.event_name for record in read_episodes(episodes)] == [
        EventName.TERMINAL,
        EventName.TERMINAL_LOSER,
    ]


def test_a_tick_record_and_an_event_at_one_tick_both_land(episodes: Path):
    append_episode(episodes, _tick_record())
    append_episode(episodes, _event_record(EventName.TERMINAL))
    assert [str(record.kind) for record in read_episodes(episodes)] == ["tick", "event"]


def test_a_replayed_record_is_a_silent_no_op(episodes: Path):
    record = _tick_record()
    append_episode(episodes, record)
    before = episodes.read_bytes()
    assert append_episode(episodes, record) is None
    assert episodes.read_bytes() == before


def test_the_file_is_append_only(episodes: Path):
    append_episode(episodes, _tick_record(tick=1))
    first = episodes.read_bytes()
    append_episode(episodes, _tick_record(tick=2))
    assert episodes.read_bytes().startswith(first)


def test_recent_episodes_is_the_tail_the_runtime_projects(episodes: Path):
    for tick in range(1, 6):
        append_episode(episodes, _tick_record(tick=tick))
    assert [record.tick for record in recent_episodes(episodes, 2)] == [4, 5]
    assert [record.tick for record in recent_episodes(episodes, 99)] == [1, 2, 3, 4, 5]
    assert recent_episodes(episodes, 0) == []
    assert recent_episodes(episodes, -1) == []


def test_a_missing_file_reads_as_no_records(tmp_path: Path):
    assert read_episodes(tmp_path / "absent.jsonl") == []
    assert recent_episodes(tmp_path / "absent.jsonl", 5) == []


def test_a_run_writes_one_tick_record_per_tick(started):
    """The hippocampus composes it, the runtime writes it — one writer, one file."""
    context, state, _router, _seat = started
    advance(context, state, 3)

    records = read_episodes(context.paths.episodes)
    ticks = [record.tick for record in records if record.kind is EpisodeKind.TICK]
    assert ticks == [1, 2, 3]
    assert all(record.task == "task-brain" for record in records)
    assert all(
        record.episode_id == episode_id(record.task, record.tick) for record in records
    )
