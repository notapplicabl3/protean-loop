"""Every inter-node contract in build 1, and the roster the conformance battery reads.

`the build specification (not in this mirror)` § Deliverable 2. State, persistence and contracts are **one**
deliverable because they are one design: a slot no artifact carries does not survive a resume,
and a prediction whose observable lives nowhere in state cannot be graded.

**Built before any seat script exists.** That ordering is the build's load-bearing bet
(`the local project notes (not in this mirror):116-117`): if the contracts are designed here the mocks conform to them; if
not, the mocks shape them and build 2 rebuilds build 1.

**`MODELS` is the roster, and it is a gate.** `tests/state/test_roster.py` asserts that the
set of pydantic models this package exports equals `MODELS`, and
`tests/state/test_conformance.py` parametrizes over `MODELS` — so a contract added without a
test fails, which is the property M7 closes on. Abstract bases (`ProteanModel`,
`ExtraTolerantModel`, `NodeOutput`, `SeatResult`, `NodeInput`) are deliberately not exported:
they are shapes, not contracts, and are never instantiated.

Three of the five binding contracts live under this package: `BrainState`'s top-level shape
and its refuse-never-migrate versioning; the per-**addressee** seat request and result models
with the `SeatEnvelope` wire shape; and `TraceRecord`'s two kinds, append-only.

**`MODELS` is build 1's contract set, amended in place — never a running total of every build's.**
Build 2's S1–S5 and build 3's P1–P5 are contracts and are not here; they are imported from their
own modules. Build A.1 follows that precedent exactly: a build-1 contract **renamed or replaced**
stays in the roster — `ManagerRequest` for `PlannerRequest`, `ManagerPlan` for `PlannerPlan`,
`WaveMember` for the retired `ExecutorRequest` — while A.1's **new** contracts are not added:
C1 `NodeCall`, C2 `SubagentSpawn`, C3 `FiringDecision` and C4 `BodyTransport` live in
`protean.state.calls`, and the three non-seat returns `ThinkResult`, `ManagerReply` and
`DelegateReturn` are imported from `protean.state.seats`.
"""

from __future__ import annotations

from protean.state.base import ExtraTolerantModel, ProteanModel
from protean.state.brain_state import BrainState
from protean.state.checkpoint import (
    INTEGRITY_FIELD,
    Checkpoint,
    canonical_body,
    compute_integrity,
    load_checkpoint,
    sealed,
    verify_integrity,
)
from protean.state.enums import (
    ANTERIOR_CINGULATE_WEIGHT_KEYS,
    CORTEX_WEIGHT_KEYS,
    HIPPOCAMPUS_WEIGHT_KEYS,
    MONITOR_ROUTER_KEYS,
    TRAP_WEIGHT_KEYS,
    WINDOW_LEN_KEYS,
    Addressee,
    CallType,
    ConstraintKind,
    EpisodeKind,
    Escalation,
    EventName,
    ExpectationKind,
    GoalStatus,
    InterruptKind,
    MismatchClass,
    NodeName,
    Raiser,
    SelectionDecision,
    TerminalState,
    Tier,
    TraceKind,
    TraceSource,
    TrapDetector,
    UnitStatus,
    window_len,
)
from protean.state.errors import (
    ExtensionVersionMismatch,
    IntegrityMismatch,
    InterruptUnanswered,
    ProteanError,
    ReadsDrift,
    RefusalError,
    SchemaVersionMismatch,
    SeedHashMismatch,
    TraceAppendRefused,
)
from protean.state.inputs import (
    BasalGangliaInput,
    HippocampusInput,
    HomeostasisInput,
    MonitorInput,
    ThalamusInput,
)
from protean.state.interrupts import (
    ANSWER_HEADING,
    Interrupt,
    InterruptRequest,
    OpenInterrupt,
    ResolvedInterrupt,
    interrupt_id,
)
from protean.state.outputs import (
    AdmittedContext,
    AdmittedItem,
    ExcludedItem,
    HomeostasisReport,
    MonitorVerdict,
    RetrievalSet,
    RetrievedEpisode,
    SelectionVerdict,
)
from protean.state.primitives import (
    CeilingOverrides,
    Constraint,
    CostCounters,
    Expectation,
    GoalItem,
    Modulators,
    PathBaseline,
    ProjectExtension,
    TrapScalar,
    UnitObservation,
    WorkspaceObservation,
    WorkUnit,
)
from protean.state.reads import (
    NODE_INPUT_MODELS,
    READS_HEADING,
    check_reads,
    declared_reads,
    parse_reads_section,
)
from protean.state.records import (
    BasalGangliaOutcome,
    BasalGangliaPrediction,
    OperatorAnswerOutcome,
    DirectorOutcome,
    DirectorPrediction,
    EpisodeRecord,
    DispatchOutcome,
    DispatchPrediction,
    GoalSnapshot,
    HippocampusOutcome,
    HippocampusPrediction,
    HomeostasisOutcome,
    HomeostasisPrediction,
    InputSignature,
    JournalEntry,
    ManagerOutcome,
    ManagerPrediction,
    MonitorOutcome,
    MonitorPrediction,
    ThalamusOutcome,
    ThalamusPrediction,
    TraceRecord,
    UnitSnapshot,
)
from protean.state.seats import (
    CACHE_READ_KEY,
    STRUCTURED_SUCCESS_STOP_REASON,
    DirectorDirection,
    ExecutorSummary,
    ManagerPlan,
    SeatEnvelope,
    WaveMember,
)
from protean.state.workspace import (
    DirectorRequest,
    LatestOutputs,
    ManagerRequest,
    Workspace,
)

