"""`brain/seats.yaml` as loaded, and the containment it is the reviewable form of.

`the build specification (not in this mirror)` § Deliverable 1's table and its containment paragraph
(folded: S-30, folded: S-31), § Directional decisions 9 and 19. Order W2's DoD row W2.

**The containment is asserted against the SPEC's own lists, transcribed here once.** That is the
whole point of putting it in a seed: the allow-list is data, so a test can hold it to the
sentence that authorized it rather than to whatever the file happens to say today. A seed edit
that drops `Bash(git push:*)` back in, or widens the environment, turns this module red.
"""

from __future__ import annotations

import os
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

import pytest
import yaml

from protean import config
from protean.cortex.live.config import (
    BODY_KEY,
    CALL_ADD_DIR,
    CALL_CAP_KEYS,
    CALL_CAP_REFERENCE_TIER,
    CALL_TOOLS,
    CALLS_BLOCK,
    ENV_ALLOWED,
    LAYER_LIVE,
    PERMISSION_MODE_BINDING,
    SANDBOX_BLOCK,
    SANDBOX_NAME_BRAIN_ROOT,
    SANDBOX_NAME_POLICY_HOME,
    RUNTIME_BLOCK,
    RUNTIME_KEYS,
    SANDBOX_PROFILE_FLAG,
    SPAWN_BOUND_KEYS,
    SPAWN_CAP_CEILINGS,
    SPAWN_WRITABLE_KEY,
    TIER_KEYS,
    PROFILE_HEAD,
    SeatConfigError,
    load_seats,
    parse_seats,
)
from protean.cortex.live.kinds import KINDS_BLOCK
from protean.intake import policy_home
from protean.state.calls import BODY_NAMES, BODY_PRINT, BODY_TERMINAL
from protean.state.enums import CallType, Tier
from tests.cortex import fake_cli

#: § Deliverable 1's containment paragraph, transcribed. The executor's allow-list is POSITIVE
#: and nothing outside it runs.
EXECUTOR_ALLOWED = (
    "Read",
    "Edit",
    "Write",
    "Grep",
    "Glob",
    "Bash(uv:*)",
    "Bash(python:*)",
    "Bash(pytest:*)",
    "Bash(git status:*)",
    "Bash(git diff:*)",
    "Bash(git add:*)",
    "Bash(git commit:*)",
    "Bash(git checkout:*)",
    "Bash(git branch:*)",
    "Bash(git log:*)",
)

#: The egress and remote set, named explicitly beside the allow-list.
EXECUTOR_DISALLOWED = (
    "WebFetch",
    "WebSearch",
    "Bash(curl:*)",
    "Bash(wget:*)",
    "Bash(git push:*)",
    "Bash(git remote:*)",
    "Bash(git fetch:*)",
    "Bash(git pull:*)",
)

#: The tool SET both T3 surfaces run under, in the seed's order (S-44). It is what makes the
#: positive allow-list above bind at all: under `--permission-mode auto` and no `--tools`, CLI
#: 2.1.263 ran every unlisted tool and reported `permission_denials: []`.
T3_TOOLS = ("Bash", "Read", "Edit", "Write", "Grep", "Glob")

#: § Deliverable 1's `brain/seats.yaml` table, model per **seat** (folded: A1-1, A1-2), re-based
#: by build A.1 to the two seats: the planner block became the manager's and the executor block
#: is deleted with its tier.
TIER_MODELS = {
    "director": "claude-fable-5-1",
    "manager": "claude-opus-5",
}


@pytest.fixture(scope="session")
def seats():
    """The tracked `brain/seats.yaml`, loaded the way `build()` loads it.

    Session-scoped: every case here reads it and none mutates it — the refusal cases mutate a
    fresh `_seed()` payload instead — so one `load_seats()` serves the module rather than one
    per test.
    """
    loaded = load_seats(config.repo_root() / "brain")
    assert loaded is not None, "the tracked brain root carries seats.yaml"
    return loaded


# --------------------------------------------------------------------------------------
# The table
# --------------------------------------------------------------------------------------


def test_the_tracked_seed_selects_the_live_layer(seats) -> None:
    """`layer:` is what `build()` reads; the workload run uses this file unedited."""
    assert seats.layer == LAYER_LIVE
    assert seats.is_live


@pytest.mark.parametrize("tier", [str(item) for item in Tier])
def test_every_tier_carries_every_key_the_table_names(seats, tier: str) -> None:
    seat = seats.tier(tier)
    assert seat.model == TIER_MODELS[tier]
    assert seat.effort == "high"
    assert seat.max_call_usd > 0, "a static per-call cap, per tier (folded: S-5)"
    assert seat.timeout_seconds > 0, "the wall bound that holds when the dollar cap cannot"
    assert seat.prompt == f"seats/{tier}.md"
    assert seat.prompt_path(seats.root).is_file(), "the prefix file is a seed on disk"


def test_no_seat_carries_tools_a_mode_or_a_workspace(seats) -> None:
    """Re-based by build A.1: **both** seats are tool-less, because the acting seat is gone.

    Build 1's rule was "director and planner calls carry no tools … no `--add-dir`" (folded:
    S-6), with the executor as the one exception. A.1 deletes that seat — tier three is a
    specialized subagent library the manager dispatches, and a subagent's tools, `add_dir` and
    permission mode come from a **kind block, which is build A.1.i's** (§ Out of scope). So the
    exception has no subject and the rule is now universal over the seat set.

    This is also the module's **named guard** — the loop never merges and never pushes:
    `allowed_tools == ()` and `tools == ""` mean no seat can reach for `Bash(git push:*)`,
    `Bash(git remote:*)` or `Task` (the egress pair and the bare-shell verb), because no seat
    reaches for any tool at all.
    """
    for tier in config.TIERS:
        seat = seats.tier(tier)
        assert seat.allowed_tools == ()
        assert seat.permission_mode is None
        assert seat.add_dir is False
        assert seat.tools == "" and seat.tools_argument() == ""


