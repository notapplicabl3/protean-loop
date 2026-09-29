"""The `kinds:` container as loaded, and everything outside a kind block's shape refusing by name.

`the build specification (not in this mirror)` § Deliverable 1 (seam contract **I1 `KindBlock`**),
§ Directional decisions 2, § Resolutions A1-3, A1-8, A1-13, § Deliverable R row R17. Order W1's
DoD row G1 — **its container half**: the `RUNTIME_KEYS` clause, the licensed capability sets, the
composed profile and the spawn itself are later orders' and are asserted nowhere here.

**The refusals are proven by mutating a loaded payload**, on `tests/cortex/test_live_config.py`'s
landed precedent, rather than by authoring a brain root per case (folded: S-i29). Two roots are
the exception, because their subject is the root rather than the document: the loadable pair under
`fixtures/calls/kinds/`, and the one whose `prompt:` names a file that is not there.

**The kinds this module loads are fixtures, never the library.** The two it loads —
`fixture_one` and `fixture_two` — name no work at all; the shipping seed now carries the library's
two kinds, `dispatch.editor` and `delegate.reader`, with their prefixes in `brain/seats/kinds/`
(`the build specification (not in this mirror)` § Deliverables 1–3), and `tests/cortex/test_library.py` is
where they are proven. The shipped-seed read-backs below keep A.1.i's receipts in inverted form.
"""

from __future__ import annotations

import copy
import inspect
import json
import os
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from protean import config
from protean.brain.folders import seed_hashes
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
from protean.cortex.live.kinds import (
    BASH,
    CLASS_KEY,
    EGRESS_REMOTE,
    KINDS_BLOCK,
    LICENSED_PATTERNS,
    NAMED_BY_THEIR_OWN_REFUSAL,
    SPAWN_PROCESS_ALLOWANCES,
    CapabilityProfile,
    KindBlock,
    derived_names,
    kinds_dir,
    licensed_names,
    licensed_patterns,
    parse_kinds,
    resolve_capability,
    spawn_allowance_literals,
    spawn_allowance_subpaths,
    tool_name,
)
from protean.runtime.seat import decode_seat_result
from protean.state.calls import BODY_TERMINAL
from protean.state.enums import CallType
from protean.state.seats import ExecutorSummary, SeatEnvelope
from tests.conftest import tagged_show
from tests.cortex import fake_cli

#: The two fixture kinds, one per class, as `fixtures/calls/kinds/two_kinds.yaml` spells them.
DISPATCH_KIND = "fixture_one"
DELEGATE_KIND = "fixture_two"

#: § Deliverable R row R17's third anchor, transcribed: the `body` note is kept **byte-identical**
#: to its pre-A.1.i text, deliberately — it is the sentence the landed walk already makes true of
#: `kinds:`, and row G1's two container-level cases are its receipt.
BODY_NOTE = """\
  # It applies to the TWO CORTEX SEATS ONLY. The two `calls:` blocks below and every subagent run
  # under `claude -p` whatever this says; tier three always does. A `body` key ANYWHERE ELSE in
  # this file — on a tier block, on a `calls:` block, on `oracle:`, or on anything build A.1.i
  # adds — is refused at load by name: a body selectable per call is a body that could differ per
  # call, which is the one thing "the body never changes the result" cannot survive.
"""

#: The two sentences R17 corrects. Neither may survive anywhere in the seed: both called the kind
#: block A.1.i's *future*, and the landed container is what makes them false.
FUTURE_SENTENCES = (
    "from a kind block build A.1.i defines",
    "its per-kind configuration is build A.1.i's",
)


#: Three spellings of the evidence printer stood in this module — `show` for row G1's container,
#: `floor` for row G2's positive grant and `kernel` for row G3's composed profile — differing in
#: nothing but the tag, so the tag is a keyword and the printer is `tests.conftest.show`.
show = tagged_show("G1")


@pytest.fixture()
def shipped_root() -> Path:
    """The tracked `brain/` — the shipping seed, which defines the library's two kinds."""
    return config.repo_root() / "brain"


