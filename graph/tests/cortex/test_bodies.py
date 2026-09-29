"""Row G9: the body never changes the result — one recorded state, two bodies, the same bytes.

`the build specification (not in this mirror)` § Deliverable 5 (seam contract C4, decision 9, § Rulings 7,
folded: A1-8, folded: S-A30, folded: S-A31, folded: S-A66, folded: S-A78).

**Proven dry, and nothing here spends.** The recorded state and the scripted answer are
`fixtures/calls/body_invariance.yaml`; the transport standing in for each body is
`tests/cortex/fake_cli.py`, a stand-in binary the shipping adapter really spawns — the real
argv, the real scrub, the real sandbox wrap, a real process, and only the process on the other
end is ours. The **live** half of the same claim is the operator's row B32, queued behind their go at B42.

**The comparison is over the *assembled* prefix, never either file alone** (folded: S-A66), and
`test_the_control_makes_the_same_comparison_fail` is why that matters: the control body hands
the model the seat's own prefix **file** instead of the assembled two halves, which is the
substitution § Deliverable 5 warns about — it passes a file-level comparison of the second half
and fails this one. Without it, a byte-identity that is true by construction would be
indistinguishable from a comparison that never ran.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from protean import config
from protean.brain.folders import inventory_seed_files, seed_hashes, widened_seed_files
from protean.cortex.bodies import (
    BODY_FLAGS,
    NO_SESSION_MECHANICS,
    PRINT_FLAG,
    SEAT_SESSION_MECHANICS,
    TERMINAL_FLAGS,
    Body,
    BodyCall,
    BodyRefused,
    body_for,
    for_addressee,
    refuse_an_unlaunched_body,
    request_on_stdin,
    request_payload,
    select,
)
from protean.cortex.live.config import parse_seats
from protean.state.calls import (
    BODY_INVARIANTS,
    BODY_NAMES,
    BODY_PRINT,
    BODY_TERMINAL,
    BodyTransport,
)
from protean.state.enums import CallType, Escalation, NodeName, Tier
from protean.state.primitives import GoalItem
from protean.state.workspace import ManagerRequest, Workspace
from tests.cortex import fake_cli

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "fixtures" / "calls" / "body_invariance.yaml"

#: The one tier this row is proven on — the seat whose request carries the most.
TIER = Tier.MANAGER


def _fixture() -> dict[str, Any]:
    """The recorded state and the scripted answer, read from the one artifact both runs read."""
    return yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))


def _request(state: dict[str, Any]) -> ManagerRequest:
    """The recorded state, as the request the port is handed."""
    goal = state["goal"]
    workspace = Workspace(
        task_id=state["task"],
        tick=state["at"],
        goals=[
            GoalItem(
                id=goal["id"],
                text=goal["text"],
                opened_at_tick=state["at"],
                last_progress_tick=state["at"],
            )
        ],
    )
    return ManagerRequest(workspace=workspace, escalation=Escalation(state["escalation"]))


def _answer(fixture: dict[str, Any]) -> dict[str, Any]:
    """The scripted transport's answer for `TIER`, off the fixture's `responses` list."""
    result = next(
        item["result"] for item in fixture["responses"] if item["tier"] == str(TIER)
    )
    return fake_cli.envelope(dict(result))


@dataclass(frozen=True, slots=True)
class Replay:
    """One body's replay of the recorded state: what it was handed, and what came back."""

    body: str
    carried: BodyCall
    argv: list[str]
    stdin: bytes
    environment: dict[str, str]
    envelope: bytes
    recorded_argv: tuple[str, ...]

    def flags(self) -> set[str]:
        """Every flag on the argv the CLI actually saw."""
        return fake_cli.flags_of(self.argv)


def _replay(
    tmp_path: Path, monkeypatch, label: str, body_name: str, *, handed: Body | None = None
) -> Replay:
    """Replay the recorded state through one body, against its own stand-in transport."""
    fixture = _fixture()
    binaries = fake_cli.install(tmp_path / f"bin-{label}", [_answer(fixture)])
    fake_cli.on_path(monkeypatch, binaries)
    # A fake-backed root whose `runtime.body` is the one named, and whose containment is
    # otherwise the tracked seed's exactly as `seed_live_root()` leaves it — the file's,
    # never the test's.
    root = fake_cli.select_body(
        fake_cli.seed_live_root(tmp_path / f"brain-{label}"), body_name
    )
    seat = fake_cli.live_seat(root)
    if handed is not None:
        seat.body = handed
    request = _request(fixture["state"])
    seat.sessions.open_task(fixture["state"]["task"])
    envelope = seat(TIER, request)
    return Replay(
        body=seat.body_of(TIER).name,
        carried=seat.body_of(TIER).carried(seat, TIER, request),
        argv=fake_cli.argv_of(binaries),
        stdin=fake_cli.stdin_of(binaries).encode("utf-8"),
        environment=fake_cli.environment_of(binaries),
        envelope=envelope.model_dump_json().encode("utf-8"),
        recorded_argv=seat.calls()[0].argv,
    )