def test_the_tool_set_that_makes_an_allow_list_bind_is_named_nowhere_in_the_seed(seats) -> None:
    """S-44 is unchanged and has no live surface here: no seat carries a tool to bind.

    The measured rule — a positive allow-list binds only under `dontAsk` **beside an explicit
    `--tools` set** — is still the rule, and A.1.i is where it is asserted again, against a kind
    block. What A.1 owes is the absence: `T3_TOOLS` names a set no seat block carries.
    """
    payload = _seed(seats)
    for tier in config.TIERS:
        assert payload[tier]["tools"] == ""
        assert payload[tier]["add_dir"] is False
    assert "executor" not in payload, "the block that carried T3_TOOLS is deleted"
    assert T3_TOOLS == ("Bash", "Read", "Edit", "Write", "Grep", "Glob")


@pytest.mark.parametrize("surface", ["oracle"])
def test_a_seed_that_says_auto_on_a_t3_surface_refuses_to_load(seats, surface: str) -> None:
    """The measured hole, refused in code rather than in prose (S-44).

    Under `auto` on CLI 2.1.263 the allow-list did not bind at all — unlisted tools ran and the
    envelope carried `permission_denials: []` — so `auto` is not a weaker mode on a T3 surface,
    it is *no* mode. Both surfaces refuse it, and the message says which ruling it is.
    """
    from protean.oracle.config import parse_oracle

    payload = _seed(seats)
    # The cortex's own T3 surface left with the executor seat; the oracle is the one that
    # remains in A.1, and the per-kind surface is build A.1.i's.
    payload[surface]["permission_mode"] = "auto"
    parse = parse_oracle
    with pytest.raises(SeatConfigError) as raised:
        parse(payload, seats.root)
    assert "auto" in str(raised.value) and "S-44" in str(raised.value)


def test_a_toolless_seat_may_still_carry_no_mode_at_all(seats) -> None:
    """The refusal is about `auto`, not about every mode: `null` omits the flag and is fine."""
    payload = _seed(seats)
    payload["manager"]["permission_mode"] = None
    assert parse_seats(payload, seats.root).tier("manager").permission_mode is None


def test_the_positive_allow_list_the_spec_names_now_sits_on_the_oracle_alone(seats) -> None:
    """Re-based by build A.1: the cortex block that carried it is deleted with its seat.

    `EXECUTOR_ALLOWED` and `EXECUTOR_DISALLOWED` stay named here because the **oracle** takes
    that containment whole (`tests/oracle/test_config.py`), and because A.1.i re-bases the
    per-kind containment onto the same two literals.
    """
    from protean.oracle.config import load_oracle

    seat, _ = load_oracle(seats.root)
    assert set(EXECUTOR_ALLOWED) < set(seat.allowed_tools)
    assert seat.disallowed_tools == EXECUTOR_DISALLOWED


# --------------------------------------------------------------------------------------
# The two `calls:` blocks — cheap and contained, each by a rule checked at load (row G10)
# --------------------------------------------------------------------------------------


@lru_cache(maxsize=None)
def _parsed(path: Path) -> dict:
    """The tracked `seats.yaml`, parsed **once** for the whole module."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _seed(seats) -> dict:
    """The tracked payload as a document a case may mutate: parsed once, copied per call.

    Every refusal below works by breaking one key of the real seed, so the payload has to be
    fresh each time — but the *parse* does not: the 23 KB file is read once and each caller takes
    a `deepcopy`, which is the only reason the file on disk is still the single source.
    """
    return deepcopy(_parsed(seats.root / "seats.yaml"))


def _body_keys(node, where: tuple[str, ...] = ()) -> list[str]:
    """Every place in the loaded document a `body` key appears, dotted."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            path = (*where, str(key))
            if str(key) == BODY_KEY:
                found.append(".".join(path))
            found.extend(_body_keys(value, path))
    return found



def test_the_calls_mapping_holds_exactly_think_and_escalate(seats) -> None:
    """"holding `think` and `escalate` and no other block" (§ Deliverable 2, folded: S-A30).

    The other two call types configure nothing here at all: a spawn's whole process comes from a
    kind block, and kind blocks are build A.1.i's.
    """
    print(f"    [G10] calls: {sorted(seats.calls)}")
    assert sorted(seats.calls) == sorted(config.CONFIGURED_CALL_TYPES)
    assert config.CONFIGURED_CALL_TYPES == ("think", "escalate")
    payload = _seed(seats)
    assert sorted(payload[CALLS_BLOCK]) == ["escalate", "think"]
    # **Re-based by A.1.i** (§ Deliverable 1): the container is landed beside this mapping rather
    # than absent, and it is what the other two call types are configured by. Since A.2's library
    # (`the build specification (not in this mirror)` § Deliverables 1–2) each class holds exactly one kind,
    # `dispatch` holds `editor` and `delegate` holds `reader` — the claim this
    # assertion was making about `calls:` holds one container over, and
    # `tests/cortex/test_kinds.py` is where the container's own battery lives.
    assert set(payload[KINDS_BLOCK]) == {"dispatch", "delegate"}
    assert set(payload[KINDS_BLOCK]["dispatch"]) == {"editor"}
    assert set(payload[KINDS_BLOCK]["delegate"]) == {"reader"}
    assert set(seats.kinds) == set(config.KIND_CLASSES)
    assert set(seats.kinds["dispatch"]) == {"editor"} and set(seats.kinds["delegate"]) == {"reader"}


@pytest.mark.parametrize("call_type", list(config.CONFIGURED_CALL_TYPES))
def test_every_calls_block_carries_tier_keys_exactly(seats, call_type: str) -> None:
    """Not a subset and not a superset: the same ten keys a seat block takes."""
    payload = _seed(seats)
    assert sorted(payload[CALLS_BLOCK][call_type]) == sorted(TIER_KEYS)
    block = seats.call(call_type)
    assert block.model and block.effort, "its own model and effort"
    assert block.max_call_usd > 0 and block.timeout_seconds > 0, "its own two caps"
    assert block.prompt == f"seats/calls/{call_type}.md"
    assert block.prompt_path(seats.root).is_file(), "the prefix file is a seed on disk"
    assert seats.block(CallType(call_type)) is block, "one resolver for either addressee"


