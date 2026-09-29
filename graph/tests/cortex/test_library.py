"""The shipping kind library, read off the seed that ships and driven against the stand-in.

`the build specification (not in this mirror)` § Deliverable 6 (the library's own battery), § Deliverable 1
(the `editor` block, a T3 surface), § Deliverable 3 (its prefix and binding clause 1),
§ Resolutions L1, L2, L3, L6, L8. Order W1's DoD rows **G1** (the `editor` half and the
`REASON_NO_KIND` pair), **G2** and **G4** (the `editor.md` half); each case carries its row in its
name, so `-k G1`, `-k G2` and `-k G4` select it. Order W2 appends § Deliverable 2 (the `reader`
block) and § Deliverable 3's binding clause 2, § Resolutions L15, L18: **G1** (the `reader` half and
the container's exactly-two-kinds clause), **G3** and **G4** (the `reader.md` half). Order W3
appends § Deliverable 4 (the manager's dispatch clause), § Resolutions L5, L7, L9, L17: **G5** (the
library's two homes held in step) and **M1** (no kind name under `src/**` as a literal). Order W5
appends § Deliverable 7 (the intent channel, a T3 surface) and I5's one `units` keyword
(§ Scaffold clause item 2), § Resolutions L19, L20, L23: **G9** (a)–(i). Order W6 appends the two
clauses of row **G7** it collects about the unrun `tests/wet/probe_library.py` (§ Deliverable 6,
L10, V3-12): its name matches no `python_files` pattern, and it carries its member's unit statically.

**Its subject is the shipping seed, not a fixture.** `tests/cortex/test_kinds.py` proves the
container and the floor on fixture kinds; this module loads `brain/seats.yaml` off disk and asserts
the library as landed. Two readings of it, and the split is § Deliverable 6 ¶2's:

* **Every block, cap, grant and profile-string assertion reads the unspliced seed** — the tracked
  file, parsed or loaded as it ships, and the refusal cases mutate a loaded copy of it.
* **Every spawn-driving case reads a spliced copy.** The stand-in writes its argv, stdin, cwd and env
  recordings beside itself, and the shipped `runtime.spawn_writable` (`/tmp` and uv's cache) does
  not cover a pytest `tmp_path`, so those cases seed a root with `fake_cli.seed_live_root()` and
  rewrite `runtime.spawn_writable` to exactly `[/tmp, <resolved evidence dir>]` — what
  `fake_cli.seed_kinds_root(..., evidence=)` does for a fixture root. Nothing else in the payload
  moves, so the `editor` block a spliced case spawns is the shipping one.

**Dry throughout.** Every spawn runs `tests/cortex/fake_cli.py`'s stand-in; nothing spends.
"""

from __future__ import annotations

import ast
import copy
import inspect
import json
import math
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from protean import config
from protean.brain.folders import seed_hashes
from protean.cortex.layer import build_live_layer
from protean.cortex.live.config import (
    BODY_KEY,
    PERMISSION_MODE_BINDING,
    PROFILE_HEAD,
    RUNTIME_BLOCK,
    SANDBOX_BLOCK,
    SANDBOX_PROFILE_FLAG,
    SPAWN_CAP_CEILINGS,
    SPAWN_WRITABLE_KEY,
    TIER_KEYS,
    SeatConfigError,
    load_seats,
    parse_seats,
)
from protean.cortex.live.invoke import (
    ALLOWED_TOOLS_FLAG,
    DISALLOWED_TOOLS_FLAG,
    SYSTEM_PROMPT_FLAG,
    TOOLS_FLAG,
    UNIT_DELIMITER,
    LiveSeat,
)
from protean.cortex.live.kinds import (
    CLASS_KEY,
    EGRESS_REMOTE,
    KINDS_BLOCK,
    LICENSED_PATTERNS,
    NAMED_BY_THEIR_OWN_REFUSAL,
    derived_names,
    kinds_dir,
    resolve_capability,
    spawn_allowance_literals,
    spawn_allowance_subpaths,
)
from protean.cortex.live.wave import REASON_NO_KIND, REASON_WAVE_BOUND, SpawnDesk, SpawnDesks
from protean.mailbox.files import build as build_mailbox
from protean.runtime import cycle, engine
from protean.runtime.commit import build_checkpoint, write_checkpoint
from protean.runtime.cycle import REASON_NO_UNIT, WAVE_CALL_NUMBER, run_wave
from protean.runtime.errors import SeatUnavailable
from protean.runtime.journal import load as load_journal
from protean.runtime.paths import BrainPaths
from protean.runtime.seat import TickSpawns, spawn_desk_of, tick_calls_of
from protean.state.checkpoint import load_checkpoint
from protean.state.enums import CallType, NodeName, TerminalState
from protean.state.errors import SeedHashMismatch
from protean.state.inputs import WAVE_COMPLETE
from protean.state.seats import DelegateReturn, SeatEnvelope, WaveMember
from tests.conftest import PREFIXES, tagged_show
from tests.cortex import fake_cli
from tests.cortex.conftest import assert_dry, delegate_plan, drive, task_paths
from tests.mailbox.answering import answer

#: The library's one `dispatch` kind and the class it sits under (§ Deliverable 1, L1).
EDITOR = "editor"
DISPATCH = "dispatch"

#: § Deliverable 1's granted pair, transcribed from the SPEC's own fence (L2, L8) — so a seed edit
#: that widens or narrows the T3 surface turns this module red instead of drifting past it.
EDITOR_ALLOWED = (
    "Read",
    "Edit",
    "Write",
    "Grep",
    "Glob",
    "Bash(uv:*)",
    "Bash(git status:*)",
    "Bash(git diff:*)",
    "Bash(git add:*)",
    "Bash(git commit:*)",
    "Bash(git checkout:*)",
    "Bash(git branch:*)",
)
EDITOR_TOOLS = ("Read", "Edit", "Write", "Grep", "Glob", "Bash")

#: The three licensed `dispatch` patterns the workload does not name, and so the grant omits.
EDITOR_OMITTED = ("Bash(python:*)", "Bash(pytest:*)", "Bash(git log:*)")

#: § Deliverable 3's binding clause 1 (L6), and the structured-JSON clause every prefix carries
#: (`brain/nodes/cortex/NODE.md:21-24`) — each asserted as a literal body string.
RERUNNABLE_CLAUSE = "Your work must be re-runnable, because a torn wave re-runs whole."
JSON_LEAD = "You answer as structured JSON and nothing else."
JSON_CLAUSE = (
    "The request arrives on stdin as one JSON object; your answer is validated against the schema "
    "you were handed, and there is no channel beside them."
)

#: A kind name the library does not define — the other side of `REASON_NO_KIND`.
UNDEFINED_KIND = "kind_not_in_the_library"

#: The mutated copy's second `dispatch` kind: the `editor` block, one cent over (row G2).
ONE_CENT_OVER = "editor_one_cent_over"

GOAL = "change the clone and prove the change"
TASK = "task-library"
UNIT = "u-library-1"
TICK = 1

show = tagged_show("G1")


# --------------------------------------------------------------------------------------
# The two readings: the unspliced seed, and a spliced copy the stand-in can record into
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def shipped_root() -> Path:
    """The tracked `brain/` — the shipping seed, read and never written."""
    return config.repo_root() / "brain"


