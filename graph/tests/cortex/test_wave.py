"""Rows G6, G7, G5's (c) and (d), and G3's delegate-arm clause — the bounds and the wave.

`the build specification (not in this mirror)` § Deliverable 4 (I5 `SpawnDesk`, the two openers, the
two open-time refusals, the concurrency, the kill and the torn wave) and § Deliverable 5 (the four
static bounds, the **sum**, and the bound check as one function on the desk).

**Dry throughout, and every fixture drives the stand-in.** The binary under test is
`tests/cortex/fake_cli`, installed on a **fixture** brain root whose `kinds:` container comes from
`fixtures/calls/kinds/wave_kinds.yaml`; the adapter is the shipping one, so it builds the real argv,
composes the real per-spawn profile, spawns real processes and kills real process groups. Nothing
here spends, and the repo's own `brain/` is read by `seed_kinds_root()` and written by nothing.

**Two levels, and the split is deliberate.** A refusal's **class and reason** are read off the desk
directly, where `pytest.raises` can see them; the **terminal, the checkpoint and the resume** are
read off a whole tick driven through `engine.start`, because those are facts about the boundary and
not about the desk. The arithmetic a refusal quotes is asserted against the numbers the *seed*
carries rather than against a second transcription of them.

**What is not here.** The witness — the four derived audit lists, the receipt's four new columns and
the schema bump — is order W5's, and this module asserts nothing about them. Row G7's own
process-group **read** at join is order W5's carrier too; what this module proves is the kill's
reach, which is the landed `kill_process_group()`'s.
"""

from __future__ import annotations

import dataclasses
import json
import math
import os
import signal
import time
from pathlib import Path

import pytest
import yaml

from protean.brain.folders import seed_hashes
from protean.cortex.calls import CallRefusal, REFUSAL_NO_CONFIGURATION
from protean.cortex.layer import build_live_layer
from protean.cortex.live.config import SeatConfigError
from protean.cortex.live.kinds import resolve_capability
from protean.cortex.live.wave import (
    REASON_NO_KIND,
    REASON_NO_WORKSPACE,
    REASON_WAVE_BOUND,
    SpawnDesk,
    SpawnDesks,
)
from protean.mailbox.files import build as build_mailbox
from protean.runtime import engine
from protean.runtime.commit import build_checkpoint, write_checkpoint
from protean.runtime.cycle import WAVE_CALL_NUMBER, calls_by_type
from protean.runtime.errors import SeatUnavailable
from protean.runtime.journal import load as load_journal
from protean.runtime.paths import BrainPaths
from protean.runtime.seat import MemberUnfinished, spawn_desk_of, tick_calls_of
from protean.state.checkpoint import load_checkpoint
from protean.state.enums import CallType, NodeName, TerminalState
from protean.state.inputs import WAVE_COMPLETE, WAVE_PARTIAL
from protean.state.seats import SeatEnvelope, WaveMember
from tests.conftest import tagged_show
from tests.cortex import fake_cli
from tests.cortex.conftest import (
    ALPHA,
    BETA,
    GAMMA,
    OVER,
    READER,
    UNDER,
    WIDER,
    ZETA,
    assert_dry,
    delegate_plan,
    drive,
    task_paths,
    wave_root,
)
from tests.mailbox.answering import answer

GOAL = "run the bounded wave"
TASK = "task-wave"
UNIT = "u-wave-1"
TICK = 1


show = tagged_show("W4-wave")


# --------------------------------------------------------------------------------------
# The root, the stand-in, and the ways a wave is driven
# --------------------------------------------------------------------------------------


@pytest.fixture()
def wave(tmp_path: Path, monkeypatch):
    """`conftest.wave_root()` under this module's task and unit — the shared spawn-root factory."""

    def _build(kinds=UNDER, **keys):
        return wave_root(tmp_path, monkeypatch, kinds, task=TASK, unit=UNIT, **keys)

    return _build


def _desk(wave_root, *, task: str = TASK, tick: int = TICK, workspace=None) -> SpawnDesk:
    """The tick's one desk, resolved through the seam exactly as the runtime resolves it."""
    seam = SpawnDesks(config=wave_root.seats, root=wave_root.root)
    named = wave_root.workspace if workspace is None else workspace
    return seam(task, tick, "" if named is None else str(named))


def _members(kinds, *, unit: str = UNIT) -> dict[int, WaveMember]:
    """`member#` assigned before anything starts, from the order the plan listed the kinds."""
    return {
        number: WaveMember(kind=kind, unit_id=unit, admitted_ref="admitted")
        for number, kind in enumerate(kinds, start=1)
    }


def _drive(world, *, task: str = TASK, workspace=None, max_ticks: int = 1):
    """`conftest.drive()` under this module's goal and task."""
    return drive(world, goal=GOAL, task=task, workspace=workspace, max_ticks=max_ticks)


def _paths(root, task: str = TASK):
    return task_paths(root, task)


def _payload(root: Path) -> dict:
    """One seeded root's `seats.yaml` as a payload a case may mutate and hand back."""
    return yaml.safe_load((root / "seats.yaml").read_text(encoding="utf-8"))


def _committed(root: Path, task: str = TASK):
    return load_checkpoint(
        json.loads(_paths(root, task).checkpoint.read_text(encoding="utf-8")), seed_reader=None
    )