@pytest.mark.parametrize("call_type", list(config.CONFIGURED_CALL_TYPES))
def test_every_calls_block_is_toolless_and_declares_no_containment_of_its_own(
    seats, call_type: str
) -> None:
    """The containment is inherited from `runtime:` and `sandbox:`, never re-declared."""
    block = seats.call(call_type)
    assert block.tools == CALL_TOOLS and block.tools_argument() == ""
    assert block.add_dir is CALL_ADD_DIR
    assert block.allowed_tools == () and block.disallowed_tools == ()
    assert block.permission_mode is None
    assert "Task" not in block.allowed_tools and block.tools != "Task"


@pytest.mark.parametrize("call_type", list(config.CONFIGURED_CALL_TYPES))
def test_every_calls_block_is_strictly_below_the_managers_two_caps(seats, call_type) -> None:
    """"Token cheap is a configuration fact, not an intention" (digest §2.8, folded: S-A47)."""
    manager = seats.tier(CALL_CAP_REFERENCE_TIER)
    block = seats.call(call_type)
    for cap in CALL_CAP_KEYS:
        print(f"    [G10] {call_type}.{cap}={getattr(block, cap)} < "
              f"{manager.tier}.{cap}={getattr(manager, cap)}")
        assert getattr(block, cap) < getattr(manager, cap)


@pytest.mark.parametrize("key", list(TIER_KEYS))
def test_a_calls_block_missing_a_key_refuses_by_name(seats, key: str) -> None:
    payload = _seed(seats)
    del payload[CALLS_BLOCK]["think"][key]
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(payload, seats.root)
    assert key in str(raised.value) and "calls.think" in str(raised.value)


@pytest.mark.parametrize("eleventh", ["kinds", "workspace_path"])
def test_a_calls_block_carrying_an_eleventh_key_refuses_by_name(seats, eleventh: str) -> None:
    """`TIER_KEYS` exactly. The `body` arm lives with its worked example on the `body`-key test."""
    payload = _seed(seats)
    payload[CALLS_BLOCK]["escalate"][eleventh] = "terminal"
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(payload, seats.root)
    assert eleventh in str(raised.value) and "exactly" in str(raised.value)


@pytest.mark.parametrize("call_type", list(config.CONFIGURED_CALL_TYPES))
@pytest.mark.parametrize("cap,over", [("max_call_usd", 0.0), ("timeout_seconds", 0.0)])
def test_a_cap_at_or_above_the_managers_refuses_by_name(
    seats, call_type: str, cap: str, over: float
) -> None:
    """At the manager's figure is already a refusal: the rule is STRICTLY below."""
    ceiling = getattr(seats.tier(CALL_CAP_REFERENCE_TIER), cap)
    payload = _seed(seats)
    payload[CALLS_BLOCK][call_type][cap] = ceiling + over
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(payload, seats.root)
    assert cap in str(raised.value) and "STRICTLY below" in str(raised.value)


def test_a_cap_above_the_managers_on_a_third_block_never_reaches_the_cap_check(seats) -> None:
    """"and that check reaches those two blocks and nothing else" (row G10).

    A third block carrying a cap far above the manager's is refused as a block the mapping may
    not hold — it never reaches the comparison at all, because it never loads. That is what
    makes "reaches nothing else" a load-time fact rather than a claim about a code path.
    """
    payload = _seed(seats)
    manager = seats.tier(CALL_CAP_REFERENCE_TIER)
    payload[CALLS_BLOCK]["delegate"] = {
        **payload[CALLS_BLOCK]["think"],
        "max_call_usd": manager.max_call_usd * 10,
        "timeout_seconds": manager.timeout_seconds * 10,
    }
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(payload, seats.root)
    message = str(raised.value)
    print(f"    [G10] third block: {message[:110]}")
    # **Re-based by A.1.i** (route row R13): the refusal named a kind block as A.1.i's *future*
    # when this case was written; it now names the landed container instead. What the case asserts
    # is unchanged — the third block is refused before the cap comparison can see it.
    assert "delegate" in message and f"`{KINDS_BLOCK}:` container" in message
    assert "STRICTLY below" not in message, "the cap check never saw it"


@pytest.mark.parametrize("tools", ["Bash", ["Read"], None])
def test_a_calls_block_that_carries_a_tool_refuses_by_name(seats, tools) -> None:
    """Tool-less by **load-time refusal**, not by convention."""
    payload = _seed(seats)
    payload[CALLS_BLOCK]["think"]["tools"] = tools
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(payload, seats.root)
    assert "tools" in str(raised.value) and "tool-less" in str(raised.value)


def test_a_calls_block_that_asks_for_a_workspace_refuses_by_name(seats) -> None:
    payload = _seed(seats)
    payload[CALLS_BLOCK]["escalate"]["add_dir"] = True
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(payload, seats.root)
    assert "add_dir" in str(raised.value) and "tool-less" in str(raised.value)


def test_a_seed_with_no_calls_mapping_refuses_to_load(seats) -> None:
    """Eager like the sandbox block: a cheap seam authored by omission is the hole to close."""
    payload = {key: value for key, value in _seed(seats).items() if key != CALLS_BLOCK}
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(payload, seats.root)
    assert CALLS_BLOCK in str(raised.value)


def test_a_calls_mapping_missing_one_of_the_two_refuses_by_name(seats) -> None:
    payload = _seed(seats)
    del payload[CALLS_BLOCK]["escalate"]
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(payload, seats.root)
    assert "escalate" in str(raised.value)


@pytest.mark.parametrize("call_type", [CallType.DELEGATE, CallType.DISPATCH])
def test_delegate_and_dispatch_have_no_call_type_block_at_all(seats, call_type) -> None:
    """Their whole process comes from a kind block — **re-based by A.1.i's route row R13**: the
    refusal pointed at a build that had not happened, and now points at the landed container and
    at the resolver that reads it."""
    with pytest.raises(SeatConfigError) as raised:
        seats.call(call_type)
    message = str(raised.value)
    assert str(call_type) in message
    assert f"{KINDS_BLOCK}.{call_type}.<kind>" in message
    assert f"kind({str(call_type)!r}, <kind>)" in message