@pytest.fixture()
def shipped(shipped_root: Path) -> dict:
    """The tracked `brain/seats.yaml` as a payload — the **unspliced** loaded copy a case mutates."""
    return yaml.safe_load((shipped_root / "seats.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def seats(shipped_root: Path):
    """The shipping seed as the loader resolves it."""
    loaded = load_seats(shipped_root)
    assert loaded is not None, "the tracked brain root carries seats.yaml"
    return loaded


@pytest.fixture(scope="module")
def editor(seats):
    """The shipping `editor` block, resolved through the one resolver that can name a kind."""
    return seats.kind(DISPATCH, EDITOR)


def _splice(root: Path, evidence: Path) -> Path:
    """Rewrite a seeded root's `runtime.spawn_writable` to exactly `[/tmp, <evidence dir>]`.

    § Deliverable 6 ¶2's one test-owned entry, spelled the way `fake_cli.seed_kinds_root(...,
    evidence=)` spells it for a fixture root — the list replaced outright rather than appended to,
    and the evidence directory resolved, because `sandbox-exec` matches a subpath against the
    realpath. `tests/cortex/fake_cli.py` is read, never edited (V3-8).
    """
    seats_file = root / "seats.yaml"
    payload = yaml.safe_load(seats_file.read_text(encoding="utf-8"))
    payload[RUNTIME_BLOCK][SPAWN_WRITABLE_KEY] = [
        fake_cli.FIXTURE_WRITABLE_TREE,
        str(evidence.resolve()),
    ]
    seats_file.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return root


def library_root(base: Path, patch, kinds=(EDITOR,), *, plans: int = 1) -> SimpleNamespace:
    """A spliced copy of the shipping seed, its stand-in on `PATH`, and a task workspace.

    The stand-in answers the manager with a plan naming `kinds` and each member with an
    `ExecutorSummary`; `conftest.wave_root()`'s shape, with the shipping seed in place of a fixture
    container.
    """
    binaries = fake_cli.install(
        base / "bin",
        [fake_cli.wave_plan(UNIT, f"{TASK}-g1", kinds)] * plans,
        members=fake_cli.member_answers(kinds, UNIT),
    )
    fake_cli.on_path(patch, binaries)
    root = _splice(fake_cli.seed_live_root(base / "brain"), binaries)
    workspace = base / "clone"
    workspace.mkdir()
    return SimpleNamespace(
        root=root,
        binaries=binaries.resolve(),
        workspace=workspace.resolve(),
        seats=fake_cli.seats_of(root),
        kinds=tuple(kinds),
    )


def _desk(world, seats=None) -> SpawnDesk:
    """The tick's one desk, resolved through the seam exactly as the runtime resolves it."""
    seam = SpawnDesks(config=world.seats if seats is None else seats, root=world.root)
    return seam(TASK, TICK, str(world.workspace))


def _members(kinds) -> dict[int, WaveMember]:
    """`member#` assigned before anything starts, from the order the plan listed the kinds."""
    return {
        number: WaveMember(kind=kind, unit_id=UNIT, admitted_ref="admitted")
        for number, kind in enumerate(kinds, start=1)
    }


def _no_process(world) -> None:
    """The receipt every pre-process refusal closes on, both recording devices at once."""
    assert fake_cli.spawn_recordings(world.binaries) == [], "no spawn recording: no process"
    assert_dry()


def _payload(root: Path) -> dict:
    return yaml.safe_load((root / "seats.yaml").read_text(encoding="utf-8"))


def _prose(text: str) -> str:
    """A prefix's prose with Markdown's soft line breaks collapsed — the words are matched exactly."""
    return " ".join(text.split())


def _wave_entries(root: Path, tick: int):
    return [
        entry
        for entry in load_journal(task_paths(root, TASK).journal(tick))
        if entry.tier is CallType.DISPATCH and entry.is_call()
    ]


def _answer_the_refusal(root: Path, text: str = "retry it") -> dict:
    """Answer the one mailbox item a refused tick raised, and hand back its evidence."""
    item = next(BrainPaths(root=root).mailbox_open.glob("*.md"))
    body = item.read_text(encoding="utf-8")
    answer(item, text)
    return {"path": item, "text": body}


def _age_the_task(root: Path, ticks: int = 10) -> None:
    """Re-seal the checkpoint as a task that had already run `ticks` ticks when the wave refused.

    One refusal on tick one is an error rate of 1.0, so homeostasis would skip the next tick's seat
    call — `tests/cortex/test_wave.py`'s helper of the same name, for the same reason.
    """
    paths = task_paths(root, TASK)
    checkpoint = load_checkpoint(
        json.loads(paths.checkpoint.read_text(encoding="utf-8")), seed_reader=None
    )
    state = checkpoint.state
    state.cost.ticks = ticks
    write_checkpoint(
        paths,
        build_checkpoint(state, seed_hashes=seed_hashes(root), revision=checkpoint.revision),
    )


@pytest.fixture(scope="module")
def editor_spawn(tmp_path_factory: pytest.TempPathFactory) -> SimpleNamespace:
    """One `editor` member spawned through the desk on a spliced copy, recorded once for the module.

    Driven through `SpawnDesk.dispatch_wave` directly — the opener `run_wave` calls — so the
    recorded argv is the production argv, and every case below reads a different part of it.
    """
    base = tmp_path_factory.mktemp("editor-spawn")
    with pytest.MonkeyPatch.context() as patch:
        world = library_root(base, patch)
        desk = _desk(world)
        world.results = desk.dispatch_wave(_members((EDITOR,)), call_number=WAVE_CALL_NUMBER)
        (world.fact,) = desk.spawns_of().values()
        world.argv = fake_cli.argv_of(world.binaries, world.fact.session_handle)
        yield world


# --------------------------------------------------------------------------------------
# Row G1 — the `editor` block loads off the shipping seed, and its mutations refuse by name
# --------------------------------------------------------------------------------------


def test_G1_the_dispatch_class_carries_exactly_editor_and_the_block_takes_tier_keys_exactly(
    shipped: dict, seats
) -> None:
    """"`kinds.dispatch` carries exactly `editor`, and the block takes `TIER_KEYS` exactly"."""
    dispatch = shipped[KINDS_BLOCK][DISPATCH]
    show("kinds.dispatch", sorted(dispatch))
    assert sorted(dispatch) == [EDITOR]
    show("editor keys", sorted(dispatch[EDITOR]))
    assert sorted(dispatch[EDITOR]) == sorted(TIER_KEYS)
    assert len(TIER_KEYS) == 10
    assert sorted(seats.kinds[DISPATCH]) == [EDITOR], "and the loader resolves exactly that"


def test_G1_the_editor_prompt_resolves_by_realpath_to_an_existing_file_inside_the_directory(
    shipped_root: Path, editor
) -> None:
    """"`prompt:` resolves **by realpath** to an existing `brain/seats/kinds/editor.md` inside that
    directory"."""
    directory = kinds_dir(shipped_root).resolve()
    show("prompt", f"{editor.prompt} -> {editor.prompt_path}")
    assert editor.prompt == f"seats/{KINDS_BLOCK}/{EDITOR}.md"
    assert editor.prompt_path == (directory / f"{EDITOR}.md").resolve()
    assert editor.prompt_path.is_relative_to(directory)
    assert editor.prompt_path.is_file(), "the prefix is a seed on disk"
    assert not (kinds_dir(shipped_root) / f"{EDITOR}.md").is_symlink()


def test_G1_the_editor_runs_under_dont_ask_with_both_caps_at_or_under_the_spawn_ceilings(
    shipped: dict, seats, editor
) -> None:
    """"`permission_mode` is `dontAsk`. `max_call_usd` is 2.50 ≤ `runtime.spawn_max_call_usd` 5.0,
    and `timeout_seconds` is 1800 ≤ `runtime.spawn_timeout_seconds` 1800." The ceilings are read
    off the seed rather than transcribed."""
    runtime = shipped[RUNTIME_BLOCK]
    show("caps", f"{editor.max_call_usd}/{editor.timeout_seconds}")
    assert editor.permission_mode == PERMISSION_MODE_BINDING == "dontAsk"
    assert editor.max_call_usd == 2.50
    assert editor.timeout_seconds == 1800
    assert float(runtime["spawn_max_call_usd"]) == seats.spawn_max_call_usd == 5.0
    assert float(runtime["spawn_timeout_seconds"]) == seats.spawn_timeout_seconds == 1800
    assert editor.max_call_usd <= seats.spawn_max_call_usd
    assert editor.timeout_seconds <= seats.spawn_timeout_seconds


def _an_eleventh_key(block: dict, runtime: dict) -> tuple[str, ...]:
    block["writable_paths"] = ["/tmp"]
    return ("writable_paths", "exactly")


def _a_missing_key(block: dict, runtime: dict) -> tuple[str, ...]:
    del block["timeout_seconds"]
    return ("timeout_seconds",)


def _a_class_key(block: dict, runtime: dict) -> tuple[str, ...]:
    block[CLASS_KEY] = DISPATCH
    return (CLASS_KEY, "the class is the sub-mapping")


def _a_per_kind_sandbox(block: dict, runtime: dict) -> tuple[str, ...]:
    block[SANDBOX_BLOCK] = {"deny_write": []}
    return (SANDBOX_BLOCK, "declares no containment of its own")


def _a_body_key(block: dict, runtime: dict) -> tuple[str, ...]:
    block[BODY_KEY] = "terminal"
    return (BODY_KEY, "exactly")


def _max_call_usd_above_its_ceiling(block: dict, runtime: dict) -> tuple[str, ...]:
    block["max_call_usd"] = float(runtime[SPAWN_CAP_CEILINGS["max_call_usd"]]) + 0.01
    return ("max_call_usd", SPAWN_CAP_CEILINGS["max_call_usd"])


def _timeout_seconds_above_its_ceiling(block: dict, runtime: dict) -> tuple[str, ...]:
    block["timeout_seconds"] = float(runtime[SPAWN_CAP_CEILINGS["timeout_seconds"]]) + 0.01
    return ("timeout_seconds", SPAWN_CAP_CEILINGS["timeout_seconds"])


def _a_prompt_leaving_by_dotdot(block: dict, runtime: dict) -> tuple[str, ...]:
    block["prompt"] = "../notes.md"
    return ("../notes.md", "outside")


def _a_prompt_one_directory_over(block: dict, runtime: dict) -> tuple[str, ...]:
    block["prompt"] = "seats/calls/think.md"
    return ("seats/calls/think.md", "outside")


@pytest.mark.parametrize(
    "mutate",
    [
        _an_eleventh_key,
        _a_missing_key,
        _a_class_key,
        _a_per_kind_sandbox,
        _a_body_key,
        _max_call_usd_above_its_ceiling,
        _timeout_seconds_above_its_ceiling,
        _a_prompt_leaving_by_dotdot,
        _a_prompt_one_directory_over,
    ],
    ids=lambda mutate: mutate.__name__.lstrip("_"),
)
def test_G1_a_mutated_editor_block_refuses_by_name(shipped_root: Path, shipped: dict, mutate) -> None:
    """The seven refusals, on an **unspliced** loaded copy: an eleventh key, a missing key, a
    `class:` key, a per-kind `sandbox:`, a `body:` key, a cap above its ceiling (each of the two)
    and a `prompt:` resolving outside the directory (two spellings). Every refusal names the block
    and what was wrong with it."""
    payload = copy.deepcopy(shipped)
    expected = mutate(payload[KINDS_BLOCK][DISPATCH][EDITOR], payload[RUNTIME_BLOCK])
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(payload, shipped_root)
    message = str(raised.value)
    show(mutate.__name__.lstrip("_"), message[:130])
    assert f"{KINDS_BLOCK}.{DISPATCH}.{EDITOR}" in message, "refused by the block's own name"
    for fragment in expected:
        assert fragment in message, fragment


def test_G1_a_manager_plan_naming_editor_proceeds_under_the_stand_in(
    tmp_path: Path, monkeypatch
) -> None:
    """`REASON_NO_KIND`'s first side, on a spliced copy: a plan naming the library's kind spawns it.

    Through the production layer and a whole tick, so "proceeds" is a fact about the boundary: the
    wave completes, one process ran, and the journal names the shipping block.
    """
    world = library_root(tmp_path, monkeypatch, (EDITOR,))
    _layer, outcome = drive(world, goal=GOAL, task=TASK)
    show("terminal · wave", f"{outcome.terminal} · {outcome.ticks[0].wave_status}")
    assert outcome.terminal is not TerminalState.STOPPED
    assert outcome.ticks[0].wave_status == WAVE_COMPLETE
    assert len(fake_cli.spawn_recordings(world.binaries)) == 1, "one member, one process"
    entries = _wave_entries(world.root, 1)
    assert [(entry.kind, entry.block_ref) for entry in entries] == [
        (EDITOR, f"{KINDS_BLOCK}.{DISPATCH}.{EDITOR}")
    ]
    assert_dry()


def test_G1_a_plan_naming_an_undefined_kind_stops_and_a_reseeded_resume_proceeds(
    tmp_path: Path, monkeypatch
) -> None:
    """`REASON_NO_KIND`'s other side, still standing beside a defined kind: the tick stops with no
    process created — not even for the `editor` member — and a checkpoint on disk; a seed edit that
    defines the name plus `resume --reseed` then replays the same journalled plan and proceeds."""
    kinds = (EDITOR, UNDEFINED_KIND)
    world = library_root(tmp_path, monkeypatch, kinds, plans=2)
    _layer, outcome = drive(world, goal=GOAL, task=TASK)
    show("terminal", outcome.terminal)
    assert outcome.terminal is TerminalState.STOPPED
    assert task_paths(world.root, TASK).checkpoint.is_file(), "a checkpoint is on disk"
    _no_process(world)
    journalled = json.loads(
        [entry for entry in load_journal(task_paths(world.root, TASK).journal(1)) if entry.is_call()][0]
        .envelope.result
    )
    assert [member["kind"] for member in journalled["wave"]] == list(kinds)
    raised = _answer_the_refusal(world.root)
    assert REASON_NO_KIND in raised["text"], "the named reason reached the mailbox"

    # The seed edit that defines the name — the `editor` block copied under it — then the verb.
    payload = _payload(world.root)
    payload[KINDS_BLOCK][DISPATCH][UNDEFINED_KIND] = copy.deepcopy(payload[KINDS_BLOCK][DISPATCH][EDITOR])
    (world.root / "seats.yaml").write_text(yaml.safe_dump(payload, sort_keys=False), "utf-8")
    reseeded = engine.resume(
        world.root, build_live_layer(root=world.root), mailbox=build_mailbox(world.root), reseed=True
    )
    assert any("seats.yaml" in message for message in reseeded.messages)
    _age_the_task(world.root)
    resumed = engine.resume(
        world.root, build_live_layer(root=world.root), mailbox=build_mailbox(world.root), max_ticks=1
    )
    dispatched = [entry.kind for entry in _wave_entries(world.root, 2)]
    show("dispatched after the reseed", dispatched)
    assert dispatched == [member["kind"] for member in journalled["wave"]]
    assert resumed.ticks[0].wave_status == WAVE_COMPLETE
    assert len(fake_cli.spawn_recordings(world.binaries)) == len(kinds)


# --------------------------------------------------------------------------------------
# Row G2 — the `editor` grant, its recorded argv, its profile and the bound arithmetic
# --------------------------------------------------------------------------------------


def test_G2_the_editor_grant_is_exactly_the_twelve_patterns_and_the_six_names_they_derive(
    seats, editor
) -> None:
    """`allowed_tools` is the twelve; `tools` equals `derived(allowed_tools)` **as a set**; the three
    licensed patterns the workload does not name are absent; and the block names no egress verb."""
    licensed = LICENSED_PATTERNS[DISPATCH]
    show("allowed_tools", list(editor.allowed_tools), tag="G2")
    assert editor.allowed_tools == EDITOR_ALLOWED
    assert len(editor.allowed_tools) == 12 and len(licensed) == 15
    assert set(editor.allowed_tools) < set(licensed), "a narrowing of the class's set"
    assert set(licensed) - set(editor.allowed_tools) == set(EDITOR_OMITTED)
    for omitted in EDITOR_OMITTED:
        assert omitted not in editor.allowed_tools, omitted
    show("tools", list(editor.tools), tag="G2")
    assert set(editor.tools) == set(derived_names(editor.allowed_tools)) == set(EDITOR_TOOLS)
    assert editor.disallowed_tools == (), "the block names none of the eight"

    profile = resolve_capability(editor, spawn_writable=seats.spawn_writable)
    assert profile.granted_patterns == EDITOR_ALLOWED
    assert set(profile.granted_names) == set(EDITOR_TOOLS)
    assert profile.refused_patterns() == EGRESS_REMOTE


def test_G2_the_recorded_argv_carries_the_grant_and_all_eight_egress_verbs(editor_spawn) -> None:
    """Off the stand-in's own recording, on a spliced copy: `--allowedTools` is the twelve, `--tools`
    the six, and `--disallowedTools` all eight `EGRESS_REMOTE` verbs though the block names none."""
    argv = editor_spawn.argv
    assert isinstance(editor_spawn.results[1], SeatEnvelope)
    patterns = argv[argv.index(ALLOWED_TOOLS_FLAG) + 1 : argv.index(DISALLOWED_TOOLS_FLAG)]
    refused = argv[argv.index(DISALLOWED_TOOLS_FLAG) + 1 : argv.index(TOOLS_FLAG)]
    names = argv[argv.index(TOOLS_FLAG) + 1]
    show("--allowedTools", patterns, tag="G2")
    show("--disallowedTools", refused, tag="G2")
    show("--tools", names, tag="G2")
    assert patterns == list(EDITOR_ALLOWED)
    assert refused == list(EGRESS_REMOTE) and len(refused) == 8
    assert set(names.split(",")) == set(EDITOR_TOOLS)
    for omitted in EDITOR_OMITTED:
        assert omitted not in argv, omitted


def test_G2_the_composed_profile_allows_the_workspace_and_the_spawn_writable_trees(
    shipped: dict, seats, editor, tmp_path: Path
) -> None:
    """The profile **string**, composed off the **unspliced** seed: the landed head, `file-write*`
    denied, then allowed back over the task workspace, the shipped `runtime.spawn_writable` trees
    and the measured allowances — and nothing else."""
    workspace = (tmp_path / "clone").resolve()
    workspace.mkdir()
    trees = tuple(Path(entry).expanduser().resolve() for entry in shipped[RUNTIME_BLOCK][SPAWN_WRITABLE_KEY])
    assert seats.spawn_writable == trees, "the trees are the seed's own"
    profile = resolve_capability(
        editor, workspace=workspace, spawn_writable=seats.spawn_writable
    ).sandbox_profile(seats.sandbox)
    show("editor profile", profile, tag="G2")
    expected = (
        f"{PROFILE_HEAD}(deny file-write*)(allow file-write* "
        + " ".join(
            [f'(subpath "{workspace}")']
            + [f'(subpath "{tree}")' for tree in trees]
            + [f'(subpath "{path}")' for path in spawn_allowance_subpaths()]
            + [f'(literal "{path}")' for path in spawn_allowance_literals()]
        )
        + ")"
    )
    assert profile == expected


def _run_under(profile: str, seats, argv: list[str]) -> subprocess.CompletedProcess:
    """One process under a composed spawn profile, with no `TMPDIR` in its environment."""
    return subprocess.run(
        [seats.sandbox.binary, SANDBOX_PROFILE_FLAG, profile, *argv],
        capture_output=True,
        text=True,
        input="",
        env={"PATH": "/usr/bin:/bin"},
        timeout=120,
    )


def test_G2_the_recorded_profile_denies_a_third_path_at_the_kernel(
    editor_spawn, tmp_path: Path
) -> None:
    """The profile the `editor` spawn actually ran under, off its recorded wrapped argv: it allows the
    task workspace and the spliced `runtime.spawn_writable` trees — the stand-in's own recordings
    landed in one of them — and the kernel refuses a write to a third path outside all of them."""
    world = editor_spawn
    fact = world.fact
    assert list(fact.argv[:2]) == [world.seats.sandbox.binary, SANDBOX_PROFILE_FLAG]
    profile = fact.argv[2]
    allowed = [Path(path) for path in re.findall(r'\(subpath "([^"]+)"\)', profile)]
    show("recorded allowed subpaths", [str(path) for path in allowed], tag="G2")
    assert allowed[0] == world.workspace, "the task workspace, first"
    assert tuple(allowed[1 : 1 + len(world.seats.spawn_writable)]) == world.seats.spawn_writable
    assert world.binaries in world.seats.spawn_writable, "the spliced evidence directory"
    assert (world.binaries / f"argv-{fact.session_handle}.txt").is_file(), "the allowed write landed"

    third = (tmp_path / "third").resolve()
    third.mkdir()
    refused_path = third / "refused.txt"
    for tree in allowed:
        assert not refused_path.is_relative_to(tree), f"a third path, outside {tree}"
    outside = _run_under(profile, world.seats, ["/bin/sh", "-c", f"echo no > {refused_path}"])
    show("third-path write", f"{outside.returncode} · {outside.stderr.strip()[:80]}", tag="G2")
    assert outside.returncode != 0
    assert "Operation not permitted" in outside.stderr
    assert not refused_path.exists()

    inside = world.workspace / "wrote.txt"
    allowed_write = _run_under(profile, world.seats, ["/bin/sh", "-c", f"echo ok > {inside}"])
    assert allowed_write.returncode == 0 and inside.exists(), "the workspace is writable"


def test_G2_a_four_editor_wave_sums_to_exactly_the_wave_ceiling_and_runs(
    tmp_path: Path, monkeypatch, shipped: dict
) -> None:
    """Four `editor` members at `2.50` sum to exactly `spawn_max_wave_usd` 10.0 — a ceiling, not a
    strict bound — and all four spawn. The numbers come off the seed."""
    kinds = (EDITOR,) * 4
    world = library_root(tmp_path, monkeypatch, kinds)
    caps = [world.seats.kind(DISPATCH, kind).max_call_usd for kind in kinds]
    show("arithmetic", f"{caps} -> {math.fsum(caps)} vs {world.seats.spawn_max_wave_usd}", tag="G2")
    assert float(shipped[RUNTIME_BLOCK]["spawn_max_wave_usd"]) == world.seats.spawn_max_wave_usd
    assert math.fsum(caps) == world.seats.spawn_max_wave_usd == 10.0
    assert len(kinds) == world.seats.max_wave_members == 4
    results = _desk(world).dispatch_wave(_members(kinds), call_number=WAVE_CALL_NUMBER)
    assert sorted(results) == [1, 2, 3, 4]
    assert all(isinstance(value, SeatEnvelope) for value in results.values())
    assert len(fake_cli.spawn_recordings(world.binaries)) == 4


def test_G2_a_fifth_editor_refuses_under_the_wave_bound_with_no_process_created(
    tmp_path: Path, monkeypatch
) -> None:
    """A fifth member is one past `max_wave_members`: refused before the first spawn, by name."""
    kinds = (EDITOR,) * 5
    world = library_root(tmp_path, monkeypatch, kinds)
    with pytest.raises(SeatUnavailable) as raised:
        _desk(world).dispatch_wave(_members(kinds), call_number=WAVE_CALL_NUMBER)
    show("width refusal", raised.value.message[:120], tag="G2")
    assert raised.value.reason == REASON_WAVE_BOUND
    assert len(kinds) > world.seats.max_wave_members
    assert not isinstance(raised.value, SeatConfigError)
    _no_process(world)


@pytest.mark.parametrize("position", [1, 2, 3, 4])
def test_G2_one_cent_more_on_any_member_refuses_under_the_wave_bound(
    tmp_path: Path, monkeypatch, position: int
) -> None:
    """One cent more on any one member: built on a mutated loaded copy carrying `2.51` on that
    member, since every member of a shipping-library wave carries `2.50`. The width is legal and the
    sum is 10.01, so the refusal is the sum's."""
    kinds = tuple(ONE_CENT_OVER if number == position else EDITOR for number in range(1, 5))
    world = library_root(tmp_path, monkeypatch, kinds)
    payload = _payload(world.root)
    over = copy.deepcopy(payload[KINDS_BLOCK][DISPATCH][EDITOR])
    over["max_call_usd"] = 2.51
    payload[KINDS_BLOCK][DISPATCH][ONE_CENT_OVER] = over
    mutated = parse_seats(payload, world.root)
    caps = [mutated.kind(DISPATCH, kind).max_call_usd for kind in kinds]
    assert math.fsum(caps) > mutated.spawn_max_wave_usd and len(caps) <= mutated.max_wave_members
    with pytest.raises(SeatUnavailable) as raised:
        _desk(world, mutated).dispatch_wave(_members(kinds), call_number=WAVE_CALL_NUMBER)
    show(f"sum refusal, 2.51 at member {position}", raised.value.message[:120], tag="G2")
    assert raised.value.reason == REASON_WAVE_BOUND
    assert str(math.fsum(caps)) in raised.value.message, "the refusal quotes the sum"
    _no_process(world)


# --------------------------------------------------------------------------------------
# Row G4 — `editor.md`: confined, hashed, carrying its clauses and no token outside its grant
# --------------------------------------------------------------------------------------


def test_G4_editor_md_exists_resolves_inside_the_directory_and_is_a_hashed_seed(
    shipped_root: Path, editor
) -> None:
    """The file exists, resolves inside `brain/seats/kinds/` and appears in `seed_hashes()`."""
    path = kinds_dir(shipped_root) / f"{EDITOR}.md"
    relative = f"seats/{KINDS_BLOCK}/{EDITOR}.md"
    hashes = seed_hashes(shipped_root)
    show("hashed", relative in hashes, tag="G4")
    assert path.is_file()
    assert path.resolve().is_relative_to(kinds_dir(shipped_root).resolve())
    assert editor.prompt_path == path.resolve()
    assert relative in hashes and hashes[relative]


def test_G4_editing_editor_md_moves_the_hash_and_a_resume_across_the_edit_refuses_as_drift(
    tmp_path: Path, monkeypatch
) -> None:
    """A task opened on a spliced copy hashes `editor.md` into its checkpoint; an edit moves that
    hash, and a plain `resume` across the edit refuses as drift, naming the file."""
    world = library_root(tmp_path, monkeypatch, (EDITOR,), plans=2)
    drive(world, goal=GOAL, task=TASK)
    relative = f"seats/{KINDS_BLOCK}/{EDITOR}.md"
    recorded = json.loads(task_paths(world.root, TASK).checkpoint.read_text(encoding="utf-8"))
    before = seed_hashes(world.root)
    assert recorded["seed_hashes"][relative] == before[relative], "hashed into the checkpoint"

    prefix = kinds_dir(world.root) / f"{EDITOR}.md"
    prefix.write_text(prefix.read_text(encoding="utf-8") + "\n<!-- a hand edit -->\n", "utf-8")
    after = seed_hashes(world.root)
    show("hash moved", before[relative] != after[relative], tag="G4")
    assert before[relative] != after[relative]
    assert before["seats.yaml"] == after["seats.yaml"], "and nothing else moved with it"

    with pytest.raises(SeedHashMismatch) as raised:
        engine.resume(
            world.root, build_live_layer(root=world.root), mailbox=build_mailbox(world.root), max_ticks=1
        )
    show("drift refusal", str(raised.value)[:120], tag="G4")
    assert raised.value.path == relative


def test_G4_editor_md_carries_its_re_runnable_clause_and_the_structured_json_answer_clause(
    editor,
) -> None:
    """Binding clause 1 (L6) and the JSON clause, each as a literal body string."""
    prose = _prose(editor.prompt_path.read_text(encoding="utf-8"))
    show("re-runnable clause", RERUNNABLE_CLAUSE in prose, tag="G4")
    assert RERUNNABLE_CLAUSE in prose
    assert JSON_LEAD in prose
    assert JSON_CLAUSE in prose


def test_G4_editor_md_names_its_own_kind_and_class(editor) -> None:
    """One H1 naming the kind and its class (§ Deliverable 3's shape)."""
    lines = editor.prompt_path.read_text(encoding="utf-8").splitlines()
    show("H1", lines[0], tag="G4")
    assert lines[0].startswith("# ")
    assert EDITOR in lines[0] and DISPATCH in lines[0]
    assert sum(line.startswith("# ") for line in lines) == 1, "one H1"


def test_G4_the_complement_sweep_finds_no_tool_token_outside_the_editor_grant(editor) -> None:
    """Case-sensitive and token-level, over **the complement of `editor`'s own grant**: both
    classes' licensed patterns and their derived names, `EGRESS_REMOTE` and
    `NAMED_BY_THEIR_OWN_REFUSAL`, minus the block's own `allowed_tools` and `tools` — never over
    English words. Neither forbidden home-directory prefix appears either."""
    universe: set[str] = set(EGRESS_REMOTE) | set(NAMED_BY_THEIR_OWN_REFUSAL)
    for patterns in LICENSED_PATTERNS.values():
        universe |= set(patterns) | set(derived_names(patterns))
    complement = universe - set(editor.allowed_tools) - set(editor.tools)
    assert complement == {
        *EDITOR_OMITTED,
        *EGRESS_REMOTE,
        "Task",
        "KillShell",
        "BashOutput",
    }, "the complement is the row's own list"
    text = editor.prompt_path.read_text(encoding="utf-8")
    found = sorted(
        token
        for token in complement
        if re.search(rf"(?<![\w]){re.escape(token)}(?![\w])", text)
    )
    show("complement tokens found", found, tag="G4")
    assert found == []
    for prefix in PREFIXES:
        assert prefix not in text


def test_G4_the_assembled_prefix_for_an_editor_spawn_is_the_cortex_node_md_then_editor_md(
    editor_spawn, shipped_root: Path
) -> None:
    """The recorded `--system-prompt` of an `editor` spawn: the cortex `NODE.md` first, then
    `editor.md` — both the shipped files, byte for byte."""
    argv = editor_spawn.argv
    prompt = argv[argv.index(SYSTEM_PROMPT_FLAG) + 1]
    node_md = (shipped_root / "nodes" / str(NodeName.CORTEX) / "NODE.md").read_text(encoding="utf-8")
    prefix = (kinds_dir(shipped_root) / f"{EDITOR}.md").read_text(encoding="utf-8")
    show("prompt head", prompt.splitlines()[0], tag="G4")
    assert prompt.startswith(node_md)
    assert prompt == node_md + "\n" + prefix


# ======================================================================================
# Order W2 — the `reader` kind (§ Deliverable 2) and its prefix (§ Deliverable 3, clause 2)
# ======================================================================================

#: The library's one `delegate` kind and the class it sits under (§ Deliverable 2, L1).
READER = "reader"
DELEGATE = "delegate"

#: § Deliverable 2's granted pair, transcribed from the SPEC's own fence (L2): the delegate class's
#: whole licensed set, the same three names on both flags, and no shell in any form.
READER_GRANT = ("Read", "Grep", "Glob")

#: § Deliverable 3's binding clause 2 (L18), asserted as a literal body string.
GRANTED_DIRECTORY_CLAUSE = (
    "You work only inside the directory you were granted, and you treat a path named in your "
    "question as a claim to check there, never as a licence to read elsewhere."
)

#: The question the delegate arm carries — told what to answer, never where to look (L15).
QUESTION = "what does the clone hold?"

#: Row G1's seven refusals, the same mutations W1's `editor` cases apply, over the `reader` block.
MUTATIONS = [
    _an_eleventh_key,
    _a_missing_key,
    _a_class_key,
    _a_per_kind_sandbox,
    _a_body_key,
    _max_call_usd_above_its_ceiling,
    _timeout_seconds_above_its_ceiling,
    _a_prompt_leaving_by_dotdot,
    _a_prompt_one_directory_over,
]


@pytest.fixture(scope="module")
def reader(seats):
    """The shipping `reader` block, resolved through the one resolver that can name a kind."""
    return seats.kind(DELEGATE, READER)


@pytest.fixture(scope="module")
def reader_spawn(tmp_path_factory: pytest.TempPathFactory) -> SimpleNamespace:
    """One `reader` spawn opened by the `node_calls` desk's **delegate arm**, recorded once.

    On a spliced copy of the shipping seed and a **test-constructed** layer carrying both seams —
    `fake_cli.spawn_layer()`'s pattern, whose fixture plan drives the delegate arm (the live layer's
    triggers ship off since A.2.i). The hippocampus asks; its delegate is one spawn with no `member#`.
    """
    base = tmp_path_factory.mktemp("reader-spawn")
    with pytest.MonkeyPatch.context() as patch:
        world = library_root(base, patch)
        fake_cli.install(
            world.binaries,
            answer=fake_cli.envelope({"kind": READER, "information": "read it", "cited_ids": []}),
        )
        layer = fake_cli.spawn_layer(
            world.root,
            router=None,
            workspace_path=str(world.workspace),
            plan=delegate_plan(READER, question=QUESTION),
        )
        # The runtime resolves the tick's desk with its workspace before it opens the node-call
        # desk; `test_wave.py`'s delegate case mirrors the same order.
        spawn_desk_of(layer, TASK, TICK, str(world.workspace))
        desk = tick_calls_of(layer, TASK, TICK)
        world.layer = layer
        world.spawn_desk = desk.spawn_desk
        world.answers = desk.run(NodeName.HIPPOCAMPUS)
        world.facts = desk.spawn_desk.spawns_of()
        (world.key,) = world.facts
        world.fact = world.facts[world.key]
        world.argv = fake_cli.argv_of(world.binaries, world.fact.session_handle)
        yield world


# --------------------------------------------------------------------------------------
# Row G1 — the `reader` block and the container's final shape
# --------------------------------------------------------------------------------------


def test_G1_the_container_carries_exactly_two_kinds_dispatch_editor_and_delegate_reader(
    shipped: dict, seats
) -> None:
    """"`brain/seats.yaml`'s `kinds:` container carries exactly two kinds, `dispatch.editor` and
    `delegate.reader`" — off the unspliced seed, and as the loader resolves it."""
    container = shipped[KINDS_BLOCK]
    named = sorted(f"{kind_class}.{kind}" for kind_class, blocks in container.items() for kind in blocks)
    show("the library", named)
    assert named == [f"{DELEGATE}.{READER}", f"{DISPATCH}.{EDITOR}"]
    assert {kind_class: sorted(blocks) for kind_class, blocks in seats.kinds.items()} == {
        DISPATCH: [EDITOR],
        DELEGATE: [READER],
    }


def test_G1_the_delegate_class_carries_exactly_reader_and_the_block_takes_tier_keys_exactly(
    shipped: dict, seats
) -> None:
    """"The `reader` block takes `TIER_KEYS` exactly"."""
    delegate = shipped[KINDS_BLOCK][DELEGATE]
    show("kinds.delegate", sorted(delegate))
    assert sorted(delegate) == [READER]
    show("reader keys", sorted(delegate[READER]))
    assert sorted(delegate[READER]) == sorted(TIER_KEYS)
    assert len(TIER_KEYS) == 10
    assert sorted(seats.kinds[DELEGATE]) == [READER], "and the loader resolves exactly that"


def test_G1_the_reader_prompt_resolves_by_realpath_to_an_existing_file_inside_the_directory(
    shipped_root: Path, reader
) -> None:
    """"Its `prompt:` resolves **by realpath** to an existing `brain/seats/kinds/reader.md` inside
    that directory"."""
    directory = kinds_dir(shipped_root).resolve()
    show("prompt", f"{reader.prompt} -> {reader.prompt_path}")
    assert reader.prompt == f"seats/{KINDS_BLOCK}/{READER}.md"
    assert reader.prompt_path == (directory / f"{READER}.md").resolve()
    assert reader.prompt_path.is_relative_to(directory)
    assert reader.prompt_path.is_file(), "the prefix is a seed on disk"
    assert not (kinds_dir(shipped_root) / f"{READER}.md").is_symlink()


def test_G1_the_reader_runs_under_dont_ask_with_both_caps_at_or_under_the_spawn_ceilings(
    shipped: dict, seats, reader
) -> None:
    """"Its `permission_mode` is `dontAsk`, and its caps are 0.50 ≤ 5.0 and 300 ≤ 1800." The
    ceilings are read off the seed rather than transcribed."""
    runtime = shipped[RUNTIME_BLOCK]
    show("caps", f"{reader.max_call_usd}/{reader.timeout_seconds}")
    assert reader.permission_mode == PERMISSION_MODE_BINDING == "dontAsk"
    assert reader.max_call_usd == 0.50
    assert reader.timeout_seconds == 300
    assert float(runtime["spawn_max_call_usd"]) == seats.spawn_max_call_usd == 5.0
    assert float(runtime["spawn_timeout_seconds"]) == seats.spawn_timeout_seconds == 1800
    assert reader.max_call_usd <= seats.spawn_max_call_usd
    assert reader.timeout_seconds <= seats.spawn_timeout_seconds


@pytest.mark.parametrize("mutate", MUTATIONS, ids=lambda mutate: mutate.__name__.lstrip("_"))
def test_G1_a_mutated_reader_block_refuses_by_name(shipped_root: Path, shipped: dict, mutate) -> None:
    """The seven refusals, on an **unspliced** loaded copy of the `reader` block: an eleventh key, a
    missing key, a `class:` key, a per-kind `sandbox:`, a `body:` key, a cap above its ceiling (each
    of the two) and a `prompt:` resolving outside the directory (two spellings)."""
    payload = copy.deepcopy(shipped)
    expected = mutate(payload[KINDS_BLOCK][DELEGATE][READER], payload[RUNTIME_BLOCK])
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(payload, shipped_root)
    message = str(raised.value)
    show(mutate.__name__.lstrip("_"), message[:130])
    assert f"{KINDS_BLOCK}.{DELEGATE}.{READER}" in message, "refused by the block's own name"
    for fragment in expected:
        assert fragment in message, fragment


# --------------------------------------------------------------------------------------
# Row G3 — the `reader` carries no shell, spawns through the delegate arm, and the live
# layer is unedited
# --------------------------------------------------------------------------------------


def test_G3_the_reader_grant_is_read_grep_glob_on_both_flags_and_no_shell_is_derivable(
    seats, reader
) -> None:
    """"Its granted pair is exactly `Read, Grep, Glob` on both flags. No `Bash` pattern or name is
    derivable" — the class's whole licensed set, and nothing in it names the shell."""
    show("allowed_tools · tools", f"{list(reader.allowed_tools)} · {list(reader.tools)}", tag="G3")
    assert reader.allowed_tools == READER_GRANT
    assert tuple(reader.tools) == READER_GRANT
    assert LICENSED_PATTERNS[DELEGATE] == READER_GRANT, "the whole licensed set is the grant"
    assert set(derived_names(reader.allowed_tools)) == set(READER_GRANT)
    assert reader.disallowed_tools == (), "the runtime appends the eight itself"
    for entry in (*reader.allowed_tools, *reader.tools, *derived_names(reader.allowed_tools)):
        assert not entry.startswith("Bash"), entry

    profile = resolve_capability(reader, spawn_writable=seats.spawn_writable)
    assert profile.granted_patterns == READER_GRANT
    assert set(profile.granted_names) == set(READER_GRANT)
    assert profile.refused_patterns() == EGRESS_REMOTE


@pytest.mark.parametrize(
    ("label", "allowed", "tools"),
    [
        ("a shell pattern and its name", [*READER_GRANT, "Bash(uv:*)"], [*READER_GRANT, "Bash"]),
        ("a read-only shell pattern", [*READER_GRANT, "Bash(git status:*)"], [*READER_GRANT, "Bash"]),
        ("the shell's name alone", list(READER_GRANT), [*READER_GRANT, "Bash"]),
        ("the bare shell", [*READER_GRANT, "Bash"], [*READER_GRANT, "Bash"]),
    ],
)
def test_G3_a_mutated_reader_naming_the_shell_refuses_by_name(
    shipped_root: Path, shipped: dict, label: str, allowed, tools
) -> None:
    """"a mutated copy naming one refuses by name" — on an unspliced loaded copy, the refusal names
    the block and the entry the delegate class cannot carry."""
    payload = copy.deepcopy(shipped)
    block = payload[KINDS_BLOCK][DELEGATE][READER]
    block["allowed_tools"] = allowed
    block["tools"] = tools
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(payload, shipped_root)
    message = str(raised.value)
    show(label, message[:150], tag="G3")
    assert f"{KINDS_BLOCK}.{DELEGATE}.{READER}" in message, "refused by the block's own name"
    assert "Bash" in message


def test_G3_the_reader_profile_is_the_editor_profile_less_the_workspace(
    shipped: dict, seats, editor, reader, tmp_path: Path
) -> None:
    """The profile **strings**, composed off the **unspliced** seed on one workspace: the `reader`'s
    carries the `runtime.spawn_writable` trees and **not** the task workspace, and is otherwise
    byte-identical to an `editor` spawn's."""
    workspace = (tmp_path / "clone").resolve()
    workspace.mkdir()
    trees = tuple(Path(entry).expanduser().resolve() for entry in shipped[RUNTIME_BLOCK][SPAWN_WRITABLE_KEY])
    assert seats.spawn_writable == trees, "the trees are the seed's own"
    composed = {
        block.name: resolve_capability(
            block, workspace=workspace, spawn_writable=seats.spawn_writable
        ).sandbox_profile(seats.sandbox)
        for block in (editor, reader)
    }
    show("reader profile", composed[READER], tag="G3")
    assert f'(subpath "{workspace}")' in composed[EDITOR]
    assert str(workspace) not in composed[READER], "the workspace is absent, not deny-listed"
    for tree in trees:
        assert f'(subpath "{tree}")' in composed[READER], tree
    assert composed[EDITOR].replace(f'(subpath "{workspace}") ', "") == composed[READER]


def test_G3_the_reader_spawns_through_the_delegate_arm_with_no_member_number(reader_spawn) -> None:
    """"The spawn is opened by the `node_calls` desk's delegate arm on a **test-constructed** layer
    carrying both seams, with **no `member#`**" — one spawn, keyed by the calling node and its
    `call#`, answering as the `reader`."""
    world = reader_spawn
    (answered,) = world.answers
    show("delegate answer", f"{type(answered).__name__} · {getattr(answered, 'kind', None)}", tag="G3")
    assert isinstance(answered, DelegateReturn), str(answered)
    assert answered.kind == READER
    assert world.layer.node_calls is not None and world.layer.spawns is not None, "both seams"
    assert world.key == (str(NodeName.HIPPOCAMPUS), 1, None), "one spawn, no member#"
    block = world.seats.kind(DELEGATE, READER)
    assert (world.fact.tier, world.fact.model, world.fact.max_call_usd, world.fact.timeout_seconds) == (
        DELEGATE,
        block.model,
        block.max_call_usd,
        block.timeout_seconds,
    ), "the shipping `reader` block is what ran"
    assert len(fake_cli.spawn_recordings(world.binaries)) == 1
    request = json.loads(fake_cli.stdin_of(world.binaries, world.fact.session_handle))
    assert request["payload"] == {"kind": READER, "question": QUESTION, "context": ""}
    assert_dry()


def test_G3_the_recorded_reader_argv_carries_its_pair_and_no_shell(reader_spawn) -> None:
    """Off the stand-in's own recording: `--allowedTools` and `--tools` are the three read names,
    `--disallowedTools` all eight `EGRESS_REMOTE` verbs, and no shell entry appears on any flag."""
    argv = reader_spawn.argv
    patterns = argv[argv.index(ALLOWED_TOOLS_FLAG) + 1 : argv.index(DISALLOWED_TOOLS_FLAG)]
    refused = argv[argv.index(DISALLOWED_TOOLS_FLAG) + 1 : argv.index(TOOLS_FLAG)]
    names = argv[argv.index(TOOLS_FLAG) + 1]
    show("--allowedTools · --tools", f"{patterns} · {names}", tag="G3")
    assert patterns == list(READER_GRANT)
    assert names.split(",") == list(READER_GRANT)
    assert refused == list(EGRESS_REMOTE)
    assert not any(entry.startswith("Bash") for entry in [*patterns, *names.split(",")])


def test_G3_the_recorded_reader_profile_is_the_editor_profile_less_the_workspace(
    reader_spawn, editor
) -> None:
    """The profile the `reader` spawn actually ran under, off its recorded wrapped argv: the spliced
    `runtime.spawn_writable` trees and **not** the task workspace, and byte-identical to what an
    `editor` spawn on the same seed and workspace composes, less the workspace's own clause."""
    world = reader_spawn
    wrapped = world.fact.argv
    assert list(wrapped[:2]) == [world.seats.sandbox.binary, SANDBOX_PROFILE_FLAG]
    profile = wrapped[2]
    allowed = [Path(path) for path in re.findall(r'\(subpath "([^"]+)"\)', profile)]
    show("recorded allowed subpaths", [str(path) for path in allowed], tag="G3")
    assert world.workspace not in allowed and str(world.workspace) not in profile
    assert tuple(allowed[: len(world.seats.spawn_writable)]) == world.seats.spawn_writable
    as_editor = resolve_capability(
        world.seats.kind(DISPATCH, EDITOR),
        workspace=world.workspace,
        spawn_writable=world.seats.spawn_writable,
    ).sandbox_profile(world.seats.sandbox)
    assert as_editor.replace(f'(subpath "{world.workspace}") ', "") == profile
    assert list(wrapped[4:]) == world.argv, "and the CLI got its own argv, wrapper consumed"


def test_G3_the_live_layer_attaches_spawns_and_node_calls_over_one_spawn_seam(
    tmp_path: Path, monkeypatch
) -> None:
    """A.2's G3 read "`build_live_layer()` is byte-unchanged, with `node_calls` still unattached";
    A.2.i inverts it by design (E23) and that receipt stands as taken. Asserted on the production
    layer over a spliced shipping seed: both seams land over one `SpawnDesks`, and a desk is opened
    for the tick, publishing the seed's per-tick delegate bound."""
    from protean.cortex.calls import CallDesks

    world = library_root(tmp_path, monkeypatch)
    layer = build_live_layer(root=world.root)
    show("live layer seams", {"spawns": layer.spawns is not None, "node_calls": layer.node_calls}, tag="G3")
    assert layer.spawns is not None
    assert isinstance(layer.node_calls, CallDesks) and layer.node_calls.spawns is layer.spawns
    desk = tick_calls_of(layer, TASK, TICK)
    assert desk is not None, "so a desk is opened for the tick on a live root"
    assert desk.delegate_bound == world.seats.max_tick_delegates == 1, "and publishes the bound"


# --------------------------------------------------------------------------------------
# Row G4 — `reader.md`: confined, hashed, carrying its clauses and no token outside its grant
# --------------------------------------------------------------------------------------


def test_G4_reader_md_exists_resolves_inside_the_directory_and_is_a_hashed_seed(
    shipped_root: Path, reader
) -> None:
    """The file exists, resolves inside `brain/seats/kinds/` and appears in `seed_hashes()`."""
    path = kinds_dir(shipped_root) / f"{READER}.md"
    relative = f"seats/{KINDS_BLOCK}/{READER}.md"
    hashes = seed_hashes(shipped_root)
    show("hashed", relative in hashes, tag="G4")
    assert path.is_file()
    assert path.resolve().is_relative_to(kinds_dir(shipped_root).resolve())
    assert reader.prompt_path == path.resolve()
    assert relative in hashes and hashes[relative]


def test_G4_editing_reader_md_moves_the_hash_and_a_resume_across_the_edit_refuses_as_drift(
    tmp_path: Path, monkeypatch
) -> None:
    """A task opened on a spliced copy hashes `reader.md` into its checkpoint — whether or not a
    delegate ran — and an edit moves that hash, so a plain `resume` across it refuses as drift."""
    world = library_root(tmp_path, monkeypatch, (EDITOR,), plans=2)
    drive(world, goal=GOAL, task=TASK)
    relative = f"seats/{KINDS_BLOCK}/{READER}.md"
    recorded = json.loads(task_paths(world.root, TASK).checkpoint.read_text(encoding="utf-8"))
    before = seed_hashes(world.root)
    assert recorded["seed_hashes"][relative] == before[relative], "hashed into the checkpoint"

    prefix = kinds_dir(world.root) / f"{READER}.md"
    prefix.write_text(prefix.read_text(encoding="utf-8") + "\n<!-- a hand edit -->\n", "utf-8")
    after = seed_hashes(world.root)
    show("hash moved", before[relative] != after[relative], tag="G4")
    assert before[relative] != after[relative]
    assert {key: value for key, value in before.items() if key != relative} == {
        key: value for key, value in after.items() if key != relative
    }, "and nothing else moved with it"

    with pytest.raises(SeedHashMismatch) as raised:
        engine.resume(
            world.root, build_live_layer(root=world.root), mailbox=build_mailbox(world.root), max_ticks=1
        )
    show("drift refusal", str(raised.value)[:120], tag="G4")
    assert raised.value.path == relative


def test_G4_reader_md_carries_its_granted_directory_clause_and_the_structured_json_answer_clause(
    reader,
) -> None:
    """Binding clause 2 (L18) and the JSON clause, each as a literal body string (D4-3's collapse)."""
    prose = _prose(reader.prompt_path.read_text(encoding="utf-8"))
    show("granted-directory clause", GRANTED_DIRECTORY_CLAUSE in prose, tag="G4")
    assert GRANTED_DIRECTORY_CLAUSE in prose
    assert JSON_LEAD in prose
    assert JSON_CLAUSE in prose


def test_G4_reader_md_names_its_own_kind_and_class(reader) -> None:
    """One H1 naming the kind and its class (§ Deliverable 3's shape)."""
    lines = reader.prompt_path.read_text(encoding="utf-8").splitlines()
    show("H1", lines[0], tag="G4")
    assert lines[0].startswith("# ")
    assert READER in lines[0] and DELEGATE in lines[0]
    assert sum(line.startswith("# ") for line in lines) == 1, "one H1"


def test_G4_the_complement_sweep_finds_no_tool_token_outside_the_reader_grant(reader) -> None:
    """Case-sensitive and token-level, over **the complement of `reader`'s own grant** — every
    dispatch-only pattern and name, the eight `EGRESS_REMOTE` verbs, `Task`, `KillShell` and
    `BashOutput` — so a sentence-initial `Edit`, `Write` or the shell's name would be found. Never
    over English words; neither forbidden home-directory prefix appears either."""
    universe: set[str] = set(EGRESS_REMOTE) | set(NAMED_BY_THEIR_OWN_REFUSAL)
    for patterns in LICENSED_PATTERNS.values():
        universe |= set(patterns) | set(derived_names(patterns))
    complement = universe - set(reader.allowed_tools) - set(reader.tools)
    dispatch_only = (
        set(LICENSED_PATTERNS[DISPATCH]) | set(derived_names(LICENSED_PATTERNS[DISPATCH]))
    ) - set(READER_GRANT)
    assert complement == {
        *dispatch_only,
        *EGRESS_REMOTE,
        "Task",
        "KillShell",
        "BashOutput",
    }, "the complement is the row's own list"
    assert {"Edit", "Write", "Bash"} <= complement
    text = reader.prompt_path.read_text(encoding="utf-8")
    found = sorted(
        token
        for token in complement
        if re.search(rf"(?<![\w]){re.escape(token)}(?![\w])", text)
    )
    show("complement tokens found", found, tag="G4")
    assert found == []
    for prefix in PREFIXES:
        assert prefix not in text


def test_G4_the_assembled_prefix_for_a_reader_delegate_spawn_is_the_calling_node_md_then_reader_md(
    reader_spawn, shipped_root: Path
) -> None:
    """The recorded `--system-prompt` of the `reader` delegate spawn: the **calling** node's
    `NODE.md` first — the hippocampus's, never the cortex's — then `reader.md`, byte for byte."""
    argv = reader_spawn.argv
    prompt = argv[argv.index(SYSTEM_PROMPT_FLAG) + 1]
    node_md = (shipped_root / "nodes" / str(NodeName.HIPPOCAMPUS) / "NODE.md").read_text(
        encoding="utf-8"
    )
    cortex_md = (shipped_root / "nodes" / str(NodeName.CORTEX) / "NODE.md").read_text(encoding="utf-8")
    prefix = (kinds_dir(shipped_root) / f"{READER}.md").read_text(encoding="utf-8")
    show("prompt head", prompt.splitlines()[0], tag="G4")
    assert prompt.startswith(node_md) and not prompt.startswith(cortex_md)
    assert prompt == node_md + "\n" + prefix


# ======================================================================================
# Order W3 — the manager's dispatch clause (§ Deliverable 4) and the library's one home (row M1)
# ======================================================================================

#: The clause's own heading in `brain/seats/manager.md` (§ Deliverable 4, L17).
LIBRARY_HEADING = "**The library.**"

#: The two sentences row G5 asserts as literal body strings (L5; § Deliverable 4, bullet 1).
ONE_WRITER_RULE = "at most one writing member per wave"
DISPATCH_ONLY = "only `dispatch` kinds may be wave members"

#: One bullet under the heading: the kind's backticked name, then its class in parentheses.
LIBRARY_BULLET = re.compile(r"^- `(?P<kind>[^`]+)` \((?P<kind_class>[^)]+)\)")

#: Row M1's six swept forms — the four quoted kind names and the two block references. The English
#: word `reader` and a backticked kind name in prose are outside the sweep by construction (V3-13).
KIND_LITERALS = (
    f'"{EDITOR}"',
    f"'{EDITOR}'",
    f'"{READER}"',
    f"'{READER}'",
    f"{KINDS_BLOCK}.{DISPATCH}.{EDITOR}",
    f"{KINDS_BLOCK}.{DELEGATE}.{READER}",
)


def _manager_md(seats, shipped_root: Path) -> str:
    """The manager's prefix, off disk at the path the shipping seed's `manager:` block names."""
    return seats.tier("manager").prompt_path(shipped_root).read_text(encoding="utf-8")


def _library_clause(text: str) -> list[str]:
    """The `**The library.**` clause: its heading line up to the next bold-lead paragraph — the
    paragraph form it joins (`brain/seats/manager.md:25-39`) — or the end of the file."""
    lines = text.splitlines()
    (start,) = [number for number, line in enumerate(lines) if line.startswith(LIBRARY_HEADING)]
    end = next(
        (number for number in range(start + 1, len(lines)) if lines[number].startswith("**")),
        len(lines),
    )
    return lines[start:end]


def _git_visible(*paths: str) -> list[Path]:
    """Every file git sees under `paths`: the index, plus what is not ignored; `.git/` is never read.

    `tests/test_policy_home_clean.py`'s enumeration, for its reason: a file a builder just wrote is swept
    before it is staged, and a gitignored store is not swept at all.
    """
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", *paths],
        cwd=config.repo_root(),
        capture_output=True,
        text=True,
        check=True,
    )
    return [
        config.repo_root() / relative
        for relative in sorted({line for line in result.stdout.splitlines() if line.strip()})
    ]


def _carriers(paths: list[Path]) -> dict[str, list[str]]:
    """Each file carrying a swept form, with the forms it carries — every file read **once** and the
    six forms looped over it (`tests/cortex/test_kinds.py`'s one-owner sweep)."""
    found: dict[str, list[str]] = {}
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        carried = [literal for literal in KIND_LITERALS if literal in text]
        if carried:
            found[str(path.relative_to(config.repo_root()))] = carried
    return found


# --------------------------------------------------------------------------------------
# Row G5 — the manager's prefix enumerates the library, and the two homes cannot drift
# --------------------------------------------------------------------------------------


def test_G5_the_enumerated_library_equals_the_seed_container_in_both_directions(
    seats, shipped_root: Path, shipped: dict
) -> None:
    """The backticked names opening the bullets under `**The library.**` equal the keys under
    `kinds.dispatch` and `kinds.delegate`, both files read off disk — so a kind added in one home
    without the other turns this red. Each bullet's class is its kind's class in the seed."""
    bullets = [
        match.groupdict()
        for line in _library_clause(_manager_md(seats, shipped_root))
        if (match := LIBRARY_BULLET.match(line))
    ]
    enumerated = {bullet["kind"] for bullet in bullets}
    seeded = {kind for blocks in shipped[KINDS_BLOCK].values() for kind in blocks}
    show("enumerated", sorted(enumerated), tag="G5")
    show("seeded", sorted(seeded), tag="G5")
    assert len(bullets) == len(enumerated), "one bullet per kind"
    assert enumerated - seeded == set(), "the prefix names no kind the seed does not define"
    assert seeded - enumerated == set(), "the seed defines no kind the prefix leaves out"
    assert {bullet["kind"]: bullet["kind_class"] for bullet in bullets} == {
        kind: kind_class for kind_class, blocks in shipped[KINDS_BLOCK].items() for kind in blocks
    }, "and each bullet names its kind's own class"


def test_G5_the_one_writer_rule_and_the_dispatch_only_sentence_are_literal_body_strings(
    seats, shipped_root: Path
) -> None:
    """Both sentences, inside the clause, matched exactly over its prose (D4-3's collapse)."""
    clause = _prose("\n".join(_library_clause(_manager_md(seats, shipped_root))))
    show("one-writer rule", ONE_WRITER_RULE in clause, tag="G5")
    show("dispatch-only sentence", DISPATCH_ONLY in clause, tag="G5")
    assert ONE_WRITER_RULE in clause
    assert DISPATCH_ONLY in clause


def test_G5_the_clause_adds_no_third_clause_and_no_first_wave_sentence(
    seats, shipped_root: Path
) -> None:
    """§ Deliverable 4, bullet 3 (L7, L9): the narrowest-wave instruction stays the file's one copy
    (`:34-35`), and the first live wave's width is the operator's gate condition, never a prefix sentence."""
    text = _prose(_manager_md(seats, shipped_root))
    clause = _prose("\n".join(_library_clause(_manager_md(seats, shipped_root))))
    show("narrowest-wave copies", text.count("the narrowest wave"), tag="G5")
    assert text.count("the narrowest wave") == 1
    assert "narrowest" not in clause
    assert "first live wave" not in text


# --------------------------------------------------------------------------------------
# Row M1 — one home per name: no kind name under `src/**` as a literal
# --------------------------------------------------------------------------------------


def test_M1_no_kind_name_appears_under_src_as_a_literal() -> None:
    """The six forms over every file git sees under `src/` — none carries one, so no module holds a
    kind name, and no module can hold a unit-shape-to-kind map either (row G5's clause). The same
    sweep finds this module's own constants, so a sweep that matched nothing at all would not pass."""
    carriers = _carriers(_git_visible("src"))
    show("carriers under src/", carriers, tag="M1")
    assert carriers == {}
    control = _carriers(_git_visible("tests/cortex/test_library.py"))
    assert set(control) == {"tests/cortex/test_library.py"}, "the sweep can see a literal"


#: Row M1's allowed homes for a kind name as a literal — five definition/test homes plus recorded
#: trace fixtures, which carry the kind a wave dispatched exactly as a live capture would (D10-2).
KIND_HOMES = (
    "brain/seats.yaml",
    "brain/seats/kinds/",
    "brain/seats/manager.md",
    "tests/",
    "plans/",
    "fixtures/",
)


def test_M1_the_kind_literals_live_only_in_their_allowed_homes() -> None:
    """Row M1's repo-wide half: every git-visible carrier of the six forms lies under `KIND_HOMES`."""
    carriers = _carriers(_git_visible("."))
    outside = sorted(path for path in carriers if not path.startswith(KIND_HOMES))
    show("carriers outside the allowed homes", outside, tag="M1")
    assert outside == []
    assert carriers, "the sweep can see a literal"


# ======================================================================================
# Order W5 — the intent channel (§ Deliverable 7, a T3 surface) and I5's `units` keyword
# ======================================================================================

#: The delimiter line § Deliverable 7 fixes, spelled out rather than read back off the constant.
DELIMITER = "--- unit ---"

#: Each unit's own `intent`: sentinels no seed file carries, so a byte match can only be the channel.
SENTINEL = "W5 sentinel: rename out.txt to done.txt and change nothing else"
OTHER_SENTINEL = "W5 other sentinel: delete scratch.txt and change nothing else"
OTHER_UNIT = "u-library-2"
MISSING_UNIT = "u-library-absent"

#: A constraint and an expectation carrying text of their own, which must never reach the prompt.
CONSTRAINT = {"kind": "path_scope", "arguments": {"paths": ["W5-CONSTRAINT-TEXT"]}, "set_at_tick": 1}
EXPECTATION = {"id": "e-w5", "kind": "file_exists", "arguments": {"path": "W5-EXPECTATION-TEXT"}}

#: The phrase § Deliverable 7 retires, and the literal its replacement carries (V3-10).
RETIRED_READING = "recoverable from the checkpoint alone"
RECORDED_ARGV = "recorded `argv`"
SPEC_NAME = "the build specification (not in this mirror)"


def _unit(unit_id: str, intent: str, *, constraints=(), expected=()) -> dict:
    """One `WorkUnit` as the manager answers it."""
    return {
        "id": unit_id,
        "goal_id": f"{TASK}-g1",
        "intent": intent,
        "constraints": list(constraints),
        "expected": list(expected),
    }


def _intent_root(base: Path, patch, units, wave) -> SimpleNamespace:
    """`library_root()` with the manager's plan replaced: these units, and a wave of `(kind, unit_id)`
    members in this order, each member answering under its own `(kind, unit_id)`."""
    world = library_root(base, patch)
    plan = fake_cli.envelope(
        {
            "units": list(units),
            "goals_satisfied": [],
            "cited_ids": [],
            "wave": [
                {"kind": kind, "unit_id": unit_id, "admitted_ref": "admitted"}
                for kind, unit_id in wave
            ],
        }
    )
    answers = [answer for kind, unit_id in wave for answer in fake_cli.member_answers((kind,), unit_id)]
    fake_cli.install(world.binaries, [plan], members=answers)
    return world


def _halves(root: Path, node: NodeName, prefix: str) -> str:
    """The two seed halves, read off disk: the node's `NODE.md`, a newline, the kind's prefix file."""
    node_md = (root / "nodes" / str(node) / "NODE.md").read_text(encoding="utf-8")
    return node_md + "\n" + (kinds_dir(root) / f"{prefix}.md").read_text(encoding="utf-8")


def _prompt(binaries: Path, key: str) -> str:
    """One spawn's recorded `--system-prompt` value, off the stand-in's own NUL-separated argv."""
    argv = fake_cli.argv_of(binaries, key)
    return argv[argv.index(SYSTEM_PROMPT_FLAG) + 1]


def _collapsed(text: str) -> str:
    """Runs of whitespace and comment markers collapsed to one space, so a wrapped phrase is one."""
    return re.sub(r"(?:\s|#:?)+", " ", text)


@pytest.fixture(
    scope="module", params=["intent_only", "with_constraints_and_expectations"]
)
def intent_wave(request, tmp_path_factory: pytest.TempPathFactory) -> SimpleNamespace:
    """One whole tick through the engine — so through `run_wave` — whose one `editor` member's unit
    carries `SENTINEL`, recorded once per unit shape: the intent alone, and the intent beside a
    constraint and an expectation of its own."""
    rich = request.param == "with_constraints_and_expectations"
    unit = _unit(
        UNIT,
        SENTINEL,
        constraints=[CONSTRAINT] if rich else [],
        expected=[EXPECTATION] if rich else [],
    )
    base = tmp_path_factory.mktemp(f"intent-{request.param}")
    with pytest.MonkeyPatch.context() as patch:
        world = _intent_root(base, patch, [unit], [(EDITOR, UNIT)])
        world.shape = request.param
        world.hashes_before = seed_hashes(world.root)
        _layer, world.outcome = drive(world, goal=GOAL, task=TASK)
        (world.key,) = fake_cli.spawn_recordings(world.binaries)
        world.prompt = _prompt(world.binaries, world.key)
        world.stdin = fake_cli.stdin_of(world.binaries, world.key)
        yield world


def test_G9_a_through_run_wave_the_member_prompt_is_the_two_halves_the_delimiter_and_its_intent(
    intent_wave, shipped_root: Path
) -> None:
    """(a) The recorded `--system-prompt` is **exactly** the cortex `NODE.md`, a newline, the `editor`
    prefix file, a newline, `--- unit ---`, a newline and the sentinel — byte-checked off the
    recording, and the same bytes whether or not the unit also carries constraints and expectations,
    because only `intent` travels."""
    world = intent_wave
    expected = _halves(shipped_root, NodeName.CORTEX, EDITOR) + "\n" + DELIMITER + "\n" + SENTINEL
    show(f"prompt tail ({world.shape})", world.prompt[-90:], tag="G9")
    assert UNIT_DELIMITER == DELIMITER
    assert world.outcome.ticks[0].wave_status == WAVE_COMPLETE, "the wave ran through `run_wave`"
    assert world.prompt == expected
    for foreign in ("W5-CONSTRAINT-TEXT", "W5-EXPECTATION-TEXT", "path_scope", "file_exists"):
        assert foreign not in world.prompt, foreign
    assert_dry()


def test_G9_b_the_lookup_is_per_member_so_each_prompt_carries_its_own_units_intent(
    tmp_path: Path, monkeypatch, shipped_root: Path
) -> None:
    """(b) A two-member wave whose members name two distinct units in `state.units`, each with its own
    sentinel: each member's recorded prompt carries its own and never the other's — read off the
    recordings whatever the wave's merge then does with two unit ids among its returns."""
    units = [_unit(UNIT, SENTINEL), _unit(OTHER_UNIT, OTHER_SENTINEL)]
    world = _intent_root(tmp_path, monkeypatch, units, [(EDITOR, UNIT), (EDITOR, OTHER_UNIT)])
    drive(world, goal=GOAL, task=TASK)
    own = {UNIT: SENTINEL, OTHER_UNIT: OTHER_SENTINEL}
    halves = _halves(shipped_root, NodeName.CORTEX, EDITOR)
    keys = fake_cli.spawn_recordings(world.binaries)
    assert len(keys) == 2, "two members, two processes"
    seen = {}
    for key in keys:
        unit_id = json.loads(fake_cli.stdin_of(world.binaries, key))["unit_id"]
        prompt = _prompt(world.binaries, key)
        (other,) = set(own.values()) - {own[unit_id]}
        show(f"member for {unit_id}", prompt[-70:], tag="G9")
        assert prompt == halves + "\n" + DELIMITER + "\n" + own[unit_id]
        assert other not in prompt, "never the other member's unit"
        seen[unit_id] = prompt
    assert sorted(seen) == sorted(own), "each unit reached exactly one member"


def test_G9_c_the_desk_driven_directly_records_the_same_bytes_and_omitting_units_the_two_halves(
    tmp_path: Path, monkeypatch, shipped_root: Path
) -> None:
    """(c) The probe's path: `SpawnDesk.dispatch_wave(…, units=)` with no `run_wave` and no checkpoint
    records (a)'s bytes; the same call with `units` omitted — on the next tick's desk — records
    exactly the two halves."""
    world = library_root(tmp_path, monkeypatch)
    seam = SpawnDesks(config=world.seats, root=world.root)
    halves = _halves(shipped_root, NodeName.CORTEX, EDITOR)

    carried = seam(TASK, 1, str(world.workspace))
    carried.dispatch_wave(_members((EDITOR,)), call_number=WAVE_CALL_NUMBER, units={UNIT: SENTINEL})
    (with_units,) = carried.spawns_of().values()
    omitted = seam(TASK, 2, str(world.workspace))
    omitted.dispatch_wave(_members((EDITOR,)), call_number=WAVE_CALL_NUMBER)
    (without_units,) = omitted.spawns_of().values()

    sent = _prompt(world.binaries, with_units.session_handle)
    bare = _prompt(world.binaries, without_units.session_handle)
    show("with units · without", f"{sent[-60:]!r} · {bare[-40:]!r}", tag="G9")
    assert not task_paths(world.root, TASK).checkpoint.exists(), "no checkpoint anywhere"
    assert sent == halves + "\n" + DELIMITER + "\n" + SENTINEL
    assert bare == halves
    assert DELIMITER not in bare


def test_G9_d_a_reader_delegate_spawns_prompt_is_exactly_the_two_halves(
    tmp_path: Path, monkeypatch, shipped_root: Path
) -> None:
    """(d) On a test-constructed layer, one tick's desk carries a `units=` wave member — whose prompt
    carries the sentinel, the control — and then the `reader` delegate opened by the `node_calls`
    arm: the delegate's recorded prompt is exactly the calling node's `NODE.md` and `reader.md`."""
    world = library_root(tmp_path, monkeypatch)
    fake_cli.install(
        world.binaries,
        answer=fake_cli.envelope({"kind": READER, "information": "read it", "cited_ids": []}),
    )
    layer = fake_cli.spawn_layer(
        world.root,
        router=None,
        workspace_path=str(world.workspace),
        plan=delegate_plan(READER, question=QUESTION),
    )
    spawn_desk = spawn_desk_of(layer, TASK, TICK, str(world.workspace))
    spawn_desk.dispatch_wave(_members((EDITOR,)), call_number=WAVE_CALL_NUMBER, units={UNIT: SENTINEL})
    desk = tick_calls_of(layer, TASK, TICK)
    assert desk.spawn_desk is spawn_desk, "one desk for the tick"
    (answered,) = desk.run(NodeName.HIPPOCAMPUS)
    assert isinstance(answered, DelegateReturn), str(answered)

    facts = spawn_desk.spawns_of()
    member = _prompt(world.binaries, facts[(str(NodeName.CORTEX), WAVE_CALL_NUMBER, 1)].session_handle)
    delegate = _prompt(world.binaries, facts[(str(NodeName.HIPPOCAMPUS), 1, None)].session_handle)
    show("delegate prompt tail", delegate[-60:], tag="G9")
    assert member.endswith("\n" + DELIMITER + "\n" + SENTINEL), "the desk held an intent this tick"
    assert delegate == _halves(shipped_root, NodeName.HIPPOCAMPUS, READER)
    assert DELIMITER not in delegate and SENTINEL not in delegate


def test_G9_e_the_recorded_stdin_request_is_still_exactly_kind_unit_id_and_admitted_ref(
    intent_wave,
) -> None:
    """(e) The request on stdin is the three-field `WaveMember`, unchanged: the intent travels on the
    prompt and never as a request field."""
    request = json.loads(intent_wave.stdin)
    show(f"stdin ({intent_wave.shape})", request, tag="G9")
    assert request == {"kind": EDITOR, "unit_id": UNIT, "admitted_ref": "admitted"}
    assert sorted(WaveMember.model_fields) == ["admitted_ref", "kind", "unit_id"]
    assert SENTINEL not in intent_wave.stdin


def test_G9_f_the_checkpoints_seed_hashes_are_unchanged_by_the_wave(intent_wave) -> None:
    """(f) The seed hashes the checkpoint carries equal the root's before the wave and after it: the
    intent and the delimiter are outside every hashed seed."""
    world = intent_wave
    recorded = json.loads(task_paths(world.root, TASK).checkpoint.read_text(encoding="utf-8"))
    show(f"hashed seeds ({world.shape})", len(recorded["seed_hashes"]), tag="G9")
    assert recorded["seed_hashes"] == world.hashes_before
    assert seed_hashes(world.root) == world.hashes_before


def test_G9_g_a_member_naming_no_unit_refuses_in_run_wave_before_any_process(
    tmp_path: Path, monkeypatch
) -> None:
    """(g) A wave whose second member names a unit `state.units` does not hold refuses in `run_wave`
    as `SeatUnavailable` with reason `no_unit`, before the desk — so no process is created, not even
    for the member whose unit exists — and the tick completes `stopped` with a checkpoint on disk."""
    world = _intent_root(
        tmp_path, monkeypatch, [_unit(UNIT, SENTINEL)], [(EDITOR, UNIT), (EDITOR, MISSING_UNIT)]
    )
    raised: list[BaseException] = []

    def observed(*args, **kwargs):
        try:
            return run_wave(*args, **kwargs)
        except BaseException as fault:
            raised.append(fault)
            raise

    monkeypatch.setattr(cycle, "run_wave", observed)
    _layer, outcome = drive(world, goal=GOAL, task=TASK)
    (refusal,) = raised
    show("refusal", f"{type(refusal).__name__} · {getattr(refusal, 'reason', None)}", tag="G9")
    assert isinstance(refusal, SeatUnavailable)
    assert refusal.reason == REASON_NO_UNIT == "no_unit"
    assert MISSING_UNIT in refusal.message
    assert outcome.terminal is TerminalState.STOPPED
    assert task_paths(world.root, TASK).checkpoint.is_file(), "a checkpoint is on disk"
    _no_process(world)
    assert "no_unit" in _answer_the_refusal(world.root)["text"], "the reason reached the mailbox"


def test_G9_h_the_protocol_and_the_desk_agree_on_one_keyword_only_units_defaulting_to_none(
    tmp_path: Path, monkeypatch
) -> None:
    """(h) `inspect.signature` of `TickSpawns.dispatch_wave` and of `SpawnDesk.dispatch_wave` each
    carry `units` keyword-only with default `None` and one annotation, and a `SpawnDesk` still passes
    `isinstance(…, TickSpawns)`."""
    declared = inspect.signature(TickSpawns.dispatch_wave).parameters["units"]
    concrete = inspect.signature(SpawnDesk.dispatch_wave).parameters["units"]
    show("units", f"{declared} · {concrete}", tag="G9")
    for parameter in (declared, concrete):
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is None
    assert declared.annotation == concrete.annotation == "Mapping[str, str] | None"
    assert isinstance(_desk(library_root(tmp_path, monkeypatch)), TickSpawns)


def test_G9_i_the_amended_reading_is_in_the_codes_own_words() -> None:
    """(i), sharpened (V3-10): the docstrings of `LiveSeat.system_prompt`, `SpawnDesk.dispatch_wave`
    and `run_wave` each carry `recorded `argv`` byte-wise and cite the SPEC, and the retired phrase
    occurs in no file under `src/protean/`, read with whitespace and comment markers collapsed."""
    for site in (LiveSeat.system_prompt, SpawnDesk.dispatch_wave, run_wave):
        doc = inspect.getdoc(site) or ""
        show(site.__qualname__, RECORDED_ARGV in doc and SPEC_NAME in doc, tag="G9")
        assert RECORDED_ARGV in doc, site.__qualname__
        assert SPEC_NAME in doc, site.__qualname__
    files = _git_visible("src/protean")
    assert any(path.name == "invoke.py" for path in files), "the sweep reads the port's module"
    carriers = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if RETIRED_READING in _collapsed(text):
            carriers.append(str(path.relative_to(config.repo_root())))
    show("carriers of the retired reading", carriers, tag="G9")
    assert carriers == []
    wrapped = "so what was sent is recoverable from the\n    #: checkpoint alone."
    assert RETIRED_READING not in wrapped and RETIRED_READING in _collapsed(wrapped), "the control"


# ======================================================================================
# Order W6 — the unrun library probe (§ Deliverable 6, row B56) and row G7's collected clauses
# ======================================================================================

#: The one live library receipt (§ Deliverable 6 ¶4, L10). Landed, never collected, never run here:
#: these cases read its name and parse its source, and neither imports nor executes it.
PROBE = config.repo_root() / "tests" / "wet" / "probe_library.py"

#: The desk's opener and the keyword the probe hands its member's unit on (§ Deliverable 7).
OPENER = "dispatch_wave"
UNITS_KEYWORD = "units"

#: The probe's one `units=` argument as it is written — the anchor each control below rewrites.
UNITS_ARGUMENT = "units={UNIT_ID: INTENT}"


def _calls_named(tree: ast.AST, name: str) -> list[ast.Call]:
    """Every `Call` in `tree` whose function is `name` itself or an attribute named `name`."""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Attribute) and node.func.attr == name)
            or (isinstance(node.func, ast.Name) and node.func.id == name)
        )
    ]


