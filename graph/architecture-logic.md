# architecture-logic — protean

Why the structure in `architecture.md` is that shape, and what was rejected to get there. Every
decision below is load-bearing: reversing one invalidates work built on it.

The binding doctrine lives in the SPECs, not in an inference from the code. Builds 1–3 retain
`the build specification (not in this mirror)` § Rulings as their doctrine home. The A-series amendments live
in `the build specification (not in this mirror)` § Scaffold clause and § Rulings; A.1.i changes only the
receipt half of S2/C2 and adds I1, I2, I4 and I5. Everything outside the clauses' binding sets
remains a builder default. A.2 owns the library contents and is landed; A.2.i's trigger and edge
rules are landed too: every trigger ships off, and the edge rule declares no edge.

## The tick order is fixed, and from A.1 a node may sit out the pass

`homeostasis → hippocampus → thalamus → basal ganglia → cortex → anterior cingulate`, declared
once as a literal in `config.py` and iterated by the loop. It is never branched on and never
hardcoded inside a node.

The order is the dependency chain read forwards: you cannot gate context you have not retrieved,
cannot select against context you have not gated, cannot judge with a seat that has not been
selected for, and cannot grade an act that has not happened. Homeostasis leads so a task past its ceiling suppresses later model calls. Remaining cheap
node steps still run, with retrieval subject to its own firing check.

**The alternative was rejected here, and A.1 reverses that rejection.** This section used to
read that a conditional graph — fire the monitor only after an act, skip retrieval when the
workspace is warm — is the obvious efficiency, and that it was rejected because it moves
adaptation into the wiring, and wiring that changes per project is a different program per
project. Build A.1 rules the other way (`the build specification (not in this mirror)` § Deliverable 1):
every outer node carries a **cheap firing check** beside its body. Four compare their projected
input against `firing_threshold`; the gate checks whether a unit is pending and reads no threshold.
Homeostasis's body always runs; its check can suppress an optional think call, not its ceiling check.

**Why the original objection does not bite.** Threshold checks are pure functions of projected
input and a key in the node's own `weights.yaml`, written only by the offline sleep graph.
Adaptation stays in **data**: the same six nodes load in the same order for every project, and
skipping an eligible body never removes an edge from the graph. Each check writes a
`FiringDecision` prediction at the node's reserved `call# = 0` journal entry; the next boundary
grades it against whether work for that node arrived. The learner can adjust the four threshold
keys; the gate's structural check has no learned key.

**What it costs, and what it no longer costs.** Cheap local checks can avoid unnecessary bodies
or optional calls. Contractual inhibitions remain: homeostasis always evaluates its stop, and the
gate runs whenever a unit needs its veto. A node still cannot run twice in one pass, though it may
reach the cortex several times *within* its own step. The four shipping thresholds are seeded at
`0.0` and every score is `≥ 0`, so they cause no threshold-based skips until a learner moves a key.
The gate still skips when no unit is pending. Live body invariance remains B32's unrun check.

## The journal is a crash record, not a resume point

A node records its output at `call# = 0`; each returned call has its own
`(task, tick, node, call#[, member#])` entry. Exactly one checkpoint commits the completed tick.
Resume restarts from the last boundary and replays the interrupted tick in full, replacing its
journal. Keyed appends make a repeated boundary commit idempotent.

A seat call with a restorable result reuses its envelope. A dispatch wave restores only when
every member has a restorable result; otherwise the whole wave runs again, including previously
completed members. Outer-node calls restore as a group only when every journalled call for
that node is restorable; otherwise the node reissues its planned calls. A refusal, timeout or
crash inside a call may therefore invoke again. Replay is not unconditionally free.

The rejected alternative was a resume point after every node: that would create a consistency
contract at each intermediate state before the tick's grading completed. The redo window stays
one tick. The original unreviewed-literature assumption remains recorded in
`the build specification (not in this mirror)` § Named assumptions 3.

Two known gaps remain explicit in A.1 § Resolutions: D7-3 records lost habit provenance on
replay, and D9-6 records buffered proposals lost on a crash between a director tick and the next
manager tick. Neither is cured by the boundary-only checkpoint rule.

## Versioning is a refusal, never a migration

Every versioned persisted contract carries a `schema_version`, and its loader **refuses** a mismatch
with a named error quoting both sides. There is no migration path. A.1 writes version 2 for brain state, checkpoint, journal,
trace and mailbox; A.1.i writes version 3 for seat-call receipts. Episode records remain at
version 1. The private checkout still held pre-A.1 run state at the time, and B42 reserved its archive-and-reset to the operator;
new code refusing it is expected, not an instruction to repair or migrate it. The refusal ladder runs in a fixed order — envelope version, state
version, extension versions, integrity hash, seed hashes — so the first thing that is wrong is
the thing you are told about.

## Contracts before mocks

The state object and every inter-node contract were built before any seat script existed. This
is the whole reason the build was cut here rather than at a working runtime: if the contracts
are designed first, the mocks conform to them; if the mocks come first, they shape the contracts
and the next build rebuilds this one.

**It is mitigation, not proof, and the SPEC says so.** The required-field envelope model, the
request-keyed responders, the real temp workspace, and the rule that a scenario needing a
contract changed is a blocker rather than an edit — all of them narrow the risk. None of them
retires it. Whether these are contracts a live cortex will honour is judged on a live cortex,
which is build 2.

