"""Row G2's new-process clause: a seat session minted in **one interpreter**, reported to another.

`the build specification (not in this mirror)` § Deliverable 1 and DoD row **G2**: "with the first call
made in a child interpreter, the directory still exists after that interpreter exits and the
parent's call resumes without the fallback". The seats' landed cwd was a `mkdtemp` registered for
removal at interpreter exit, so the session the CLI filed under it was lost with the process; this
child makes the first call and exits, and the parent case in `test_live_invoke.py` restores the
handles it reports on a second layer.

**It is not a test module and pytest never collects it** — `live_replay_child.py`'s precedent: the
parent runs it with `sys.executable`, hands it the paths on argv, and reads the JSON it writes. It
asserts nothing; the parent owns the assertions, because a child that judged itself could exit 0
for the wrong reason.

argv: `<brain root> <task id> <request JSON file> <destination JSON file>`.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from protean.cortex.layer import build_live_layer
from protean.cortex.live.session import SESSION_MINT_FLAG, SESSION_RESUME_FLAG
from protean.state.enums import Tier


def main(argv: list[str]) -> int:
    root = Path(argv[0])
    task_id = argv[1]
    request = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    destination = Path(argv[3])

    # The shipping factory, in a process that has never seen this task: open it, one manager call.
    layer = build_live_layer(root=root)
    handles = layer.sessions.open_task(task_id)
    layer.port(Tier.MANAGER, request)
    facts = layer.calls()[0]

    ran_with = [
        [flag, facts.argv[facts.argv.index(flag) + 1]]
        for flag in (SESSION_MINT_FLAG, SESSION_RESUME_FLAG)
        if flag in facts.argv
    ]
    destination.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "handles": handles,
                "session_handle": facts.session_handle,
                "session_flags": ran_with,
                "cwd": facts.cwd,
                "outcome": facts.outcome,
                "error": facts.error,
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - driven as a subprocess
    raise SystemExit(main(sys.argv[1:]))
