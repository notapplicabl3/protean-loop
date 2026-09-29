"""Row G8 — the witness: the four derived lists, the four receipt columns and the one bump.

`the build specification (not in this mirror)` § Deliverable 6 (I4 `SpawnWitness`, the derivation table,
the two wave-level lists and the two per-spawn ones), § Scaffold clause item 2's S2/C2 amendment,
§ Resolutions A1-7, A1-9 and A1-15, and § Deliverable R rows R11 and R14.

**Dry throughout, and every fixture drives the stand-in.** The binary is `tests/cortex/fake_cli`, on a
**fixture** brain root whose `kinds:` container comes from `fixtures/calls/kinds/wave_kinds.yaml`; the
adapter, the desk and the runtime are the shipping ones, so the argv is real, the profile is real, the
processes are real and the receipt is read back **off disk** from `seat_calls.jsonl`. Nothing here
spends and the repo's own `brain/` is read by `seed_kinds_root()` and written by nothing.

**The claim under test is "derived rather than reported", and it takes two fixtures to state.** The
positive one has the stand-in really write inside the granted workspace, really write under a
`runtime.spawn_writable` tree, and come back with denials that name a path outside the workspace and
attempt an exec. The **negative control** has the stand-in's own *narrative* claim all four in prose
and leaves every list empty. One without the other proves nothing: a list that fills when the model
says so is a list read off the model (S-63).
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from protean import config as protean_config
from protean.cortex.live import audit as spawn_audit
from protean.cortex.live.kinds import KINDS_BLOCK, CapabilityProfile, KindBlock
from protean.cortex.live.wave import SpawnDesks
from protean.runtime.cycle import WAVE_CALL_NUMBER, dispatch_id_of
from protean.runtime.journal import load as load_journal
from protean.runtime.seat import SeatCallFacts, spawn_desk_of, tick_calls_of
from protean.state.calls import (
    SPAWN_JOURNAL_FIELDS,
    SPAWN_LICENSED_DUPLICATES,
    SPAWN_RECEIPT_FIELDS,
    SpawnAudit,
    SpawnTreeDiff,
    SpawnWitness,
)
from protean.state.enums import CallType, NodeName
from protean.state.errors import SchemaVersionMismatch
from protean.state.seat_calls import SeatCallRecord, load_seat_calls
from tests.conftest import tagged_show
from tests.cortex import fake_cli
from tests.cortex.conftest import (
    READER,
    SHIM_LOG,
    UNDER,
    assert_dry,
    delegate_plan,
    drive,
    live_layer_for,
    task_paths,
    wave_root,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

GOAL = "witness the wave"
TASK = "task-witness"
UNIT = "u-witness-1"
TICK = 1

#: The prose the **negative control's** stand-in answers with. It claims all four lists in as many
#: words, and every list stays empty — which is the whole content of "derived rather than reported"
#: (S-63). The sentence is deliberately the one a session would actually write.
NARRATIVE = (
    "I wrote /etc/hosts and ~/.ssh/authorized_keys, I left the clone to read "
    "/home/other/secrets, I ran `claude -p` to spawn a nested session, and I dropped a file "
    "in /tmp. rm -rf / ; git push --force"
)

#: A path no fixture root grants: outside the workspace, outside `runtime.spawn_writable` and outside
#: the stand-in's own directory. It is **named** by a denial and never written.
OUTSIDE = "/home/nobody/protean-witness-outside.txt"


show = tagged_show("W5-witness")


# --------------------------------------------------------------------------------------
# The root, the stand-in, and the two ways a spawn is driven
# --------------------------------------------------------------------------------------


def _denial(command: str) -> dict:
    """One entry of `permission_denials`, in the shape the CLI's own captures carry.

    Measured rather than invented: `tests/cortex/captures/containment-dontask.json`'s three denials
    each carry `tool_name`, `tool_use_id` and a `tool_input` holding `command`.
    """
    return {
        "tool_name": "Bash",
        "tool_use_id": f"toolu_{abs(hash(command)) % 10**16:016d}",
        "tool_input": {"command": command, "description": "refused"},
    }


def _typed_denial(path: str) -> dict:
    """A denial whose path arrives as the **typed field it is**, not inside a command."""
    return {
        "tool_name": "Write",
        "tool_use_id": "toolu_typed_0000000000000",
        "tool_input": {"file_path": path, "content": "x"},
    }


@pytest.fixture()
def witness(tmp_path: Path, monkeypatch):
    """A fixture-kind root, its stand-in, and the task workspace a spawn is granted.

    `evidence=` names the stand-in's own directory as a `runtime.spawn_writable` entry (D5-5) — which
    is also what makes it the tree `wrote_outside_workspace` is read on: the stand-in writes its argv,
    its stdin, its cwd and its environment beside `$0` on every invocation, so a spawn that ran really
    did write under a granted tree that is not the workspace.
    """

    def _build(
        kinds=UNDER,
        *,
        narrative: str = "wrote it",
        denials=(),
        writes_in_cwd: str | None = None,
        detached_child_seconds: float | None = None,
        delegate_answer: bool = False,
    ):
        return _witness_world(
            tmp_path,
            monkeypatch,
            kinds,
            narrative=narrative,
            denials=denials,
            writes_in_cwd=writes_in_cwd,
            detached_child_seconds=detached_child_seconds,
            delegate_answer=delegate_answer,
        )

    return _build


def _witness_world(
    base: Path,
    patch,
    kinds=UNDER,
    *,
    narrative: str = "wrote it",
    denials=(),
    writes_in_cwd: str | None = None,
    detached_child_seconds: float | None = None,
    delegate_answer: bool = False,
) -> SimpleNamespace:
    """`conftest.wave_root()` under this module's task and unit, and its narrative default.

    `delegate_answer` is a flag here rather than a kind name: this module has exactly one
    delegate kind to open, and the factory takes the name.
    """
    return wave_root(
        base,
        patch,
        kinds,
        task=TASK,
        unit=UNIT,
        narrative=narrative,
        denials=denials,
        delegate_answer=READER if delegate_answer else None,
        writes_in_cwd=writes_in_cwd,
        detached_child_seconds=detached_child_seconds,
    )


def _layer(root, *, plan=None):
    """`conftest.live_layer_for()` — the production layer, `node_calls` attached on demand."""
    return live_layer_for(root, plan=plan)


def _drive(root, *, plan=None, task: str = TASK, max_ticks: int = 1):
    """One live tick through the shipping runtime, to the boundary that writes the receipt."""
    return drive(root, goal=GOAL, task=task, plan=plan, max_ticks=max_ticks)


def _paths(root, task: str = TASK):
    return task_paths(root, task)


def _receipts(root, task: str = TASK) -> list[SeatCallRecord]:
    """Every receipt line, **off disk**, through the loader that refuses a version mismatch."""
    return load_seat_calls(_paths(root, task).seat_calls)


def _spawn_receipts(root, task: str = TASK) -> list[SeatCallRecord]:
    """The receipt lines of the tick's spawns — a wave's members and a node's delegates."""
    return [
        line
        for line in _receipts(root, task)
        if line.tier in (CallType.DISPATCH, CallType.DELEGATE)
    ]


