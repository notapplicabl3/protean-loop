"""The runtime model layer: seat calls, advisory calls, and bounded worker spawns.

`the build specification (not in this mirror)` § Deliverable 1 (seam contract S1) and § Directional
decisions 4, 9, 10, 11, 13, 19. A.1 and A.1.i extend the original four modules:

* `config.py`  — the `brain/seats.yaml` loader: model, effort, permission mode, the allow-list,
  the disallowed set, `add_dir`, the two per-call caps, the prefix file, and the `PATH` the
  child inherits. Configuration, not code (decision 9).
* `schema.py`  — the narrowed `--json-schema`: the tier's result model minus the two
  runtime-owned fields, derived from pydantic and never hand-written (decision 10).
* `session.py` — the handles: `--session-id` mints on a task's first call, `--resume` on every
  later one, and a checkpoint's two seat handles are adopted rather than re-minted.
* `invoke.py`  — the process call, the scrubbed environment, the timeout kill, the dollar cap,
  the classification of a failure, and the one decode retry.
* `kinds.py` — the closed grants for dispatch and delegate kinds.
* `wave.py` — the per-tick spawn desk, concurrent wave members, and static cap checks.
* `audit.py` — the disk and process witnesses attached to spawn receipts.

`oracle/` is the other package licensed to spawn model processes. The production kind library
is landed, seed-side: two kinds, one per class, under `brain/seats.yaml`'s `kinds:` container
(`the build specification (not in this mirror)`). The live layer attaches the `node_calls` seam, and the
outer-node triggers that plan its calls ship off (`the build specification (not in this mirror)`).

**This package is a T3 surface** (§ Directional decisions 19, the operator-ruled): it runs an autonomous
tool-bearing session on a real path. The containment in `config.py` and `invoke.py` — a positive
allow-list, an explicit disallowed egress set, an environment scrubbed to five variables and a
`PATH` that cannot resolve the binary itself — is a contract, not a default.
"""