def _age_the_task(root: Path, task: str = TASK, ticks: int = 10) -> None:
    """Re-seal the checkpoint as a task that had already run `ticks` ticks when the wave refused.

    One refusal on tick one is an error **rate** of 1.0, so homeostasis's `max_error_rate` ceiling
    skips the very next tick's seat call — correct behaviour, and not what a resume clause is about.
    The landed `tests/runtime/test_seat_failure.py` states the same rule for a refused seat call;
    only `cost.ticks` moves, and the envelope is re-sealed through the same `build_checkpoint()` the
    boundary commit uses, so every arm of the resume's refusal ladder stays armed.
    """
    paths = _paths(root, task)
    checkpoint = _committed(root, task)
    state = checkpoint.state
    state.cost.ticks = ticks
    write_checkpoint(
        paths,
        build_checkpoint(state, seed_hashes=seed_hashes(root), revision=checkpoint.revision),
    )


def _answer_the_refusal(root: Path, text: str = "retry it") -> dict:
    """Answer the one mailbox item a refused tick raised, and hand back its evidence.

    The refusal's **named reason** travels to the operator in that item's evidence, which is what makes
    "refused by name" a fact on disk rather than an exception a test caught.
    """
    item = next(BrainPaths(root=root).mailbox_open.glob("*.md"))
    body = item.read_text(encoding="utf-8")
    answer(item, text)
    return {"path": item, "text": body}


def _no_process(world) -> None:
    """The receipt every pre-process refusal closes on, both recording devices at once."""
    assert fake_cli.spawn_recordings(world.binaries) == [], "no spawn recording: no process"
    assert_dry()


def _wave_entries(root: Path, tick: int, task: str = TASK):
    return [
        entry
        for entry in load_journal(_paths(root, task).journal(tick))
        if entry.tier is CallType.DISPATCH and entry.is_call()
    ]


# --------------------------------------------------------------------------------------
# The seam: one desk per tick, and the two layers that carry it
# --------------------------------------------------------------------------------------


def test_a_scripted_layer_has_no_spawn_seam_and_the_accessor_answers_none(
    brain: Path, script_for
) -> None:
    """Row M3's half, on the builder's own list: the accessor a machine row reads.

    `spawn_desk_of()` answers `None` where the seam is absent — `spawns_of()` being the desk's own
    method and reachable only through a desk that exists (folded: S-i23) — so a layer without it
    spawns nothing and writes no `SubagentSpawn`. Closed by no row here.
    """
    from protean.cortex.layer import build_layer

    layer = build_layer(root=brain, script=script_for("plan_and_execute"))
    show("scripted layer's fifth seam", layer.spawns)
    assert layer.spawns is None
    assert spawn_desk_of(layer, TASK, TICK, "/tmp") is None
    desk = tick_calls_of(layer, TASK, TICK)
    assert desk is not None and desk.spawn_desk is None, "and its node-call desk has none either"


def test_build_live_layer_attaches_spawns_and_node_calls_over_one_spawn_seam(wave) -> None:
    """A.2.i's live attachment, asserted on the production layer: both seams land, over one seam.

    D5-3's negative stood here until A.2.i attached `node_calls`
    (`the build specification (not in this mirror)` § Deliverable 1), and it is inverted by design (E23): the
    fourth seam is a `CallDesks` holding the layer's own `spawns` instance, so the wave's opener and
    the delegate arm meet one desk per tick. Row G3's last clause is still proven on a
    **test-constructed** layer below, which is the one that carries a static plan naming a delegate.
    """
    from protean.cortex.calls import CallDesks

    root = wave()
    layer = build_live_layer(root=root.root)
    show("live layer seams", {"spawns": layer.spawns is not None, "node_calls": layer.node_calls})
    assert layer.spawns is not None, "the fifth seam is attached"
    assert isinstance(layer.node_calls, CallDesks), "and the fourth is attached beside it"
    assert layer.node_calls.spawns is layer.spawns, "over the same `SpawnDesks` instance"
    assert layer.port.workspace_path == "", "the landed default stays exactly as it is"


def test_the_seam_is_memoized_per_task_and_tick_so_the_tick_has_exactly_one_desk(wave) -> None:
    """The one departure from `tick_calls_of()`'s precedent (folded: S-i36).

    Two resolutions inside one tick are the **same object**, a third for the next tick is not, and
    the workspace is the one the **first** caller handed it — which is what lets the wave's opener
    and the delegate arm meet one desk and one `spawns_of()`.
    """
    root = wave()
    seam = SpawnDesks(config=root.seats, root=root.root)
    first = seam(TASK, TICK, str(root.workspace))
    second = seam(TASK, TICK)
    show("same object", first is second)
    assert first is second, "a second resolution inside one tick opens no second desk"
    assert second.workspace == str(root.workspace), "the first opener's workspace is the desk's"
    assert seam(TASK, TICK + 1) is not first, "and the desk dies with the tick that opened it"


def test_the_runtimes_two_openers_reach_one_desk_through_the_accessor(wave) -> None:
    """`CallDesks` holds the **seam** and `NodeCallDesk` is constructed with the resolved desk."""
    root = wave()
    layer = fake_cli.spawn_layer(root.root, router=None, workspace_path=str(root.workspace))
    through_the_accessor = spawn_desk_of(layer, TASK, TICK, str(root.workspace))
    on_the_call_desk = tick_calls_of(layer, TASK, TICK).spawn_desk
    show("one desk, two openers", through_the_accessor is on_the_call_desk)
    assert through_the_accessor is on_the_call_desk
    assert layer.node_calls.spawns is layer.spawns, "the factory holds the seam, not a desk"


