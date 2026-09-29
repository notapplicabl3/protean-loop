"""The episode writer: one file per task, `tick` records and runtime-authored `event` records.

`the build specification (not in this mirror)` § Deliverable 2's `EpisodeRecord` row — "One FILE per task
holding many records"; `episode_id` is `<task_id>:<tick>`, minted by the runtime; the dedupe key
is `(task, tick, kind, event_name)` — and § Deliverable 3, which names every `event` the runtime
writes: task start, lock reclamation, interrupt resolution, terminal, a losing terminal
condition, abandoned, reseeded.

**The hippocampus composes the `tick` record; the runtime writes it** (folded: S-3). That split
is why this module takes a finished `EpisodeRecord` and never builds one from state: a writer
that composed the record would be a second author of a node's output.

**`event` records share the file and the append-only rule.** Their key carries the event name,
so two different events at the same tick both land, and a replayed tick's re-emission of the
same event is the silent no-op every appended artifact gets.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from pathlib import Path
from typing import Any

from protean.brain.jsonl import append_keyed, read_lines
from protean.state.records import EpisodeRecord

#: The one file per task. Its directory is `brain/episodes/<task_id>/`.
EPISODES_FILENAME = "episodes.jsonl"


def episode_id(task: str, tick: int) -> str:
    """`<task_id>:<tick>` — minted by the runtime (§ Deliverable 2)."""
    return f"{task}:{tick}"


def dedupe_key(payload: Mapping[str, Any]) -> Hashable:
    """`(task, tick, kind, event_name)` (folded: T-5)."""
    name = payload.get("event_name")
    return (
        str(payload.get("task")),
        int(payload.get("tick", -1)),
        str(payload.get("kind")),
        None if name is None else str(name),
    )


def append_episode(path: Path, record: EpisodeRecord) -> EpisodeRecord | None:
    """Append one record unless its key is already committed. `None` means already there."""
    written = append_keyed(path, record.model_dump(mode="json"), key_fn=dedupe_key)
    return None if written is None else record


def read_episodes(path: Path) -> list[EpisodeRecord]:
    """Every record in this task's file, in order."""
    return [EpisodeRecord.model_validate(line) for line in read_lines(path)]


def recent_episodes(path: Path, window: int) -> list[EpisodeRecord]:
    """The last `window` records — what the runtime projects onto `HippocampusInput`.

    The window is `candidate_window` from `brain/nodes/hippocampus/weights.yaml`, so the number
    is data the node folder owns and not a literal here. Cross-task retrieval is build 3's; this
    file is one task's, so the projection is task-local by construction (folded: T-12).
    """
    if window <= 0:
        return []
    return read_episodes(path)[-window:]
