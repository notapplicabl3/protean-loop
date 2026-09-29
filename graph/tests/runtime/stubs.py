"""The test-local seat responder, router and mailbox — the runtime's seams, driven by hand.

`the build specification (not in this mirror)` § Deliverable 6 and § Deliverable 7. `src/protean/cortex/` and
`src/protean/mailbox/` are a later order's; the runtime holds only the ports, so its own battery
supplies the other side of each seam here rather than in `fixtures/`, which belongs to the
scenario orders.

**These stubs are conformance fixtures, not conveniences.** The envelope they build carries all
four of `SeatEnvelope`'s measured facts, and the responder is **request-keyed**, never
tick-indexed — the same two rules the scripted seats are held to, so a runtime test cannot pass
against a shape the real seats could not produce.

**Zero model calls.** Nothing here spawns a process, and no binary is named.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from protean import config
from protean.cortex.adapters import ScriptedSeat, SeatDesk
from protean.cortex.calls import CallDesks
from protean.cortex.ladder import LadderWeights
from protean.cortex.router import LadderRouter
from protean.cortex.scripts import load_script
from protean.runtime.engine import build_context, new_state
from protean.runtime.seat import SeatCallFacts, SeatLayer, SeatSelection
from protean.state.enums import CallType, Escalation, InterruptKind, Raiser, Tier
from protean.state.interrupts import ANSWER_HEADING, Interrupt, InterruptRequest
from protean.state.seats import ManagerPlan, SeatEnvelope, WaveMember
from protean.state.workspace import DirectorRequest, ManagerRequest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The scripted call fixtures every live-transport module in this battery drives against.
CALL_FIXTURES = REPO_ROOT / "fixtures" / "calls"

#: A stand-in for the overhead entry a real envelope carries beside the first-party call. It is
#: a shape, not a model id: no module in this repo outside `src/protean/cortex/` names one.
OVERHEAD_MODEL = "overhead-tier"
FIRST_PARTY_MODEL = "seat-tier"


def envelope(result: Mapping | object, *, tokens: int = 0, cache_read: int = 0) -> SeatEnvelope:
    """A `SeatEnvelope` carrying all four measured facts around one tier's result payload."""
    payload = result if isinstance(result, Mapping) else result.model_dump(mode="json")
    return SeatEnvelope(
        stop_reason="tool_use",
        result=json.dumps(payload),
        modelUsage={
            FIRST_PARTY_MODEL: {"inputTokens": tokens},
            OVERHEAD_MODEL: {"inputTokens": 0},
        },
        usage={"cache_read_input_tokens": cache_read, "output_tokens": tokens},
    )


@dataclass(slots=True)
class StubSeat:
    """A request-keyed responder: `(tier, request) -> result model`, recorded as it goes."""

    responder: Callable[[Tier, object], object]
    calls: list[tuple[str, object]] = field(default_factory=list)
    tokens_per_call: int = 0
    on_call: Callable[[str], None] | None = None

    def __call__(self, tier: Tier, request) -> SeatEnvelope:
        self.calls.append((str(tier), request))
        if self.on_call is not None:
            self.on_call(config.CORTEX_NODE)
        return envelope(self.responder(tier, request), tokens=self.tokens_per_call)


@dataclass(slots=True)
class StubRouter:
    """A tier selector driven by a hand-written rule over the workspace. No tick indexing.

    It answers on **every** tick, including one whose seat call the runtime skips: the two skip
    conditions skip the call, never the routing.
    """

    rule: Callable[[object], SeatSelection]
    selections: list[SeatSelection] = field(default_factory=list)

    def __call__(self, workspace) -> SeatSelection:
        selection = self.rule(workspace)
        self.selections.append(selection)
        return selection


def layer(router: StubRouter, seat: StubSeat) -> SeatLayer:
    """The pair the runtime is handed, exactly as `protean.cortex.layer.build()` will return."""
    return SeatLayer(router=router, port=seat)