def _entries(root, tick: int = TICK, task: str = TASK):
    return load_journal(_paths(root, task).journal(tick))


# --------------------------------------------------------------------------------------
# Row G8's first clause — every spawn's receipt, column by column, off disk
# --------------------------------------------------------------------------------------


def test_every_spawns_receipt_carries_the_four_new_columns_read_back_off_disk(witness) -> None:
    """Row G8: the argv, the **effective caps in the two columns this build adds**, the usage, the
    outcome, the kind, `dispatch_id`, the envelope's `permission_denials` and an `audit` object.

    Read off `seat_calls.jsonl` through `load_seat_calls()` rather than off the desk, because the
    claim is about the line the boundary wrote and not about the facts it wrote it from.

    Carries A1-15 too: the `dispatch_id` is the landed literal format `<task>-t<tick>-c<call#>`,
    one id across the whole wave, derived from the wave's own key and minted nowhere.
    """
    root = witness(denials=[_denial(f"touch {OUTSIDE}")])
    _layer_used, outcome = _drive(root)
    show("terminal", str(outcome.terminal))

    lines = _spawn_receipts(root)
    show("spawn receipt keys", [(str(r.node), r.call_number, r.member_number) for r in lines])
    assert len(lines) == len(UNDER), "one receipt line per member of the wave"

    for line, kind in zip(lines, UNDER, strict=True):
        block = root.seats.kind(protean_config.CALL_DISPATCH, kind)
        assert line.argv and line.argv[0] == root.seats.sandbox.binary, "the wrapped argv as it ran"
        assert line.max_call_usd == pytest.approx(float(block.max_call_usd))
        assert line.timeout_seconds == pytest.approx(float(block.timeout_seconds))
        assert line.usage.get("cache_read_input_tokens") is not None, "the usage, off the envelope"
        assert line.outcome == "ok"
        assert line.kind == kind, "the kind — the one licensed duplicate"
        assert line.dispatch_id == dispatch_id_of(TASK, TICK, WAVE_CALL_NUMBER)
        assert [one["tool_input"]["command"] for one in line.permission_denials] == [
            f"touch {OUTSIDE}"
        ], "the envelope's own denial list, as received"
        assert line.audit is not None, "and an `audit` object"
        assert isinstance(line.audit, SpawnAudit)
    show("caps", [(line.max_call_usd, line.timeout_seconds) for line in lines])
    show("dispatch_id", {line.dispatch_id for line in lines})
    assert {line.dispatch_id for line in lines} == {f"{TASK}-t{TICK}-c{WAVE_CALL_NUMBER}"}, (
        "A1-15: the landed format, one id for the wave"
    )


