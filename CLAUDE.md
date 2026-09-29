# PROTEAN

A small loop around Claude Code: a director seat plans units, a contained editor does each one in a clone, a grader verifies, a mailbox carries questions to the operator. `README.md` says how to run it and what this public mirror leaves out.

| Task | Go to |
|---|---|
| Change the loop, a tick, resume or abandon | `src/protean/loop.py` |
| Change what the director is sent or how its reply is decoded | `src/protean/director.py`, prompt `brain/protean/director.md` |
| Change the editor's containment, clone or branch handling | `src/protean/worker.py`, prompt `brain/protean/editor.md` |
| Change a predicate kind or how a unit passes | `src/protean/grade.py` |
| Change a ceiling, a cap or cost accounting | `src/protean/budget.py`, `src/protean/runner.py`, `brain/protean/config.json` |
| Change task state or where files live | `src/protean/state.py` |
| Add a dry scenario | `fixtures/protean/<scenario>/`, `src/protean/dry.py` |

Rules:

- Every model call goes through a `Runner`; tests inject scripted runners and the shim on PATH fails any test that reaches the real binary.
- Only `grade.grade()` sets a unit `passed`. A director reply never carries a status. An ungradeable predicate never passes. A unit whose branch carries no change delivered nothing and is ungradeable, so a predicate satisfied by pre-existing files cannot pass. `file_exists` and `file_contains` read the branch's tree objects, never the working tree: only a committed regular file counts, and a symlink, a directory, a nested repository, an ignored path or anything under `.git` never does.
- A unit's `needs` must pass and be integrated before it runs; a need that fails or is descoped makes its dependents `blocked`. Decode rejects an unknown need, a self-need and a cycle.
- `task/<task>` in the workspace is the accepted work: every unit branches from its tip, and it moves only by a checked `update-ref` fast-forward to a candidate that passed its own predicates and every integrated unit's `file_exists`, `file_contains` and `command` predicates. The grade and the re-checks count only if the clone still sits clean on the candidate afterwards (a check command that moves HEAD or leaves a file fails the attempt). A pass saves `passed` + `candidate` first, then moves the ref and saves `integrated`; a tick or resume finishes a cut pass without re-running the worker, and a ref moved outside the loop parks the task on a question instead (`--abandon` still closes it). `main` is never checked out, moved or merged into.
- A `command` predicate runs under `sandbox-exec`: no network, writes only inside the clone, uv's caches and the temp dirs. Without the sandbox binary it is ungradeable; a check command never runs unconfined.
- A model call interrupted mid-flight (Ctrl-C, SIGTERM, SIGHUP or any exception) books its spend on the task and saves before the interruption propagates: the clipped `--max-budget-usd` while the call runs, the receipt's cost once it has returned. The CLI exits 130 and `protean resume` continues the task. A SIGKILL books nothing.
- A bug fix lands its repro test first. Behaviour a landed test pins does not change silently.
- Nothing spends without the operator's go. `protean run` and `protean resume` spend on a real workspace.
- `brain/protean/state/` and `brain/protean/mailbox/` are runtime state, never hand-edited except a mailbox item's `## Answer` body.