@dataclass(slots=True)
class StubMailbox:
    """The mailbox's file half, as `src/protean/mailbox/` will implement it.

    YAML front matter over a markdown body is that order's format decision; this stub stores the
    same fields as JSON with the answer under the literal `## Answer` heading, because what the
    runtime's own battery is entitled to assert is the *protocol* — write, read, list, delete,
    orphan — and not the rendering.
    """

    root: Path
    written: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    orphaned: list[str] = field(default_factory=list)

    @property
    def open_dir(self) -> Path:
        return self.root / "mailbox" / "open"

    @property
    def orphan_dir(self) -> Path:
        return self.root / "mailbox" / "orphaned"

    def path_for(self, interrupt_id: str) -> Path:
        return self.open_dir / f"{interrupt_id}.md"

    def write(self, interrupt: Interrupt) -> Path:
        self.open_dir.mkdir(parents=True, exist_ok=True)
        path = self.path_for(interrupt.id)
        body = json.dumps(interrupt.model_dump(mode="json", exclude={"answer"}))
        answer = interrupt.answer or ""
        path.write_text(f"{body}\n\n{ANSWER_HEADING}\n\n{answer}\n", encoding="utf-8")
        self.written.append(interrupt.id)
        return path

    def read(self, interrupt_id: str) -> Interrupt | None:
        path = self.path_for(interrupt_id)
        if not path.exists():
            return None
        head, _, tail = path.read_text(encoding="utf-8").partition(ANSWER_HEADING)
        payload = json.loads(head.strip())
        payload["answer"] = tail.strip() or None
        return Interrupt.model_validate(payload)

    def open_ids(self) -> list[str]:
        if not self.open_dir.exists():
            return []
        return sorted(path.stem for path in self.open_dir.glob("*.md"))

    def delete(self, interrupt_id: str) -> None:
        self.path_for(interrupt_id).unlink(missing_ok=True)
        self.deleted.append(interrupt_id)

    def orphan(self, interrupt_id: str) -> Path:
        self.orphan_dir.mkdir(parents=True, exist_ok=True)
        target = self.orphan_dir / f"{interrupt_id}.md"
        self.path_for(interrupt_id).replace(target)
        self.orphaned.append(interrupt_id)
        return target

    def answer(self, interrupt_id: str, text: str) -> None:
        """What the operator does with an editor: write a body under the literal `## Answer` heading."""
        path = self.path_for(interrupt_id)
        head, _, _ = path.read_text(encoding="utf-8").partition(ANSWER_HEADING)
        path.write_text(f"{head}{ANSWER_HEADING}\n\n{text}\n", encoding="utf-8")


def seed_brain(source: Path, destination: Path) -> Path:
    """Copy the tracked seed tree to a throwaway root and create its generated directories.

    Every test runs against a copy: the repo's own `brain/` is read-only to this battery, which
    is the same rule `protean dry` enforces by construction for a scenario run.
    """
    shutil.copytree(source / "nodes", destination / "nodes")
    for node in config.NODE_ORDER:
        (config.node_dir(node, destination) / "trace.jsonl").write_text("", encoding="utf-8")
    for relative in config.GENERATED_BRAIN_DIRS:
        (destination / relative).mkdir(parents=True, exist_ok=True)
    return destination


def recorded_nodes(monkeypatch, sink: list[str]) -> None:
    """Wrap every deterministic node so the cycle's real call sequence is observable."""
    from protean.runtime import cycle as cycle_module

    wrapped = {}
    for name, callable_ in cycle_module.NODES.items():
        def _wrap(fn=callable_, node=name):
            def _call(payload):
                sink.append(node)
                return fn(payload)

            return _call

        wrapped[name] = _wrap()
    monkeypatch.setattr(cycle_module, "NODES", wrapped)


def always(selection: SeatSelection) -> Callable[[object], SeatSelection]:
    """A router rule that answers the same way every tick — the simplest request-keyed rule."""
    return lambda workspace: selection


def manager_then_dispatch(unit_id: str) -> Callable[[object], SeatSelection]:
    """Plan while the unit stack is empty, then act — selection off workspace signals only.

    **Re-based by build A.1** (`the build specification (not in this mirror)` § Deliverable 3): there is
    no acting *seat* to select any more. The manager plans and then assembles the tick's single
    dispatch wave at its own step, so both ticks name the manager and the second carries the
    rung that put it there. **Dispatching that wave is order W8's**, which is why no
    `ExecutorSummary` reaches `latest.dispatch` from this router yet.
    """

    def _rule(workspace) -> SeatSelection:
        if workspace.latest.manager is None:
            return SeatSelection(tier=Tier.MANAGER, escalation=Escalation.EMPTY_UNIT_STACK)
        return SeatSelection(
            tier=Tier.MANAGER, escalation=Escalation.MISMATCH_STREAK, unit_id=unit_id
        )

    return _rule


def request_keyed(
    responses: Mapping[str, Callable[[object], object]]
) -> Callable[[Tier, object], object]:
    """A responder keyed by the incoming request's tier, never by a tick index."""

    def _respond(tier: Tier, request):
        if isinstance(request, (DirectorRequest, ManagerRequest)):
            return responses[str(tier)](request)
        raise AssertionError(f"unexpected request type {type(request).__name__}")

    return _respond


def selections_of(router: StubRouter) -> Sequence[str]:
    """The recorded tier climb — the escalation sequence a ladder scenario is graded on."""
    return tuple(str(item.tier) for item in router.selections if item is not None)