def test_the_caps_columns_are_empty_on_a_receipt_with_no_spawn_behind_it(witness) -> None:
    """The four columns are a **spawn's**: a seat call resolves no kind block and reports no caps."""
    root = witness()
    _drive(root)
    seats = [
        line
        for line in _receipts(root)
        if line.tier not in (CallType.DISPATCH, CallType.DELEGATE)
    ]
    show("non-spawn receipts", [(str(line.tier), line.max_call_usd) for line in seats])
    assert seats, "the manager's own call wrote a line"
    for line in seats:
        assert line.max_call_usd is None and line.timeout_seconds is None
        assert line.permission_denials == [] and line.audit is None


# --------------------------------------------------------------------------------------
# Row G8's four lists — the positive fixture and its negative control
# --------------------------------------------------------------------------------------


def test_the_four_lists_are_derived_from_disk_and_from_the_denials(witness) -> None:
    """The positive fixture: it writes twice, names a path outside, and attempts an exec.

    Four facts, four sources, and not one of them the model's account of itself: the write **inside**
    the workspace and the write **under a `runtime.spawn_writable` tree** are read off the
    filesystem by mtime and size, and the path named outside plus the exec attempted are read out of
    the envelope's own `permission_denials` through build 2's landed classifier.
    """
    root = witness(
        writes_in_cwd="member-wrote-this.txt",
        denials=[
            _denial(f"cat {OUTSIDE}"),
            _denial("/usr/local/bin/claude -p 'a nested session'"),
            _typed_denial("/home/nobody/typed-outside.txt"),
        ],
    )
    _drive(root)
    line = _spawn_receipts(root)[0]
    audit = line.audit
    assert audit is not None

    inside = [one for one in audit.wrote if one.tree == str(root.workspace)]
    show("wrote", [(one.tree, one.moved, one.changed) for one in audit.wrote])
    assert len(inside) == 1, "one diff for the granted workspace"
    assert inside[0].moved is True, "the workspace moved"
    assert inside[0].digest, "and one digest per tree says so"
    assert "member-wrote-this.txt" in inside[0].changed, "the file the member really wrote"

    granted = {one.tree: one for one in audit.wrote_outside_workspace}
    show("wrote_outside_workspace trees", sorted(granted))
    evidence = granted.get(str(root.binaries.resolve()))
    assert evidence is not None, "the stand-in's own `spawn_writable` tree is asked too"
    assert evidence.moved is True and evidence.changed, "and it really wrote under it"
    assert any("argv-" in one for one in evidence.changed), "its own recordings, off disk"
    assert str(root.workspace) not in granted, "the workspace is `wrote`'s subject, not this list's"

    show("left_the_clone", audit.left_the_clone)
    assert any(OUTSIDE in one for one in audit.left_the_clone), "the path named outside"
    assert any("typed-outside" in one for one in audit.left_the_clone), "read as the typed field"
    assert all(one.startswith(("Bash:", "Write:")) for one in audit.left_the_clone)

    show("exec_attempted", audit.exec_attempted)
    assert any("attempts to execute the CLI binary" in one for one in audit.exec_attempted)


def test_the_negative_control_claims_all_four_and_every_list_stays_empty(witness) -> None:
    """S-63, and the whole content of "derived rather than reported".

    The stand-in answers with prose claiming every one of the four, carries **no** denials and writes
    nothing but its own recordings. Three lists are empty; the fourth — the granted tree it records
    into — is non-empty for a reason that has nothing to do with what it said.
    """
    root = witness(narrative=NARRATIVE)
    _drive(root)
    line = _spawn_receipts(root)[0]
    audit = line.audit
    assert audit is not None
    show("the narrative", NARRATIVE[:60] + "…")
    show("lists", (audit.left_the_clone, audit.exec_attempted))

    assert audit.left_the_clone == [], "it said it left the clone; no denial says so"
    assert audit.exec_attempted == [], "it said it ran the binary; no denial says so"
    assert line.permission_denials == [], "and it carried no denials at all"
    workspace = [one for one in audit.wrote if one.tree == str(root.workspace)]
    assert workspace and workspace[0].moved is False, "it said it wrote; the workspace did not move"
    assert workspace[0].changed == []
    # The narrative is still on the record where a narrative belongs — the journalled envelope —
    # which is what makes the empty lists a statement rather than an absence.
    envelopes = [
        entry
        for entry in _entries(root)
        if entry.tier is CallType.DISPATCH and entry.envelope is not None
    ]
    assert envelopes and NARRATIVE in envelopes[0].envelope.result