## One model-call port, two seats, and a third tier of workers

The cortex has two seats, director and manager. The director reads the compressed workspace and
changes goals, constraints and modulators. The manager decomposes work and assembles at most one
wave of specialized subagents per tick. Tier three is addressed by call type, has no seat-session
handle, and is never selected by the router. The runtime conducts every spawn through
`cortex/live/`; `oracle/` is separately licensed to spawn benchmark sessions. The two-package
boundary is checked by `tests/test_zero_calls.py`.

Seat calls and the think, escalate, delegate and dispatch call types share the
`(addressee, request) -> SeatEnvelope` contract and result decoder. The outer-node seams are
built, and A.2.i's call policy (`runtime/triggers.py`) decides that a node calls; every trigger
ships off, so the shipping seed makes no node call. A think answer reaches its node's body on the
input model's `think_answer` field and moves no authored output
(`the build specification (not in this mirror)` § Deliverable 2). A seam's existence is not live graph
behaviour.

A compiled procedure can answer a director or manager request without a seat process. It cannot
supply a canned workspace observation. Its original pass records a `HabitHit`; any dispatch
wave still requires its own members and observations. D7-3's replay accounting caveat applies.

### The spawn floor is a positive grant

A.1.i classifies kinds as `dispatch` or `delegate`. Each class licenses one closed permission-pattern
set; tool names are derived from that set, and a kind can only narrow the grant. The composed
`sandbox-exec` profile denies writes by default, then allows the configured spawn-writable trees
and measured process allowances; only dispatch also receives workspace write access. The runtime
supplies the workspace through one checkpointed channel. Missing workspace, unknown kinds and
exceeded static bounds refuse before a member starts.

The wave runs members concurrently, with width and summed caps checked before the first spawn.
Its per-spawn witness derives four lists from disk and CLI denials, not from the member's claims.
The shipping `kinds.dispatch` and `kinds.delegate` mappings carry A.2's `editor` and `reader`, so
a production kind can spawn behind the live gates — a manager wave's `editor`; `reader` is
reachable once a trigger rule plans a delegate, and no shipped rule does. The fixture and dry
proofs do not establish a live run; B49 is the operator's
live receipt behind B42.

The floor does not prove that a dispatch interpreter cannot open a socket or start a nested seat
by absolute path. The CLI's auto-run read class and global link farm also remain limitations.
The three-tier ceiling stays contractual for dispatch, the `wrote` witness is wave-level rather
than per-member attribution, and the outside-workspace walk prunes by directory mtime. These are
recorded limitations, not permissions to broaden the grant; see A.1.i § Resolutions S-i21, S-i40,
D11-3 and rows B51–B52, plus `cortex/live/invoke.py`'s containment notes.

## One writer of committed brain state

The runtime alone commits task state, journals, traces and receipts. The operator owns the `## Answer`
body of an open mailbox item; the runtime reads and resolves it. Intake and sleep write their
licensed stores only between tasks, with sleep the sole learner that rewrites weights and
procedures. Dispatch workers may change the task workspace within their grants; that does not
make them writers of committed brain state. The manager remains the sole conductor of those
workspace changes.

## Two trees, and no graph library

`src/protean/` is the package; `brain/` is the runtime's folder tree. Generated state never
lives inside the installed package, which is what lets a dry run point the whole loop at a
throwaway copy by setting one variable.

**The road not taken: LangGraph, and graph libraries generally.** Nothing was taken from one.
Build 1 needed a fixed ring and a boundary commit, so a library would have brought a scheduler
and a competing checkpoint model before either earned its cost. A.1 now adds conditional firing
and call seams; A.1.i adds concurrent wave members. The former claim that this system has no
fan-out is obsolete. These mechanisms remain hand-rolled and preserve the boundary contract.
The standing ruling requires measured evidence before reopening a graph-library dependency;
its rationale must be tested against the graph as it exists now, not the old ring alone.

**The road not taken: the folder-agent pattern's layout.** The *organism vs organ* rule was
taken — a folder persists and accumulates state, a single file is a stateless role — and the
layout was not. The brain's shape derives from the node set: six nodes, six folders, the same
four entries in each. That derivation is also the only real defence against absorbing another
system's structure by imitation, which no grep can catch.

## What remains outside the runtime

The production operator surface is six foreground verbs on stdlib `argparse`, one task per
brain root. Intake and sleep are offline verbs because a running node cannot rewrite its own
priors. There is no production daemon or autonomous scheduler. Worker concurrency uses threads;
it does not change the tick's single commit boundary.

A separate dashboard prototype existed (not in this mirror). It is not an accepted operator surface and does
not authorize a second state writer. `protean status` and the operator's mailbox answer remain the
supported observation and response paths. The deferred hippocampus and gate rules, the
firing-grade follow-up fix (`the build specification (not in this mirror)` E11, E12), B42's reset, the live
receipts B49, B56 and B69 behind it and the new two-run wet comparison remain distinct pending work.

## Where to start reading

Read the current SPECs' scaffold clauses and rulings first, then `runtime/cycle.py` for the
boundary and call order, `runtime/firing.py` for the inhibition exceptions, and
`cortex/live/wave.py` with `cortex/live/kinds.py` for tier-three spawning. `architecture.md`
locates the rest; historical receipts explain what was measured, not what is permitted now.