@pytest.fixture(scope="module")
def both_bodies(tmp_path_factory: pytest.TempPathFactory):
    """The recorded state replayed through **both** bodies, once for the module's comparisons.

    Row G9's four readings — the request bytes, the envelope bytes, all six of C4's invariants and
    the assembled prefix's order — are four questions asked of one pair of replays, so the pair is
    produced once rather than four times over. `test_the_control_makes_the_same_comparison_fail`
    keeps its own pair on purpose: a control that shared this one would not be a control.
    """
    base = tmp_path_factory.mktemp("bodies")
    with pytest.MonkeyPatch.context() as patch:
        printed = _replay(base, patch, "print", BODY_PRINT)
        terminal = _replay(base, patch, "terminal", BODY_TERMINAL)
        yield printed, terminal


def _diff(left: bytes, right: bytes, first: str, second: str) -> list[str]:
    """A byte-level unified diff, printed so a pass shows an empty diff rather than a claim."""
    return list(
        difflib.unified_diff(
            left.decode("utf-8", errors="replace").splitlines(),
            right.decode("utf-8", errors="replace").splitlines(),
            fromfile=first,
            tofile=second,
            lineterm="",
        )
    )


# --------------------------------------------------------------------------------------
# C4 — what a body is, and the loader's refusal
# --------------------------------------------------------------------------------------


def test_both_bodies_implement_every_invariant_c4_names() -> None:
    """"C4 `BodyTransport` names exactly that list, and the loader refuses a body that does not
    implement all of it" (§ Deliverable 5)."""
    for name in BODY_NAMES:
        transport = select(name).transport()
        print(f"    [C4] {name}: {list(transport.implements)}")
        assert transport.implements == BODY_INVARIANTS
        assert transport.runtime_launched is True
        assert isinstance(transport, BodyTransport)
    assert BODY_INVARIANTS == (
        "system_prompt_prefix",
        "request_on_stdin",
        "tool_set",
        "schema",
        "session_mechanics",
        "journaling",
    )


def test_a_body_that_implements_five_of_the_six_is_refused_by_name() -> None:
    """The refusal is the contract's, and it quotes the invariant that is missing."""

    class _HalfABody(Body):
        """A body that cannot journal. Nothing else about it differs."""

        journaling = None

    with pytest.raises(ValidationError) as raised:
        _HalfABody(name=BODY_TERMINAL).transport()
    print(f"    [C4] refusal: {str(raised.value).splitlines()[1].strip()}")
    assert "journaling" in str(raised.value)
    assert _HalfABody(name=BODY_TERMINAL).implements() == BODY_INVARIANTS[:-1]


def test_a_body_the_runtime_did_not_launch_is_refused_by_name() -> None:
    """"the operator attaches to the runtime-launched session, never the reverse" (row G13)."""
    unlaunched = Body(name=BODY_TERMINAL, runtime_launched=False)
    with pytest.raises(BodyRefused) as raised:
        refuse_an_unlaunched_body(unlaunched)
    print(f"    [G13] refusal: {raised.value}")
    assert BODY_TERMINAL in str(raised.value)
    assert "before any session handle is minted" in str(raised.value)
    with pytest.raises(BodyRefused):
        select(BODY_TERMINAL, runtime_launched=False)


@pytest.mark.parametrize("name", ["stream-json", "interactive", "", "PRINT"])
def test_a_body_name_outside_the_two_is_refused_by_name(name: str) -> None:
    with pytest.raises(BodyRefused) as raised:
        select(name)
    assert name in str(raised.value) and BODY_PRINT in str(raised.value)


def test_the_two_bodies_differ_by_the_print_flag_and_nothing_else() -> None:
    """§ Deliverable 5: "the same argv **minus the print flag** plus the interactive flags".

    The interactive list is the part A.1 does not fix (§ Named assumptions 1), so it is named
    as **empty** rather than guessed — which is also why row G13 asserts "no flag outside the
    named `-p` set" instead of a whole-argv equality (folded: S-A86).
    """
    print(f"    [G13] flags: {dict(BODY_FLAGS)}")
    assert select(BODY_PRINT).flags() == (PRINT_FLAG,)
    assert select(BODY_TERMINAL).flags() == TERMINAL_FLAGS == ()


