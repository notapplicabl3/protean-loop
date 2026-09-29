"""Row W2's resume-and-replay half, run in a **genuinely new process**.

`the build specification (not in this mirror)` § Deliverable 1 → *Sessions*, and DoD row **W2**:

* "the three handles are checkpointed in `BrainState.seat_sessions` and reused across a resume
  **in a new process** without minting" — a second interpreter, a second `build()`, a second
  session book, and nothing carried over in memory;
* "a replayed tick restores the journalled envelope and **spawns no process**" — this process
  runs with `tests/shim/claude` first on its `PATH`, so anything that reached for the binary
  would be logged and would exit 89 rather than answering.

**It is not a test module and pytest never collects it.** The parent case in
`test_live_seat.py` runs it with `sys.executable`, hands it the paths on argv, and reads the
JSON it writes. Everything it asserts, it asserts by *reporting* — the parent owns the
assertions, because a child that judged itself could exit 0 for the wrong reason.

**It restores through the runtime's own two lines** (`engine.resume`: build the layer, then
`layer.sessions.restore(task_id, state.seat_sessions)`) and replays through the runtime's own
call (`_drive`: `run_tick(..., replay=True)` on the tick the crash left journalled). The
tick's *start* state arrives as a snapshot the parent wrote, which is what a real resume reads
out of the previous tick's checkpoint — the live half of row W2 has a one-call budget, and a
crashed tick after a completed one would cost a second live call.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from protean.cortex.layer import build
from protean.mailbox.files import build as build_mailbox
from protean.runtime import engine
from protean.runtime.cycle import run_tick
from protean.runtime.journal import journaled_envelope
from protean.runtime.paths import BrainPaths
from protean.state.brain_state import BrainState
from protean.state.enums import CallType, Tier


def main(argv: list[str]) -> int:
    root = Path(argv[0])
    task_id = argv[1]
    snapshot = Path(argv[2])
    destination = Path(argv[3])
    tick = int(argv[4])
    workspace_path = argv[5]

    paths = BrainPaths(root=root).task(task_id)
    checkpoint = engine.load_task(paths)
    carried = dict(checkpoint.state.seat_sessions)

    # The shipping zero-argument factory, in a process that has never seen this task.
    layer = build()
    minted_before = list(layer.sessions.minted_tasks)
    layer.sessions.restore(task_id, carried)
    reused = {str(tier): layer.sessions.handle(tier) for tier in Tier}

    state = BrainState.model_validate_json(snapshot.read_text(encoding="utf-8"))
    state.seat_sessions = carried
    state.tick = tick
    context = engine.build_context(
        root,
        task_id,
        layer,
        mailbox=build_mailbox(root),
        workspace_path=workspace_path,
        revision=checkpoint.revision,
    )

    journalled = journaled_envelope(paths.journal(tick), CallType.DISPATCH)
    result = run_tick(context, state, replay=True)
    decoded = state.latest.dispatch

    destination.write_text(
        json.dumps(
            {
                "which_claude": shutil.which("claude"),
                "carried_handles": carried,
                "reused_handles": reused,
                "minted_before_restore": minted_before,
                "minted_tasks": list(layer.sessions.minted_tasks),
                "seat_restored": result.seat_restored,
                "selected_tier": str(context.layer.router.selections[-1].tier),
                "journalled_result": None if journalled is None else journalled.result,
                "decoded_model": None if decoded is None else decoded.model_dump_json(),
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - driven as a subprocess
    raise SystemExit(main(sys.argv[1:]))