#: Every contract in § Deliverable 2's tables, and nothing else. The battery parametrizes over
#: this tuple and the roster test proves the tuple is the whole exported model set.
MODELS: tuple[type, ...] = (
    # the state object and its envelope
    BrainState,
    Checkpoint,
    # the shared primitives
    Constraint,
    Expectation,
    WorkUnit,
    GoalItem,
    PathBaseline,
    UnitObservation,
    WorkspaceObservation,
    CostCounters,
    CeilingOverrides,
    Modulators,
    ProjectExtension,
    TrapScalar,
    # the mailbox
    InterruptRequest,
    Interrupt,
    OpenInterrupt,
    ResolvedInterrupt,
    # the five deterministic node outputs
    HomeostasisReport,
    RetrievedEpisode,
    RetrievalSet,
    AdmittedItem,
    ExcludedItem,
    AdmittedContext,
    SelectionVerdict,
    MonitorVerdict,
    # the five deterministic node inputs
    HomeostasisInput,
    HippocampusInput,
    ThalamusInput,
    BasalGangliaInput,
    MonitorInput,
    # the workspace and the two per-seat requests
    LatestOutputs,
    Workspace,
    DirectorRequest,
    ManagerRequest,
    # the seat wire shape, the two seat results and the dispatch member
    SeatEnvelope,
    DirectorDirection,
    ManagerPlan,
    WaveMember,
    ExecutorSummary,
    # the prediction payloads
    HomeostasisPrediction,
    HippocampusPrediction,
    ThalamusPrediction,
    BasalGangliaPrediction,
    MonitorPrediction,
    DispatchPrediction,
    ManagerPrediction,
    DirectorPrediction,
    # the outcome payloads
    HomeostasisOutcome,
    HippocampusOutcome,
    ThalamusOutcome,
    BasalGangliaOutcome,
    MonitorOutcome,
    DispatchOutcome,
    ManagerOutcome,
    DirectorOutcome,
    OperatorAnswerOutcome,
    # the three appended artifacts
    InputSignature,
    TraceRecord,
    GoalSnapshot,
    UnitSnapshot,
    EpisodeRecord,
    JournalEntry,
)

#: The one extra-tolerant model in the build (§ Deliverable 6). Named here rather than
#: discovered, so the asymmetry is a stated contract and not an accident of a base class.
EXTRA_TOLERANT_MODELS: tuple[type, ...] = (SeatEnvelope,)

__all__ = [
    "ANSWER_HEADING",
    "ANTERIOR_CINGULATE_WEIGHT_KEYS",
    "CACHE_READ_KEY",
    "CORTEX_WEIGHT_KEYS",
    "EXTRA_TOLERANT_MODELS",
    "HIPPOCAMPUS_WEIGHT_KEYS",
    "INTEGRITY_FIELD",
    "MODELS",
    "MONITOR_ROUTER_KEYS",
    "NODE_INPUT_MODELS",
    "READS_HEADING",
    "STRUCTURED_SUCCESS_STOP_REASON",
    "TRAP_WEIGHT_KEYS",
    "WINDOW_LEN_KEYS",
    "Addressee",
    "AdmittedContext",
    "AdmittedItem",
    "CallType",
    "BasalGangliaInput",
    "BasalGangliaOutcome",
    "BasalGangliaPrediction",
    "OperatorAnswerOutcome",
    "BrainState",
    "CeilingOverrides",
    "Checkpoint",
    "Constraint",
    "ConstraintKind",
    "CostCounters",
    "DirectorDirection",
    "DirectorOutcome",
    "DirectorPrediction",
    "DirectorRequest",
    "DispatchOutcome",
    "DispatchPrediction",
    "EpisodeKind",
    "EpisodeRecord",
    "Escalation",
    "EventName",
    "ExcludedItem",
    "ExecutorSummary",
    "Expectation",
    "ExpectationKind",
    "ExtensionVersionMismatch",
    "ExtraTolerantModel",
    "GoalItem",
    "GoalSnapshot",
    "GoalStatus",
    "HippocampusInput",
    "HippocampusOutcome",
    "HippocampusPrediction",
    "HomeostasisInput",
    "HomeostasisOutcome",
    "HomeostasisPrediction",
    "HomeostasisReport",
    "InputSignature",
    "IntegrityMismatch",
    "Interrupt",
    "InterruptKind",
    "InterruptRequest",
    "InterruptUnanswered",
    "JournalEntry",
    "LatestOutputs",
    "ManagerOutcome",
    "ManagerPlan",
    "ManagerPrediction",
    "ManagerRequest",
    "MismatchClass",
    "Modulators",
    "MonitorInput",
    "MonitorOutcome",
    "MonitorPrediction",
    "MonitorVerdict",
    "NodeName",
    "OpenInterrupt",
    "PathBaseline",
    "ProjectExtension",
    "ProteanError",
    "ProteanModel",
    "Raiser",
    "ReadsDrift",
    "RefusalError",
    "ResolvedInterrupt",
    "RetrievalSet",
    "RetrievedEpisode",
    "SchemaVersionMismatch",
    "SeatEnvelope",
    "SeedHashMismatch",
    "SelectionDecision",
    "SelectionVerdict",
    "TerminalState",
    "ThalamusInput",
    "ThalamusOutcome",
    "ThalamusPrediction",
    "Tier",
    "TraceAppendRefused",
    "TraceKind",
    "TraceRecord",
    "TraceSource",
    "TrapDetector",
    "TrapScalar",
    "UnitObservation",
    "UnitSnapshot",
    "UnitStatus",
    "WaveMember",
    "WorkUnit",
    "Workspace",
    "WorkspaceObservation",
    "canonical_body",
    "check_reads",
    "compute_integrity",
    "declared_reads",
    "interrupt_id",
    "load_checkpoint",
    "parse_reads_section",
    "sealed",
    "verify_integrity",
    "window_len",
]