def test_wrote_is_byte_identical_on_every_members_receipt_of_one_wave(witness) -> None:
    """One wave, one baseline, one diff — so the list is the **wave's** (folded: S-i24).

    Written identically to every member's receipt exactly as `dispatch_id` is, because per-member
    attribution is not available from one baseline and one diff and A.1.i does not fake it (row B52).
    """
    root = witness(writes_in_cwd="all-four-wrote-here.txt")
    _drive(root)
    lines = _spawn_receipts(root)
    assert len(lines) == 4, "a four-member wave"

    serialised = {
        json.dumps(
            [one.model_dump(mode="json") for one in line.audit.wrote], sort_keys=True
        )
        for line in lines
    }
    outside = {
        json.dumps(
            [one.model_dump(mode="json") for one in line.audit.wrote_outside_workspace],
            sort_keys=True,
        )
        for line in lines
    }
    show("distinct `wrote` values across four receipts", len(serialised))
    assert len(serialised) == 1, "`wrote` is byte-identical across the wave's four lines"
    assert len(outside) == 1, "and so is `wrote_outside_workspace`"
    assert len({line.dispatch_id for line in lines}) == 1, "exactly as `dispatch_id` is"
    # The two per-spawn lists are per spawn: four members, four session handles, four argvs.
    assert len({tuple(line.argv) for line in lines}) == 4, "the per-spawn columns still differ"


def test_the_process_group_read_at_the_join_witnesses_a_live_grandchild(witness) -> None:
    """Folded: S-i21, folded: S-i57 — the only witness of the nested-session route there is.

    The stand-in leaves a sleeping grandchild in its own process group and returns; the desk reads
    that group's live members as it joins **that** spawn, and the pids land on `exec_attempted`. A
    grandchild that had already exited would not appear, which is the limit row B51 states.
    """
    root = witness(kinds=UNDER[:1], detached_child_seconds=8.0)
    pids: list[int] = []
    try:
        _drive(root)
        line = _spawn_receipts(root)[0]
        show("exec_attempted", line.audit.exec_attempted)
        assert any("still had live members at the join" in one for one in line.audit.exec_attempted)
        recorded = fake_cli.grandchild_pid(root.binaries, line.session_handle)
        pids.append(recorded)
        assert any(str(recorded) in one for one in line.audit.exec_attempted), (
            "the pid the stand-in recorded is the pid the group read found"
        )
    finally:
        # The fixture's own scaffolding, removed by the test that created it: a sleeping grandchild
        # outliving the case would be this module leaking a process into the battery.
        for pid in pids:
            try:
                os.kill(pid, 9)
            except OSError:
                pass


# --------------------------------------------------------------------------------------
# Row G8's carrier clause — the keyed read, and the case the landed FIFO gets wrong
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def delegate_drive(tmp_path_factory: pytest.TempPathFactory):
    """One tick carrying a **pre-cortex delegate beside the wave**, driven once for the module.

    Two of row G8's clauses are read off it — the carrier clause (folded: S-i42) and the
    `block_ref` clause (folded: S-i12, folded: S-i51) — and both read the journal and the receipts
    off disk and write nothing, so the five spawns are paid once rather than twice.
    """
    base = tmp_path_factory.mktemp("delegate")
    with pytest.MonkeyPatch.context() as patch:
        root = _witness_world(base, patch, delegate_answer=True)
        _drive(root, plan=delegate_plan())
        yield root