def flatten(items: Iterable[Iterable]) -> list:
    return [item for group in items for item in group]


def committed_state(paths) -> dict:
    """The checkpoint the boundary committed, decoded off disk.

    `tests/conftest.py`'s `load_envelope` does this for a hand-authored fixture; this does it for
    the file a run wrote. The returned mapping is the whole checkpoint envelope, so a consumer
    reads `["state"]` for the state block and `["revision"]` for the revision the ladder sealed
    it at — the shape `protean.state.checkpoint.load_checkpoint()` is handed.
    """
    return json.loads(paths.checkpoint.read_text(encoding="utf-8"))


def set_weight(brain: Path, node: str, **keys) -> None:
    """Write one or more keys into the **throwaway** root's own weights file for that node.

    Every threshold this battery moves — `max_tokens`, `max_ticks`, `max_admitted`, a firing
    threshold, the cortex ladder's horizons — is a `weights.yaml` key, and the write always goes
    to the temp root a test owns: nothing in `brain/` and nothing in `fixtures/` carries a number
    a test chose. A dynamic key name is passed as `**{NAME: value}`.
    """
    path = config.node_dir(node, brain) / "weights.yaml"
    weights = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    weights.update(keys)
    path.write_text(yaml.safe_dump(weights), encoding="utf-8")


def member_keyed(
    responses: Mapping[str, Callable[[object], object]]
) -> Callable[[object, object], object]:
    """`request_keyed`, widened to the wave's member request.

    A `WaveMember` is the dispatch member's request model (`the build specification (not in this mirror)`
    § Deliverable 3's table) and is not a seat request, so the shared responder — which answers
    the two seats — is wrapped rather than replaced: the seats keep their path and the member
    takes the `dispatch` responder.
    """
    seats = request_keyed(responses)

    def _respond(addressee, request):
        if isinstance(request, WaveMember):
            return responses[str(addressee)](request)
        return seats(addressee, request)

    return _respond


def planner_layer(planner) -> SeatLayer:
    """One tick of a planner that does exactly what the test needs and nothing else.

    The manager answers from `planner`, a dispatch member answers with the bare narrative the
    unit's expectation does not read, and the director echoes the tick. The router names the
    manager on every tick off the workspace alone — no tick indexing.
    """
    seat = StubSeat(
        responder=request_keyed(
            {
                str(Tier.MANAGER): planner,
                str(CallType.DISPATCH): lambda request: {
                    "tick": 0, "unit_id": request.unit.id, "narrative": "-"
                },
                str(Tier.DIRECTOR): lambda request: {"tick": request.workspace.tick},
            }
        )
    )
    router = StubRouter(
        rule=always(SeatSelection(tier=Tier.MANAGER, escalation=Escalation.EMPTY_UNIT_STACK))
    )
    return layer(router, seat)


def asking_planner(question: str = "which directory?"):
    """A planner that raises one question interrupt rather than planning anything."""

    def _planner(request) -> ManagerPlan:
        return ManagerPlan(
            tick=request.workspace.tick,
            interrupt=InterruptRequest(
                kind=InterruptKind.QUESTION,
                raised_by=Raiser.MANAGER,
                question=question,
            ),
        )

    return _planner


def finishing_planner(request) -> ManagerPlan:
    """A planner that satisfies the task's first goal and plans nothing."""
    return ManagerPlan(
        tick=request.workspace.tick, goals_satisfied=[request.workspace.goals[0].id]
    )


def quiet_planner(request) -> ManagerPlan:
    """A planner that mints nothing and asks nothing — the tick runs, the workspace does not."""
    return ManagerPlan(tick=request.workspace.tick)


class TornTick(RuntimeError):
    """The process dying inside a call: not a refusal, and not caught by the tick."""


class RecordingPort:
    """The one port, with every invocation recorded and, on request, one of them fatal.

    "How many model calls did this tick make" has to be a count of **one** thing, so the layer's
    port and the call desk's are the same object here, exactly as `cortex.layer.build_layer()`
    builds them. Nothing is faked past the record: the scripted seat answers. `crash_on` tears
    the process **inside** the n-th call, so the journal a real tear would leave is what gets
    replayed.
    """

    def __init__(self, seat, *, crash_on: int | None = None) -> None:
        self._seat = seat
        self._crash_on = crash_on
        self.addressees: list[str] = []

    def __call__(self, addressee, request):
        self.addressees.append(str(addressee))
        if self._crash_on is not None and len(self.addressees) == self._crash_on:
            raise TornTick(f"killed inside call {self._crash_on}")
        return self._seat(addressee, request)