# --------------------------------------------------------------------------------------
# Row G6 — a wave is bounded before its first member spawns
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kinds,width_is_legal", [(WIDER, False), (OVER, True)], ids=["width", "sum"]
)
def test_a_wave_over_either_bound_is_refused_by_name_with_no_process_created(
    wave, kinds, width_is_legal: bool
) -> None:
    """Row G6's two bound paths — one setup, one raise, and everything the row names read off it.

    **Width**: five members against `max_wave_members: 4`, refused before the first spawn.
    **Sum**: the **sum**, not `members × one cap` (H4) — 4.0 + 3.0 + 2.0 + 1.01 against a ceiling
    of 10.0, at a width that is itself legal.

    Row G6's own clause: **one function** composes the comparison and the message, so both paths
    quote the same five quantities — the member count, the caps, their sum, the width ceiling and
    the sum ceiling. Each is asserted present, and the numbers come off the **seed** rather than
    out of a second transcription, so a re-seeded bound turns this red instead of drifting past it.

    And the class, on both paths: the refusal is `SeatUnavailable`, the class `run_wave` already
    catches. A `SeatConfigError` would tear the tick — nothing in the tick catches it, so no
    checkpoint is written and the replay re-refuses forever (folded: S-i3).

    `test_the_same_wave_one_cent_below_the_sum_runs` is the other side of the sum comparison and
    stays a case of its own.
    """
    root = wave(kinds)
    desk = _desk(root)
    with pytest.raises(SeatUnavailable) as raised:
        desk.dispatch_wave(_members(root.kinds), call_number=WAVE_CALL_NUMBER)
    caps = [root.seats.kind("dispatch", kind).max_call_usd for kind in root.kinds]
    show("bound refusal", raised.value.message[:120])
    show("arithmetic", f"{caps} -> {math.fsum(caps)} vs {root.seats.spawn_max_wave_usd}")
    assert raised.value.reason == REASON_WAVE_BOUND

    if width_is_legal:
        assert len(caps) <= root.seats.max_wave_members, "the width is legal; the sum is not"
        assert math.fsum(caps) > root.seats.spawn_max_wave_usd
    else:
        assert len(root.kinds) > root.seats.max_wave_members

    quantities = {
        "member count": str(len(root.kinds)),
        "the caps": str(caps),
        "the sum": str(math.fsum(caps)),
        "the width ceiling": str(root.seats.max_wave_members),
        "the sum ceiling": str(root.seats.spawn_max_wave_usd),
    }
    for label, quantity in quantities.items():
        show(f"quoted {label}", quantity)
        assert quantity in raised.value.message, f"the refusal does not quote {label}"

    show("class on the bound path", type(raised.value).__name__)
    assert not isinstance(raised.value, SeatConfigError)
    _no_process(root)


def test_the_same_wave_one_cent_below_the_sum_runs(wave) -> None:
    """The other side of the same comparison, and the only thing that changed is one member."""
    root = wave(UNDER)
    desk = _desk(root)
    caps = [root.seats.kind("dispatch", kind).max_call_usd for kind in root.kinds]
    assert math.fsum(caps) < root.seats.spawn_max_wave_usd, "one cent below"
    results = desk.dispatch_wave(_members(root.kinds), call_number=WAVE_CALL_NUMBER)
    show("members that ran", sorted(results))
    assert sorted(results) == [1, 2, 3, 4]
    assert all(isinstance(value, SeatEnvelope) for value in results.values())
    assert len(fake_cli.spawn_recordings(root.binaries)) == 4


def test_a_wave_over_the_bound_stops_the_tick_and_a_reseeded_resume_proceeds(wave) -> None:
    """Row G6's recoverability clause, end to end on a live tick.

    The manager's plan is journalled, so the refusal is recoverable: a seed edit that **widens** the
    bound plus `resume --reseed` replays that same plan and proceeds. Nothing is deleted and nothing
    is relaxed — the seed changes, which is the one legal way a bound moves.
    """
    root = wave(OVER, plans=2)
    _layer, outcome = _drive(root)
    show("terminal after the refusal", outcome.terminal)
    assert outcome.terminal is TerminalState.STOPPED
    assert _paths(root.root).checkpoint.is_file(), "a checkpoint is on disk"
    _no_process(root)
    planned = json.loads(
        [entry for entry in load_journal(_paths(root.root).journal(1)) if entry.is_call()][0]
        .envelope.result
    )
    assert [member["kind"] for member in planned["wave"]] == list(OVER)

    raised = _answer_the_refusal(root.root)
    assert REASON_WAVE_BOUND in raised["text"], "the named reason reached the operator's mailbox"

    # The seed edit that widens the bound, then the one verb that admits it.
    seats_file = root.root / "seats.yaml"
    payload = _payload(root.root)
    payload["runtime"]["spawn_max_wave_usd"] = 20.0
    seats_file.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    reseeded = engine.resume(
        root.root, build_live_layer(root=root.root), mailbox=build_mailbox(root.root), reseed=True
    )
    show("reseed messages", reseeded.messages)
    assert any("seats.yaml" in message for message in reseeded.messages)

    _age_the_task(root.root)
    outcome = engine.resume(
        root.root, build_live_layer(root=root.root), mailbox=build_mailbox(root.root), max_ticks=1
    )
    show("members after the reseeded resume", len(fake_cli.spawn_recordings(root.binaries)))
    assert len(fake_cli.spawn_recordings(root.binaries)) == len(OVER), "the same plan, dispatched"
    assert outcome.ticks[0].wave_status == WAVE_COMPLETE


# Row G6's load-time clause is carried by
# `test_kinds.py::test_a_cap_above_the_spawn_ceiling_refuses_at_load_by_name` (strictly stronger:
# it also proves the at-the-ceiling positive); a second copy here is what D5-3 forbids.