# --------------------------------------------------------------------------------------
# `runtime.body` — one key, two values, and a refusal for it anywhere else (row G13)
# --------------------------------------------------------------------------------------


def test_the_tracked_seed_carries_one_body_key_and_it_is_a_runtime_key(seats) -> None:
    """"`brain/seats.yaml` gains **`runtime.body`**, whose value is `print` or `terminal`"."""
    payload = _seed(seats)
    print(f"    [G13] runtime.body = {payload[RUNTIME_BLOCK][BODY_KEY]!r} -> {seats.body!r}")
    assert BODY_KEY in RUNTIME_KEYS, "it is a required runtime key, not an optional one"
    assert payload[RUNTIME_BLOCK][BODY_KEY] == seats.body == BODY_PRINT
    assert BODY_NAMES == (BODY_PRINT, BODY_TERMINAL)
    assert sorted(_body_keys(payload)) == [f"{RUNTIME_BLOCK}.{BODY_KEY}"], "one key, whole file"


@pytest.mark.parametrize("value", [BODY_PRINT, BODY_TERMINAL])
def test_both_legal_values_load(seats, value: str) -> None:
    payload = _seed(seats)
    payload[RUNTIME_BLOCK][BODY_KEY] = value
    assert parse_seats(payload, seats.root).body == value


@pytest.mark.parametrize(
    "illegal", ["interactive", "stream-json", "", None, "Print", "terminal-session", 1]
)
def test_a_body_value_outside_the_two_refuses_by_name(seats, illegal) -> None:
    """A body is a containment fact, so the refusal names the key and both legal values."""
    payload = _seed(seats)
    payload[RUNTIME_BLOCK][BODY_KEY] = illegal
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(payload, seats.root)
    print(f"    [G13] {illegal!r}: {str(raised.value)[:96]}")
    assert f"{RUNTIME_BLOCK}.{BODY_KEY}" in str(raised.value)
    assert BODY_PRINT in str(raised.value) and BODY_TERMINAL in str(raised.value)


def test_a_seed_with_no_body_key_at_all_refuses_by_name(seats) -> None:
    """Nothing here defaults: a root that names no body does not load (`RUNTIME_KEYS`)."""
    payload = _seed(seats)
    del payload[RUNTIME_BLOCK][BODY_KEY]
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(payload, seats.root)
    assert BODY_KEY in str(raised.value) and RUNTIME_BLOCK in str(raised.value)


@pytest.mark.parametrize("where", [str(tier) for tier in Tier] + ["oracle", SANDBOX_BLOCK])
def test_a_body_key_on_any_other_block_refuses_by_name(seats, where: str) -> None:
    """"the loader **refuses by name** a `body` key anywhere else in the file" (row G13).

    A tier block is the case `TIER_KEYS` alone would miss — it checks presence, not extras — so
    this is what makes the claim true of the whole document rather than of the two `calls:`
    blocks the eleventh-key rule already covers.
    """
    payload = _seed(seats)
    payload[where][BODY_KEY] = BODY_TERMINAL
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(payload, seats.root)
    print(f"    [G13] {where}.{BODY_KEY}: {str(raised.value)[:96]}")
    assert f"{where}.{BODY_KEY}" in str(raised.value)
    assert f"`{RUNTIME_BLOCK}.{BODY_KEY}`" in str(raised.value)


def test_a_body_key_at_the_top_level_or_nested_deeper_refuses_too(seats) -> None:
    """Walked, not enumerated — so it reaches whatever build A.1.i adds beside these blocks."""
    top = _seed(seats)
    top[BODY_KEY] = BODY_TERMINAL
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(top, seats.root)
    assert str(raised.value).startswith(f"{BODY_KEY}:")

    # **Re-based by A.1.i** (§ Deliverable 1, row G1): `kinds:` was the hypothetical "whatever
    # A.1.i adds" when this case was written, and it is now the landed container — so the case is
    # the same claim against the real thing, at both container levels the block parser never
    # reaches. `kinds.<class>.<kind>.body` is refused one level deeper by `parse_kinds()`'s own
    # `TIER_KEYS`-exactly check instead, exactly as a `calls:` block's is below.
    for location, mutate in (
        (f"{KINDS_BLOCK}.{BODY_KEY}", lambda node: node.update({BODY_KEY: BODY_TERMINAL})),
        (
            f"{KINDS_BLOCK}.dispatch.{BODY_KEY}",
            lambda node: node["dispatch"].update({BODY_KEY: BODY_TERMINAL}),
        ),
    ):
        nested = _seed(seats)
        mutate(nested[KINDS_BLOCK])
        with pytest.raises(SeatConfigError) as raised:
            parse_seats(nested, seats.root)
        print(f"    [G13] nested: {str(raised.value)[:96]}")
        assert str(raised.value).startswith(f"{location}:")


@pytest.mark.parametrize("call_type", list(config.CONFIGURED_CALL_TYPES))
def test_a_body_key_on_a_calls_block_is_refused_by_the_rule_that_already_forbids_it(
    seats, call_type: str
) -> None:
    """§ Deliverable 5: "`TIER_KEYS`-exactly already forbids a per-block one".

    The refusal a seed author sees for this case is the eleventh-key one (row G10), which names
    `body` too — the most specific refusal wins, and the walk above covers everywhere else.

    `body` is the worked example of `TIER_KEYS`-exactly: `runtime.body` is one key for the whole
    file (order W9's), and a body selectable per call is a body that could differ per call.
    """
    payload = _seed(seats)
    payload[CALLS_BLOCK][call_type][BODY_KEY] = BODY_TERMINAL
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(payload, seats.root)
    print(f"    [G13] {CALLS_BLOCK}.{call_type}.{BODY_KEY}: {str(raised.value)[:96]}")
    assert BODY_KEY in str(raised.value) and "exactly" in str(raised.value)
    assert f"{CALLS_BLOCK}.{call_type}" in str(raised.value)


# --------------------------------------------------------------------------------------
# Route R20 — the `bin_links` comment states the refusal the loader actually makes
# --------------------------------------------------------------------------------------