def test_a_pre_cortex_delegate_before_a_member_carries_its_own_facts(delegate_drive) -> None:
    """The case the landed FIFO match gets wrong (folded: S-i42), as a fixture rather than a reading.

    `hippocampus` is second in `NODE_ORDER`, so its delegate's journal entry **precedes** the wave's
    members'. Read positionally, the delegate's entry would meet a later `dispatch` fact and be
    written empty; read by the journal's own key `(node, call#, member#)`, each entry carries the
    facts of the spawn that actually produced it.
    """
    root = delegate_drive

    entries = [entry for entry in _entries(root) if entry.is_call()]
    order = [(str(entry.node), str(entry.tier), entry.member_number) for entry in entries]
    show("journal order", order)
    delegate_at = next(i for i, one in enumerate(order) if one[1] == str(CallType.DELEGATE))
    member_at = next(i for i, one in enumerate(order) if one[1] == str(CallType.DISPATCH))
    assert delegate_at < member_at, "the pre-cortex delegate's entry precedes the members'"

    lines = {
        (str(line.node), line.call_number, line.member_number): line
        for line in _receipts(root)
    }
    delegate = lines[(str(NodeName.HIPPOCAMPUS), 1, None)]
    members = [
        lines[(str(NodeName.CORTEX), WAVE_CALL_NUMBER, number)]
        for number in range(1, len(UNDER) + 1)
    ]
    show("delegate handle", delegate.session_handle)
    show("member handles", [line.session_handle for line in members])

    assert delegate.argv, "the delegate's entry is not written empty"
    assert delegate.session_handle and delegate.audit is not None
    assert delegate.dispatch_id == "", "a delegate belongs to no wave"
    for line in members:
        assert line.argv and line.session_handle and line.audit is not None
        assert line.session_handle != delegate.session_handle, "its own facts, not the member's"
    handles = {line.session_handle for line in [delegate, *members]}
    assert len(handles) == len(members) + 1, "every spawn's facts are its own"

    # And the desk is the carrier: one `spawns_of()`, keyed by the journal's own key.
    layer = _layer(root, plan=delegate_plan())
    desk = spawn_desk_of(layer, TASK, TICK, str(root.workspace))
    assert desk is not None and desk.spawns_of() == {}, "a fresh tick's desk carries no spawn yet"


def test_a_delegates_wave_is_one_spawn_so_its_lists_are_its_own(witness) -> None:
    """"per spawn only for a **delegate**, whose wave is one" (folded: S-i24)."""
    root = witness(delegate_answer=True, kinds=UNDER[:1])
    layer = _layer(root, plan=delegate_plan())
    spawn_desk_of(layer, TASK, TICK, str(root.workspace))
    desk = tick_calls_of(layer, TASK, TICK)
    desk.run(NodeName.HIPPOCAMPUS)

    facts = desk.spawn_desk.spawns_of()
    show("delegate spawn keys", sorted(facts))
    assert sorted(facts) == [(str(NodeName.HIPPOCAMPUS), 1, None)], "one spawn, no member#"
    only = facts[(str(NodeName.HIPPOCAMPUS), 1, None)]
    block = root.seats.kind(protean_config.CALL_DELEGATE, READER)
    assert only.max_call_usd == pytest.approx(float(block.max_call_usd))
    assert only.timeout_seconds == pytest.approx(float(block.timeout_seconds))
    assert only.audit is not None and len(only.audit.wrote) == 1
    assert only.pgid > 1, "the group the child led, published on the facts"


# --------------------------------------------------------------------------------------
# Row G8's `block_ref` clause — a change of value, not of field set
# --------------------------------------------------------------------------------------


def test_the_journals_block_ref_is_the_block_the_desk_resolved(delegate_drive) -> None:
    """`kinds.<class>.<name>` where A.1's `_wave_entry()` wrote the bare kind name (folded: S-i12),
    **and a delegate's entry carries `kinds.delegate.<name>` where `_entry_for()` passed none at
    all** (folded: S-i51)."""
    root = delegate_drive
    entries = [entry for entry in _entries(root) if entry.is_call()]

    members = [entry for entry in entries if entry.tier is CallType.DISPATCH]
    show("member block_refs", [entry.block_ref for entry in members])
    assert [entry.block_ref for entry in members] == [
        f"{KINDS_BLOCK}.{protean_config.CALL_DISPATCH}.{kind}" for kind in UNDER
    ]
    assert [entry.kind for entry in members] == list(UNDER), "`kind` stays the bare name"

    delegate = next(entry for entry in entries if entry.tier is CallType.DELEGATE)
    show("delegate block_ref", delegate.block_ref)
    assert delegate.block_ref == f"{KINDS_BLOCK}.{protean_config.CALL_DELEGATE}.{READER}"
    assert delegate.kind == READER

    # The reference is the block's own and is minted nowhere else.
    for entry in [*members, delegate]:
        kind_class = entry.block_ref.split(".")[1]
        assert entry.block_ref == root.seats.kind(kind_class, entry.kind).block_ref


# --------------------------------------------------------------------------------------
# Row G8's amendment clause — exactly two names, one bump, a version-2 line refused
# --------------------------------------------------------------------------------------


def test_the_receipt_half_gained_exactly_two_names_and_the_journal_half_did_not_move() -> None:
    """§ Scaffold clause item 2: the only part of A.1's seam A.1.i reopens."""
    show("receipt half", SPAWN_RECEIPT_FIELDS)
    assert SPAWN_RECEIPT_FIELDS == (
        "argv",
        "max_call_usd",
        "timeout_seconds",
        "usage",
        "outcome",
        "kind",
        "dispatch_id",
        "permission_denials",
        "audit",
    )
    assert SPAWN_JOURNAL_FIELDS == (
        "addressee",
        "payload",
        "payload_model",
        "kind",
        "block_ref",
        "envelope",
    ), "the journal's half does not move"
    overlap = set(SPAWN_JOURNAL_FIELDS) & set(SPAWN_RECEIPT_FIELDS)
    assert overlap == set(SPAWN_LICENSED_DUPLICATES) == {"kind"}