def scripted_layer(brain: Path, fixture: str, *, crash_on: int | None = None):
    """`build_layer()`'s own shape over one scripted fixture, with the port recorded.

    Returns `(layer, port, seat)`. The router is the shipping `LadderRouter` over the throwaway
    root's own ladder weights, and the node-call desks and the layer share the one recorded port.
    """
    script = load_script(CALL_FIXTURES / fixture)
    desk = SeatDesk()
    seat = ScriptedSeat(script=script, desk=desk)
    port = RecordingPort(seat, crash_on=crash_on)
    built = SeatLayer(
        router=LadderRouter(weights=LadderWeights.load(brain), on_tick=desk.open_tick),
        port=port,
        sessions=desk.sessions,
        node_calls=CallDesks(port=port, plan=script.calls),
    )
    return built, port, seat


def open_task(
    brain: Path,
    workspace: Path,
    fixture: str,
    task: str,
    *,
    goal: str,
    crash_on: int | None = None,
):
    """A task opened on a **fixture** brain root, at tick 0, with nothing run yet.

    Returns `(context, state, port, seat)`.
    """
    built, port, seat = scripted_layer(brain, fixture, crash_on=crash_on)
    context = build_context(brain, task, built, workspace_path=str(workspace))
    state = new_state(task, goal, context)
    return context, state, port, seat


@dataclass(slots=True)
class RecordingSeat:
    """A port that answers from a responder and reports its invocations like a live seat.

    Two behaviours are the live adapter's, and every consumer of this class depends on both:
    **the facts list is cleared at the top of every port call**, and a tick that makes no port
    call leaves the previous facts in place — which is what makes `calls()` the tick's own
    account rather than the run's.

    The optional fields are the three things its consumers differ on. `plan` maps a tier to the
    outcome sequence one port call emits: `("ok",)` is the ordinary call, `("decode_retry",
    "ok")` is the one retry S-8 allows, and `("unavailable",)` is the invocation of a call that
    refused. `usage` replaces the derived usage block, and `mirror_usage` makes the *envelope*
    carry that same block — once one is set — under the tier's own model key, which is what a
    live call's envelope does — `SeatCallFacts.usage` is copied off the envelope, never composed beside it.
    `record_ticks` also records the **tick** each invocation answered, read off the request the
    way `protean.cortex.scripts.facts_of()` reads it: that list is an identity's independent
    left-hand side, derived from neither file the identity is checked against. `extra` supplies
    the per-call fields a module needs beyond the shared skeleton, called `(seat, tier, index,
    outcome)`.
    """

    responder: object
    plan: dict[str, tuple[str, ...]] = field(default_factory=dict)
    tokens_per_call: int = 0
    usage: dict | None = None
    mirror_usage: bool = False
    cache_read: int = 0
    argv: tuple[str, ...] = ("--output-format", "json")
    cli_version: str = "9.9.9 (Test)"
    record_ticks: bool = False
    extra: Callable[["RecordingSeat", str, int, str], Mapping] | None = None
    invocations: list = field(default_factory=list)
    invoked: list[tuple[int, str]] = field(default_factory=list)
    _facts: list = field(default_factory=list)

    def __call__(self, tier, request):
        self._facts = []  # cleared at the top of every port call, as the live seat clears it
        if self.record_ticks:
            workspace = getattr(request, "workspace", None)
            self.invoked.append(
                (request.admitted.tick if workspace is None else workspace.tick, str(tier))
            )
        payload = request.model_dump(mode="json")
        for index, outcome in enumerate(self.plan.get(str(tier), ("ok",))):
            fields = {
                "tier": str(tier),
                "argv": self.argv,
                "cli_version": self.cli_version,
                "session_handle": f"handle-{tier}",
                "model": f"model-{tier}",
                "request": payload,
                "wall_seconds": 0.5 + index,
                "outcome": outcome,
                "usage": self.usage
                or {"cache_read_input_tokens": 0, "output_tokens": self.tokens_per_call},
            }
            if self.extra is not None:
                fields.update(self.extra(self, str(tier), index, outcome))
            facts = SeatCallFacts(**fields)
            self._facts.append(facts)
            self.invocations.append(facts)
        answer = self.responder(tier, request)
        if self.usage is None or not self.mirror_usage:
            return envelope(answer, tokens=self.tokens_per_call, cache_read=self.cache_read)
        # The envelope the boundary sums is the *same* usage the facts carry, which is what a
        # live call's is: `SeatCallFacts.usage` is copied off the envelope, not composed.
        body = answer if isinstance(answer, Mapping) else answer.model_dump(mode="json")
        return SeatEnvelope(
            stop_reason="tool_use",
            result=json.dumps(body),
            modelUsage={
                f"model-{tier}": {"inputTokens": 0},
                OVERHEAD_MODEL: {"inputTokens": 0},
            },
            usage=dict(self.usage),
        )

    def calls(self) -> tuple:
        return tuple(self._facts)
