# architecture — protean

What lives where, and what each folder owns. Pairs with `architecture-logic.md` (the *why*),
and both are derived from the build-1 specification § Deliverable 1, extended by the later build and A-series specifications (none in this mirror).

**Two trees, and the split is load-bearing.** `src/protean/` is the installed package;
`brain/` is the runtime's own folder tree. Generated, node-written state never lives inside the
installed package, and the package never reaches into the brain except through the one layer
built to do it.

## Layout

```
protean/
├── CLAUDE.md                  # task catalog; routes to current state, doctrine and operations
├── README.md                  # the human front door — why it exists, quickstart, layout
├── architecture.md            # this file: the structural map
├── architecture-logic.md      # the load-bearing decisions and the roads not taken
├── pyproject.toml             # the uv project: exact `==` pins, pytest config, the console script
├── uv.lock                    # the committed lockfile — the pins travel with the checkout
├── src/protean/               # the package
│   ├── __init__.py            # the package marker; exports nothing the CLI does not
│   ├── config.py              # the pinned literals: node order, tiers, exit codes, schema versions, brain-root resolution
│   ├── cli.py                 # the operator surface: run · resume · status · dry · intake · sleep. Parses and dispatches; holds no runtime logic
│   ├── state/                 # the pydantic contracts — nothing here executes
│   │   ├── base.py            # the shared model config: extras forbidden everywhere but the seat envelope
│   │   ├── brain_state.py     # BrainState v2 — fixed core, versioned extensions, two-seat latest/session fields
│   │   ├── calls.py           # A.1's four seam contracts: C1 NodeCall · C2 SubagentSpawn · C3 FiringDecision · C4 BodyTransport — plus A.1.i's I4 SpawnWitness
│   │   ├── checkpoint.py      # the checkpoint envelope, its integrity hash and its refusal ladder
│   │   ├── enums.py           # every closed set: node names, tiers, terminals, escalations, trap detectors
│   │   ├── errors.py          # the named refusals every loader raises
│   │   ├── habit_hits.py      # HabitHit (P3) — the seventh persisted artifact: a tick answered by a habit
│   │   ├── inputs.py          # the five node input models — one per deterministic node
│   │   ├── oracle.py          # OracleReport (S5) — the synthetic dev's report schema
│   │   ├── outputs.py         # the five node output models
│   │   ├── primitives.py      # goals, work units, expectations, constraints, observations, baselines
│   │   ├── interrupts.py      # the interrupt request and the open item it becomes
│   │   ├── records.py         # TraceRecord and EpisodeRecord — prediction, outcome, tick, event
│   │   ├── reads.py           # the NODE.md `## Reads` contract, checked against the input models
│   │   ├── run_report.py      # WorkloadRunReport — the run's own receipt; every number derived, none stored
│   │   ├── seat_calls.py      # SeatCallRecord (S2) — the sixth persisted artifact, what build 3 consumes
│   │   ├── seats.py           # the per-addressee seat and call results, and the SeatEnvelope wire shape
│   │   ├── semantic.py        # SemanticChunk (S4) — the semantic store's record and its retrieval id
│   │   ├── sleep.py           # P1 WeightUpdate · P2 Procedure · P4 ProjectMemoryRecord · P5 SleepReport
│   │   └── workspace.py       # the compressed workspace and the two seat requests
│   ├── runtime/               # the loop — the only writer of committed state
│   │   ├── CONTEXT.md          # maintainer inputs, commit/replay ownership and checks
│   │   ├── engine.py          # the drivers: start, resume, status, and the run outcome
│   │   ├── firing.py          # node → its cheap firing check, and the runtime's one reading of the answer
│   │   ├── triggers.py        # node → its call check: the per-tick call plan handed to the desk, and the `## Calls` seed check
│   │   ├── cycle.py           # one tick: every node in order, the seat, the boundary
│   │   ├── journal.py         # the per-tick journal — written after every node, replaced on replay
│   │   ├── commit.py          # the boundary commit: keyed, idempotent appends and one checkpoint
│   │   ├── resume.py          # the resume classifier and the refusal ladder it runs first
│   │   ├── lock.py            # the advisory instance lock, and dead-pid reclamation
│   │   ├── paths.py           # every path under a brain root, derived in one place
│   │   ├── clone.py           # the throwaway workspace clone a live run acts on, and its teardown
│   │   ├── projections.py     # committed state → the typed input each node reads, and the seats' workspace with file bodies and retrieval text withheld
│   │   ├── predictions.py     # the prediction payload each node folder is graded on
│   │   ├── outcomes.py        # the grading: an observable per node, derived at the next boundary
│   │   ├── observations.py    # the per-unit observation row and the windows the detectors read
│   │   ├── interrupts.py      # the state half of the mailbox, and the port its file half implements
│   │   ├── seat.py            # the seat port, the tier selector, the session seam, result decoding
│   │   ├── terminal.py        # the five terminal states and the precedence between them
│   │   ├── report.py          # the run receipt written at the terminal: five groups, every number derived, and each seat call's request bytes
│   │   ├── archive.py         # the archive on every terminal: state, product, manifest, hashes
│   │   └── errors.py          # runtime refusals: occupied root, no task, layer unavailable
│   ├── nodes/                 # the five outer nodes — each with a cheap firing check and three call seams, and a call check beside the firing check on the two authored nodes (homeostasis, anterior cingulate); the two contractual vetoes unchanged
│   │   ├── homeostasis.py     # budget and ceilings; the stop veto
│   │   ├── hippocampus.py     # episodic and semantic retrieval — candidates, never a decision
│   │   ├── thalamus.py        # the context gate: what is admitted to this pass
│   │   ├── basal_ganglia.py   # go / no-go selection; the second and last contractual veto
│   │   ├── anterior_cingulate.py  # the monitor: expectation grading, the verdict, the trap scalars
│   │   ├── detectors.py       # the six trap signals, computed from the projected windows alone
│   │   ├── registry.py        # name → callable, iterated by the cycle in `config`'s order
│   │   └── vocabulary.py      # the argument keys every constraint and expectation is read under
│   ├── cortex/                # the runtime seats and calls; oracle/ is the other licensed model-calling package
│   │   ├── layer.py           # `build()` / `build_layer()` — what the runtime resolves a layer from
│   │   ├── calls.py           # the three call types — think, escalate, delegate — as three callers of the one port
│   │   ├── subagents.py       # the tier-three seam: the call record, the wave's member, the scripted-return path
│   │   ├── bodies.py          # the two bodies behind `runtime.body`, and what C4 holds identical across them
│   │   ├── adapters.py        # the scripted seats and call answers, the session book, the router→port desk
│   │   ├── router.py          # tier selection from workspace signals alone
│   │   ├── ladder.py          # the stuck ladder: unit → manager → director, counts read from weights
│   │   ├── scripts.py         # the SeatScript format: request-keyed responders, never a turn list
│   │   ├── habits.py          # the pure matcher: a tick's facts against the compiled procedures, or nothing
│   │   ├── scenario.py        # a scenario = one goal + the name of the script that answers it
│   │   └── live/              # the live seats and tier-three spawns (T3); oracle/ also spawns benchmark calls
│   │       ├── CONTEXT.md      # invocation, capability, wave and receipt boundaries
│   │       ├── invoke.py      # the spawn: argv, containment, the two per-call caps, the retry and the kill, and the seats' per-task working directory
│   │       ├── kinds.py       # the `kinds:` container as data: I1 KindBlock, I2 CapabilityProfile, the per-class licensed sets
│   │       ├── wave.py        # I5 SpawnDesk: the tick's one spawner, the four bounds, a thread per member, the group kill
│   │       ├── audit.py       # I4's four lists — what one spawn is witnessed by, derived off disk and off the denials
│   │       ├── schema.py      # the narrowed per-tier result schema handed to `--json-schema`
│   │       ├── session.py     # the per-task session handles the warm `--resume` path reuses
│   │       └── config.py      # `brain/seats.yaml` read into the typed per-tier invocation (S1)
│   ├── intake/                # the fifth verb: the policy home's content into the stores, offline
│   │   ├── manifest.py        # IntakeManifest (S3): source → store, seed marking, the revision pin
│   │   ├── chunks.py          # the chunker — per-source granularity, one SemanticChunk each
│   │   ├── policy_home.py           # the ONE licensed reader of `~/policy-home`; no other module may name it
│   │   ├── seeds.py           # `brain/seeds.yaml`: the seeding map, and the rule that a seeder never overwrites a learner
│   │   └── run.py             # the verb's body: read, chunk, replace the store, refuse while a task is live
│   ├── dashboard/             # (not in this mirror) unpromoted read-only viewer prototype: sources, snapshot, server, static assets
│   ├── oracle/                # the synthetic dev (T3): grades a run, with no model in the grading
│   │   ├── config.py          # the `oracle:` block of `brain/seats.yaml`, typed
│   │   ├── tasks.py           # the graded task set and the baseline each is run against
│   │   ├── clone.py           # the throwaway repo clone every session runs in, and its destruction
│   │   ├── session.py         # one graded session: spawn, capture, tear down
│   │   ├── transcript.py      # the captured transcript and the facts read off it
│   │   ├── predicates.py      # the per-task predicates — hand-authored, no field a model wrote
│   │   ├── counts.py          # the derived counts every report number comes from
│   │   ├── audit.py           # the five-list containment audit: what must be empty, and was
│   │   └── run.py             # the driver: N sessions over both baselines, then the report
│   ├── sleep/                 # the sixth verb's body: the offline learner, between tasks, zero model calls
│   │   ├── CONTEXT.md          # evidence inputs, refusal gates and report review
│   │   ├── run.py             # the verb's body: refuse twice, verify the seeds, drive the phases, write the report
│   │   ├── evidence.py        # the run's records, the `ref` join, and the admissible-pair classification
│   │   ├── weights.py         # the update rule (P1): bounded steps over the persistence floor, and the cross-project split
│   │   ├── habits.py          # the compiler (P2): candidates, the four gates in order, the compiled file, withdrawal
│   │   ├── memory.py          # project memory (P4) keyed by node, and what this run's updates consumed
│   │   └── report.py          # SleepReport (P5): the five groups assembled, and the `--dry-run` diff
│   ├── mailbox/               # interrupts as files: the human is above the director
│   │   ├── format.py          # the on-disk item: front matter, evidence body, the answer body
│   │   └── files.py           # raise, list, read the answer, re-materialize, resolve and delete
│   └── brain/                 # the runtime-folder layer — the only reader of the brain tree
│       ├── folders.py         # node-folder reads: NODE.md, weights.yaml, the seed hashes
│       ├── trace.py           # trace appends, with the prediction invariant enforced
│       ├── episodes.py        # episode appends, keyed and idempotent
│       └── jsonl.py           # the one JSONL reader/writer both of them share
├── brain/                     # the runtime folder tree — seeded and tracked; generated state gitignored
│   ├── CONTEXT.md              # authored seeds, learned material, generated state and writer ownership
│   ├── seats.yaml             # the live seats as data: model, effort, tools, the two caps, prefix files — a hashed seed
│   ├── seats/<seat>.md        # the stable system-prompt prefix, one per seat: director.md, manager.md — hashed seeds
│   ├── seats/calls/<type>.md  # one prefix per call type: think.md, escalate.md — hashed seeds too, from A.1
│   ├── seats/kinds/<kind>.md  # one prefix per subagent kind — hashed seeds too, from A.1.i; ships A.2's two, `editor.md` and `reader.md`, beside `.gitkeep`
│   ├── intake/manifest.yaml   # the S3 manifest: which policy-home source seeds which store, and at which revision
│   ├── seeds.yaml             # the seeding map: a policy-home memory name → a node's weight key — a tracked seed sleep may weaken
│   ├── semantic/              # generated: the lexical store intake fills, one JSONL per source
│   ├── archive/               # generated: one folder per terminal — state, product, manifest, hashes
│   ├── projects/<slug>/       # generated, gitignored: memory/<node>/learning.jsonl, and memory/cortex/procedures/ for one project's habit
│   ├── state/<task_id>/       # generated: the checkpoint and journals, plus build 2's two artifacts and build 3's habit hits
│   │   ├── seat_calls.jsonl   # generated: one SeatCallRecord per live seat call (S2)
│   │   ├── seat-cwd/          # generated: empty, one per task, the seats' cwd, so a resumed process finds their sessions
│   │   ├── habit_hits.jsonl   # generated: one HabitHit per habit-answered tick (P3) — never a seat_calls line
│   │   └── run_report.json    # generated: the run's own receipt, written at the terminal
│   └── nodes/<node>/          # six folders, one per node incl. the cortex: the § Rulings 10 shape (build-3 SPEC)
│       ├── NODE.md            # the node's prose and its `## Reads` list — drift is refused at startup
│       ├── weights.yaml       # every threshold the node reads; the runtime never writes it
│       ├── trace.jsonl        # generated: this node's predictions and their outcomes, append-only
│       └── procedures/        # compiled habits (P2): tracked, written only by build 3's offline sleep graph
├── fixtures/                  # hand-authored but for one captured envelope; nothing copied from another repo
│   ├── calls/                 # A.1's call and wave payloads, plus kinds/ — A.1.i's fixture kind roots, test-only: no kind name ships
│   ├── envelopes/             # SeatEnvelope payloads — the wire's conformance set, plus `live-first.json`, captured live
│   ├── seat_scripts/          # reusable request-keyed responder sets, one file each
│   ├── transcripts/           # (not in this mirror) the oracle's fixture transcripts, authored before it was pointed at a real clone
│   ├── traces/                # hand-scripted run traces: one per rule arm of the dry sleep battery
│   ├── procedures/            # hand-authored compiled habits — the matcher's and withdrawal's inputs
│   ├── scenarios/<name>/      # one goal + the name of its script (+ the dry scenario's expected climb)
│   └── workspaces/<name>/     # the seeded throwaway workspace a scenario's run acts on
├── tests/                     # mirrored under pytest: one test module per src module
│   ├── state/ runtime/ nodes/ cortex/ mailbox/ brain/ intake/ sleep/   # the mirror (oracle/ not in this mirror)
│   ├── dry/                   # the scripted task end to end, and a dry run's blast radius
│   ├── wet/                   # (only two probe drivers in this mirror) the live rows and the spending drivers: `live`-marked, deselected, `--force`-gated
│   ├── shim/                  # a recording stand-in for the model binary, first on PATH
│   ├── test_zero_calls.py     # the zero-call proof: the empty shim log and the static grep
│   └── test_policy_home_clean.py    # the two forbidden path prefixes, over four trees
├── reports/oracle/            # (not in this mirror) generated: the oracle's reports, audit rows and raw transcripts
├── reports/sleep/             # (not in this mirror) generated: one SleepReport per sleep run — the review artifact for the gitignored half
├── reports/tests/             # (not in this mirror) tracked (force-added): the battery's durations profile — the split behind CLAUDE.md's lane lines
├── plans/                     # (not in this mirror) build and A-series SPECs, orders, audit records, and handoffs
│   ├── CONTEXT.md              # (not in this mirror) authority/precedence and contract-family routes
├── docs/                      # current guides; canonical decisions remain in the SPECs
│   ├── status.md               # (not in this mirror) built/planned state and individual gate dispositions
│   ├── doctrine.md             # current model and authoritative ruling crosswalk
│   └── operations.md           # command effects, inspection and human handoffs
└── .notes/                     # the framing layer (gitignored, local-only)
```

## Ownership — one line each

| Folder | Owns |
|--------|------|
| `src/protean/state/` | Every contract, and nothing that executes. If a fact has no field here, it does not survive a resume and cannot be graded. |
| `src/protean/runtime/` | The loop and the only writes to committed state: the tick, the journal, the boundary commit, resume, the lock, the terminals. |
| `src/protean/nodes/` | The five outer nodes, the cheap firing check beside each body, and the call check beside the two authored nodes' firing checks (homeostasis and the anterior cingulate). Every one of them is still a pure callable from a typed input model to a typed output model — no I/O, no clock, no filesystem — and that holds for a node's calls too: a call is a **typed request the runtime carries**, so the node itself opens nothing, spawns nothing and names no binary. |
| `src/protean/cortex/` | The two judgment seats and how one is chosen — the adapters, the router, the ladder, the script format — plus the three call types and the tier-three seam beside `live/`. The runtime reaches models only through this package; `oracle/` is separately licensed to spawn benchmark calls. From A.1.i the kind blocks and their loader, the per-class capability grant, the per-spawn kernel profile, the wave's spawner and the spawn's witness live here too — `live/kinds.py`, `live/wave.py`, `live/audit.py` — and `live/` owns these runtime spawns. |
| `src/protean/intake/` | The fifth verb's body: the manifest, the chunker, and `policy_home.py` as the one module licensed to read `~/policy-home`. Writes the stores offline; the runtime never writes a seed file. |
| `src/protean/sleep/` | The offline learner: reading a run's records, classifying its grades, and the three things it may rewrite — weights, procedures, project memory. Zero model calls, and the only writer of a node's priors. |
| `src/protean/oracle/` | The synthetic dev: the graded task set, the throwaway clone, the transcript, the hand-authored predicates, the derived counts and the containment audit. Grades a run without a model in the grading. |
| `src/protean/mailbox/` | The file half of interrupts — the format on disk and the open-items directory. The runtime owns their effect on state; this owns their bytes. |
| `src/protean/brain/` | The runtime-folder layer: reading a node folder, hashing its seed, and appending to trace and episodes with the invariants enforced. |
| `src/protean/config.py` | Every literal the runtime iterates or exits on, in one place, so the surface, the tests and the loop cannot drift apart. |
| `src/protean/cli.py` | Six verbs. Argument parsing and dispatch, no runtime logic, and no exit code written as an integer. |
| `brain/` | The runtime's folder tree, in two halves. **Tracked:** the seed — `NODE.md`, `weights.yaml`, `seats.yaml`, `seeds.yaml`, `intake/manifest.yaml` — and, from build 3, whatever sleep compiles into `nodes/<node>/procedures/`, so a learned habit is reviewed as a git diff. **Gitignored:** everything a run writes — `trace.jsonl`, `state/`, `semantic/`, `archive/` — and `projects/<slug>/memory/`, whose only review artifact is a `SleepReport`. |
| `fixtures/` | Hand-authored inputs: envelopes, responder sets, oracle transcripts, scenarios and workspace seeds. Nothing here is copied from another repo or generated by a run — with one named exception, `envelopes/live-first.json`, captured from the first live call so the wire can be diffed against the model (SPEC § Resolutions V2-5). |
| `tests/` | The mirrored battery, plus the three checks that are about the build rather than a module: the dry run, the zero-call proof, the cleanliness grep. |
| `plans/` (not in this mirror) | The contracts and the record of how they were decided; `CONTEXT.md` routes their precedence and current reuse. |
| `docs/` | Operator effects and a doctrine crosswalk (the status document is not in this mirror); the SPECs retain decision authority. |
| `src/protean/dashboard/` (not in this mirror) | Read-only viewer prototype, not a promoted operator interface or evidence of runtime correctness. |

## Control flow, one pass at a time

- **A tick** is one ordered pass over the six node folders — homeostasis, hippocampus,
  thalamus, basal ganglia, cortex, anterior cingulate — with the order read from `config.py`
  and never written inside a node. The ring is the default path and every node keeps its step. Four outer nodes check their
  projected input against `firing_threshold`; the gate checks whether a unit is pending.
  A declining check skips the body except for homeostasis, whose body always runs — the skip is recorded as a prediction at the node's reserved
  `call# = 0` journal entry, so it can be graded — and the two contractual inhibitions, the
  gate's veto and homeostasis's stop, never skip. The outer-node call seams allow think, escalate and delegate **mid-step**. A.2.i's triggers
  are landed and ship off — `runtime/triggers.py` plans a node's calls only when its trigger key
  is on — and outer-to-outer edges are rule only, with none declared. Adaptation stays in data
  rather than a graph selected per project.
