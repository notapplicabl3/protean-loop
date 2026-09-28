# PROTEAN

PROTEAN runs Claude Code inside a graph loop that gives a goal durable state, a dollar budget, a human mailbox and a grade for every unit of work.

A director seat (one Claude Code session) turns the goal into small units, each with checkable predicates. For each unit a contained editor subagent works in a clone of the workspace on its own branch. A grader checks the predicates; only the grader marks a unit passed. The loop stops on a dollar or tick ceiling, parks when the director asks you a question, and ends `done` when every unit is verified. That is the whole program.

This is a sanitized public mirror of a private working repository; see § What is withheld and why.

## Run it

```sh
uv sync --locked
uv run pytest tests/protean -q   # the battery; a shim on PATH fails any test that reaches the real binary
uv run protean dry dry           # scripted seats: a goal to done in a scratch root, no model call
uv run protean dry stuck         # the director asks a question; exits 12
```

| Verb | What it does |
|---|---|
| `protean run "<goal>" --workspace <path> [--project <slug>]` | Start a task. Spends money. Use a git clone as the workspace; the editor's work lands there as branches `unit/<task>/<unit>`, never merged. |
| `protean resume [--extend N \| $X] [--abandon]` | Continue after you answer a question; widen the tick or dollar ceiling of a stopped task; or close the task. |
| `protean status` | Task, tick, terminal, stop reason, units and their statuses, cost, open question. |
| `protean dry <scenario>` | Run a fixture scenario (`dry`, `stuck`) in a temporary root. |

`--brain PATH` picks the root (default `brain/protean/`). A question lands at `brain/protean/mailbox/open/<task>.md`; write under `## Answer` and `protean resume`. Exit codes: done 0, stopped on a ceiling 11, parked on a question 12, interrupted by Ctrl-C/SIGTERM/SIGHUP 130, usage or error 2.

Caps live in `brain/protean/config.json`: $10 per task, $2 per director call, $4 per editor call, each call clipped to what the task has left, no call under $0.50 left. Cost is summed from the CLI's own receipts; a call that leaves no receipt is charged the cap it carried, and an interrupted call (Ctrl-C, SIGTERM, SIGHUP) books the cap while it runs and the receipt's cost once it has returned, on disk before the signal propagates.

A unit passes only when its branch carries a change and every predicate holds. Four predicate kinds: `file_exists` and `file_contains` read the branch's committed regular files (never the working tree, a symlink, a nested repo or `.git`); `exit_code` is the worker's own reported verification code, never sufficient on its own; and a `command` predicate runs in the clone under `sandbox-exec` with no network and writes confined to the clone, uv's caches and the temp dirs.

## Where things are

```text
src/protean/          state · grade · budget · mailbox · runner · director · worker · loop · dry · cli
brain/protean/        director.md, editor.md, config.json (tracked) · state/, mailbox/, workspaces/ (gitignored)
fixtures/protean/     the dry scenarios
tests/protean/        the battery and the shim
evidence/live-1-2026-09-27/   the first live run: task record, event log, run output (done, 3 ticks, $0.75)
evidence/live-2-2026-09-27/   the second: parked twice and resumed twice, done in 5 ticks for $2.62
```

The receipts predate two renames: `manager` in them is the director seat, and live-1's brain root was still called `mvp`. Live-2 parked first on the design question the goal demanded, then on a decoder bug (the director's plan arrived one `}` short and the decoder misread it), which was fixed and pinned by a test before the second resume; both answers are in the `-answered` files.

## Design notes

**Only the grader passes a unit.** The director's reply never carries a status, and `done` is refused until every unit is verified or descoped. The three ways the earlier implementation let a unit pass falsely — a misspelled predicate argument dropped from the verdict, a misspelled `file_contains` argument passing on any content, a re-plan overwriting a unit's status — are pinned as negative tests in `tests/protean/test_grade.py`, `test_director.py` and `test_loop.py`.

**Predicates read the branch, never the working tree.** A pre-existing file cannot satisfy a unit, a symlink or a nested repository is not a file, a check command runs sandboxed, and the worker's self-reported exit code never passes a unit on its own: the branch must carry a change and every other predicate must hold.

**Cost is summed from receipts, never from tokens.** A capped call reports its dollars in the CLI receipt with zero tokens; a call that leaves no receipt is charged the cap it carried. An interrupted call books its spend to disk before the signal propagates.

**The seat's cwd is stable per task.** Claude Code files a session by working directory, so `--resume` silently mints a new session unless the director seat always runs from the same directory. The task's seat directory is that directory.

**What was cut.** This rewrite replaced a much larger implementation: a six-node ring with per-node traces and firing grades, a second planning seat, a semantic store and intake, torn-tick replay and receipt reconciliation, think/escalate/delegate machinery, and seventy versioned schemas. Each was bookkeeping around the two steps that matter — plan a unit, verify a unit — and the rewrite landed at roughly a tenth of the size, with a battery that calls no model.

## What is withheld and why

| Withheld | Why |
|---|---|
| `plans/`, `docs/` | Planning and status notes: process records, not code. |
| `evidence/captures/` | Probe and run captures of the earlier implementation, taken with a private repository as the workload: absolute paths, tree digests, environment dumps, CLI transcripts. |
| `brain/protean/state/`, `mailbox/`, `workspaces/` | Runtime state; gitignored in the source too. |

The renaming was small: the operator's name in the loop's notes, the director prompt, the mailbox docstring, the tests that pin those strings and the two live goals; and the absolute home path in the live receipts. No logic was altered.

## Status

The rewrite reached `done` on its first two live runs (receipts under `evidence/`; the second needed a decoder fix mid-run); a failed attempt is the one path not yet exercised live. This mirror is re-exported by hand and lags the working repository. **Last updated: 2026-09-27.**