def test_the_bin_links_comment_states_the_binary_identity_refusal(seats) -> None:
    """R20's three-part Check, run as one test (§ Deliverable R).

    A route and not an amendment: it corrects a stale *comment* and changes no key the loader
    reads (folded: S-A6). The landed rule is `binary_paths()`' — a link that resolves to the
    seat binary **itself**, under any name — and sharing its *directory* is not disqualifying,
    which is exactly why the seed's own `uv` entry loads.
    """
    text = (seats.root / "seats.yaml").read_text(encoding="utf-8")
    comment = text.split("bin_links:")[0].rsplit("\n\n", 1)[-1]
    print(f"    [R20] {comment.strip().splitlines()[3].strip()[:100]}")
    assert "seat binary ITSELF" in comment
    assert "sharing the binary's directory is not disqualifying" in comment
    assert "resolved into the excluded directory" not in comment, "the stale rule is gone"
    assert "directory is\n  # refused at load" not in text
    assert seats.bin_links == ("uv",), "and the seed's own entry still loads"


# --------------------------------------------------------------------------------------
# The environment and the PATH
# --------------------------------------------------------------------------------------


def test_the_child_environment_is_five_variables_built_from_empty(seats) -> None:
    """No `RIG_*`, no `PROTEAN_*`, no `ANTHROPIC_*` — and nothing nobody thought of either.

    Five since S-37, not four: `USER` joined `PATH`, `HOME`, `LANG` and `TERM` because the
    keychain lookup the subscription resolves through answers "Not logged in" without the
    account name (measured, dispatch-5 ledger D5-8). What the row is about is unchanged — the
    environment is built by **allow-list from empty**, so the widening moved one name and not
    the rule.
    """
    parent = {
        "PATH": "/usr/bin",
        "HOME": "/home/someone",
        "LANG": "en_US.UTF-8",
        "TERM": "xterm",
        "USER": "someone",
        "RIG_API_KEY": "secret",
        "ANTHROPIC_API_KEY": "secret",
        "PROTEAN_BRAIN": "/somewhere",
        "SOMETHING_NOBODY_LISTED": "also secret",
    }
    child = seats.child_environment(parent)
    assert sorted(child) == sorted(ENV_ALLOWED)
    assert len(ENV_ALLOWED) == 5, "the ruled set (S-37), pinned so a sixth cannot arrive quietly"
    assert child["HOME"] == "/home/someone", "the credential resolves through HOME"
    assert child["USER"] == "someone", "and the keychain lookup that reads it needs the account"
    for leaked in ("RIG_API_KEY", "ANTHROPIC_API_KEY", "PROTEAN_BRAIN", "SOMETHING_NOBODY_LISTED"):
        assert leaked not in child


def test_the_seed_may_not_widen_the_environment_by_itself(seats) -> None:
    """Decision 19 is operator-ruled (S-26), so a sixth variable is refused in code, not in prose.

    S-37 moved the boundary from four names to five; it did not move it to "whatever the seed
    says". `SHELL` is one of the variables the D5-8 delta-debug measured as *insufficient* on
    its own, so it is exactly the kind of name a widening would reach for next.
    """
    payload = _seed(seats)
    payload["runtime"]["env_passthrough"] = [*ENV_ALLOWED, "SHELL"]
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(payload, seats.root)
    assert "SHELL" in str(raised.value)


def test_the_childs_path_cannot_resolve_the_binary(seats) -> None:
    """"a nested `claude` call from inside a session fails as command-not-found" (S-31)."""
    import shutil

    path = seats.child_path()
    assert shutil.which(seats.binary, path=path) is None
    for directory in seats.binary_directories():
        assert str(directory) not in path.split(os.pathsep)


def test_the_exclusion_covers_the_launcher_and_the_resolved_binary(seats) -> None:
    """The name on PATH is a symlink; excluding one of the two directories is excluding neither."""
    directories = seats.binary_directories()
    assert seats.resolved_binary().parent in directories
    assert seats.resolved_binary().is_file()


def test_naming_the_binarys_own_directory_in_the_path_list_does_not_re_open_it(seats) -> None:
    """The list is the seed's; the exclusion is enforced, because a binary moves machines."""
    payload = _seed(seats)
    payload["runtime"]["path"] = [str(directory) for directory in seats.binary_directories()]
    widened = parse_seats(payload, seats.root)
    assert widened.child_path() == "", "every named entry was the excluded directory"


# --------------------------------------------------------------------------------------
# The sandbox — the containment's kernel half (S-45)
# --------------------------------------------------------------------------------------


def test_the_deny_write_names_resolve_to_the_three_trees(seats) -> None:
    """Logical at the seed, absolute at load: two literal paths and one indirect name.

    The third tree is `policy_home` rather than a path because naming that path under `brain/`
    is what row W4's grep forbids — it is resolved through `protean.intake.policy_home`, the one module
    licensed to know where it is.
    """
    sandbox = seats.sandbox
    assert sandbox.names == ("~/workload", SANDBOX_NAME_BRAIN_ROOT, SANDBOX_NAME_POLICY_HOME)
    assert len(sandbox.deny_write) == 3
    assert sandbox.deny_write[0] == Path("~/workload").expanduser().resolve(), "the workload"
    assert sandbox.deny_write[1] == seats.root.resolve(), "this seed's own root"
    assert sandbox.deny_write[2] == policy_home.root(), "the policy home, never spelled here"
    for tree in sandbox.deny_write:
        assert tree.is_absolute(), "a relative subpath would silently deny nothing"


def test_the_profile_denies_file_writes_under_every_resolved_tree(seats) -> None:
    """The exact profile string the spawn carries, asserted against the trees it came from."""
    profile = seats.sandbox.profile()
    assert profile.startswith("(version 1)(allow default)(deny file-write* ")
    for tree in seats.sandbox.deny_write:
        assert f'(subpath "{tree}")' in profile
    assert "process-exec" not in profile, (
        "denying it blocks the sandboxed launch itself — measured, and not usable"
    )