def test_the_tick_counters_equal_the_journals_call_keys_with_every_member_counted(wave) -> None:
    """Row G6's last clause: what homeostasis sees is the journal's own keys, `member#` included.

    A.1.i adds no counter and no ceiling to homeostasis; it adds a gate in front of the spawn that
    the counters see the effect of. So the assertion is a comparison of the tick's counters against
    the journal read back **off disk**, never against a tally kept beside it.
    """
    root = wave(UNDER)
    _layer, outcome = _drive(root)
    entries = [entry for entry in load_journal(_paths(root.root).journal(1)) if entry.is_call()]
    from_disk = calls_by_type(entries)
    show("counters", outcome.ticks[0].calls_by_type)
    assert outcome.ticks[0].calls_by_type == from_disk
    assert from_disk[str(CallType.DISPATCH)] == len(UNDER), "every member counted"
    assert outcome.ticks[0].wave_members == len(UNDER)
    assert [entry.member_number for entry in _wave_entries(root.root, 1)] == [1, 2, 3, 4]


# --------------------------------------------------------------------------------------
# Row G7 — the members run concurrently and the process accounting is exact
# --------------------------------------------------------------------------------------


def test_a_four_member_wave_spawns_exactly_four_processes_plus_one_version_probe(wave) -> None:
    """Row G7's count clause, read the way the row names it (folded: S-i53, A1-14).

    Four `--session-id`-keyed recordings — one per member, each with its own port instance and its
    own facts — beside a **seats' ordinal counter** the spawns never touched. The version is
    resolved **once per desk** and handed to every instance, which is why the count is four plus one
    probe rather than four plus four: the probe is the `--version` invocation the stand-in
    deliberately does not count.
    """
    root = wave(UNDER)
    _layer, outcome = _drive(root)
    recordings = fake_cli.spawn_recordings(root.binaries)
    show("spawn recordings", len(recordings))
    show("seats' ordinal counter", fake_cli.invocations(root.binaries))
    assert len(recordings) == len(UNDER) == 4
    assert len(set(recordings)) == 4, "four distinct minted session ids"
    assert fake_cli.invocations(root.binaries) == 1, "the manager's own call, and nothing else"
    assert outcome.ticks[0].wave_status == WAVE_COMPLETE

    facts = _layer.spawns.opened[-1].spawns_of()
    assert sorted(facts) == [(str(NodeName.CORTEX), WAVE_CALL_NUMBER, n) for n in (1, 2, 3, 4)]
    versions = {fact.cli_version for fact in facts.values()}
    show("cli_version across the wave", versions)
    assert len(versions) == 1 and versions != {""}, "one probe, handed to every instance"
    assert {fact.session_handle for fact in facts.values()} == set(recordings)


def test_the_journal_is_written_in_member_order_against_a_reversed_completion_order(wave) -> None:
    """Row G7's ordering clause, with its other side: finish backwards, read forwards.

    The members are given descending sleeps, so the wave **completes** in the reverse of the order
    the plan listed them in. `member#` is assigned before anything starts, so the journal's line
    order is the wave's order either way — which is what makes A.1's G7 byte-identity claim survive
    a real wave.
    """
    kinds = UNDER
    sleeps = [((kind, UNIT), 0.4 - 0.1 * index) for index, kind in enumerate(kinds)]
    root = wave(kinds, member_sleeps=sleeps)
    _layer, _outcome = _drive(root)

    entries = _wave_entries(root.root, 1)
    finished = sorted(
        fake_cli.spawn_recordings(root.binaries),
        key=lambda key: (root.binaries / f"argv-{key}.txt").stat().st_mtime,
    )
    facts = _layer.spawns.opened[-1].spawns_of()
    by_handle = {fact.session_handle: key[2] for key, fact in facts.items()}
    show("journal member order", [entry.member_number for entry in entries])
    show("completion order", [by_handle[key] for key in finished])
    assert [entry.member_number for entry in entries] == [1, 2, 3, 4], "written forwards"
    assert [entry.kind for entry in entries] == list(kinds)
    walls = {key[2]: fact.wall_seconds for key, fact in facts.items()}
    show("per-member wall seconds", walls)
    assert walls[1] > walls[4], "member 1 slept longest, so it returned last"


def test_the_wave_runs_its_members_at_the_same_time_rather_than_one_after_another(wave) -> None:
    """"the members run **at the same time**, one port instance per member, each on its own thread".

    The receipt is arithmetic rather than a stopwatch on the suite: four members each sleeping the
    same amount take **about one** of those sleeps wall-clock if they overlap and four if they do
    not, so the wave's own elapsed time is compared against the sum of its members' walls.
    """
    kinds = UNDER
    nap = 0.4
    root = wave(kinds, member_sleeps=[((kind, UNIT), nap) for kind in kinds])
    desk = _desk(root)
    started = time.monotonic()
    results = desk.dispatch_wave(_members(kinds), call_number=WAVE_CALL_NUMBER)
    elapsed = time.monotonic() - started
    walls = sum(fact.wall_seconds for fact in desk.spawns_of().values())
    show("wave elapsed", round(elapsed, 3))
    show("sum of the members' own walls", round(walls, 3))
    assert len(results) == 4
    assert walls > elapsed, "the members overlapped: their walls sum past the wave's own"
    assert elapsed < nap * len(kinds), "and the wave is not four naps long"