- **Two persistent writes, not one.** A journal entry lands after every node and after every
  call it made; exactly one checkpoint lands at the boundary, which is still the only resume
  point. The journal is a crash record, not a resume point.
- **The seat** is called as often as the tick's nodes ask: once at the cortex step, on the seat
  the router picked from workspace signals alone, plus one call for every think, escalate or
  delegate an outer node makes — all of them through the one `(addressee, request) -> SeatEnvelope`
  port, each **journalled under its own `(task, tick, node, call#)` key**, calls numbering from 1.
  A manager plan may supply one dispatch wave, its members sitting beneath one `call#` at
  `member#`. Complete returns merge per field into **one observation for the unit**; partial
  or conflicted waves append no observation row and leave its mismatch streak unchanged.
  Director ticks and manager plans with an empty wave dispatch nothing. From build 2 the call is live — one process per call, inside `brain/seats.yaml`'s
  containment — and the boundary writes one `SeatCallRecord` per journalled call of the committing
  pass, whether it answered, refused or failed. A veto or a mid-tick terminal skips the wave, and
  the tick still completes. From build 3 the step consults the node's compiled procedures first: a tick whose
  facts match one is answered from that procedure with no process spawned at all, and its original pass appends a
  `HabitHit` rather than a `SeatCallRecord`. A.1 § Resolutions D7-3 records the replay gap:
  the journal does not preserve habit provenance, so replay may write a call receipt instead.
  From A.1.i the wave itself is N processes, one per member, each under only the capabilities its
  kind's class licenses and a kernel profile composed for that class; the wave's width and the sum of
  its members' effective caps are **bounded before the first member spawns**, refused at the desk's
  open with no process created.
- **An interrupt** is a file. It is raised, committed, written, and the process exits; a
  non-empty mailbox blocks the task from closing, and the answer body is the one path anything
  outside the runtime may write.
- **The operator surface** is six verbs: `run` opens a task (under `--project <slug>`, else the
  projectless root), `resume` continues one, `status` reads without touching, `dry` runs a scripted
  scenario on a throwaway copy of the brain and a throwaway workspace, destroying both, `intake`
  seeds the stores from the policy home's content offline, and `sleep` re-values weights, compiles habits and
  writes project memory offline from a finished run's traces. The last two are refused while a task
  occupies the root, because the runtime may never write a seed. Sleep also refuses when a committed
  non-`done` task holds any seed hash it would write, even unchanged; no flag overrides either
  refusal. Evidence whose recorded weight hashes have moved is a separate refusal.

## Entry points

`uv sync` · `uv run pytest` · `uv run protean run "<goal>"` (+ `--project <slug>`, `--workspace <path>`) · `uv run protean resume` (+
`--extend`, `--abandon`, `--reseed`) · `uv run protean status` · `uv run protean dry <scenario>` ·
`uv run protean intake` (+ `--project <slug>`) · `uv run protean sleep` (+ `--from <run dir>`,
`--dry-run`)