def test_the_wrapper_puts_the_sandbox_in_front_of_whatever_it_is_given(seats) -> None:
    """`[<sandbox binary>, -p, <profile>, *argv]` — and the wrapped argv is what gets recorded."""
    wrapped = seats.sandbox.wrap(["/bin/echo", "hello"])
    assert wrapped[:2] == ["/usr/bin/sandbox-exec", SANDBOX_PROFILE_FLAG]
    assert wrapped[2] == seats.sandbox.profile()
    assert wrapped[3:] == ["/bin/echo", "hello"]


def test_the_profile_really_denies_a_write_under_a_named_tree(tmp_path: Path, seats) -> None:
    """Not a string assertion: the kernel's own answer, over a tree this test owns.

    The shipping profile's trees are not writable by the battery on purpose, so the mechanism is
    proven over a temporary one built by the same code path — the profile builder is the seed's.
    """
    import subprocess

    from protean.cortex.live.config import SandboxPolicy

    denied = tmp_path / "denied"
    denied.mkdir()
    policy = SandboxPolicy(
        binary=seats.sandbox.binary, names=(str(denied),), deny_write=(denied.resolve(),)
    )
    outside = subprocess.run(
        policy.wrap(["/bin/sh", "-c", f"echo ok > {tmp_path / 'allowed.txt'}"]),
        capture_output=True,
        text=True,
    )
    inside = subprocess.run(
        policy.wrap(["/bin/sh", "-c", f"echo no > {denied / 'x.txt'}"]),
        capture_output=True,
        text=True,
    )
    print(f"    [S-45] outside rc={outside.returncode} · inside rc={inside.returncode} "
          f"· {inside.stderr.strip()[:80]}")
    assert outside.returncode == 0 and (tmp_path / "allowed.txt").exists()
    assert inside.returncode != 0
    assert "Operation not permitted" in inside.stderr
    assert not (denied / "x.txt").exists()


@pytest.mark.parametrize(
    "entry", ["brain-root", "policy home", "policy-home", "workload", "$HOME/workload"]
)
def test_a_deny_write_entry_that_is_neither_a_path_nor_a_known_name_refuses(seats, entry) -> None:
    """No guessing: an entry that is not a path and not one of the two names is refused by name."""
    payload = _seed(seats)
    payload[SANDBOX_BLOCK]["deny_write"] = [entry]
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(payload, seats.root)
    assert entry in str(raised.value)


def test_an_empty_deny_write_list_is_refused(seats) -> None:
    """A profile that denies nothing is not a sandbox — the hole authored by omission."""
    payload = _seed(seats)
    payload[SANDBOX_BLOCK]["deny_write"] = []
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(payload, seats.root)
    assert "deny_write" in str(raised.value)


@pytest.mark.parametrize("key", ["binary", "deny_write"])
def test_a_sandbox_block_missing_a_key_refuses_by_name(seats, key: str) -> None:
    payload = _seed(seats)
    del payload[SANDBOX_BLOCK][key]
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(payload, seats.root)
    assert key in str(raised.value)


def test_a_seed_with_no_sandbox_block_refuses_to_load(seats) -> None:
    """Nothing defaults, least of all this: a live seat with no sandbox does not load."""
    payload = {
        key: value
        for key, value in _seed(seats).items()
        if key != SANDBOX_BLOCK
    }
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(payload, seats.root)
    assert SANDBOX_BLOCK in str(raised.value)


# --------------------------------------------------------------------------------------
# Refusals: a seed that does not say what a live seat needs
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key", ["model", "allowed_tools", "disallowed_tools", "tools", "max_call_usd", "prompt"]
)
def test_a_tier_block_missing_a_key_refuses_by_name(seats, key: str) -> None:
    payload = _seed(seats)
    del payload["manager"][key]
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(payload, seats.root)
    assert key in str(raised.value)


def test_an_unknown_layer_value_refuses_rather_than_guessing(seats) -> None:
    payload = _seed(seats)
    payload["layer"] = "probably-live"
    with pytest.raises(SeatConfigError):
        parse_seats(payload, seats.root)


def test_a_root_with_no_seats_file_is_not_an_error(tmp_path: Path) -> None:
    """Every build-1 root and every dry copy: no seats.yaml, and the scripted layer answers."""
    assert load_seats(tmp_path) is None


def test_a_bin_link_that_resolves_to_the_seat_binary_is_refused(tmp_path: Path, monkeypatch):
    """The farm exposes names one at a time; it may never expose the one it exists to exclude."""
    from protean.cortex.live.invoke import link_farm

    binaries = fake_cli.install(tmp_path / "bin")
    fake_cli.on_path(monkeypatch, binaries)
    root = fake_cli.seed_live_root(tmp_path / "brain")
    seats = fake_cli.seats_of(root)
    with pytest.raises(SeatConfigError) as raised:
        link_farm(
            [fake_cli.FAKE_BINARY], os.environ["PATH"], seats.binary_paths()
        )
    assert fake_cli.FAKE_BINARY in str(raised.value)


# --------------------------------------------------------------------------------------
# A.1.i's five `runtime:` keys — the four bounds and the writable list (row G1's last clauses)
# --------------------------------------------------------------------------------------

#: § Deliverable 5's table, transcribed, beside the writable list under it. The numbers are the operator's
#: rows B45 and B46 and no builder re-decides them; what these assert is that the seed carries them.
SPAWN_BOUNDS_SEEDED = {
    "spawn_max_call_usd": 5.0,
    "spawn_timeout_seconds": 1800.0,
    "max_wave_members": 4,
    "spawn_max_wave_usd": 10.0,
}

#: The shipping seed's writable list, as authored: the temp root the child falls back to, and uv's
#: cache as a **named entry** the leg-2 probe measured to be necessary — with the cache-poisoning
#: reach carried to the operator as row B51 (`tests/cortex/captures/spawn-profile.json` § interpreter).
SPAWN_WRITABLE_SEEDED = ["/tmp", "~/.cache/uv"]


def runtime_show(label: str, value) -> None:
    print(f"    [G1/RUNTIME_KEYS] {label}: {value}")