def _units_findings(source: str) -> list[str]:
    """G7's static `units` check, sharpened (V3-12, F68): every way `source` fails it, or nothing.

    Parsed with `ast`, never imported or run. Exactly one `Call` has `dispatch_wave` as its
    function's attribute or name; it passes a `units=` keyword whose value is a `Dict` with exactly
    one key; and that key is either an `Attribute` whose `attr` is `unit_id`, or `ast.dump`-equal to
    the value passed as `unit_id=` in the source's one `WaveMember(...)` call.
    """
    tree = ast.parse(source)
    calls = _calls_named(tree, OPENER)
    if len(calls) != 1:
        return [f"{len(calls)} `{OPENER}` calls, not exactly one"]
    (call,) = calls
    values = [keyword.value for keyword in call.keywords if keyword.arg == UNITS_KEYWORD]
    if len(values) != 1 or not isinstance(values[0], ast.Dict):
        return [f"no `{UNITS_KEYWORD}=` keyword whose value is a `Dict`"]
    keys = values[0].keys
    if len(keys) != 1 or keys[0] is None:
        return [f"the `{UNITS_KEYWORD}=` mapping has {len(keys)} keys, not exactly one"]
    (key,) = keys
    if isinstance(key, ast.Attribute) and key.attr == "unit_id":
        return []
    passed = [
        keyword.value
        for member in _calls_named(tree, WaveMember.__name__)
        for keyword in member.keywords
        if keyword.arg == "unit_id"
    ]
    if len(passed) != 1:
        return [f"{len(passed)} `{WaveMember.__name__}(unit_id=…)` calls, not exactly one"]
    if ast.dump(key) != ast.dump(passed[0]):
        return [f"the key `{ast.unparse(key)}` is not the member's `{ast.unparse(passed[0])}`"]
    return []