def test_the_no_overlap_assertion_passes_at_import_and_the_module_imports_no_runtime() -> None:
    """Route row R14's own check, run as an import rather than read as a docstring.

    A fresh interpreter, so the assertion runs where it lives — at import time — and the module's
    dependency direction is measured off `sys.modules` rather than off the source text: a contract
    under `protean.state` may not acquire a dependency on the thing it constrains.
    """
    program = (
        "import sys\n"
        "import protean.state.calls as m\n"
        "assert m.SPAWN_RECEIPT_FIELDS[-2:] == ('permission_denials', 'audit')\n"
        "assert set(m.SPAWN_JOURNAL_FIELDS) & set(m.SPAWN_RECEIPT_FIELDS) == {'kind'}\n"
        "leaked = sorted(n for n in sys.modules "
        "if n.startswith(('protean.runtime', 'protean.cortex')))\n"
        "assert leaked == [], leaked\n"
        "print('OK', m.SPAWN_RECEIPT_FIELDS)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
    )
    show("python -c", completed.stdout.strip() or completed.stderr.strip())
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.startswith("OK")


def test_a_version_two_receipt_is_refused_by_name_and_never_migrated(tmp_path: Path) -> None:
    """A1-9: one bump, 2 → 3, covering all four columns; the old line is refused **by name**."""
    assert protean_config.SEAT_CALL_SCHEMA_VERSION == 3
    path = tmp_path / "seat_calls.jsonl"
    line = SeatCallRecord.from_call(
        task="task-old", tick=1, node=NodeName.CORTEX, call_number=1, schema_version=2
    )
    path.write_text(json.dumps(line.model_dump(mode="json")) + "\n", encoding="utf-8")

    with pytest.raises(SchemaVersionMismatch) as raised:
        load_seat_calls(path)
    message = str(raised.value)
    show("refusal", message)
    assert "seat_calls" in message, "the artifact, by name"
    assert "2" in message and "3" in message, "both numbers, the old one and the running one"
    assert raised.value.found == 2 and raised.value.expected == 3
    assert "migrat" in message, "refused rather than converted"


# --------------------------------------------------------------------------------------
# Row M2's own half — the persisted shape lives with the artifact it rides on
# --------------------------------------------------------------------------------------


def test_the_persisted_witness_sits_beside_c2_and_the_unpersisted_shapes_do_not() -> None:
    """Row M2, the part order W5 owes (§ W5 Process step 15). `WaveBound` is retired (S-i16)."""
    for model in (SpawnWitness, SpawnAudit, SpawnTreeDiff):
        show(f"{model.__name__} home", model.__module__)
        assert model.__module__ == "protean.state.calls", "persisted: beside C2"
    for model in (KindBlock, CapabilityProfile):
        show(f"{model.__name__} home", model.__module__)
        assert model.__module__ == "protean.cortex.live.kinds", "not persisted: beside TierSeat"
    import protean.state.calls as calls_module

    assert not hasattr(calls_module, "WaveBound"), "I3 is retired, the letter unreused"


def test_i4_carries_the_denial_list_the_four_lists_and_no_baseline_reference() -> None:
    """§ Scaffold clause item 3's I4 entry, and folded: S-i47's own clause."""
    show("SpawnWitness fields", sorted(SpawnWitness.model_fields))
    assert sorted(SpawnWitness.model_fields) == ["audit", "permission_denials"]
    assert sorted(SpawnAudit.model_fields) == [
        "exec_attempted",
        "left_the_clone",
        "wrote",
        "wrote_outside_workspace",
    ], "the four lists, and four is the number"
    for model in (SpawnWitness, SpawnAudit, SpawnTreeDiff):
        named = [name for name in model.model_fields if "baseline" in name or "before" in name]
        assert named == [], f"{model.__name__} carries no baseline reference"
    assert "digest" in SpawnTreeDiff.model_fields, "one digest per tree — the join's, not the open's"


# --------------------------------------------------------------------------------------
# The derivations themselves — the imported classifier, and the one predicate this build owns
# --------------------------------------------------------------------------------------