def test_a_member_that_crosses_its_own_wall_is_killed_and_the_wave_merges_partial(wave) -> None:
    """Row G7's kill clause: one member fails, the other three return, the tick does not tear.

    `fixture_zeta` carries `timeout_seconds: 0.3` and is told to sleep past it. The kill raises
    `CallCapExceeded` — a `SeatConfigError` **nothing in the tick catches** — so the desk re-raises
    it as `MemberUnfinished`, which is the class `run_wave`'s landed catch already marks a member
    failed and merges the wave `partial` on (folded: S-i41).
    """
    kinds = (ALPHA, BETA, GAMMA, ZETA)
    root = wave(kinds, member_sleeps=[((ZETA, UNIT), 1.5)])
    desk = _desk(root)
    results = desk.dispatch_wave(_members(kinds), call_number=WAVE_CALL_NUMBER)
    show("member 4's outcome", type(results[4]).__name__)
    assert isinstance(results[4], MemberUnfinished), "the producer A.1 declared and never wrote"
    assert not isinstance(results[4], SeatConfigError), "and not the class that tears the tick"
    assert all(isinstance(results[number], SeatEnvelope) for number in (1, 2, 3))
    assert ZETA in str(results[4]) and "timeout_seconds" in str(results[4])


def test_the_killed_member_marks_the_wave_partial_on_a_live_tick(wave) -> None:
    """The same fault through the whole tick: `partial`, journalled, and no tear."""
    kinds = (ALPHA, BETA, GAMMA, ZETA)
    root = wave(kinds, member_sleeps=[((ZETA, UNIT), 1.5)])
    _layer, outcome = _drive(root)
    show("wave status", outcome.ticks[0].wave_status)
    assert outcome.ticks[0].wave_status == WAVE_PARTIAL
    entries = _wave_entries(root.root, 1)
    assert [entry.member_number for entry in entries] == [1, 2, 3, 4]
    assert entries[3].envelope is None, "the failed member is journalled with no envelope"
    assert outcome.ticks[0].seat_refusal is None, "the tick completed; it did not stop"


def test_the_kill_reaches_the_whole_process_group(wave) -> None:
    """Row G7's group clause, proven on a grandchild the stand-in really started.

    Every spawn is `start_new_session=True`, so it leads its own group and the tools it started are
    in that group with it. The stand-in leaves a sleeping grandchild and records its pid; after the
    killed member's group is signalled, that pid is gone.
    """
    # **A one-member wave, deliberately**: the stand-in's grandchild inherits its parent's stdout
    # pipe, so a *surviving* member's `communicate()` would wait out the grandchild's whole sleep.
    # The claim is about the killed member's group, so the wave is exactly that member.
    kinds = (ZETA,)
    root = wave(kinds, member_sleeps=[((ZETA, UNIT), 1.5)], spawn_child_seconds=30)
    desk = _desk(root)
    results = desk.dispatch_wave(_members(kinds), call_number=WAVE_CALL_NUMBER)
    assert isinstance(results[1], MemberUnfinished)

    facts = desk.spawns_of()
    killed = facts[(str(NodeName.CORTEX), WAVE_CALL_NUMBER, 1)].session_handle
    pid = fake_cli.grandchild_pid(root.binaries, killed)
    show("grandchild pid after the kill", pid)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, signal.SIG_DFL)


def test_a_torn_wave_re_runs_whole_and_re_applies_its_members_writes(wave) -> None:
    """Row G7's torn-wave clause, and the fixture A.1 could not build (§ Named assumptions 12).

    A.1's members wrote nothing, so no A.1 fixture could show a torn wave. These members **do**
    write, under the stand-in, into the directory `--add-dir` granted them: the wave re-runs whole
    and its already-returned members' observations are discarded, so the workspace carries two
    lines per member where it carried one. **Nothing enforces idempotence** and A.1.i adds nothing
    that does — which is exactly what the second line is.
    """
    kinds = (ALPHA, BETA)
    marker = "member-writes.txt"
    root = wave(kinds, writes_in_cwd=marker)
    desk = _desk(root)
    desk.dispatch_wave(_members(kinds), call_number=WAVE_CALL_NUMBER)
    before = (root.workspace / marker).read_text(encoding="utf-8").splitlines()
    show("lines after the first pass", before)
    assert len(before) == len(kinds), "both members really wrote"

    # The tear: the wave's entries are buffered, so a pass that dies after its members returned
    # journals none of them — and the replay re-runs the whole wave.
    replay = _desk(root, tick=TICK + 1)
    replay.dispatch_wave(_members(kinds), call_number=WAVE_CALL_NUMBER)
    after = (root.workspace / marker).read_text(encoding="utf-8").splitlines()
    show("lines after the re-run", after)
    assert len(after) == 2 * len(kinds), "the re-run re-applied both members' writes"
    assert after[: len(before)] == before, "and nothing rolled the first pass back"


# --------------------------------------------------------------------------------------
# Row G5 (c) — a kind the seed does not define
# --------------------------------------------------------------------------------------


def test_a_plan_naming_an_undefined_kind_is_refused_under_reason_no_kind(wave) -> None:
    """Row G5 (c): "no configuration", raised **from the desk**, with no process created."""
    root = wave()
    desk = _desk(root)
    absent = _members(("fixture_not_in_this_seed",))
    with pytest.raises(SeatUnavailable) as raised:
        desk.dispatch_wave(absent, call_number=WAVE_CALL_NUMBER)
    show("no-kind refusal", raised.value.message[:140])
    assert raised.value.reason == REASON_NO_KIND
    assert "fixture_not_in_this_seed" in raised.value.message
    assert not isinstance(raised.value, SeatConfigError)
    _no_process(root)


