"""The pinned literals: node order, call types and addressees, schema versions, exit codes.

`the build specification (not in this mirror)` § Deliverable 1 (the two-tree layout and the brain-root
rule), § Deliverable 2 (the five versioned artifacts), § Deliverable 3 (the cycle, the five
terminal states and the named refusals), § Directional decisions 8, 12, 18, 20.

**This module is the single owner of every literal the runtime iterates or exits on** — the
node order, the **tier set** (two seats, director → manager), the **four call types**
(`think`, `escalate`, `delegate`, `dispatch`), the **addressee set** the one seat port takes as
its first argument (`TIERS + CALL_TYPES`: a tier for a seat call, a call type for everything
else), the schema versions, the admissible signals and the exit codes.
Deliverable 3: "The order is a literal in `config.py`, iterated by the runtime, never
hardcoded inside a node." The same rule governs the exit codes: a caller that needs a code
reads it from here rather than writing an integer, so the operator surface and the tests
agree by construction. **Tier three is not in `TIERS` and is not a seat**: it is a specialized
subagent library the manager dispatches, so it is addressed as the call type `dispatch` and
never selected as a tier (`the build specification (not in this mirror)` § Deliverable 3, route R15).

**It imports nothing from the rest of the package**, deliberately. `protean.state` reads its
schema versions and its terminal-state names from here, so a dependency in the other
direction would be a cycle; `protean.state.enums` instead asserts at import time that its
closed sets match the tuples below.

**The brain root resolves as `$PROTEAN_BRAIN` else `<repo>/brain`** (§ Deliverable 1,
decision 20). The repo-relative branch walks up from this file, which is correct for the
editable install `uv sync` produces and for a source checkout; a non-editable install has no
repo to fall back to and must set `$PROTEAN_BRAIN`. `protean dry` always exports it
(§ Deliverable 7), so the repo's own `brain/` is untouched by a dry run *by construction*.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import MappingProxyType
from typing import Final, Mapping

# --------------------------------------------------------------------------------------
# The cycle
# --------------------------------------------------------------------------------------

#: The one ordered pass per tick (§ Deliverable 3, decision 8). Every node on the path every
#: tick; the cortex seat is the fifth step and the sixth node folder (decision 23).
NODE_ORDER: Final[tuple[str, ...]] = (
    "homeostasis",
    "hippocampus",
    "thalamus",
    "basal_ganglia",
    "cortex",
    "anterior_cingulate",
)

#: The five deterministic nodes — `NODE_ORDER` less the seat.
DETERMINISTIC_NODES: Final[tuple[str, ...]] = tuple(
    node for node in NODE_ORDER if node != "cortex"
)

#: The seat's folder. Its `trace.jsonl` is keyed by tier (§ Deliverable 4, decision 23).
CORTEX_NODE: Final[str] = "cortex"

#: The cortex's two seats, ordered director → manager — the direction of the ladder's climb
#: (`the build specification (not in this mirror)` § Deliverable 3, decision 1). Three tiers is still
#: the ceiling, and **tier three is not a seat**: it is a specialized subagent library the
#: manager dispatches, so it takes no tier, no seat block and no session handle.
TIERS: Final[tuple[str, ...]] = ("director", "manager")

# --------------------------------------------------------------------------------------
# The brain root and the tracked seed tree
# --------------------------------------------------------------------------------------

#: The environment variable that overrides the repo-relative brain root.
BRAIN_ROOT_ENV: Final[str] = "PROTEAN_BRAIN"

#: Directories the runtime owns under the brain root. Every one of them holds generated
#: state and is therefore untracked, so a fresh checkout does not carry them: the runtime
#: and `protean dry` create them on demand rather than assuming a seeded copy has them.
GENERATED_BRAIN_DIRS: Final[tuple[str, ...]] = (
    "mailbox/open",
    "mailbox/orphaned",
    "state",
    "episodes",
    "projects",
)

#: The four entries every node folder carries (§ Deliverable 4, decision 5). `trace.jsonl` is
#: generated state; the other three are the hand-authored seed.
NODE_FOLDER_ENTRIES: Final[tuple[str, ...]] = (
    "NODE.md",
    "weights.yaml",
    "trace.jsonl",
    "procedures",
)

#: The advisory instance lock, persisted at the brain root and deliberately outside the
#: versioned-artifact set: inspected for a pid, never parsed as a contract (decision 12).
LOCK_FILENAME: Final[str] = "protean.lock"


def repo_root() -> Path:
    """The checkout this package was installed from — `<repo>/src/protean/config.py`."""
    return Path(__file__).resolve().parents[2]


def brain_root() -> Path:
    """`$PROTEAN_BRAIN` if set, else `<repo>/brain` (§ Deliverable 1, decision 20)."""
    override = os.environ.get(BRAIN_ROOT_ENV)
    if override:
        return Path(override).expanduser().resolve()
    return repo_root() / "brain"


def node_dir(node: str, root: Path | None = None) -> Path:
    """The folder of one node under a brain root."""
    return (root if root is not None else brain_root()) / "nodes" / node


# --------------------------------------------------------------------------------------
# Schema versions — one per persisted artifact, plus the state object itself
# --------------------------------------------------------------------------------------

#: **Six schema versions move together, 1 → 2, in build A.1** (`the build specification (not in this mirror)`
#: § Scaffold clause item 2): brain state, checkpoint, journal, trace and mailbox here, and
#: `SEAT_CALL_SCHEMA_VERSION` in build 2's block below. `EPISODE_SCHEMA_VERSION` is the one entry
#: of `ARTIFACT_SCHEMA_VERSIONS` that does **not** move — an episode record means on disk exactly
#: what it meant at v1. Each of the six now means something different: the `latest` slots and the
#: seat set, the journal's key and validators, the receipt's columns, the trace's addressee column
#: and its renamed literals, the mailbox's raiser set and interrupt id. **Old artifacts are refused
#: by name, never migrated** — A.1 ships no migration path, and this root's own pre-A.1 artifacts
#: are archived and reset by hand (§ Build process, leg 1; row B42).

#: `BrainState.schema_version` — the `latest` slots and the two-tier seat-session key set.
BRAIN_STATE_SCHEMA_VERSION: Final[int] = 2

#: The checkpoint **envelope's** own version, distinct from the state's (§ Deliverable 2).
CHECKPOINT_SCHEMA_VERSION: Final[int] = 2

#: The remaining four of the five persisted artifacts (decision 12). The episode is the one
#: that stays at 1.
JOURNAL_SCHEMA_VERSION: Final[int] = 2
TRACE_SCHEMA_VERSION: Final[int] = 2
EPISODE_SCHEMA_VERSION: Final[int] = 1
MAILBOX_SCHEMA_VERSION: Final[int] = 2

#: The five versioned artifacts and the version the running code writes and demands. Every
#: loader refuses a mismatch with a named error; build 1 ships no migration path.
ARTIFACT_SCHEMA_VERSIONS: Final[Mapping[str, int]] = MappingProxyType(
    {
        "checkpoint": CHECKPOINT_SCHEMA_VERSION,
        "journal": JOURNAL_SCHEMA_VERSION,
        "trace": TRACE_SCHEMA_VERSION,
        "episode": EPISODE_SCHEMA_VERSION,
        "mailbox": MAILBOX_SCHEMA_VERSION,
    }
)

# --------------------------------------------------------------------------------------
# Build 2's literals — authored here for the whole build, read-only to every later order
# --------------------------------------------------------------------------------------
#
# `the work orders (not in this mirror)` order W2 (ledger entry V2-3): this module and
# `protean.runtime.paths` are read-only to orders W3–W9, so every literal build 2 needs is
# written here in one pass rather than four orders each opening the file.
#
# **Build 2's tables are separate mappings, deliberately.** `ARTIFACT_SCHEMA_VERSIONS` and
# `REFUSAL_EXIT_CODES` above are pinned name-for-name by build 1's own battery, which no order
# in this build may edit; extending them in place would falsify a landed row rather than add a
# literal. `EXIT_CODES` merges both refusal tables, so a caller that reads *that* table — which
# is what every caller does — sees one surface (recorded in the dispatch ledger).

#: `SeatCallRecord` — the sixth persisted artifact (§ Deliverable 2, seam contract S2). **At 2
#: from build A.1**: the receipt gains `node`, `call#`, `member#` and `kind`, its dedupe key
#: widens and its `request` field is removed, so it is the sixth of the six that move together.
#:
#: **2 → 3 in build A.1.i, once, and it is the only one of the six that moves**
#: (`the build specification (not in this mirror)` § Scaffold clause item 2, A1-9): the receipt gains
#: **four** columns — `max_call_usd` and `timeout_seconds`, which `SPAWN_RECEIPT_FIELDS` has named
#: since A.1 and no column ever carried, plus the two witness fields `permission_denials` and
#: `audit` — and **one bump covers all four**. A version-2 line is **refused by name, never
#: migrated**; `block_ref`'s change is a change of value and not of field set, so no other version
#: moves (folded: S-i12). This root's `brain/state/` is inside B42's reset, so nothing on disk pays
#: for a bump A.1's refusal was not already refusing.
SEAT_CALL_SCHEMA_VERSION: Final[int] = 3

#: `SemanticChunk` and `IntakeManifest` — the store's record and its manifest (S4, S3).
SEMANTIC_CHUNK_SCHEMA_VERSION: Final[int] = 1
INTAKE_MANIFEST_SCHEMA_VERSION: Final[int] = 1

#: `OracleReport` (S5) and `WorkloadRunReport` (a builder's default, folded: S-27).
ORACLE_REPORT_SCHEMA_VERSION: Final[int] = 1
WORKLOAD_RUN_REPORT_SCHEMA_VERSION: Final[int] = 1

#: Build 2's versioned artifacts, beside the five above rather than inside them.
BUILD2_ARTIFACT_SCHEMA_VERSIONS: Final[Mapping[str, int]] = MappingProxyType(
    {
        "seat_call": SEAT_CALL_SCHEMA_VERSION,
        "semantic_chunk": SEMANTIC_CHUNK_SCHEMA_VERSION,
        "intake_manifest": INTAKE_MANIFEST_SCHEMA_VERSION,
        "oracle_report": ORACLE_REPORT_SCHEMA_VERSION,
        "workload_run_report": WORKLOAD_RUN_REPORT_SCHEMA_VERSION,
    }
)

#: The fifth verb's name (§ Deliverable 3, decision 14). It is the last entry of `VERBS`,
#: carried there by the order that landed `protean intake` together with the three build-1 rows
#: that pinned the tuple at four (folded: S-39).
INTAKE_VERB: Final[str] = "intake"

# --------------------------------------------------------------------------------------
# Build 3's literals — authored here for the whole build, read-only to every later order
# --------------------------------------------------------------------------------------
#
# `the work orders (not in this mirror)` order W2 (ledger entry V2-4), on build 2's own precedent
# above: this module and `protean.runtime.paths` are read-only to orders W3–W10, so every
# literal build 3 needs is written here in one pass — the sixth verb, both new refusal codes,
# the five new schema versions, and the two closed sets Deliverable 1 names.
#
# **Build 3's tables are separate mappings too**, for build 2's reason unchanged: extending
# `ARTIFACT_SCHEMA_VERSIONS` or `REFUSAL_EXIT_CODES` in place would falsify a landed row rather
# than add a literal. `EXIT_CODES` merges all three refusal tables.

#: The five seam contracts build 3 introduces (§ Scaffold clause). P1, P2, P4 and P5 live on
#: `protean.state.sleep`; P3 lives on `protean.state.habit_hits` (order W7).
WEIGHT_UPDATE_SCHEMA_VERSION: Final[int] = 1
PROCEDURE_SCHEMA_VERSION: Final[int] = 1
HABIT_HIT_SCHEMA_VERSION: Final[int] = 1
PROJECT_MEMORY_SCHEMA_VERSION: Final[int] = 1
SLEEP_REPORT_SCHEMA_VERSION: Final[int] = 1

#: Build 3's versioned artifacts, beside build 1's five and build 2's five rather than inside
#: them. The names are the artifact names a `SchemaVersionMismatch` quotes.
BUILD3_ARTIFACT_SCHEMA_VERSIONS: Final[Mapping[str, int]] = MappingProxyType(
    {
        "weight_update": WEIGHT_UPDATE_SCHEMA_VERSION,
        "procedure": PROCEDURE_SCHEMA_VERSION,
        "habit_hit": HABIT_HIT_SCHEMA_VERSION,
        "project_memory": PROJECT_MEMORY_SCHEMA_VERSION,
        "sleep_report": SLEEP_REPORT_SCHEMA_VERSION,
    }
)

#: The sixth verb's name (§ Deliverable 2, decision 16). It is the last entry of `VERBS`,
#: beside `INTAKE_VERB` on the shape S-39 fixed for the fifth.
SLEEP_VERB: Final[str] = "sleep"

#: § Deliverable 1's closed signal list — the nine a learner may consume. `operator_answer` is
#: deliberately absent: `OperatorAnswerOutcome` declines to put a verdict on the node that asked, so
#: it is evidence for the operator and not for a learner (decision 18, folded: A1-8).
#:
#: **Build A.1 leaves it at nine: two renamed and one added** (`the build specification (not in this mirror)`
#: § Deliverable 1, decision 18). `executor_expectations` and `planner_horizon` were minted under
#: tiers A.1 deletes, so they become `dispatch_expectations` (minted from the merged dispatch
#: observation, addressee `dispatch`) and `manager_horizon` (tier `manager`); `firing_check` is the
#: ninth, the signal that makes a node's cheap firing check learnable rather than invisible.
ADMISSIBLE_SIGNALS: Final[tuple[str, ...]] = (
    "homeostasis_cost",
    "hippocampus_citation",
    "thalamus_citation",
    "gate_unit_survives",
    "monitor_next_verdict",
    "dispatch_expectations",
    "manager_horizon",
    "director_progress",
    "firing_check",
)

#: The four reasons a pair is excluded, and the keys of `SleepReport.excluded`. Closed: a fifth
#: reason would be a SPEC change, because the four tests of § Deliverable 1's table are four.
EXCLUSION_UNJOINED: Final[str] = "unjoined"
EXCLUSION_OFF_LIST: Final[str] = "off-list"
EXCLUSION_UNGRADEABLE: Final[str] = "ungradeable"
EXCLUSION_VACUOUS: Final[str] = "vacuous"
SLEEP_EXCLUSION_REASONS: Final[tuple[str, ...]] = (
    EXCLUSION_UNJOINED,
    EXCLUSION_OFF_LIST,
    EXCLUSION_UNGRADEABLE,
    EXCLUSION_VACUOUS,
)

#: The node folders whose `weights.yaml` sleep may re-value — `NODE_ORDER` less the gate
#: (§ Deliverable 3: "Five node folders are writable and one is not"). The gate's file is the
#: empty mapping by contract, so `gate_unit_survives` feeds the report and procedure candidacy
#: and is never a weights key; refusal 2's file list is derived from this tuple.
WEIGHTS_WRITABLE_NODES: Final[tuple[str, ...]] = tuple(
    node for node in NODE_ORDER if node != "basal_ganglia"
)

# --------------------------------------------------------------------------------------
# Build A.1's literals — authored here for the whole build, read-only to every later order
# --------------------------------------------------------------------------------------
#
# `the work orders (not in this mirror)` order W1, on build 2's and build 3's own precedent
# above: this module and `protean.state.enums` are read-only to orders W2–W10, so every literal
# A.1 needs is written here in one pass — the two-name `TIERS` above, the six schema versions at
# 2, the nine `ADMISSIBLE_SIGNALS`, and the call-type and addressee sets below. A producer order
# that finds a literal missing writes a `BLOCKED` entry rather than authoring a second table.
#
# **A.1's sets are their own tuples, for build 2's reason unchanged**: extending a landed table
# in place would falsify a landed row rather than add a literal.

#: The four call-type literals (§ Deliverable 2's three-type table, § Deliverable 4's legality
#: table). `think`, `escalate` and `delegate` are the three possibilities an outer node has and
#: there is no fourth; `dispatch` is the manager's own wave, which is a call type rather than a
#: tier because the executor seat is gone and `ExecutorSummary` is emitted by the addressee that
#: produced it.
CALL_THINK: Final[str] = "think"
CALL_ESCALATE: Final[str] = "escalate"
CALL_DELEGATE: Final[str] = "delegate"
CALL_DISPATCH: Final[str] = "dispatch"

#: The closed call-type set, ordered as § Deliverable 2 states them, with `dispatch` last
#: because it is the manager's and not an outer node's.
CALL_TYPES: Final[tuple[str, ...]] = (
    CALL_THINK,
    CALL_ESCALATE,
    CALL_DELEGATE,
    CALL_DISPATCH,
)

#: The two call types that carry a `calls:` block in `brain/seats.yaml` — the two that
#: configure a model call at all. `delegate` and `dispatch` configure nothing there: a spawn's
#: whole process comes from a kind block, and those live in the `kinds:` container beside it
#: (`the build specification (not in this mirror)` § Deliverable 1), grouped by the two class names
#: the literal one line below derives from this one. A.1's order W3 landed the `calls:` blocks
#: themselves; the literal is authored here with the rest.
CONFIGURED_CALL_TYPES: Final[tuple[str, ...]] = (CALL_THINK, CALL_ESCALATE)

#: The two kind classes: the call types that carry **no** `calls:` block and whose whole process
#: comes from a kind block instead, which is exactly the `kinds:` container's two sub-mapping
#: names (`the build specification (not in this mirror)` § Deliverable 1, § Directional decisions 2).
#:
#: **Derived, never restated** (folded: S-i11): `CALL_TYPES` minus `CONFIGURED_CALL_TYPES`, which
#: is `("delegate", "dispatch")` in the order that derivation produces. **That order scopes this
#: literal alone and never the document** (folded: S-i52) — the container's keys are compared as a
#: SET, so a seed may spell the two sub-mappings either way.
KIND_CLASSES: Final[tuple[str, ...]] = tuple(
    name for name in CALL_TYPES if name not in CONFIGURED_CALL_TYPES
)

#: The addressee set — the port's first argument (§ Deliverable 2, decision 10). One port, many
#: callers: the addressee is a **tier** for a seat call and a **call type** for everything else,
#: which is what keeps containment, the caps and the journal on one code path. Derived from the
#: two tuples above rather than restated, so a tier or a call type cannot be added to one and
#: forgotten in the other.
ADDRESSEES: Final[tuple[str, ...]] = TIERS + CALL_TYPES

# --------------------------------------------------------------------------------------
# Terminal states and exit codes
# --------------------------------------------------------------------------------------

#: Five terminal states, five distinct exit codes (§ Deliverable 3, decision 18).
TERMINAL_STATES: Final[tuple[str, ...]] = (
    "done",
    "blocked",
    "stopped",
    "interrupted",
    "stuck",
)

#: Precedence when several fire in one tick: `interrupted` > `stuck` > `stopped`
#: (§ Deliverable 3, decision 18). Higher wins; the losers are written as `event` records.
TERMINAL_PRECEDENCE: Final[Mapping[str, int]] = MappingProxyType(
    {"done": 0, "blocked": 1, "stopped": 2, "stuck": 3, "interrupted": 4}
)

EXIT_DONE: Final[int] = 0
EXIT_BLOCKED: Final[int] = 10
EXIT_STOPPED: Final[int] = 11
EXIT_INTERRUPTED: Final[int] = 12
EXIT_STUCK: Final[int] = 13

#: The named refusals. Each is its own code so an operator — and a test — can tell them
#: apart from a terminal state and from each other (§ Deliverable 3, § Deliverable 5).
#:
#: `EXIT_UNANSWERED_INTERRUPT` — `resume` found an open item with no `## Answer` body.
#: `EXIT_ROOT_OCCUPIED`        — `run` against a root holding a task whose committed
#:                               `terminal` is anything but `done`.
#: `EXIT_LOCK_HELD`            — a second instance against a live lock; the message names
#:                               the holder.
#: `EXIT_CONTRACT_REFUSED`     — the resume refusal ladder: envelope version → state
#:                               version → extension versions → integrity → `seed_hashes`.
#:                               Versioning is a refusal, never a migration.
#: `EXIT_SEED_DRIFT`           — a `NODE.md` `## Reads` list that no longer names exactly
#:                               its input model's fields, refused at startup; and the call
#:                               policy's seed-shape refusal, raised in
#:                               `engine.build_context()` — an on trigger key whose `NODE.md`
#:                               `## Calls` lacks its line, or a trigger key outside its
#:                               domain (`the build specification (not in this mirror)` § Deliverable 1).
EXIT_UNANSWERED_INTERRUPT: Final[int] = 20
EXIT_ROOT_OCCUPIED: Final[int] = 21
EXIT_LOCK_HELD: Final[int] = 22
EXIT_CONTRACT_REFUSED: Final[int] = 23
EXIT_SEED_DRIFT: Final[int] = 24

#: Build 2's named refusals, numbered on from build 1's (order W2 authors them for the build).
#:
#: `EXIT_INTAKE_REFUSED` — `protean intake` against a root a task occupies. Intake writes seed
#:                         files and the runtime may never write one, so the two are refused
#:                         apart rather than serialized (§ Deliverable 3, decision 14).
EXIT_INTAKE_REFUSED: Final[int] = 25

#: Build 3's two named refusals, numbered on from build 2's (order W2 authors them for the
#: build). `--force` overrides neither (decision 16, folded: A1-10).
#:
#: `EXIT_SLEEP_REFUSED`      — `protean sleep` against a root with a task **in flight**: the
#:                             instance lock held, or a task whose committed `terminal` is
#:                             `None`. Narrower than intake's arm, because the
#:                             committed-but-not-`done` case is the second one's (folded: S-11).
#: `EXIT_SLEEP_SEED_REFUSED` — the seed-hash arm, and it covers both of its conditions: a root
#:                             holding a committed, not-`done` task whose checkpoint records a
#:                             seed hash for a file this run would write (refusal 2), and a run
#:                             whose recorded `weights.yaml` hash has **moved**, refused as
#:                             evidence before one update is derived (decision 17). One code
#:                             because one fact refuses in both — the seeds are not in the state
#:                             the checkpoint recorded — and the two raise distinct exceptions,
#:                             so an operator and a test still tell them apart by name.
EXIT_SLEEP_REFUSED: Final[int] = 26
EXIT_SLEEP_SEED_REFUSED: Final[int] = 27

#: Terminal state → process exit code. The runtime exits on the *committed* `terminal`, so
#: this map is read after the boundary commit, never before it.
TERMINAL_EXIT_CODES: Final[Mapping[str, int]] = MappingProxyType(
    {
        "done": EXIT_DONE,
        "blocked": EXIT_BLOCKED,
        "stopped": EXIT_STOPPED,
        "interrupted": EXIT_INTERRUPTED,
        "stuck": EXIT_STUCK,
    }
)

#: Every refusal that is not a terminal state, by name, so no caller writes an integer.
REFUSAL_EXIT_CODES: Final[Mapping[str, int]] = MappingProxyType(
    {
        "unanswered_interrupt": EXIT_UNANSWERED_INTERRUPT,
        "root_occupied": EXIT_ROOT_OCCUPIED,
        "lock_held": EXIT_LOCK_HELD,
        "contract_refused": EXIT_CONTRACT_REFUSED,
        "seed_drift": EXIT_SEED_DRIFT,
    }
)

#: Build 2's named refusals, beside build 1's five rather than inside them (see the build-2
#: literal note above). Every caller reads `EXIT_CODES`, which merges the two.
BUILD2_REFUSAL_EXIT_CODES: Final[Mapping[str, int]] = MappingProxyType(
    {"intake_refused": EXIT_INTAKE_REFUSED}
)

#: Build 3's named refusals, in their own table beside build 2's for the same reason build 2's
#: sits beside build 1's: extending a landed table in place would falsify a landed row.
BUILD3_REFUSAL_EXIT_CODES: Final[Mapping[str, int]] = MappingProxyType(
    {
        "sleep_refused": EXIT_SLEEP_REFUSED,
        "sleep_seed_refused": EXIT_SLEEP_SEED_REFUSED,
    }
)

#: Every exit code this build can produce, name → code. Distinctness is asserted by
#: `tests/state/test_config_literals.py`.
EXIT_CODES: Final[Mapping[str, int]] = MappingProxyType(
    {
        **TERMINAL_EXIT_CODES,
        **REFUSAL_EXIT_CODES,
        **BUILD2_REFUSAL_EXIT_CODES,
        **BUILD3_REFUSAL_EXIT_CODES,
    }
)

# --------------------------------------------------------------------------------------
# The operator surface
# --------------------------------------------------------------------------------------

#: The six verbs (§ Deliverable 3, decision 21; build 2's fifth, decision 14; build 3's sixth,
#: § Deliverable 2). Build 2's console becomes a caller of this surface, not a second writer.
VERBS: Final[tuple[str, ...]] = ("run", "resume", "status", "dry", INTAKE_VERB, SLEEP_VERB)