def test_the_module_imports_the_landed_classifier_and_never_tool_violations() -> None:
    """Folded: S-i45 and folded: S-i31 — `src/protean/oracle/audit.py` stays unedited."""
    source = (REPO_ROOT / "src" / "protean" / "cortex" / "live" / "audit.py").read_text()
    for name in ("shell_segments", "wrote_or_left_the_clone", "attempted_to_execute_the_binary"):
        assert f"    {name},\n" in source, f"{name} is imported, never re-derived"
    # Measured off the module's own namespace rather than off its prose: the docstring **names**
    # `tool_violations()` in order to say it is never called, so a source grep for the token would
    # fail on the sentence that states the rule.
    assert not hasattr(spawn_audit, "tool_violations"), "never imported, never defined"
    imported = source.split("from protean.oracle.audit import")[1].split(")")[0]
    show("imported from oracle.audit", imported.strip())
    assert "tool_violations" not in imported, "fed denials alone it answers [] forever"
    assert "def shell_segments" not in source and "def wrote_or_left_the_clone" not in source
    assert "def attempted_to_execute_a_farmed_binary" in source, "the one local judgement"
    for name in ("shell_segments", "wrote_or_left_the_clone", "attempted_to_execute_the_binary"):
        assert getattr(spawn_audit, name).__module__ == "protean.oracle.audit"


def test_the_link_farm_predicate_is_this_modules_own_and_reads_the_same_segments() -> None:
    """`runtime.bin_links` is the runtime's list, not the oracle's clone rule (A1-12)."""
    assert spawn_audit.attempted_to_execute_a_farmed_binary("uv run pytest", ["uv"])
    assert spawn_audit.attempted_to_execute_a_farmed_binary("ls; /opt/homebrew/bin/git log", ["git"])
    show("named, not run", spawn_audit.attempted_to_execute_a_farmed_binary("which uv", ["uv"]))
    assert spawn_audit.attempted_to_execute_a_farmed_binary("which uv", ["uv"]) == ""
    assert spawn_audit.attempted_to_execute_a_farmed_binary("uv run pytest", []) == ""


def test_the_group_read_refuses_a_pgid_that_would_address_the_runtimes_own_group() -> None:
    """`killpg(0, …)` addresses the **caller's** group; `0` is "no process existed"."""
    assert spawn_audit.live_process_group_members(0) == ()
    assert spawn_audit.live_process_group_members(1) == ()
    assert spawn_audit.live_process_group_members(-os.getpgid(0)) == ()
    show("this process's own group is never reported", os.getpgid(0))


def test_the_workspace_digest_excludes_the_named_directories_by_name(tmp_path: Path) -> None:
    """A workspace carrying a virtualenv must not produce a receipt nobody can read."""
    tree = tmp_path / "clone"
    (tree / ".venv" / "lib").mkdir(parents=True)
    (tree / "__pycache__").mkdir()
    (tree / ".pytest_cache").mkdir()
    (tree / "src").mkdir()
    (tree / "src" / "kept.py").write_text("x", encoding="utf-8")
    baseline = spawn_audit.take_baseline(tree, [])

    (tree / ".venv" / "lib" / "noise.so").write_text("noise", encoding="utf-8")
    (tree / "__pycache__" / "noise.pyc").write_text("noise", encoding="utf-8")
    (tree / ".pytest_cache" / "noise").write_text("noise", encoding="utf-8")
    diff = spawn_audit.wrote(baseline)
    show("excluded noise", [one.changed for one in diff])
    assert diff[0].moved is False and diff[0].changed == []

    time.sleep(0.01)
    (tree / "src" / "real.py").write_text("y", encoding="utf-8")
    after = spawn_audit.wrote(baseline)
    show("a real write", after[0].changed)
    assert after[0].moved is True and after[0].changed == [str(Path("src") / "real.py")]
    assert after[0].digest != baseline.workspace_digest


def test_the_granted_trees_are_witnessed_by_mtime_against_the_opens_instant(
    tmp_path: Path,
) -> None:
    """`wrote_outside_workspace`'s own shape: mtime, no digest, the runtime's scaffolding excluded."""
    granted = tmp_path / "granted"
    (granted / "protean-seat-bin-xyz").mkdir(parents=True)
    (granted / "real").mkdir()
    baseline = spawn_audit.take_baseline(None, [granted])
    assert baseline.workspace is None and baseline.since > 0

    time.sleep(0.01)
    (granted / "protean-seat-bin-xyz" / "claude").write_text("farm", encoding="utf-8")
    (granted / "real" / "left-behind.txt").write_text("x", encoding="utf-8")
    diffs = spawn_audit.wrote_outside_workspace(baseline)
    show("granted diff", [(one.tree, one.digest, one.changed) for one in diffs])
    assert len(diffs) == 1 and diffs[0].tree == str(granted)
    assert diffs[0].digest == "", "a machine-shared tree is witnessed by mtime, never by digest"
    assert diffs[0].moved is True
    assert any("left-behind.txt" in one for one in diffs[0].changed)
    assert not any("protean-seat-bin-" in one for one in diffs[0].changed), (
        "the runtime's own scaffolding, excluded by name (S-51)"
    )