def test_an_undefined_kind_stops_the_tick_and_a_reseeded_resume_defines_it_and_proceeds(
    wave,
) -> None:
    """Row G5 (c) whole: stopped, a checkpoint on disk, and `resume --reseed` proceeding.

    The plan the refused tick journalled is read back off disk and compared against the plan the
    resumed tick dispatched, which is what "replays the same plan" is a claim about.

    The root is the `wave` fixture's, plans and all: its `monkeypatch`-scoped `PATH` is the same
    edit this case used to make by hand, undone by pytest instead of by a `finally` clause.
    """
    kinds = (ALPHA, "fixture_not_in_this_seed")
    wave_root = wave(kinds, plans=2)
    root, binaries = wave_root.root, wave_root.binaries
    outcome = engine.start(
        root, GOAL, build_live_layer(root=root), mailbox=build_mailbox(root),
        workspace_path=str(wave_root.workspace), task_id=TASK, max_ticks=1,
    )
    show("terminal", outcome.terminal)
    assert outcome.terminal is TerminalState.STOPPED
    assert _paths(root).checkpoint.is_file()
    assert fake_cli.spawn_recordings(binaries) == [], "no process for either member"
    journalled = json.loads(
        [e for e in load_journal(_paths(root).journal(1)) if e.is_call()][0].envelope.result
    )
    raised = _answer_the_refusal(root)
    assert REASON_NO_KIND in raised["text"]

    # The seed edit that defines the kind, then the verb that admits it.
    seats_file = root / "seats.yaml"
    payload = _payload(root)
    defined = dict(payload["kinds"]["dispatch"][ALPHA])
    payload["kinds"]["dispatch"]["fixture_not_in_this_seed"] = defined
    seats_file.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    engine.resume(root, build_live_layer(root=root), mailbox=build_mailbox(root), reseed=True)
    _age_the_task(root)
    resumed = engine.resume(
        root, build_live_layer(root=root), mailbox=build_mailbox(root), max_ticks=1
    )
    dispatched = [entry.kind for entry in _wave_entries(root, 2)]
    show("dispatched after the reseed", dispatched)
    assert dispatched == [member["kind"] for member in journalled["wave"]]
    assert resumed.ticks[0].wave_status == WAVE_COMPLETE
    assert len(fake_cli.spawn_recordings(binaries)) == len(kinds)


# --------------------------------------------------------------------------------------
# Row G5 (d) — the workspace, and the channel that supplies one
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("named", ["empty", "unresolvable", "deny_write"])
def test_a_workspace_the_desk_cannot_open_refuses_by_name_with_no_process(
    wave, tmp_path: Path, named: str
) -> None:
    """Row **G5 (d)**: the absence lands at the desk, so a wave never runs in a throwaway directory.

    Three arms of the one refusal, differing only in the value handed to the open.

    * `empty` — the absence itself.
    * `unresolvable` — "empty **or unresolvable**": a path the machine does not have is the
      second arm.
    * `deny_write` — the collision between the allowed set and the denied one, at the desk's open
      (folded: S-i43). `sandbox.deny_write` names `brain_root`, so a workspace inside the brain
      root is a workspace the composed profile would allow `file-write*` back under while the seed
      denies it, and that arm keeps its own pre-assert that the path really is inside one.
    """
    root = wave()
    handed = {
        "empty": "",
        "unresolvable": tmp_path / "no-such-clone",
        "deny_write": root.root / "state",
    }[named]
    if named == "deny_write":
        assert any(
            handed == tree or tree in handed.parents for tree in root.seats.sandbox.deny_write
        )
    desk = _desk(root, workspace=handed)
    with pytest.raises(SeatUnavailable) as raised:
        desk.dispatch_wave(_members((ALPHA,)), call_number=WAVE_CALL_NUMBER)
    show(f"{named} refusal", raised.value.message[:140])
    assert raised.value.reason == REASON_NO_WORKSPACE
    _no_process(root)


def test_the_link_farm_resolves_inside_no_allowed_subpath(wave) -> None:
    """Refusal (b), now an assertion that holds **structurally** (folded: S-i48).

    Order W3 moved the farm and the `add_dir: false` cwd into `brain/state/<task>/spawns/<tick>/`,
    a tree `sandbox.deny_write` names, so a farm inside the allowed set is unreachable by
    construction. The check stays because an assertion that cannot fire costs one comparison.
    """
    root = wave()
    desk = _desk(root)
    desk.open()
    farm = desk.scaffold().resolve()
    allowed = desk.allowed_subpaths(root.workspace)
    show("farm", str(farm))
    show("allowed subpaths", [str(path) for path in allowed])
    assert allowed, "there is an allowed set to be outside of"
    for tree in allowed:
        assert farm != tree and tree not in farm.parents


