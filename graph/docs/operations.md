# PROTEAN — operations

Use this guide for command effects and human handoffs. the status document (not in this mirror) owned current gates; [doctrine.md](doctrine.md) and the governing specification (not in this mirror) lead to the controlling rulings. Commands below describe capability, not approval to reset or spend.

## Start with inspection

From the repository, with its locked environment available:

```sh
uv run protean --help
uv run protean status
uv run protean dry dry
```

Help reads no brain state. `status` takes no lock and writes nothing; it reports raw committed fields, so a readable status is not proof that a checkpoint can resume. `dry dry` uses scripted seats in a temporary brain and workspace, then removes both; it calls no model and never writes the checkout's brain. `dry stuck` demonstrates the stuck interrupt and exits nonzero by design; its temporary files are removed too.

Select a root with `uv run protean --brain <path> <verb>`: the global option precedes the verb. Resolution is explicit `--brain`, then `PROTEAN_BRAIN`, then the checkout's `brain/`. `dry` always substitutes its temporary root. Inspect the selected root before a state-changing command.

The checkout's schema-1 workload state is retired evidence. Current code refuses its old artifacts; do not repair that refusal by editing schemas or deleting state. B42 is the operator's archive-and-reset gate. The old mailbox item it carried was not the next continuation step. Documentation work does not authorize B42, B32, B49 or wet spending.

## The six verbs

| Command shape | Reads and effect | Human handoff |
|---|---|---|
| `uv run protean run "<goal>" --project <slug> --workspace <path>` | Starts a task in the selected root; refuses an occupied non-`done` task. Records the project and workspace in task state. | Before a live run, confirm its goal, selected root, workspace, configured kinds, budget and applicable gates. |
| `uv run protean resume` | Reconciles mailbox answers, validates the checkpoint/seeds and replays or advances a compatible task. | Answer its open question or resolve its specific stop; inspect the result before continuing. |
| `uv run protean status` | Reads task, tick, terminal and open interrupts without a lock or writes. | Use it to locate what needs attention; it does not close a gate. |
| `uv run protean dry <scenario>` | Copies node seeds and a fixture workspace, runs scripted responders and deletes the temporary tree. | Inspect terminal and printed ticks; `dry` and `stuck` are the supplied examples. |
| `uv run protean intake [--project <slug>]` | Reads `brain/intake/manifest.yaml` and `brain/seeds.yaml`; replaces semantic stores and applies eligible first-write seed values without overwriting learned values. Makes no model calls; refuses an occupied root. | Review the source manifest, printed writes and tracked seed diff. |
| `uv run protean sleep [--from <archive-dir>] [--dry-run]` | Reads one archived run, or live node traces and the most recent committed task when `--from` is absent; verifies seeds, derives learning and writes a report. Makes no model calls. | Review the report and proposed/applied diff, including project memory that is not tracked by git. |

`--project` and `--workspace` on `run` are optional syntactically. A projectless task uses `_root`. The spawn desk refuses a wave without a supplied workspace; the runtime does not discover one. `resume` reuses the checkpointed workspace and has no workspace flag.

A root with live seat configuration can make paid calls through **both `run` and ordinary `resume`, without any `--force` flag**. A root without `seats.yaml` resolves scripted seats. The shipping library defines two kinds: a plan naming `editor` runs its wave behind the live gates, while `reader` is a delegate kind, reached only by an outer node's delegate call. The live layer attaches `node_calls`, so an outer node's think, escalate or delegate call can spend once its trigger key is turned on; no trigger is on in the shipping seed, and a delegate is bounded per tick by `runtime.max_tick_delegates` (seeded `1`). A plan naming `reader` as a wave member, or naming any undefined kind, still stops under `REASON_NO_KIND`; that refusal does not promise that earlier seat calls were free.

## A compatible task's human steps