def test_runtime_keys_carries_the_four_bounds_and_the_writable_list(seats) -> None:
    """"`RUNTIME_KEYS` carries the four bound keys **and `spawn_writable`**" (row G1).

    The four are one tuple beside the key set rather than five loose strings, because order W4
    enforces them and the spawn ceilings' own reference map reads two of them by name.
    """
    runtime_show("RUNTIME_KEYS", list(RUNTIME_KEYS))
    assert SPAWN_BOUND_KEYS == tuple(SPAWN_BOUNDS_SEEDED)
    for key in (*SPAWN_BOUND_KEYS, SPAWN_WRITABLE_KEY):
        assert key in RUNTIME_KEYS, f"{key} is a required runtime key, not an optional one"
    assert sorted(SPAWN_CAP_CEILINGS) == ["max_call_usd", "timeout_seconds"]
    assert set(SPAWN_CAP_CEILINGS.values()) <= set(SPAWN_BOUND_KEYS)


def test_the_shipping_seed_carries_all_five_keys_with_deliverable_5s_values(seats) -> None:
    """The seed read back: the four bounds at § Deliverable 5's figures, and the writable list."""
    payload = _seed(seats)
    runtime = payload[RUNTIME_BLOCK]
    for key, value in SPAWN_BOUNDS_SEEDED.items():
        runtime_show(f"{RUNTIME_BLOCK}.{key}", runtime[key])
        assert float(runtime[key]) == float(value)
    assert seats.spawn_max_call_usd == SPAWN_BOUNDS_SEEDED["spawn_max_call_usd"]
    assert seats.spawn_timeout_seconds == SPAWN_BOUNDS_SEEDED["spawn_timeout_seconds"]
    assert seats.max_wave_members == SPAWN_BOUNDS_SEEDED["max_wave_members"]
    assert seats.spawn_max_wave_usd == SPAWN_BOUNDS_SEEDED["spawn_max_wave_usd"]

    runtime_show(f"{RUNTIME_BLOCK}.{SPAWN_WRITABLE_KEY}", runtime[SPAWN_WRITABLE_KEY])
    assert runtime[SPAWN_WRITABLE_KEY] == SPAWN_WRITABLE_SEEDED
    assert seats.spawn_writable == tuple(
        Path(entry).expanduser().resolve() for entry in SPAWN_WRITABLE_SEEDED
    ), "resolved at load, because sandbox-exec matches a subpath against the realpath"
    for tree in seats.spawn_writable:
        assert tree.is_dir(), "required to exist: a tree the machine lacks is a hole by typo"


@pytest.mark.parametrize("key", [*SPAWN_BOUND_KEYS, SPAWN_WRITABLE_KEY])
def test_a_seed_missing_any_one_of_the_five_refuses_by_name(seats, key: str) -> None:
    """"a seed missing any one of the five refuses by name" (row G1).

    One check does it — `_require(runtime, RUNTIME_KEYS, RUNTIME_BLOCK)` — which is why the five
    keys and the five seed values are one order's: either both land or the shipping root stops
    loading (ledger entry V2-2).
    """
    payload = _seed(seats)
    del payload[RUNTIME_BLOCK][key]
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(payload, seats.root)
    runtime_show(f"missing {key}", str(raised.value)[:110])
    assert key in str(raised.value) and RUNTIME_BLOCK in str(raised.value)


@pytest.mark.parametrize("value", ["not a number", None, [5.0]])
def test_a_bound_whose_value_is_not_a_number_refuses_by_name(seats, value) -> None:
    """Nothing defaults and nothing guesses: a ceiling the loader cannot read does not bind."""
    payload = _seed(seats)
    payload[RUNTIME_BLOCK]["spawn_max_call_usd"] = value
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(payload, seats.root)
    assert "spawn_max_call_usd" in str(raised.value)


def test_a_writable_entry_that_does_not_resolve_to_an_existing_tree_refuses_by_name(
    seats, tmp_path: Path
) -> None:
    """"a `spawn_writable` entry that does not resolve to an existing tree refuses by name"
    (row G1, folded: S-i20) — a tree the composed profile would allow and the machine does not
    have is invisible once composed, so it is refused where it is still readable."""
    missing = tmp_path / "no-such-tree"
    payload = _seed(seats)
    payload[RUNTIME_BLOCK][SPAWN_WRITABLE_KEY] = [str(missing)]
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(payload, seats.root)
    runtime_show("absent tree", str(raised.value)[:130])
    assert str(missing) in str(raised.value)
    assert SPAWN_WRITABLE_KEY in str(raised.value) and "typo" in str(raised.value)


@pytest.mark.parametrize("tree", [SANDBOX_NAME_BRAIN_ROOT, "~/workload", SANDBOX_NAME_POLICY_HOME])
def test_a_writable_entry_inside_a_denied_tree_refuses_at_load_by_name(seats, tree: str) -> None:
    """"a `spawn_writable` entry that resolves **inside any `sandbox.deny_write` tree** refuses at
    load by name" (row G1, folded: S-i43).

    The collision matters because the inverted profile carries no deny clause to win it back:
    `(allow file-write* (subpath X))` under a tree the seed denied simply **grants** the write. So
    the seed's two lists are made non-overlapping at the only moment either can be read. One case
    per denied tree, each asked with a subdirectory rather than the tree itself, because nesting is
    the shape a seed author actually writes.
    """
    resolved = {
        SANDBOX_NAME_BRAIN_ROOT: seats.root.resolve(),
        "~/workload": Path("~/workload").expanduser().resolve(),
        SANDBOX_NAME_POLICY_HOME: policy_home.root(),
    }[tree]
    inside = resolved / "state"
    payload = _seed(seats)
    payload[RUNTIME_BLOCK][SPAWN_WRITABLE_KEY] = [str(inside)]
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(payload, seats.root)
    runtime_show(f"collision with {tree}", str(raised.value)[:140])
    assert str(inside) in str(raised.value) and str(resolved) in str(raised.value)
    assert f"{SANDBOX_BLOCK}.deny_write" in str(raised.value)