def test_the_session_mechanics_clause_is_met_by_both_bodies_doing_nothing() -> None:
    """"Mint, resume, discard at task end" for the two seats and **none** for everything else."""
    for name in BODY_NAMES:
        body = select(name)
        assert body.session_mechanics(Tier.DIRECTOR) == SEAT_SESSION_MECHANICS
        assert body.session_mechanics(Tier.MANAGER) == SEAT_SESSION_MECHANICS
        for call_type in CallType:
            assert body.session_mechanics(call_type) == NO_SESSION_MECHANICS


# --------------------------------------------------------------------------------------
# One key, and it applies to the two cortex seats only (row G13, folded: S-A78)
# --------------------------------------------------------------------------------------


def test_the_key_applies_to_the_two_seats_and_everything_else_takes_print(tmp_path: Path) -> None:
    """"Tier three always runs under the `claude -p` body", and so do the two `calls:` blocks."""
    root = fake_cli.select_body(fake_cli.seed_live_root(tmp_path / "brain"), BODY_TERMINAL)
    seats = parse_seats(yaml.safe_load((root / "seats.yaml").read_text(encoding="utf-8")), root)
    assert seats.body == BODY_TERMINAL
    assert body_for(seats).name == BODY_TERMINAL
    for tier in Tier:
        assert for_addressee(seats, tier).name == BODY_TERMINAL
    for call_type in CallType:
        print(f"    [G13] {call_type} under runtime.body={seats.body}: "
              f"{for_addressee(seats, call_type).name}")
        assert for_addressee(seats, call_type).name == BODY_PRINT


def test_a_root_that_selects_no_body_at_all_is_the_print_body() -> None:
    """`SeatsConfig.body` defaults, so the oracle's directly-built containment is unchanged."""

    class _NoBody:
        pass

    assert body_for(_NoBody()).name == BODY_PRINT


# --------------------------------------------------------------------------------------
# Row G9 — the same state through both bodies, byte for byte
# --------------------------------------------------------------------------------------


def test_the_request_bytes_are_byte_identical_across_bodies(both_bodies) -> None:
    """Row G9's first half, over `fixtures/calls/body_invariance.yaml`'s recorded state."""
    printed, terminal = both_bodies

    diff = _diff(printed.stdin, terminal.stdin, BODY_PRINT, BODY_TERMINAL)
    print(f"    [G9] request bytes: {len(printed.stdin)} vs {len(terminal.stdin)}; diff={diff}")
    assert diff == []
    assert printed.stdin == terminal.stdin
    assert printed.carried.request_on_stdin == terminal.carried.request_on_stdin == printed.stdin
    assert json.loads(printed.stdin) == json.loads(terminal.stdin)


def test_the_envelope_handed_back_is_byte_identical_across_bodies(both_bodies) -> None:
    """Row G9's second half: the body carries bytes back and amends none of them."""
    printed, terminal = both_bodies

    diff = _diff(printed.envelope, terminal.envelope, BODY_PRINT, BODY_TERMINAL)
    print(f"    [G9] envelope bytes: {len(printed.envelope)}; diff={diff}")
    assert diff == []
    assert printed.envelope == terminal.envelope


def test_every_one_of_c4s_six_invariants_is_identical_across_bodies(both_bodies):
    """The whole of C4's list, not only the two row G9 names — compared field by field."""
    printed, terminal = both_bodies

    left, right = printed.carried.invariants(), terminal.carried.invariants()
    moved = [name for name in BODY_INVARIANTS if left[name] != right[name]]
    print(f"    [G9] invariants compared: {list(left)}; moved: {moved}")
    assert moved == []
    assert printed.carried.tool_set == terminal.carried.tool_set == ()
    assert printed.carried.session_mechanics == SEAT_SESSION_MECHANICS


def test_the_assembled_prefix_puts_the_node_md_half_first_for_both_bodies(both_bodies):
    """"A `NODE.md` **first**, then the seat or call-type prefix file" (folded: S-A30, S-A66)."""
    printed, terminal = both_bodies

    root = REPO_ROOT / "brain"
    node_md = (root / "nodes" / str(NodeName.CORTEX) / "NODE.md").read_bytes()
    seat_md = (root / "seats" / f"{TIER}.md").read_bytes()
    for replay in (printed, terminal):
        prefix = replay.carried.system_prompt_prefix
        print(f"    [G9] {replay.body} prefix: {len(prefix)} bytes, "
              f"first half {prefix[:28]!r}…")
        assert prefix.startswith(node_md), "the NODE.md half is first"
        assert prefix.endswith(seat_md), "the block's own prefix file is second"
    assert printed.carried.system_prompt_prefix == terminal.carried.system_prompt_prefix