def test_the_workspace_survives_a_resume_through_the_checkpointed_extension(
    wave, tmp_path: Path
) -> None:
    """Row G5 (d)'s second half: written by `start`, read back by `resume`, no version moved.

    The refused run names a workspace that does not exist yet, so the desk refuses by name; the
    directory is then created and a plain `resume` — **no flag** — re-reads the path off
    `BrainState.extensions` and the wave proceeds. `extensions` is the open registry by design, so
    the state's own schema version is the same on both sides of the resume.
    """
    kinds = (ALPHA, BETA)
    wave_root = wave(kinds, plans=2, workspace=tmp_path / "clone-to-be")
    root, binaries, later = wave_root.root, wave_root.binaries, wave_root.workspace
    assert not later.exists(), "the refused run names a workspace that does not exist yet"
    outcome = engine.start(
        root, GOAL, build_live_layer(root=root), mailbox=build_mailbox(root),
        workspace_path=str(later), task_id=TASK, max_ticks=1,
    )
    assert outcome.terminal is TerminalState.STOPPED
    assert fake_cli.spawn_recordings(binaries) == []
    before = _committed(root)
    assert engine.task_workspace(before.state) == str(later), "start wrote the extension"
    version_before = before.state.schema_version

    later.mkdir()
    _answer_the_refusal(root)
    _age_the_task(root)
    resumed = engine.resume(
        root, build_live_layer(root=root), mailbox=build_mailbox(root), max_ticks=1
    )
    show("workspace after the resume", engine.task_workspace(_committed(root).state))
    assert resumed.ticks[0].wave_status == WAVE_COMPLETE
    assert len(fake_cli.spawn_recordings(binaries)) == len(kinds)
    granted = {
        fake_cli.argv_of(binaries, key)[fake_cli.argv_of(binaries, key).index("--add-dir") + 1]
        for key in fake_cli.spawn_recordings(binaries)
    }
    assert granted == {str(later.resolve())}, "the resumed wave was granted the same path"
    assert _committed(root).state.schema_version == version_before, "no version moved"


def test_the_flags_value_reaches_the_engine_as_the_one_workspace_argument(
    tmp_path: Path, monkeypatch
) -> None:
    """The channel end to end: `--workspace` → `engine.start(workspace_path=…)`, and nothing else.

    Exactly as `dry` and `tests/wet/probe_refusal.py` already hand one (folded: S-i34), so there is
    one argument and no second channel. The engine is stubbed because the claim is the **wiring**;
    what `start` then does with the value is the extension case above. `--brain` points the verb at
    a throwaway root, so the lock this takes is never the repo's own.
    """
    from protean import config as protean_config
    from protean import cli

    elsewhere = tmp_path / "brain"
    elsewhere.mkdir()
    monkeypatch.setenv(protean_config.BRAIN_ROOT_ENV, str(elsewhere))
    seen: dict[str, object] = {}

    def _start(root, goal, layer, **kwargs):
        seen.update(kwargs)
        raise SystemExit(0)

    monkeypatch.setattr(cli.engine, "start", _start)
    monkeypatch.setattr(cli.seat, "resolve_seat_layer", lambda: object())
    monkeypatch.setattr(cli, "resolve_mailbox", lambda root: None)
    parser = cli.build_parser()
    base = ["--brain", str(elsewhere), "run", "a goal"]
    args = parser.parse_args([*base, "--workspace", "/tmp/clone-named"])
    with pytest.raises(SystemExit):
        args.handler(args)
    show("engine.start saw", seen.get("workspace_path"))
    assert seen["workspace_path"] == "/tmp/clone-named"

    args = parser.parse_args(base)
    with pytest.raises(SystemExit):
        args.handler(args)
    assert seen["workspace_path"] == "", "omitting it hands the engine the empty default"


def test_run_offers_the_workspace_flag_and_omitting_it_stays_legal(capsys) -> None:
    """The channel that supplies one on a live root, read off the parser's own help."""
    from protean import cli

    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["run", "--help"])
    printed = capsys.readouterr().out
    show("run --help mentions", [line.strip() for line in printed.splitlines() if "workspace" in line][:2])
    assert "--workspace" in printed
    parsed = parser.parse_args(["run", "a goal"])
    assert parsed.workspace is None, "omitting it stays legal at the parser"
    assert parser.parse_args(["run", "a goal", "--workspace", "/tmp"]).workspace == "/tmp"


# --------------------------------------------------------------------------------------
# Row G3's last clause — the delegate, through the seam, by the delegate arm
# --------------------------------------------------------------------------------------


def test_a_delegate_spawn_opened_by_the_arm_carries_the_composed_delegate_profile(wave) -> None:
    """Row G3's one clause order W2 could not reach (ledger entry V2-5).

    The spawn is opened **through the `spawns` seam by the `node_calls` desk's delegate arm**, on a
    test-constructed layer carrying both seams — a fixture plan drives the arm, since the shipping
    triggers A.2.i attached ship off. The profile is read back off the stand-in's own
    `--session-id`-keyed recording and compared against the profile composed for the `delegate`
    class: the per-class allowed set **without** the task workspace.
    """
    root = wave()
    fake_cli.install(
        root.binaries, answer=fake_cli.envelope({"kind": READER, "information": "read it", "cited_ids": []})
    )
    layer = fake_cli.spawn_layer(
        root.root, router=None, workspace_path=str(root.workspace), plan=delegate_plan(READER)
    )
    # The runtime resolves the desk with the tick's own workspace at the top of `run_tick`, before it
    # opens the node-call desk; this mirrors that order rather than relying on the late binding that
    # makes it survive the other one.
    spawn_desk_of(layer, TASK, TICK, str(root.workspace))
    desk = tick_calls_of(layer, TASK, TICK)
    assert desk.spawn_desk is not None, "the layer carries both seams"
    answers = desk.run(NodeName.HIPPOCAMPUS)
    show("delegate answer", type(answers[0]).__name__)
    assert not isinstance(answers[0], CallRefusal), str(answers[0])

    facts = desk.spawn_desk.spawns_of()
    assert sorted(facts) == [(str(NodeName.HIPPOCAMPUS), 1, None)], "one spawn, no member#"
    recorded = fake_cli.argv_of(root.binaries, facts[(str(NodeName.HIPPOCAMPUS), 1, None)].session_handle)
    wrapped = facts[(str(NodeName.HIPPOCAMPUS), 1, None)].argv
    expected = resolve_capability(
        root.seats.kind("delegate", READER),
        workspace=root.workspace,
        spawn_writable=root.seats.spawn_writable,
    ).sandbox_profile(root.seats.sandbox)
    show("profile head", wrapped[2][:80])
    assert wrapped[1] == "-p" and wrapped[2] == expected
    assert str(root.workspace) not in wrapped[2], "the workspace is absent, not deny-listed"
    assert list(wrapped[4:]) == recorded, "and the CLI got its own argv, wrapper consumed"