1. Read `status`, the committed terminal and any file in `brain/mailbox/open/`. For `interrupted` or `stuck`, the operator writes only the answer body under `## Answer`; leave the item's metadata and runtime-owned state alone. An unanswered item blocks continuation and task close.
2. After the answer or an appropriate correction, use ordinary `resume` only within the task's live authorization. Inspect its new terminal and receipts. A refused schema, changed seed or missing kind is a named condition to resolve, not permission to bypass validation.
3. Use an administrative flag only for its named action. `resume --extend 10` adds ticks; `resume --extend 5m` adds minutes. `resume --reseed` accepts deliberate seed changes under a suspended task. `resume --abandon` resolves open items as abandoned, closes open goals and frees the root. These flags write state without making a seat call, bypass the answer check but retain the lock and applicable validation; they are not an old-schema migration. Extension reports that a separate `resume` is needed to continue.
4. Inspect the product and run receipt at the terminal. Human acceptance and SPEC gates require their named evidence; no terminal result grants merge or push authority.

For the checkout's old task, these generic steps yield to B42. The operator's reset driver (not in this mirror) archives and empties exactly node traces, `brain/projects/`, `brain/state/` and `brain/mailbox/`; it spends nothing but is destructive. Preserve the archive regression evidence owed by RB21 when that gate is exercised. Do not use an administrative flag as a substitute for the approved reset.

## Sleep review and refusals

On an eligible root and compatible evidence, a preview takes this shape:

```sh
uv run protean --brain <eligible-root> sleep --from <archive-dir> --dry-run
```

`--dry-run` writes `reports/sleep/<sleep-id>.json` and prints the proposed diff; it writes nothing under the selected brain. It is not a read-only inspection command. A running task, or a committed non-`done` task holding seeds sleep would write, refuses even a dry run and even with `--from`. No flag overrides either refusal. Evidence also refuses if its recorded weight hashes no longer match.

Without `--dry-run`, the writer can update eligible `nodes/*/weights.yaml`, compiled procedures and `projects/<slug>/memory/<node>/`, plus its report outside the brain. It never edits the source archive or node identity. Review both the tracked diff and `SleepReport`; no change or **no data** is a valid outcome when the evidence floor is unmet. Hand invocation and review remain required; sleep is not scheduled.

## Tests and separate drivers

```sh
uv sync --locked
uv run pytest
uv run pytest -m "not slow"
uv run pytest -m slow
```

The lockfile supplies dependency versions. The default suite excludes `live`; the test configuration keeps live tests excluded in the fast/slow lanes too. A lane with no collected tests exits 5, which is not a runtime failure. Test collection and dry fixtures do not prove live efficacy.

The `--force` gates belong to separate operational drivers under `tests/`, not to the six-verb CLI. Read a driver's argument help and governing row before use; an existing script does not prove that its inherited assumptions match the current graph.

The separate operational drivers (live runs, containment probes, the archive reset, the wet
comparison, the synthetic-dev oracle) are not in this mirror; each ran against a private
workload and spent money.

## Where results live

The terminal names map to exit codes in `src/protean/config.py`: `done` 0, `blocked` 10, `stopped` 11, `interrupted` 12, `stuck` 13. Named refusals have separate codes; read the accompanying reason.

Task checkpoints, journals, call receipts, habit hits and run reports live under `brain/state/<task-id>/`; mailbox items under `brain/mailbox/open/`; terminal archives under `brain/archive/`; oracle and sleep reports under `reports/oracle/` and `reports/sleep/`. The two seats' working directory lives there too, at `brain/state/<task-id>/seat-cwd/` (a `resume` must run on the same absolute brain root — the CLI keys a session's transcript by that path, and a moved root re-mints every seat session silently as `resumed_as_new`): empty, one per task, the directory a seat's session is filed from; and the run report lists each seat call's request bytes (`seat_requests`, one row per seat call, the largest named when it renders). [../brain/CONTEXT.md](../brain/CONTEXT.md) describes writer ownership. These generated artifacts are inspected as evidence, not manually edited to manufacture a result.