@pytest.mark.parametrize("entry", ["tmp", "brain_root", "$HOME/scratch", "./tmp"])
def test_a_writable_entry_that_is_not_a_path_refuses_by_name(seats, entry: str) -> None:
    """A `deny_write` entry may be one of two logical names; a `spawn_writable` entry may not.

    It is a list of `~`/`/` paths (§ Deliverable 5) and nothing else — the trees a spawn may write
    are read off the seed and never guessed, which is `_sandbox_tree()`'s own rule one key over.
    """
    payload = _seed(seats)
    payload[RUNTIME_BLOCK][SPAWN_WRITABLE_KEY] = [entry]
    with pytest.raises(SeatConfigError) as raised:
        parse_seats(payload, seats.root)
    assert entry in str(raised.value) and SPAWN_WRITABLE_KEY in str(raised.value)


def test_an_empty_writable_list_loads_and_allows_no_tree_at_all(seats) -> None:
    """The key is required; its **contents** are the seed author's, and empty is a legal narrowing.

    Unlike `sandbox.deny_write`, where empty is the hole S-45 exists to close, an empty allowed set
    under a write-denied-by-default profile is the *narrowest* possible statement rather than the
    widest. A `dispatch` spawn would still get the task workspace; a `delegate` spawn would get
    nothing writable at all.
    """
    payload = _seed(seats)
    payload[RUNTIME_BLOCK][SPAWN_WRITABLE_KEY] = []
    loaded = parse_seats(payload, seats.root)
    runtime_show("empty writable list", loaded.spawn_writable)
    assert loaded.spawn_writable == ()


# --------------------------------------------------------------------------------------
# The per-spawn composition, beside the seats' landed profile (row G3's own module half)
# --------------------------------------------------------------------------------------


def test_the_seats_landed_profile_is_unchanged_by_the_inversion(seats) -> None:
    """"the seats' landed `profile()` is unchanged" — the inversion belongs to the spawn path alone
    (B26's class), so nothing that runs today changes shape."""
    profile = seats.sandbox.profile()
    runtime_show("seats profile", profile[:90])
    assert profile.startswith(f"{PROFILE_HEAD}(deny file-write* ")
    assert "(allow file-write*" not in profile, "the seats' shape is allow-default over a deny list"
    assert PROFILE_HEAD == "(version 1)(allow default)", "retained verbatim by the composition"


def test_a_composed_spawn_profile_denies_writes_then_allows_the_named_set(seats, tmp_path) -> None:
    """The composed literal, stated whole in § Deliverable 2 and built here from the same policy.

    Two clauses appended to the landed head: `(deny file-write*)`, then one `(allow file-write* …)`
    carrying directories as `(subpath …)` and devices as `(literal …)`. `process-exec` is never
    denied — the deny reaches the sandboxed launch itself and nothing runs (measured 2026-09-07).
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    composed = seats.sandbox.spawn_profile(
        subpaths=(workspace, *seats.spawn_writable), literals=("/dev/null",)
    )
    runtime_show("composed", composed[:120])
    assert composed.startswith(f"{PROFILE_HEAD}(deny file-write*)(allow file-write* ")
    assert f'(subpath "{workspace}")' in composed
    for tree in seats.spawn_writable:
        assert f'(subpath "{tree}")' in composed
    assert '(literal "/dev/null")' in composed
    assert "process-exec" not in composed
    for denied in seats.sandbox.deny_write:
        assert f'(subpath "{denied}")' not in composed, "the deny list is reached by the default"


def test_the_wrapper_puts_the_sandbox_in_front_of_a_composed_spawn_profile_too(seats) -> None:
    """One wrapper, now able to wrap a composed spawn profile as well as the seats' landed one —
    `argv[0]` stays the sandbox binary, which is row G3's own clause."""
    composed = seats.sandbox.spawn_profile(subpaths=seats.spawn_writable)
    wrapped = seats.sandbox.wrap(["/bin/echo", "hi"])
    spawn_wrapped = [seats.sandbox.binary, SANDBOX_PROFILE_FLAG, composed, "/bin/echo", "hi"]
    runtime_show("argv[0]", spawn_wrapped[0])
    assert wrapped[0] == spawn_wrapped[0] == seats.sandbox.binary
    assert spawn_wrapped[1] == SANDBOX_PROFILE_FLAG


# --------------------------------------------------------------------------------------
# Route row R13 — the `kinds:` paragraph, and both forward references re-pointed
# --------------------------------------------------------------------------------------

#: The three sentences R13 corrects. Each called a kind block build A.1.i's **future**, and the
#: landed container is what makes them false. None may survive anywhere in the module.
R13_FUTURE_SENTENCES = (
    "from a kind block build A.1.i defines",
    "a kind block is build A.1.i's",
    "a `kinds:` container is build A.1.i's",
)

#: The body walk's own docstring sentence, which R13 leaves **exactly** as written. The function is
#: unedited by name (it is what refuses `kinds.body` and `kinds.<class>.body`), and its claim about
#: reaching "anything build A.1.i later adds" is not a forward reference to a kind block: it is the
#: sentence row G1 is the receipt of, and it stays true of the landed container.
R13_WALK_SENTENCE = "`oracle:` block, the top level and **anything build A.1.i later adds**"


def test_no_docstring_in_this_module_calls_a_kind_block_future() -> None:
    """R13's own `Check` column, first clause: "no docstring in the file calls a kind block future"."""
    text = (config.repo_root() / "src" / "protean" / "cortex" / "live" / "config.py").read_text(
        encoding="utf-8"
    )
    for sentence in R13_FUTURE_SENTENCES:
        assert sentence not in text, f"R13 corrects: {sentence!r}"
    runtime_show("body walk sentence kept", R13_WALK_SENTENCE[:40])
    assert R13_WALK_SENTENCE in text, "the walk's docstring is unedited, and its claim is landed"


def test_the_module_docstring_names_the_container_the_bounds_and_the_writable_list() -> None:
    """R13's second clause: "the docstring names the container, the four bounds and the writable
    list"."""
    import protean.cortex.live.config as module

    docstring = module.__doc__ or ""
    runtime_show("docstring names kinds:", "`kinds:` container" in docstring)
    assert "`kinds:` container" in docstring
    for key in (*SPAWN_BOUND_KEYS, SPAWN_WRITABLE_KEY):
        assert key in docstring, f"{key} is named in the docstring R13 re-pointed"
    assert "RUNTIME_KEYS" in docstring and "TIER_KEYS" in docstring
    assert "resolved and required to **exist**" in docstring