def test_a_delegate_naming_an_undefined_kind_is_the_calling_nodes_refusal_signal(wave) -> None:
    """Folded: S-i3 — a delegate takes A.1's delegate class, never the wave's named reason.

    A `delegate` is an advisory call: every fault on one is a **signal** the calling node proceeds
    without, so a kind the seed does not define is `missing_configuration` and not
    `SeatUnavailable`/`REASON_NO_KIND`.
    """
    root = wave()
    layer = fake_cli.spawn_layer(
        root.root,
        router=None,
        workspace_path=str(root.workspace),
        plan=delegate_plan("fixture_not_in_this_seed"),
    )
    spawn_desk_of(layer, TASK, TICK, str(root.workspace))
    desk = tick_calls_of(layer, TASK, TICK)
    answers = desk.run(NodeName.HIPPOCAMPUS)
    show("refusal class", getattr(answers[0], "reason", None))
    assert isinstance(answers[0], CallRefusal)
    assert answers[0].reason == REFUSAL_NO_CONFIGURATION
    _no_process(root)


def test_a_delegates_cap_exceeded_is_left_as_the_calling_nodes_refusal_signal(wave) -> None:
    """Row G7's last clause: the desk re-raises a **member's** fault and leaves a delegate's.

    The delegate kind's own wall is crossed by a stand-in told to sleep past it; what comes back is
    the calling node's `cap_exceeded` refusal, not `MemberUnfinished` and not a stop.
    """
    root = wave()
    seats_file = root.root / "seats.yaml"
    payload = _payload(root.root)
    payload["kinds"]["delegate"][READER]["timeout_seconds"] = 0.3
    seats_file.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    fake_cli.install(
        root.binaries, answer=fake_cli.envelope({"kind": READER, "information": "read it", "cited_ids": []}), sleep_seconds=1.5
    )
    layer = fake_cli.spawn_layer(
        root.root, router=None, workspace_path=str(root.workspace), plan=delegate_plan(READER)
    )
    spawn_desk_of(layer, TASK, TICK, str(root.workspace))
    desk = tick_calls_of(layer, TASK, TICK)
    answers = desk.run(NodeName.HIPPOCAMPUS)
    show("delegate fault", getattr(answers[0], "reason", None))
    assert isinstance(answers[0], CallRefusal)
    assert answers[0].reason == "cap_exceeded", "left exactly as the site that owns the cap raised it"


# --------------------------------------------------------------------------------------
# Rows M2 and M3 — the builder's own list. Written here, closed nowhere.
# --------------------------------------------------------------------------------------


def test_every_subpath_on_a_composed_spawn_profile_traces_to_one_of_three_provenances(
    wave,
) -> None:
    """Row M2's provenance half for a spawn reached **through the desk** (folded: S-i49).

    The handed workspace, `runtime.spawn_writable`, and the closed `SPAWN_PROCESS_ALLOWANCES`
    literal the probe's capture fixed — a third provenance class and the last one. On the builder's
    own list; closed by no row.
    """
    import re

    from protean.cortex.live.kinds import spawn_allowance_literals, spawn_allowance_subpaths

    root = wave((ALPHA,))
    desk = _desk(root)
    desk.dispatch_wave(_members((ALPHA,)), call_number=WAVE_CALL_NUMBER)
    # The string that actually ran, off the spawn's own facts — not a profile composed beside it.
    profile = desk.spawns_of()[(str(NodeName.CORTEX), WAVE_CALL_NUMBER, 1)].argv[2]
    traced = {str(root.workspace)}
    traced |= {str(tree) for tree in root.seats.spawn_writable}
    traced |= {str(Path(entry).expanduser().resolve()) for entry in spawn_allowance_subpaths()}
    found = set(re.findall(r'\(subpath "([^"]+)"\)', profile))
    literals = set(re.findall(r'\(literal "([^"]+)"\)', profile))
    show("subpaths with no provenance", sorted(found - traced))
    assert found - traced == set(), "every subpath traces to one of the three"
    assert literals == set(spawn_allowance_literals()), "and the devices are the measured literal"


def test_a_spawn_desk_carries_no_path_but_the_ones_the_runtime_handed_it(wave) -> None:
    """Row M2's other half, one object over: a `KindBlock` carries no path but `prompt`.

    The desk's own paths are the workspace the runtime handed it and the scaffold the builder
    derived from the brain root — never a value read off a kind block.
    """
    root = wave()
    block = root.seats.kind("dispatch", ALPHA)
    paths = [
        field.name
        for field in dataclasses.fields(block)
        if isinstance(getattr(block, field.name), Path)
        or (isinstance(getattr(block, field.name), str) and getattr(block, field.name).startswith("/"))
    ]
    show("path-bearing keys on the block", paths)
    assert paths == ["prompt_path"], "the one named exception, resolved from the seed's directory"
    desk = _desk(root)
    assert desk.workspace == str(root.workspace)
    assert desk.scaffold().is_relative_to(root.root), "and the scaffold is runtime-owned"