@pytest.fixture()
def shipped(shipped_root: Path) -> dict:
    """The tracked `brain/seats.yaml` as a payload, for mutation."""
    return yaml.safe_load((shipped_root / "seats.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def kinds_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A fixture brain root whose container carries the two loadable kinds.

    Module-scoped: every consumer below either reads the root or mutates a `_payload()` **copy**
    of its `seats.yaml` and hands that to `parse_seats()`, so the tree on disk is an input and
    never an output. The three cases that do write into it — the two symlink cases and the hash
    case — take `mutable_kinds_root` instead.
    """
    return fake_cli.seed_kinds_root(tmp_path_factory.mktemp("kinds") / "brain")


@pytest.fixture()
def mutable_kinds_root(tmp_path: Path) -> Path:
    """The same root, per test, for the cases that write into the tree they then read back."""
    return fake_cli.seed_kinds_root(tmp_path / "brain")


@pytest.fixture()
def loaded(kinds_root: Path):
    """That root's `SeatsConfig`."""
    return fake_cli.seats_of(kinds_root)


def _payload(root: Path) -> dict:
    return yaml.safe_load((root / "seats.yaml").read_text(encoding="utf-8"))


def _refused(payload: dict, root: Path) -> str:
    """Parse a mutated payload, requiring a refusal, and answer what it said."""
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(payload, root)
    return str(raised.value)


# --------------------------------------------------------------------------------------
# The container, in the shipping seed
# --------------------------------------------------------------------------------------


def test_the_shipping_seed_carries_the_container_with_two_empty_sub_mappings(
    shipped_root: Path, shipped: dict
) -> None:
    """"each sub-mapping present and **empty in the shipping seed**" (row G1).

    The read-back row G1 asks for: the container is there and both classes are there. A.1.i
    defined no kind (§ Goal, row B48); A.2's library has landed since, so the receipt is kept in
    inverted form — each class holds exactly one kind, `dispatch` holds `editor` and `delegate`
    holds `reader` (`the build specification (not in this mirror)` § Deliverables 1–2, § Files it
    changes).
    """
    container = shipped[KINDS_BLOCK]
    show("the seed's container", container)
    assert set(container) == {"dispatch", "delegate"}
    assert set(container["dispatch"]) == {"editor"} and set(container["delegate"]) == {"reader"}

    seats = load_seats(shipped_root)
    assert seats is not None
    show("as loaded", {name: dict(block) for name, block in seats.kinds.items()})
    assert set(seats.kinds) == set(config.KIND_CLASSES)
    assert set(seats.kinds["dispatch"]) == {"editor"} and set(seats.kinds["delegate"]) == {"reader"}


def test_the_container_keys_equal_the_derived_class_set_in_either_spelling(
    shipped_root: Path, shipped: dict
) -> None:
    """Row **G1**: "keys **equal `config.KIND_CLASSES` as a SET**" — the order scopes the literal
    alone. Two halves of one sentence.

    The derivation, and the seed's spelling reversed: the shipping seed spells `dispatch:` first
    and the derivation produces `delegate` first, so the seed itself is the case that proves the
    comparison is a set comparison (folded: S-i52).

    Then both orders parse: a seed may spell the two sub-mappings in either order and each loads
    to the same set, which is what makes the set comparison a rule rather than a coincidence.
    """
    derived = tuple(
        name for name in config.CALL_TYPES if name not in config.CONFIGURED_CALL_TYPES
    )
    show("KIND_CLASSES", config.KIND_CLASSES)
    assert config.KIND_CLASSES == derived == ("delegate", "dispatch")
    assert list(shipped[KINDS_BLOCK]) == ["dispatch", "delegate"], "the seed's own spelling"
    assert list(shipped[KINDS_BLOCK]) != list(config.KIND_CLASSES), "and it is the other order"
    assert set(shipped[KINDS_BLOCK]) == set(config.KIND_CLASSES)

    for order in (["dispatch", "delegate"], ["delegate", "dispatch"]):
        payload = copy.deepcopy(shipped)
        payload[KINDS_BLOCK] = {name: {} for name in order}
        parsed = parse_seats(payload, shipped_root).kinds
        show(f"{order} loads", sorted(parsed))
        assert set(parsed) == set(config.KIND_CLASSES)


def test_the_prefix_directory_ships_a_gitkeep_and_no_kind_prefix(shipped_root: Path) -> None:
    """"`brain/seats/kinds/` holding only `.gitkeep`" (row G11 is W6's), read back after A.2's two
    prefixes landed beside it: `.gitkeep`, `editor.md` and `reader.md`
    (`the build specification (not in this mirror)` § Deliverable 3; `.gitkeep` is kept)."""
    directory = kinds_dir(shipped_root)
    entries = sorted(entry.name for entry in directory.iterdir())
    show("brain/seats/kinds/", entries)
    assert entries == [".gitkeep", "editor.md", "reader.md"]
    assert (directory / ".gitkeep").read_bytes() == b""


# --------------------------------------------------------------------------------------
# The container's own refusals
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("absent", [None, [], "kinds", 3])
def test_an_absent_kinds_container_refuses_by_name(
    shipped_root: Path, shipped: dict, absent
) -> None:
    """Eager like `calls:` and `sandbox:`: "a containment surface that is simply missing is a
    floor authored by omission" (§ Deliverable 1)."""
    payload = copy.deepcopy(shipped)
    del payload[KINDS_BLOCK]
    message = _refused(payload, shipped_root)
    show("no container", message[:88])
    assert f"`{KINDS_BLOCK}`" in message

    payload = copy.deepcopy(shipped)
    payload[KINDS_BLOCK] = absent
    assert f"`{KINDS_BLOCK}`" in _refused(payload, shipped_root)


@pytest.mark.parametrize("missing", list(config.KIND_CLASSES))
def test_a_container_missing_one_class_sub_mapping_refuses_by_name(
    shipped_root: Path, shipped: dict, missing: str
) -> None:
    """Both sub-mappings are present and **may** be empty; one that is absent is not the same."""
    payload = copy.deepcopy(shipped)
    del payload[KINDS_BLOCK][missing]
    message = _refused(payload, shipped_root)
    show(f"no {missing} sub-mapping", message[:88])
    assert missing in message and KINDS_BLOCK in message


def test_an_unknown_class_name_refuses_by_name(shipped_root: Path, shipped: dict) -> None:
    """"an unknown class name" (row G1): the two classes are the derived set and nothing else."""
    payload = copy.deepcopy(shipped)
    payload[KINDS_BLOCK]["reviewer"] = {}
    message = _refused(payload, shipped_root)
    show("unknown class", message[:110])
    assert "reviewer" in message
    assert str(list(config.KIND_CLASSES)) in message


def test_a_block_outside_the_two_sub_mappings_refuses_by_name(
    shipped_root: Path, shipped: dict, kinds_root: Path
) -> None:
    """"a block outside the two sub-mappings" — the class is the sub-mapping, never beside one.

    The same code path as an unknown class name, and the refusal says which of the two mistakes
    it is looking at: this key's value carries block keys, so it reads as a misplaced block.
    """
    block = _payload(kinds_root)[KINDS_BLOCK]["dispatch"][DISPATCH_KIND]
    payload = copy.deepcopy(shipped)
    payload[KINDS_BLOCK]["loose_block"] = block
    message = _refused(payload, shipped_root)
    show("misplaced block", message[:150])
    assert "loose_block" in message
    assert "container level" in message and "sub-mapping" in message


@pytest.mark.parametrize("illegal", ["not a mapping", [], 7])
def test_a_class_sub_mapping_that_is_not_a_mapping_refuses_by_name(
    shipped_root: Path, shipped: dict, illegal
) -> None:
    payload = copy.deepcopy(shipped)
    payload[KINDS_BLOCK]["dispatch"] = illegal
    message = _refused(payload, shipped_root)
    show(f"dispatch: {illegal!r}", message[:96])
    assert f"{KINDS_BLOCK}.dispatch" in message


# --------------------------------------------------------------------------------------
# `TIER_KEYS` exactly, and the block as data (I1)
# --------------------------------------------------------------------------------------


def test_the_two_fixture_kinds_load_as_kind_blocks(loaded, kinds_root: Path) -> None:
    """I1's field list: the class, the name, the ten resolved values, the resolved `prompt` path
    and the block reference `kinds.<class>.<name>`."""
    for kind_class, name in (("dispatch", DISPATCH_KIND), ("delegate", DELEGATE_KIND)):
        block = loaded.kind(kind_class, name)
        show(f"{kind_class}/{name}", block.block_ref)
        assert isinstance(block, KindBlock)
        assert block.kind_class == kind_class and block.name == name
        assert block.block_ref == f"{KINDS_BLOCK}.{kind_class}.{name}"
        assert block.model and block.effort
        assert block.permission_mode == PERMISSION_MODE_BINDING
        assert block.max_call_usd > 0 and block.timeout_seconds > 0
        assert block.prompt == f"seats/{KINDS_BLOCK}/{name}.md"
        assert block.prompt_path == (kinds_dir(kinds_root) / f"{name}.md").resolve()
        assert block.prompt_path.is_file(), "the prefix file is a seed on disk"
        assert loaded.kinds[kind_class][name] is block, "one resolver, one object"


def test_a_kind_block_takes_tier_keys_exactly(kinds_root: Path) -> None:
    """Not a subset and not a superset: the same ten keys a seat block and a `calls:` block take."""
    container = _payload(kinds_root)[KINDS_BLOCK]
    for kind_class, name in (("dispatch", DISPATCH_KIND), ("delegate", DELEGATE_KIND)):
        keys = sorted(container[kind_class][name])
        show(f"{kind_class}.{name} keys", keys)
        assert keys == sorted(TIER_KEYS)


@pytest.mark.parametrize("key", list(TIER_KEYS))
def test_a_kind_block_missing_a_key_refuses_by_name(kinds_root: Path, key: str) -> None:
    """Nothing defaults on a containment surface: a block missing one of the ten refuses."""
    payload = _payload(kinds_root)
    del payload[KINDS_BLOCK]["dispatch"][DISPATCH_KIND][key]
    message = _refused(payload, kinds_root)
    assert key in message
    assert f"{KINDS_BLOCK}.dispatch.{DISPATCH_KIND}" in message


@pytest.mark.parametrize(
    "eleventh", [CLASS_KEY, SANDBOX_BLOCK, "workspace_path", "spawn_writable", "bin_links"]
)
def test_a_kind_block_carrying_an_eleventh_key_refuses_by_name(
    kinds_root: Path, eleventh: str
) -> None:
    """"a `class:` key on a block, a per-kind `sandbox:` key" and every other extra (row G1).

    One check, `TIER_KEYS`-exactly, and the two extras a seed author is most likely to reach for
    get the reason as well as the name: the class is the sub-mapping, and a kind declares no
    containment of its own.
    """
    payload = _payload(kinds_root)
    payload[KINDS_BLOCK]["dispatch"][DISPATCH_KIND][eleventh] = "dispatch"
    message = _refused(payload, kinds_root)
    show(f"eleventh key {eleventh}", message[:130])
    assert eleventh in message and "exactly" in message
    assert f"{KINDS_BLOCK}.dispatch.{DISPATCH_KIND}" in message
    if eleventh == CLASS_KEY:
        assert "the class is the sub-mapping" in message
    if eleventh == SANDBOX_BLOCK:
        assert "declares no containment of its own" in message


def test_a_body_key_on_a_kind_block_is_refused_as_the_eleventh_key_it_is(
    kinds_root: Path,
) -> None:
    """"a `body` key **on a kind block** through `parse_kinds()`'s own `TIER_KEYS`-exactly check
    as the eleventh key it is" (row G1) — the specific refusal wins, and the landed walk, which
    runs last, is not what a seed author reads here."""
    payload = _payload(kinds_root)
    payload[KINDS_BLOCK]["dispatch"][DISPATCH_KIND][BODY_KEY] = BODY_TERMINAL
    message = _refused(payload, kinds_root)
    show("body on a kind block", message[:130])
    assert BODY_KEY in message and "exactly" in message
    assert f"{KINDS_BLOCK}.dispatch.{DISPATCH_KIND}" in message
    assert "nowhere else in seats.yaml" not in message, "the walk's refusal, not this one"


@pytest.mark.parametrize("level", ["container", "class"])
def test_a_body_key_on_either_container_level_is_refused_by_the_landed_walk(
    kinds_root: Path, level: str
) -> None:
    """"a `body` key on either **container** level, `kinds.body` and `kinds.<class>.body`, through
    the landed `refuse_a_body_key_anywhere_else()` walk, which this build does not edit" (row G1).

    The walk was written against the shape of the document so that it would reach "anything build
    A.1.i adds"; these two cases are the receipt that it did, at both levels the block parser
    never reaches. The refusal is the walk's own sentence, word for word.
    """
    payload = _payload(kinds_root)
    if level == "container":
        payload[KINDS_BLOCK][BODY_KEY] = BODY_TERMINAL
        location = f"{KINDS_BLOCK}.{BODY_KEY}"
    else:
        payload[KINDS_BLOCK]["dispatch"][BODY_KEY] = BODY_TERMINAL
        location = f"{KINDS_BLOCK}.dispatch.{BODY_KEY}"
    message = _refused(payload, kinds_root)
    show(location, message[:120])
    assert message.startswith(f"{location}:")
    assert f"`{RUNTIME_BLOCK}.{BODY_KEY}`" in message and "nowhere else in seats.yaml" in message


@pytest.mark.parametrize("illegal", ["not a mapping", [], 7])
def test_a_kind_block_that_is_not_a_mapping_refuses_by_name(kinds_root: Path, illegal) -> None:
    payload = _payload(kinds_root)
    payload[KINDS_BLOCK]["dispatch"][DISPATCH_KIND] = illegal
    message = _refused(payload, kinds_root)
    assert f"{KINDS_BLOCK}.dispatch.{DISPATCH_KIND}" in message


# --------------------------------------------------------------------------------------
# `prompt:` — by realpath, inside `brain/seats/kinds/`, and it must exist (A1-8)
# --------------------------------------------------------------------------------------


def test_a_prompt_naming_a_file_that_is_not_there_refuses_by_name(tmp_path: Path) -> None:
    """The one refusal whose subject is the root rather than the document: the fixture container
    whose `prompt:` names a prefix this build ships nowhere."""
    root = fake_cli.seed_kinds_root(tmp_path / "brain", fake_cli.KINDS_MISSING_PREFIX)
    with pytest.raises(SeatConfigError) as raised:
        fake_cli.seats_of(root)
    message = str(raised.value)
    show("missing prefix", message[:120])
    assert "no_prefix_ships_under_this_name.md" in message
    assert f"{KINDS_BLOCK}.dispatch.{DISPATCH_KIND}" in message
    assert "not a file" in message


@pytest.mark.parametrize(
    "prompt",
    [
        "../notes.md",
        "seats/kinds/../../notes.md",
        "/etc/hosts",
        "seats/calls/think.md",
    ],
)
def test_a_prompt_resolving_outside_the_kinds_directory_refuses_by_name(
    kinds_root: Path, prompt: str
) -> None:
    """"a `prompt: ../notes.md`, an absolute `prompt:`" — and a path inside the brain root but
    outside `seats/kinds/`, which is the same mistake one directory over (row G1, folded: S-i26)."""
    payload = _payload(kinds_root)
    payload[KINDS_BLOCK]["dispatch"][DISPATCH_KIND]["prompt"] = prompt
    message = _refused(payload, kinds_root)
    show(f"prompt {prompt!r}", message[:120])
    assert prompt in message and str(kinds_dir(kinds_root).resolve()) in message
    assert "outside" in message


def test_a_symlinked_prompt_whose_target_leaves_the_directory_refuses_by_name(
    mutable_kinds_root: Path,
) -> None:
    """"a symlink whose target leaves the directory" — which is why resolution is by realpath and
    the confinement is checked rather than assumed (folded: S-i26)."""
    outside = mutable_kinds_root / "notes.md"
    outside.write_text("# not a seed under seats/kinds/\n", encoding="utf-8")
    link = kinds_dir(mutable_kinds_root) / "escapes.md"
    link.symlink_to(outside)
    payload = _payload(mutable_kinds_root)
    payload[KINDS_BLOCK]["dispatch"][DISPATCH_KIND]["prompt"] = f"seats/{KINDS_BLOCK}/escapes.md"
    message = _refused(payload, mutable_kinds_root)
    show("symlink out", message[:120])
    assert "escapes.md" in message and str(outside.resolve()) in message
    assert "outside" in message


def test_a_symlink_that_stays_inside_resolves_to_its_realpath(mutable_kinds_root: Path) -> None:
    """The positive half of the same rule: inside is inside, and `prompt_path` is the realpath."""
    target = kinds_dir(mutable_kinds_root) / f"{DISPATCH_KIND}.md"
    link = kinds_dir(mutable_kinds_root) / "alias.md"
    link.symlink_to(target)
    payload = _payload(mutable_kinds_root)
    payload[KINDS_BLOCK]["dispatch"][DISPATCH_KIND]["prompt"] = f"seats/{KINDS_BLOCK}/alias.md"
    block = parse_seats(payload, mutable_kinds_root).kind("dispatch", DISPATCH_KIND)
    show("alias.md resolves to", block.prompt_path.name)
    assert block.prompt_path == target.resolve(), "by realpath, not as written"


# --------------------------------------------------------------------------------------
# The resolver, beside `tier()` and `call()` — and `block()` still addressee-only
# --------------------------------------------------------------------------------------


def test_an_undefined_kind_refuses_plainly_and_names_what_the_class_holds(loaded) -> None:
    """"raise a plain refusal here and no `SeatUnavailable`" — that class is the desk's, which is
    where `REASON_NO_KIND` is raised from in a later order."""
    with pytest.raises(SeatConfigError) as raised:
        loaded.kind("dispatch", "no_such_kind")
    message = str(raised.value)
    show("undefined kind", message[:120])
    assert "no_such_kind" in message and DISPATCH_KIND in message
    assert type(raised.value) is SeatConfigError


def test_a_name_that_is_not_a_kind_class_refuses_by_name(loaded) -> None:
    with pytest.raises(SeatConfigError) as raised:
        loaded.kind("manager", DISPATCH_KIND)
    message = str(raised.value)
    show("not a class", message[:120])
    assert "manager" in message and str(list(config.KIND_CLASSES)) in message


def test_the_addressee_resolver_still_cannot_name_a_kind(loaded) -> None:
    """`block()` is **unedited and addressee-only**: an addressee cannot name WHICH kind, so a
    `dispatch` addressee still refuses there and the desk resolves `(class, kind)` through
    `kind()` instead (folded: S-i2)."""
    for addressee in config.KIND_CLASSES:
        with pytest.raises(SeatConfigError) as raised:
            loaded.block(addressee)
        show(f"block({addressee!r})", str(raised.value)[:96])
        assert f"calls.{addressee}" in str(raised.value)


def test_a_containment_object_built_without_a_seed_carries_no_kinds() -> None:
    """`kinds` defaults empty for `protean.oracle.config`'s reason, exactly as `calls` does."""
    from protean.cortex.live.config import SandboxPolicy, SeatsConfig

    direct = SeatsConfig(
        root=Path("/nonexistent"),
        layer="live",
        binary="claude",
        path_entries=(),
        bin_links=(),
        env_passthrough=(),
        tiers={},
        sandbox=SandboxPolicy(binary="/usr/bin/sandbox-exec", names=(), deny_write=()),
    )
    assert direct.kinds == {}
    with pytest.raises(SeatConfigError):
        direct.kind("dispatch", DISPATCH_KIND)


# --------------------------------------------------------------------------------------
# The hash claim — proven without editing `brain/folders.py` (row G1's last clause)
# --------------------------------------------------------------------------------------


def test_a_fixture_kind_prefix_is_a_hashed_seed_and_editing_it_moves_the_hash(
    mutable_kinds_root: Path,
) -> None:
    """"proven by a fixture kind prefix appearing in `seed_hashes()` and by editing it moving the
    hash" (row G1). The landed recursive glob has reached `seats/kinds/*.md` since D11-4, so this
    is the **receipt** of that ruling reaching one tier down rather than an amendment: no line of
    `src/protean/brain/folders.py` is edited by this build."""
    relative = f"seats/{KINDS_BLOCK}/{DISPATCH_KIND}.md"
    before = seed_hashes(mutable_kinds_root)
    show("hashed kind prefix", relative in before)
    assert relative in before, "a kind prefix is a hashed seed the moment the directory holds one"
    assert f"seats/{KINDS_BLOCK}/{DELEGATE_KIND}.md" in before

    prefix = kinds_dir(mutable_kinds_root) / f"{DISPATCH_KIND}.md"
    prefix.write_text(prefix.read_text(encoding="utf-8") + "\nedited\n", encoding="utf-8")
    after = seed_hashes(mutable_kinds_root)
    show("hash moved", before[relative] != after[relative])
    assert before[relative] != after[relative], "editing a kind prefix mid-task is drift"
    assert before["seats.yaml"] == after["seats.yaml"], "and nothing else moved with it"


# --------------------------------------------------------------------------------------
# The builder's own list: row M2's first half and row M3's decode half (closed by neither)
# --------------------------------------------------------------------------------------


def test_no_kind_block_key_but_prompt_is_a_path(loaded, kinds_root: Path) -> None:
    """Row M2's first half: "no kind-block key but `prompt` is a path".

    The two named exceptions are `prompt` and its resolution; everything else a spawn's profile
    will be composed from — the workspace and `runtime.spawn_writable` — reaches it from the
    runtime and the `runtime:` block, never from a kind block. The composed-profile provenance
    half of this row is a later order's.
    """
    block = loaded.kind("dispatch", DISPATCH_KIND)
    paths = {
        name: value
        for name, value in ((f, getattr(block, f)) for f in block.__slots__)
        if isinstance(value, Path)
    }
    show("path-valued fields", sorted(paths))
    assert sorted(paths) == ["prompt_path"]
    assert paths["prompt_path"].is_relative_to(kinds_dir(kinds_root).resolve())
    assert "prompt" in TIER_KEYS and block.prompt == f"seats/{KINDS_BLOCK}/{DISPATCH_KIND}.md"
    for forbidden in ("workspace", "writable", "add_dir_path", SANDBOX_BLOCK):
        assert not any(forbidden in name for name in block.__slots__ if name != "add_dir")


def test_a_scripted_subagent_return_still_decodes_on_the_one_path() -> None:
    """Row M3's decode half: "a scripted subagent return still decodes through the one
    `decode_seat_result()` path, so A.1's dry fixtures are unchanged by the container's arrival".

    Structural rather than asserted: the decoder takes an addressee, an envelope and a tick, and
    no configuration at all — so a container that resolves kinds cannot reach it — which is why
    this case seeds **no root**: that the fixture container is non-empty is owned by
    `test_the_two_fixture_kinds_load_as_kind_blocks` and is not restated here.
    """
    parameters = list(inspect.signature(decode_seat_result).parameters)
    show("decode_seat_result parameters", parameters)
    assert parameters == ["tier", "envelope", "tick"]

    envelope = SeatEnvelope.model_validate(fake_cli.envelope(fake_cli.executor_result("u-1")))
    decoded = decode_seat_result(CallType.DISPATCH, envelope, 4)
    show("decoded", type(decoded).__name__)
    assert isinstance(decoded, ExecutorSummary)
    assert decoded.emitter == "dispatch" and decoded.unit_id == "u-1" and decoded.tick == 4


# --------------------------------------------------------------------------------------
# Route row R17 — three comments, two corrected and the third byte-identical
# --------------------------------------------------------------------------------------


def test_no_comment_in_the_seed_calls_a_kind_block_future(shipped_root: Path) -> None:
    """R17's own check, first two clauses: "no comment in the file calls a kind block future"."""
    text = (shipped_root / "seats.yaml").read_text(encoding="utf-8")
    for sentence in FUTURE_SENTENCES:
        assert sentence not in text, f"R17 corrects: {sentence!r}"
    assert "from a kind block under `kinds:` below" in text
    assert f"its per-kind configuration is the `{KINDS_BLOCK}:` container below" in text
    show("remaining A.1.i mentions", text.count("build A.1.i"))
    assert text.count("build A.1.i") == 1, "the `body` note's own sentence, and nothing else"


def test_the_body_note_is_byte_identical_to_its_pre_a1i_text(shipped_root: Path) -> None:
    """R17's third clause: the `body` note is kept exactly as written — it is the sentence the
    landed walk already makes true of `kinds:`, and row G1's two container cases are its receipt."""
    text = (shipped_root / "seats.yaml").read_text(encoding="utf-8")
    show("body note unchanged", BODY_NOTE.splitlines()[0][:60])
    assert BODY_NOTE in text
    assert "or on anything build A.1.i" in BODY_NOTE


def test_the_container_is_the_only_key_the_route_row_added(shipped_root: Path, shipped) -> None:
    """"no key the loader reads is changed by this row" — R17 moved comments only, so the seed's
    top-level keys are the landed ones plus the container Deliverable 1 adds."""
    keys = list(shipped)
    show("top-level keys", keys)
    assert keys == ["layer", "runtime", "sandbox", "director", "manager", "calls", KINDS_BLOCK,
                    "oracle"]
    parsed = parse_kinds(shipped, shipped_root)
    assert {name: sorted(blocks) for name, blocks in parsed.items()} == {
        "dispatch": ["editor"],
        "delegate": ["reader"],
    }


# --------------------------------------------------------------------------------------
# Order W2 — the containment floor as a positive grant (row G2) and the composed kernel
# half (row G3's composition clauses). The licensed sets are I2's content and the operator's B43.
# --------------------------------------------------------------------------------------

#: § Deliverable 2's `delegate` set, transcribed: **exactly** three read patterns, and no `Bash`
#: pattern — so no `Bash` name is derivable and the class cannot carry the shell in any form.
DELEGATE_LICENSED = ("Read", "Grep", "Glob")

#: The rig-specific pattern the `dispatch` class's literal is the `oracle:` block's list **less**.
RIG_SPECIFIC = "Bash(postman:*)"

#: The capture `tests/cortex/probe_profile.py` wrote — the receipt that **fixed** the device
#: literals. Read off disk by the cases below, never re-derived.
SPAWN_CAPTURE = Path(__file__).resolve().parent / "captures" / "spawn-profile.json"


@pytest.fixture()
def oracle_block(shipped: dict) -> dict:
    """The shipping seed's `oracle:` block — build 2's landed acting surface, read off disk.

    It is **unedited** by this build; what the `dispatch` class authors is a literal taken from it,
    and these cases compare the two rather than trusting that they were copied correctly.
    """
    return shipped["oracle"]


def _spawn_world(base: Path) -> SimpleNamespace:
    """A fixture kind root, its stand-in, a task workspace, and a **third** path outside both.

    The evidence directory is a `runtime.spawn_writable` entry (§ Deliverable 7, folded: S-i37),
    because under the inverted profile the stand-in writes its argv, stdin, cwd and env files
    beside `$0`. The third path is what row G3's refused write has to target: outside the task
    workspace, outside `spawn_writable` and outside the evidence directory.
    """
    binaries = fake_cli.install(base / "bin")
    root = fake_cli.seed_kinds_root(base / "brain", evidence=binaries)
    workspace = (base / "workspace").resolve()
    workspace.mkdir()
    third = (base / "third").resolve()
    third.mkdir()
    seats = fake_cli.seats_of(root)
    return SimpleNamespace(
        root=root,
        binaries=binaries.resolve(),
        workspace=workspace,
        third=third,
        seats=seats,
        dispatch=seats.kind("dispatch", DISPATCH_KIND),
        delegate=seats.kind("delegate", DELEGATE_KIND),
    )


@pytest.fixture(scope="module")
def spawn(tmp_path_factory: pytest.TempPathFactory) -> SimpleNamespace:
    """`_spawn_world()`, once for the module: every consumer composes profiles and compares
    strings, and the payload mutations go through a `_payload()` copy rather than the file."""
    return _spawn_world(tmp_path_factory.mktemp("spawn"))


@pytest.fixture()
def writing_spawn(tmp_path: Path) -> SimpleNamespace:
    """The per-test copy for the one case that really runs processes under the composed profile.

    Its `workspace` and `third` are written into and its stand-in's ordinal counter is read back,
    so that case cannot share either directory with the module-scoped root above.
    """
    return _spawn_world(tmp_path)


def _capability(spawn, block, *, workspace: Path | None = None) -> CapabilityProfile:
    return resolve_capability(
        block, workspace=workspace, spawn_writable=spawn.seats.spawn_writable
    )


# ---- the one authored set per class, and the NAME set derived from it ------------------


def test_the_dispatch_class_licenses_the_oracle_blocks_list_less_the_rig_specific_pattern(
    oracle_block: dict,
) -> None:
    """"`dispatch` the `oracle:` block's `allowed_tools` less `Bash(postman:*)`" (row G2).

    Compared against the seed read off disk rather than against a second transcription, so a seed
    edit to build 2's acting surface turns this red instead of drifting silently past it.
    """
    expected = tuple(entry for entry in oracle_block["allowed_tools"] if entry != RIG_SPECIFIC)
    show("dispatch licensed patterns", list(licensed_patterns("dispatch")), tag="G2")
    assert licensed_patterns("dispatch") == expected
    assert len(expected) == 15
    assert RIG_SPECIFIC in oracle_block["allowed_tools"], "the one cut, still in the seed"
    assert RIG_SPECIFIC not in licensed_patterns("dispatch")
    for absent in (BASH, "Task", "KillShell", "BashOutput", "WebFetch", "Bash(git push:*)"):
        assert absent not in licensed_patterns("dispatch"), "note the absences as much as the entries"


def test_the_delegate_class_licenses_three_read_patterns_and_no_shell_in_any_form(
    oracle_block: dict,
) -> None:
    """"`delegate` exactly `("Read", "Grep", "Glob")`, with **no `Bash` pattern and therefore no
    derivable `Bash` name, in any form**" (row G2, folded: S-i27)."""
    show("delegate licensed patterns", list(licensed_patterns("delegate")), tag="G2")
    assert licensed_patterns("delegate") == DELEGATE_LICENSED
    assert BASH not in licensed_names("delegate")
    assert not any(tool_name(pattern) == BASH for pattern in licensed_patterns("delegate"))


def test_the_dispatch_names_derive_to_the_oracle_blocks_own_tool_set_exactly(
    oracle_block: dict,
) -> None:
    """"the licensed **NAME** set is **derived** from it (`X(...)`/`X` → `X`, first-appearance
    order), which for `dispatch` reproduces that same block's `tools` set exactly" (row G2).

    S-44's pair fact — a `Bash(...)` pattern binds only with the `Bash` name beside it — is
    therefore inherited by construction rather than restated as a second literal.
    """
    derived = licensed_names("dispatch")
    show("derived names", list(derived), tag="G2")
    assert set(derived) == set(oracle_block["tools"])
    assert derived == ("Read", "Edit", "Write", "Grep", "Glob", BASH), "first-appearance order"
    assert len(derived) == len(set(derived)) == 6


@pytest.mark.parametrize(
    ("pattern", "name"),
    [("Read", "Read"), ("Bash(uv:*)", BASH), ("Bash(git status:*)", BASH), ("Glob", "Glob")],
)
def test_a_name_is_read_off_a_pattern_by_the_token_before_the_parenthesis(pattern, name) -> None:
    """The whole of the derivation, which is why one list has one owner."""
    assert tool_name(pattern) == name


def test_the_two_licensed_sets_are_the_only_authored_pattern_literals(oracle_block: dict) -> None:
    """Row M1's own half, on the builder's list: one literal, one owner.

    `LICENSED_PATTERNS` holds exactly the two classes, the NAME sets are derived rather than
    authored, and `config.KIND_CLASSES` is what the mapping is keyed by — restated nowhere.
    """
    show("licensed classes", sorted(LICENSED_PATTERNS), tag="G2")
    assert sorted(LICENSED_PATTERNS) == sorted(config.KIND_CLASSES)
    for kind_class in config.KIND_CLASSES:
        assert licensed_names(kind_class) == derived_names(LICENSED_PATTERNS[kind_class])


# ---- the granted pair, and the positive control ---------------------------------------


def test_the_dispatch_fixture_carries_the_fifteen_patterns_beside_the_six_names_they_derive(
    spawn,
) -> None:
    """Row G2's positive control: the fixture grants its class's whole licensed set and loads."""
    profile = _capability(spawn, spawn.dispatch, workspace=spawn.workspace)
    show("granted patterns", len(profile.granted_patterns), tag="G2")
    assert profile.granted_patterns == licensed_patterns("dispatch")
    assert profile.granted_names == licensed_names("dispatch")
    assert len(profile.granted_patterns) == 15 and len(profile.granted_names) == 6
    assert profile.permission_mode == PERMISSION_MODE_BINDING
    assert profile.kind_class == "dispatch" and profile.name == DISPATCH_KIND


def test_both_fixture_kinds_load_and_the_delegate_grants_no_shell(spawn) -> None:
    """The other half of the control: two kinds, two classes, one resolution."""
    profile = _capability(spawn, spawn.delegate)
    show("delegate granted", list(profile.granted_patterns), tag="G2")
    assert profile.granted_patterns == DELEGATE_LICENSED
    assert profile.granted_names == DELEGATE_LICENSED
    assert BASH not in profile.granted_names


def test_a_permuted_tools_carrying_the_same_names_loads(spawn) -> None:
    """"a permuted `tools` carrying the same names loads, and that is one case of this row"
    (row G2, folded: S-i46) — the comparison is set equality, because order is not a capability.

    The dispatch fixture's own `tools` is already in another order than the derivation's; this
    reverses it as well, so the case cannot pass by accident of how the fixture was written.
    """
    payload = _payload(spawn.root)
    block = payload[KINDS_BLOCK]["dispatch"][DISPATCH_KIND]
    assert tuple(block["tools"]) != licensed_names("dispatch"), "the fixture is already permuted"
    block["tools"] = list(reversed(block["tools"]))
    loaded = parse_seats(payload, spawn.root)
    resolved = resolve_capability(loaded.kind("dispatch", DISPATCH_KIND))
    show("permuted tools", list(block["tools"]), tag="G2")
    assert set(resolved.tools) == set(resolved.granted_names)


def test_the_block_is_never_held_to_the_egress_set_and_the_runtime_appends_it(spawn) -> None:
    """"**no `disallowed_tools` fixture, because a block is never held to the egress/remote set:
    the runtime appends the one `EGRESS_REMOTE` literal itself**" (row G2, folded: S-i15)."""
    payload = _payload(spawn.root)
    for kind_class, name in (("dispatch", DISPATCH_KIND), ("delegate", DELEGATE_KIND)):
        assert payload[KINDS_BLOCK][kind_class][name]["disallowed_tools"] == []
    refused = _capability(spawn, spawn.dispatch).refused_patterns()
    show("appended egress set", list(refused), tag="G2")
    assert refused == EGRESS_REMOTE
    assert len(EGRESS_REMOTE) == 8

    # A block that adds to it keeps its own entries first, and never restates the eight.
    payload[KINDS_BLOCK]["dispatch"][DISPATCH_KIND]["disallowed_tools"] = ["Bash(rm:*)"]
    loaded = parse_seats(payload, spawn.root)
    widened = resolve_capability(loaded.kind("dispatch", DISPATCH_KIND)).refused_patterns()
    assert widened == ("Bash(rm:*)", *EGRESS_REMOTE), "adds to it; there is no superset refusal"


def test_the_floor_reaches_no_other_block_in_the_file(spawn) -> None:
    """Row G2's positive control, second half: "the same battery shows the floor reaching **no
    other block** — `director:`, `manager:`, the two `calls:` blocks and `oracle:` load
    byte-unchanged".

    Read both ways. The five blocks' loaded values equal what the seed says; and a tool that no
    licensed set contains — `Task`, the sharpest one — is accepted on each of them, because the
    positive grant is the **kinds'** floor and reaches nothing else. `oracle:` is not parsed by this
    module at all, so the payload it carries is the assertion.
    """
    payload = _payload(spawn.root)
    loaded = parse_seats(payload, spawn.root)
    for tier in ("director", "manager"):
        assert loaded.tier(tier).allowed_tools == tuple(payload[tier]["allowed_tools"])
        assert loaded.tier(tier).tools == payload[tier]["tools"]
    for call_type in config.CONFIGURED_CALL_TYPES:
        assert loaded.call(call_type).allowed_tools == tuple(payload["calls"][call_type]["allowed_tools"])
    assert payload["oracle"]["allowed_tools"] == _payload(spawn.root)["oracle"]["allowed_tools"]

    widened = _payload(spawn.root)
    widened["director"]["allowed_tools"] = ["Task"]
    widened["calls"]["think"]["allowed_tools"] = ["Task", BASH]
    reloaded = parse_seats(widened, spawn.root)
    show("Task accepted off the kinds container", reloaded.tier("director").allowed_tools, tag="G2")
    assert reloaded.tier("director").allowed_tools == ("Task",)
    assert reloaded.call("think").allowed_tools == ("Task", BASH)


# ---- the adversarial set: one case per named refusal, by payload mutation --------------


def _refused_grant(spawn, kind_class: str, name: str, **keys) -> str:
    """Mutate one fixture block's keys, require a refusal, and answer what it said."""
    payload = _payload(spawn.root)
    payload[KINDS_BLOCK][kind_class][name].update(keys)
    return _refused(payload, spawn.root)


@pytest.mark.parametrize(
    ("kind_class", "name", "entry"),
    [
        ("dispatch", DISPATCH_KIND, RIG_SPECIFIC),
        ("dispatch", DISPATCH_KIND, "WebFetch"),
        ("delegate", DELEGATE_KIND, "Write"),
    ],
)
def test_an_entry_outside_the_classs_licensed_patterns_refuses_by_name(
    spawn, kind_class, name, entry
) -> None:
    """"an entry outside the licensed patterns (one per class)" (row G2).

    Including the rig-specific pattern the `dispatch` literal was deliberately cut down by: the
    grant is positive, so an unlisted tool is refused **by absence** rather than by enumeration —
    which is the whole of A1-1.
    """
    payload = _payload(spawn.root)
    block = payload[KINDS_BLOCK][kind_class][name]
    block["allowed_tools"] = [*block["allowed_tools"], entry]
    block["tools"] = sorted({*block["tools"], tool_name(entry)})
    message = _refused(payload, spawn.root)
    show(f"{kind_class} + {entry}", message[:120], tag="G2")
    assert entry in message and kind_class in message
    assert "licensed patterns" in message


#: The sentinel for the one shape that is not a *value*: the key is deleted rather than set.
ABSENT = object()


@pytest.mark.parametrize(
    "value", [[], None, "", ABSENT], ids=["empty", "null", "empty_string", "absent"]
)
def test_an_allowed_tools_that_names_no_pattern_refuses_by_name(spawn, value) -> None:
    """Row **G2**: "an `allowed_tools` that is **empty, absent, `null`** or `""`" — a kind exists
    in order to carry tools, and a tool-less one is a think call wearing a kind's prefix.

    The four shapes the row enumerates, as the four rows of one parametrize: `[]` and `null` are
    values that name nothing, `""` is not a list of patterns at all, and `absent` is the key
    deleted — `TIER_KEYS` is required per block, so it cannot be missing. Each refusal names the
    key, and the three value shapes name the block as well.
    """
    if value is ABSENT:
        payload = _payload(spawn.root)
        del payload[KINDS_BLOCK]["dispatch"][DISPATCH_KIND]["allowed_tools"]
        message = _refused(payload, spawn.root)
        show("allowed_tools absent", message[:120], tag="G2")
        assert "allowed_tools" in message
        return
    message = _refused_grant(spawn, "dispatch", DISPATCH_KIND, allowed_tools=value)
    show(f"allowed_tools={value!r}", message[:120], tag="G2")
    assert "allowed_tools" in message and f"{KINDS_BLOCK}.dispatch.{DISPATCH_KIND}" in message


@pytest.mark.parametrize(("kind_class", "name"), [("dispatch", DISPATCH_KIND), ("delegate", DELEGATE_KIND)])
def test_a_bare_bash_pattern_refuses_for_either_class_under_its_own_clause(
    spawn, kind_class, name
) -> None:
    """"a bare `Bash` pattern (either class)" — it licenses every command there is."""
    message = _refused_grant(
        spawn, kind_class, name, allowed_tools=[BASH], tools=[BASH]
    )
    show(f"bare Bash on {kind_class}", message[:130], tag="G2")
    assert f"bare {BASH!r} pattern" in message
    assert "licenses every command" in message


@pytest.mark.parametrize("entry", sorted(NAMED_BY_THEIR_OWN_REFUSAL))
def test_task_killshell_and_bashoutput_each_refuse_under_their_own_name(spawn, entry) -> None:
    """"`Task`, `KillShell` and `BashOutput` (each also refused **under its own name**)" (row G2).

    The positive grant already refuses them by absence; what the specific message adds is the
    reason, because a seed author who wrote one is owed it (T1).
    """
    message = _refused_grant(
        spawn, "dispatch", DISPATCH_KIND, allowed_tools=[entry], tools=[entry]
    )
    show(f"{entry} by its own name", message[:140], tag="G2")
    assert entry in message and NAMED_BY_THEIR_OWN_REFUSAL[entry].split(",")[0][:24] in message
    assert "under its own name" in message


def test_bash_find_on_a_delegate_refuses_because_the_class_licenses_no_shell(spawn) -> None:
    """"`Bash(find:*)` on a delegate" (row G2): S-A49's enumerated read-only list is **retired** —
    `Bash(find:*)` executes and deletes, and every prefix admits redirection."""
    message = _refused_grant(
        spawn, "delegate", DELEGATE_KIND, allowed_tools=["Bash(find:*)"], tools=[BASH]
    )
    show("Bash(find:*) on a delegate", message[:150], tag="G2")
    assert "Bash(find:*)" in message and "delegate" in message
    assert "cannot carry the shell in any form" in message
    assert "retired" in message


@pytest.mark.parametrize(
    ("label", "tools"),
    [
        ("a pattern whose name is missing", ["Read", "Edit", "Write", "Grep", "Glob"]),
        ("a name no pattern covers", ["Read", "Edit", "Write", "Grep", "Glob", BASH, "WebFetch"]),
        ("tools: null", None),
        ("tools: ''", ""),
        ("an empty tools", []),
    ],
)
def test_a_tools_unequal_to_the_derived_names_refuses_by_name(spawn, label, tools) -> None:
    """"a `tools` unequal to `derived(allowed_tools)` — a pattern whose name is missing from it, a
    name it carries that no pattern covers, `tools: null`, `tools: ""`, an empty `tools`" (row G2).

    One comparison where two authored lists would have needed two cross-rules: a `Bash(uv:*)` with
    no `Bash` name never binds (S-44), and a name no pattern covers is an unbound tool the seed
    author believes it granted.
    """
    message = _refused_grant(spawn, "dispatch", DISPATCH_KIND, tools=tools)
    show(label, message[:150], tag="G2")
    assert "tools" in message and "derived" in message
    assert f"{KINDS_BLOCK}.dispatch.{DISPATCH_KIND}" in message


def test_the_name_bash_on_a_delegate_refuses_through_the_same_comparison(spawn) -> None:
    """"the name `Bash` on a delegate, through that same comparison" — no `Bash` pattern being
    licensed for it to derive from (row G2, folded: S-i27, folded: S-i46)."""
    message = _refused_grant(
        spawn, "delegate", DELEGATE_KIND, tools=[*DELEGATE_LICENSED, BASH]
    )
    show("Bash name on a delegate", message[:150], tag="G2")
    assert BASH in message and "derived" in message


@pytest.mark.parametrize("mode", [None, "acceptEdits", "plan"])
def test_a_permission_mode_that_is_not_dont_ask_refuses_by_name(spawn, mode) -> None:
    """"`permission_mode` that is not `dontAsk`, **including `null`**" (row G2): a tool-bearing kind
    has no legal mode but the one measured to bind."""
    message = _refused_grant(spawn, "dispatch", DISPATCH_KIND, permission_mode=mode)
    show(f"permission_mode={mode!r}", message[:130], tag="G2")
    assert "permission_mode" in message and PERMISSION_MODE_BINDING in message


def test_permission_mode_auto_refuses_by_the_landed_measurement(spawn) -> None:
    """"and `permission_mode: auto`" — the landed T3 refusal, whose message is the measurement
    itself: under `auto` the allow-list did not bind at all (S-44)."""
    message = _refused_grant(spawn, "dispatch", DISPATCH_KIND, permission_mode="auto")
    show("permission_mode=auto", message[:130], tag="G2")
    assert "auto" in message and "permission_denials: []" in message
    assert PERMISSION_MODE_BINDING in message, "the same refusal on a kind block (S-44)"


@pytest.mark.parametrize("cap", sorted(SPAWN_CAP_CEILINGS))
def test_a_cap_above_the_spawn_ceiling_refuses_at_load_by_name(spawn, cap) -> None:
    """"two caps above the spawn ceiling" (§ Deliverable 2's fourth resolution refusal, against
    § Deliverable 5's two `runtime.spawn_*` values).

    Refused at **load**, before anything is spawned — and the ceiling is a ceiling: a kind
    configured exactly at it loads, and one cent above it does not.
    """
    ceiling = float(_payload(spawn.root)[RUNTIME_BLOCK][SPAWN_CAP_CEILINGS[cap]])
    at_the_ceiling = parse_seats(
        {
            **_payload(spawn.root),
            KINDS_BLOCK: _with_cap(_payload(spawn.root), cap, ceiling),
        },
        spawn.root,
    )
    assert float(getattr(at_the_ceiling.kind("dispatch", DISPATCH_KIND), cap)) == ceiling

    message = _refused_grant(spawn, "dispatch", DISPATCH_KIND, **{cap: ceiling + 0.01})
    show(f"{cap} above {ceiling}", message[:150], tag="G2")
    assert cap in message and SPAWN_CAP_CEILINGS[cap] in message and str(ceiling) in message


def _with_cap(payload: dict, cap: str, value: float) -> dict:
    container = copy.deepcopy(payload[KINDS_BLOCK])
    container["dispatch"][DISPATCH_KIND][cap] = value
    return container


# ---- the kernel half, composed per spawn from the class (row G3's composition clauses) -


def _run_under(profile: str, seats, argv: list[str]) -> subprocess.CompletedProcess:
    """One process under a composed spawn profile, with **no `TMPDIR`** in its environment.

    The absence is load-bearing (folded: S-i48): with no per-user temp root reaching the child, the
    CLI and Python fall back to `/tmp`, which `runtime.spawn_writable` seeds — which is why no
    per-user temp root appears in either profile.
    """
    return subprocess.run(
        [seats.sandbox.binary, SANDBOX_PROFILE_FLAG, profile, *argv],
        capture_output=True,
        text=True,
        input="",
        env={"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "")},
        timeout=120,
    )


def test_a_dispatch_spawns_profile_is_the_workspace_the_trees_and_the_measured_allowances(
    spawn,
) -> None:
    """Row G3's first clause, asserted whole: `(deny file-write*)` then `(allow file-write*
    (subpath …))` over the **task workspace**, the resolved `runtime.spawn_writable` trees **and
    every entry of the closed `SPAWN_PROCESS_ALLOWANCES` literal the probe's capture fixed** —
    enumerated here, subpaths and device literals alike, so a measured allowance is asserted and not
    merely allowed."""
    profile = _capability(spawn, spawn.dispatch, workspace=spawn.workspace).sandbox_profile(
        spawn.seats.sandbox
    )
    show("dispatch profile", profile, tag="G3")
    expected = (
        f"{PROFILE_HEAD}(deny file-write*)(allow file-write* "
        + " ".join(
            [f'(subpath "{spawn.workspace}")']
            + [f'(subpath "{tree}")' for tree in spawn.seats.spawn_writable]
            + [f'(subpath "{path}")' for path in spawn_allowance_subpaths()]
            + [f'(literal "{path}")' for path in spawn_allowance_literals()]
        )
        + ")"
    )
    assert profile == expected
    for entry in SPAWN_PROCESS_ALLOWANCES:
        clause = "literal" if entry.device else "subpath"
        assert f'({clause} "{entry.path}")' in profile, "every measured allowance, by name"
    assert SPAWN_PROCESS_ALLOWANCES == (
        type(SPAWN_PROCESS_ALLOWANCES[0])(path="/dev/null", device=True),
    ), "the capture's own measurement, and the only entry it fixed"
    assert profile.startswith(PROFILE_HEAD), "the seats' landed head, retained verbatim"
    assert "process-exec" not in profile


def test_a_delegate_spawns_profile_is_the_same_set_without_the_workspace(spawn) -> None:
    """"a `delegate` fixture spawn's profile on the same state carries the **same set without the
    workspace**; both profiles are otherwise byte-identical" (row G3).

    The workspace is **absent** rather than named in a deny list, which is a stronger statement and
    needs no clause of its own to stay true.

    The sole carrier of this G3 sentence: `test_wave.py`'s
    `test_the_delegate_profile_is_the_dispatch_one_less_the_workspace_subpath` was a 3-for-3 map
    of these assertions and is removed.
    """
    dispatch = _capability(spawn, spawn.dispatch, workspace=spawn.workspace).sandbox_profile(
        spawn.seats.sandbox
    )
    delegate = _capability(spawn, spawn.delegate, workspace=spawn.workspace).sandbox_profile(
        spawn.seats.sandbox
    )
    show("delegate profile", delegate, tag="G3")
    assert str(spawn.workspace) not in delegate
    assert dispatch.replace(f'(subpath "{spawn.workspace}") ', "") == delegate, (
        "byte-identical but for the workspace's own (subpath …)"
    )
    assert f'(subpath "{spawn.workspace}")' in dispatch


def test_neither_profile_names_a_per_user_temp_root_or_a_denied_tree(spawn) -> None:
    """"**no per-user temp root appears in either profile**", and the link farm sits where no
    allowed subpath reaches it (row G3, folded: S-i48).

    The farm and any `add_dir: false` cwd resolve inside `brain/state/<task>/spawns/<tick>/` under
    `brain_root`, which `sandbox.deny_write` names — so the invariant holds **by construction** and
    is asserted here as that: no allowed subpath of either profile contains the brain root's state
    tree, and the collision that would make one is refused at load.
    """
    profiles = {
        "dispatch": _capability(spawn, spawn.dispatch, workspace=spawn.workspace).sandbox_profile(
            spawn.seats.sandbox
        ),
        "delegate": _capability(spawn, spawn.delegate).sandbox_profile(spawn.seats.sandbox),
    }
    farm = (spawn.root / "state" / "task" / "spawns" / "1").resolve()
    temp_root = Path(os.environ["TMPDIR"]).resolve() if os.environ.get("TMPDIR") else None
    show("parent TMPDIR", str(temp_root) or "<unset>", tag="G3")
    for label, profile in profiles.items():
        subpaths = [Path(path) for path in re.findall(r'\(subpath "([^"]+)"\)', profile)]
        for denied in spawn.seats.sandbox.deny_write:
            assert f'(subpath "{denied}")' not in profile
        for allowed in subpaths:
            # The per-user temp root is not granted: no clause IS it, and no clause contains it. A
            # specific directory that happens to live under it — a pytest tmp directory — is a tree
            # the test owns and is the opposite of granting the root.
            if temp_root is not None:
                assert allowed != temp_root, f"{label}: the temp root itself is never allowed"
                assert not temp_root.is_relative_to(allowed), f"{label}: nor any ancestor of it"
            assert not farm.is_relative_to(allowed), f"{label}: the farm is reached by nothing"
            assert allowed != spawn.root.resolve()


def test_no_kind_block_carries_a_sandbox_key(spawn) -> None:
    """"and no kind block carries a `sandbox:` key" (row G3, through G1's refusal): a kind declares
    no containment of its own, because a per-kind declaration is a widening vector (S-A5)."""
    assert spawn.seats.sandbox.binary == "/usr/bin/sandbox-exec", (
        "row G3's one wrapper, named once — the wrapped argv itself is proven off production "
        "output at `test_wave.py` and `test_spawn_audit.py`"
    )
    container = _payload(spawn.root)[KINDS_BLOCK]
    for kind_class, name in (("dispatch", DISPATCH_KIND), ("delegate", DELEGATE_KIND)):
        assert SANDBOX_BLOCK not in container[kind_class][name]
        assert SPAWN_WRITABLE_KEY not in container[kind_class][name]
    assert SANDBOX_BLOCK in _payload(spawn.root), "one top-level block, and it is unedited"


def test_the_stand_in_writes_inside_the_allowed_set_and_is_refused_outside_it(
    writing_spawn,
) -> None:
    """Row G3's kernel claim, proven **dry** with the stand-in (folded: S-i33).

    `sandbox-exec` is already exercised by collected tests, so the fact is obtainable without a
    model call: with the composed profile applied, the stand-in's write **inside** the allowed set
    succeeds — its argv, stdin, cwd and env files land in the evidence directory, which is a
    `runtime.spawn_writable` entry — and its write **outside** it is refused **by the kernel**, the
    refused write targeting a **third** path: outside the task workspace, outside `spawn_writable`
    and outside the evidence directory.
    """
    world = writing_spawn
    profile = _capability(world, world.dispatch, workspace=world.workspace).sandbox_profile(
        world.seats.sandbox
    )
    stand_in = world.binaries / fake_cli.FAKE_BINARY
    inside = _run_under(profile, world.seats, [str(stand_in), "--print", "probe"])
    show("stand-in rc", f"{inside.returncode} · {inside.stderr.strip()[:60]}", tag="G3")
    assert inside.returncode == 0
    assert fake_cli.invocations(world.binaries) == 1
    assert fake_cli.argv_of(world.binaries) == ["--print", "probe"]

    refused_path = world.third / "refused.txt"
    for tree in (world.workspace, *world.seats.spawn_writable, world.binaries):
        assert not refused_path.is_relative_to(tree), "a third path, outside all three"
    outside = _run_under(
        profile, world.seats, ["/bin/sh", "-c", f"echo no > {refused_path}"]
    )
    show("third-path write", f"{outside.returncode} · {outside.stderr.strip()[:80]}", tag="G3")
    assert outside.returncode != 0
    assert "Operation not permitted" in outside.stderr
    assert not refused_path.exists()

    allowed_path = world.workspace / "wrote.txt"
    allowed = _run_under(
        profile, world.seats, ["/bin/sh", "-c", f"echo ok > {allowed_path}"]
    )
    assert allowed.returncode == 0 and allowed_path.exists(), "the workspace is writable"


def test_the_committed_capture_is_the_receipt_that_fixed_the_device_literals(spawn) -> None:
    """"**`tests/cortex/captures/` holds `probe_profile.py`'s capture**, and it shows exit 0 for both
    `claude --version` and the stand-in under the composed profile beside `EPERM` for the write
    outside the allowed set" (row G3).

    And the drift closure: the landed composition, handed the capture's own recorded inputs,
    reproduces the string the kernel actually ran — **byte for byte**. The probe composed its
    profile locally because it ran before `SandboxPolicy.spawn_profile()` existed; this is what
    makes that safe rather than a second spelling.
    """
    capture = json.loads(SPAWN_CAPTURE.read_text(encoding="utf-8"))
    show("capture rung", capture["measured_rung"], tag="G3")
    assert capture["measured_allowances"] == [
        {"path": entry.path, "device": entry.device} for entry in SPAWN_PROCESS_ALLOWANCES
    ], "the literal is the capture's measurement, not an authored list"

    winner = next(trial for trial in capture["trials"] if trial["passes"])
    assert winner["claude_version"]["exit_status"] == 0
    assert capture["claude_version_unsandboxed"]["exit_status"] == 0
    assert winner["stand_in"]["exit_status"] == 0 and winner["stand_in"]["wrote_its_evidence_files"]
    assert winner["write_inside_the_allowed_set"]["exit_status"] == 0
    assert winner["write_outside_the_allowed_set"]["exit_status"] != 0
    assert "Operation not permitted" in winner["write_outside_the_allowed_set"]["stderr"]
    assert winner["write_outside_the_allowed_set"]["refused"] is True
    assert capture["profile_head_retained"] == PROFILE_HEAD

    reproduced = spawn.seats.sandbox.spawn_profile(
        subpaths=(
            capture["directories"]["evidence"],
            *capture["spawn_writable_seed_resolved"],
            *spawn_allowance_subpaths(),
        ),
        literals=spawn_allowance_literals(),
    )
    show("reproduced == measured", reproduced == capture["measured_profile"], tag="G3")
    assert reproduced == capture["measured_profile"]

    # The narrower rung the ladder rejected, and why it is in the capture rather than in prose.
    narrowest = capture["trials"][0]
    assert narrowest["allowances"] == [] and narrowest["passes"] is False
    assert "Operation not permitted" in narrowest["shell_redirect_to_dev_null"]["stderr"]
    assert capture["controlling_tty"] == "", "unmeasured here, and the literal carries no tty"


# ---- the builder's own list: row M1's one-owner rule and row M2's provenance -----------


#: The five literals row M1 gives one owner apiece.
ONE_OWNER_LITERALS = (
    "Bash(git checkout:*)",
    "Bash(pytest:*)",
    "Bash(git push:*)",
    "WebSearch",
    "/dev/null",
)


def test_one_literal_one_owner_across_the_source_tree() -> None:
    """Row M1, on the builder's list: the two licensed PATTERN sets, `EGRESS_REMOTE` and
    `SPAWN_PROCESS_ALLOWANCES` live in `src/protean/cortex/live/kinds.py` **and nowhere else**.

    Read over `src/protean/**` alone, deliberately: `brain/seats.yaml`'s `oracle:` block names the
    same patterns and the same eight egress verbs and is **unedited** by this build — it is build 2's
    landed surface, the set the `dispatch` literal was taken *from*, not a second copy of it. What
    row M1 forbids is a second copy **in code**, so a prose mention is not one either:
    `src/protean/oracle/audit.py` explains `2>/dev/null` in a comment about shell redirection and is
    a module this build does not edit at all.

    The tree is read **once** and the five literals are looped over it, rather than once per
    literal: each literal still carries its own assertion message, so a second owner is still
    named by the literal that found it.
    """
    owner = Path("src/protean/cortex/live/kinds.py")
    sources = {
        path.relative_to(config.repo_root()): path.read_text(encoding="utf-8").splitlines()
        for path in sorted((config.repo_root() / "src" / "protean").rglob("*.py"))
    }
    for literal in ONE_OWNER_LITERALS:
        carriers = [
            relative
            for relative, lines in sources.items()
            if any(literal in line and not line.lstrip().startswith("#") for line in lines)
        ]
        show(f"carriers of {literal!r}", [str(path) for path in carriers])
        assert carriers == [owner], f"one literal, one owner: {literal!r}"


def test_two_delegate_kinds_share_one_profile_string(spawn) -> None:
    """Row M2: "two `delegate` kinds sharing one profile string".

    The kernel half is composed from the **class**, never from the kind — which is the hook A1-10
    names: narrowing one member's writable set later is a change to this one composition and not to
    the seam.
    """
    payload = _payload(spawn.root)
    second = copy.deepcopy(payload[KINDS_BLOCK]["delegate"][DELEGATE_KIND])
    second["prompt"] = f"seats/{KINDS_BLOCK}/{DISPATCH_KIND}.md"
    payload[KINDS_BLOCK]["delegate"]["fixture_three"] = second
    loaded = parse_seats(payload, spawn.root)
    profiles = {
        name: resolve_capability(
            loaded.kind("delegate", name), spawn_writable=loaded.spawn_writable
        ).sandbox_profile(loaded.sandbox)
        for name in (DELEGATE_KIND, "fixture_three")
    }
    show("two delegates, one profile", len(set(profiles.values())))
    assert len(set(profiles.values())) == 1


def test_every_subpath_on_a_composed_profile_traces_to_one_of_three_provenances(spawn) -> None:
    """Row M2: "every subpath on a composed spawn profile tracing to the handed workspace, to
    `runtime.spawn_writable`, or to the `SPAWN_PROCESS_ALLOWANCES` literal — the third provenance
    class and the last one"; and "one kind per class differing in **exactly** the workspace's
    `(subpath …)`"."""
    dispatch = _capability(spawn, spawn.dispatch, workspace=spawn.workspace)
    delegate = _capability(spawn, spawn.delegate, workspace=spawn.workspace)
    provenance = {
        str(spawn.workspace): "the handed workspace",
        **{str(tree): f"{RUNTIME_BLOCK}.{SPAWN_WRITABLE_KEY}" for tree in spawn.seats.spawn_writable},
        **{path: "SPAWN_PROCESS_ALLOWANCES" for path in spawn_allowance_subpaths()},
    }
    for profile in (dispatch, delegate):
        composed = profile.sandbox_profile(spawn.seats.sandbox)
        subpaths = re.findall(r'\(subpath "([^"]+)"\)', composed)
        show(f"{profile.kind_class} subpath provenance", [provenance[path] for path in subpaths])
        assert subpaths, "an allowed set of nothing would be a different claim"
        for path in subpaths:
            assert path in provenance, f"{path} traces to nothing"
        literals = re.findall(r'\(literal "([^"]+)"\)', composed)
        assert literals == list(spawn_allowance_literals())
    assert set(dispatch.allowed_subpaths) - set(delegate.allowed_subpaths) == {spawn.workspace}
    assert set(delegate.allowed_subpaths) - set(dispatch.allowed_subpaths) == set()