def test_the_control_makes_the_same_comparison_fail(tmp_path, monkeypatch) -> None:
    """The positive control: a passing comparison cannot mean a comparison that never ran.

    The control body substitutes a different first half — it hands the model the seat's prefix
    **file** rather than the assembled two halves — which is the exact substitution
    § Deliverable 5 narrows the clause against. A **file-level** comparison of the second half
    still passes; this one fails.
    """

    class _FileLevelPrefixBody(Body):
        """A body that reads the prefix file and skips the `NODE.md` half."""

        def system_prompt_prefix(self, port, addressee, node=None, *, block=None) -> bytes:
            resolved = port.block_for(addressee) if block is None else block
            return resolved.prompt_path(port.config.root).read_bytes()

    printed = _replay(tmp_path, monkeypatch, "print-control", BODY_PRINT)
    altered = _replay(
        tmp_path,
        monkeypatch,
        "terminal-control",
        BODY_TERMINAL,
        handed=_FileLevelPrefixBody(name=BODY_TERMINAL),
    )

    diff = _diff(
        printed.carried.system_prompt_prefix,
        altered.carried.system_prompt_prefix,
        BODY_PRINT,
        "altered",
    )
    print(f"    [G9 control] the comparison fails: {len(diff)} diff lines")
    assert diff != [], "the control has to FAIL the same comparison the row passes"
    # …and the substitution really reached the wire, rather than a record beside it:
    sent = altered.argv[altered.argv.index("--system-prompt") + 1].encode("utf-8")
    assert sent == altered.carried.system_prompt_prefix
    assert sent != printed.argv[printed.argv.index("--system-prompt") + 1].encode("utf-8")
    assert printed.carried.system_prompt_prefix != altered.carried.system_prompt_prefix
    assert printed.carried.invariants() != altered.carried.invariants()
    # …and the file-level comparison it would have passed:
    seat_md = (altered.carried.system_prompt_prefix)
    assert printed.carried.system_prompt_prefix.endswith(seat_md), (
        "the second half is identical — which is why the comparison is over the assembled bytes"
    )


def test_one_implementation_builds_the_request_bytes_for_both_bodies() -> None:
    """"Identical by construction": the port and the body call the same two functions."""
    payload = {"b": 1, "a": "é"}
    assert request_on_stdin(payload) == json.dumps(payload, ensure_ascii=False)
    assert request_payload({"a": 1}) == {"a": 1}
    body = select(BODY_PRINT)
    assert body.request_on_stdin(payload) == request_on_stdin(payload).encode("utf-8")


# --------------------------------------------------------------------------------------
# The prefix is half of what a body holds identical — so both halves are hashed seeds
# (§ Resolutions D11-4; `tests/brain/test_folders.py` is outside order W9's writable set)
# --------------------------------------------------------------------------------------


def test_both_halves_of_every_assembled_prefix_are_hashed_seeds(tmp_path: Path) -> None:
    """The seat prefixes **and** the two call-type prefixes: `seats/**/*.md`, recursive.

    D11-4: the glob reached `seats/*.md` and stopped at the directory boundary, so editing
    `seats/calls/think.md` mid-task was not a drift refusal while editing `manager.md` was —
    for two files the loader reads the same way and a body holds identical the same way.
    """
    root = fake_cli.select_body(fake_cli.seed_live_root(tmp_path / "brain"), BODY_PRINT)
    hashes = seed_hashes(root)
    widened = widened_seed_files(root)
    print(f"    [D11-4] seat seeds: {[key for key in sorted(hashes) if key.startswith('seats')]}")
    for tier in config.TIERS:
        assert f"seats/{tier}.md" in hashes
    for call_type in config.CONFIGURED_CALL_TYPES:
        relative = f"seats/calls/{call_type}.md"
        assert relative in widened, "a call-type prefix is a seed like any other"
        assert hashes[relative], "and it is hashed into the checkpoint"
        assert relative in inventory_seed_files(root), "the appearance detector covers it too"


def test_editing_a_call_type_prefix_moves_the_recorded_hash(tmp_path: Path) -> None:
    """Which is the whole point: a mid-task edit to a prefix is a drift refusal, not a silence."""
    root = fake_cli.select_body(fake_cli.seed_live_root(tmp_path / "brain"), BODY_PRINT)
    before = seed_hashes(root)
    prefix = root / "seats" / "calls" / "think.md"
    prefix.write_text(prefix.read_text(encoding="utf-8") + "\n<!-- a hand edit -->\n", "utf-8")
    after = seed_hashes(root)
    moved = [key for key in before if before[key] != after[key]]
    print(f"    [D11-4] moved: {moved}")
    assert "seats/calls/think.md" in moved