def test_the_composition_shares_the_waves_two_lists_and_derives_the_other_two() -> None:
    """`compose()` is where "identically to every member's receipt" is a property of the code."""
    shared = SpawnAudit(
        wrote=[SpawnTreeDiff(tree="/w", moved=True, digest="d", changed=["a"])],
        wrote_outside_workspace=[SpawnTreeDiff(tree="/tmp", moved=False)],
    )
    first = spawn_audit.compose(
        wave_level=shared, denials=[_denial("cat /etc/hosts")], workspace=None
    )
    second = spawn_audit.compose(wave_level=shared, denials=[], workspace=None)
    show("shared halves equal", first.wrote == second.wrote)
    assert first.wrote == second.wrote == shared.wrote
    assert first.wrote_outside_workspace == second.wrote_outside_workspace
    assert first.left_the_clone and second.left_the_clone == [], "the per-spawn halves are not"


# --------------------------------------------------------------------------------------
# Route rows R11 and R14 — each row's own `Check` column
# --------------------------------------------------------------------------------------


def _docstring_of(relative: str) -> str:
    return (REPO_ROOT / relative).read_text().split('"""')[1]


def test_route_row_r11_names_the_spawn_path_no_library_kind_and_still_points_at_c2() -> None:
    """Row R11's own `Check` column, clause by clause."""
    docstring = _docstring_of("src/protean/cortex/subagents.py")
    show("R11 head", docstring.strip().splitlines()[0])
    assert "There is no spawn path here" not in docstring, "that sentence is now false"
    assert "spawn path exists now" in docstring, "the spawn path, named as present"
    for named in ("kinds:", "positive grant", "per spawn", "SpawnDesk"):
        assert named in docstring, f"R11 names {named!r}"
    assert "library kind" in docstring and "still not here is any library kind" in docstring
    assert "protean.state.calls" in docstring, "and it still points at `protean.state.calls` for C2"


def test_route_row_r14_names_the_receipt_half_amendment_and_the_no_import_rule() -> None:
    """Row R14's own `Check` column, clause by clause."""
    docstring = _docstring_of("src/protean/state/calls.py")
    show("R14 head", docstring.strip().splitlines()[0])
    assert "spawn path exists now" in docstring, "the spawn path, re-pointed"
    for named in ("receipt half", "permission_denials", "audit", "SpawnWitness"):
        assert named in docstring, f"R14 names {named!r}"
    assert "still not here is **any library kind**" in docstring
    assert "imports nothing from" in docstring, "and it still states the no-import rule"
    assert "`protean.runtime`" in docstring and "`protean.cortex`" in docstring


def test_the_no_import_rule_is_true_of_the_module_and_not_only_stated() -> None:
    """R14's third clause, as a fact about the source rather than about the docstring."""
    source = (REPO_ROOT / "src" / "protean" / "state" / "calls.py").read_text()
    offending = [
        line
        for line in source.splitlines()
        if line.startswith(("import ", "from ")) and ("protean.runtime" in line or "protean.cortex" in line)
    ]
    show("offending imports", offending)
    assert offending == []


# --------------------------------------------------------------------------------------
# The build stays dry: the recording shim never fires
# --------------------------------------------------------------------------------------


def test_no_case_in_this_module_reached_a_real_binary() -> None:
    """The shim's log stays zero bytes, which is what "dry throughout" means physically."""
    show("shim log bytes", SHIM_LOG.stat().st_size if SHIM_LOG.exists() else 0)
    assert_dry()


def test_the_facts_carry_the_four_fields_and_the_fifth_that_is_not_a_column() -> None:
    """Folded: S-i4 and folded: S-i57 — the carrier, and the one field that rides no column."""
    names = [field.name for field in dataclasses.fields(SeatCallFacts)]
    show("SeatCallFacts additions", names[-5:])
    for name in ("max_call_usd", "timeout_seconds", "permission_denials", "audit", "pgid"):
        assert name in names
    assert "pgid" not in SeatCallRecord.model_fields, "the pgid is not a receipt column"
    assert "pgid" not in SPAWN_RECEIPT_FIELDS and "pgid" not in SPAWN_JOURNAL_FIELDS


def test_the_seam_still_answers_none_where_a_layer_has_no_fifth_seam(witness) -> None:
    """Row M3's shape: a layer without the seam spawns nothing, and the boundary reads nothing."""
    root = witness()
    seam = SpawnDesks(config=root.seats, root=root.root)
    desk = seam(TASK, TICK, str(root.workspace))
    show("a desk that never spawned", desk.spawns_of())
    assert desk.spawns_of() == {} and desk.block_refs_of() == {}