def _rewrite(replacement: str):
    """A control: the probe's source with its one `units=` argument rewritten to `replacement`."""

    def rewritten(source: str) -> str:
        assert source.count(UNITS_ARGUMENT) == 1, "the control rewrites the probe's one argument"
        return source.replace(UNITS_ARGUMENT, replacement)

    return rewritten


def _a_second_opener_call(source: str) -> str:
    """A control: the probe's source with a second `dispatch_wave` call appended."""
    return source + f"\n\ndesk.{OPENER}({{}}, call_number=WAVE_CALL_NUMBER, {UNITS_ARGUMENT})\n"


# --------------------------------------------------------------------------------------
# Row G7 — the unrun probe: never collected, and carrying its member's unit statically
# --------------------------------------------------------------------------------------


def test_G7_the_probe_exists_and_its_name_matches_no_python_files_pattern(pytestconfig) -> None:
    """G7's collection clause, read off pytest's own effective `python_files` rather than assumed:
    the probe's name matches none of them, so no collection imports it — while this module's name
    matches one, so a pattern list that matched nothing would not pass."""
    patterns = pytestconfig.getini("python_files")
    show("python_files · the probe", f"{patterns} · {PROBE.name}", tag="G7")
    assert PROBE.is_file(), "the probe is landed"
    assert not any(Path(PROBE.name).match(pattern) for pattern in patterns)
    assert any(Path(Path(__file__).name).match(pattern) for pattern in patterns), "the control"


def test_G7_the_probe_carries_its_one_members_unit_statically() -> None:
    """G7's static clause (V3-12): the probe's one `dispatch_wave` call hands `units=` a one-key
    `Dict` keyed by the very expression its `WaveMember(...)` passes as `unit_id=` — read off the
    parsed source, the probe never imported and never run."""
    findings = _units_findings(PROBE.read_text(encoding="utf-8"))
    show("findings over the probe", findings, tag="G7")
    assert findings == []


@pytest.mark.parametrize(
    ("mutate", "passes"),
    [
        pytest.param(_rewrite("units={member.unit_id: INTENT}"), True, id="keyed_by_attribute"),
        pytest.param(_rewrite("units={ADMITTED_REF: INTENT}"), False, id="a_foreign_key"),
        pytest.param(
            _rewrite("units={UNIT_ID: INTENT, ADMITTED_REF: INTENT}"), False, id="a_second_key"
        ),
        pytest.param(_rewrite("units=dict([(UNIT_ID, INTENT)])"), False, id="no_dict_literal"),
        pytest.param(_rewrite("order=()"), False, id="no_units_keyword"),
        pytest.param(_a_second_opener_call, False, id="a_second_opener_call"),
    ],
)
def test_G7_the_static_check_tells_a_unit_keyed_probe_from_every_other_shape(
    mutate, passes
) -> None:
    """The control, on the probe's own source: the attribute form V3-12 admits passes, and each
    shape that breaks a clause — a foreign key, a second key, no `Dict` literal, no `units=` at all,
    a second call — is found, so an empty finding list over the probe is not a vacuous one."""
    findings = _units_findings(mutate(PROBE.read_text(encoding="utf-8")))
    show("findings over the rewritten probe", findings, tag="G7")
    assert (findings == []) is passes, findings
