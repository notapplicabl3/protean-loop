"""`brain/seats.yaml` → every block's invocation configuration, and the child's environment.

`the build specification (not in this mirror)` § Deliverable 1's `brain/seats.yaml` table and its
containment paragraph (folded: A1-1, folded: A1-2, folded: S-5, folded: S-30, folded: S-31),
and § Directional decisions 9 — **the live seat is configuration, not code**.

**Build A.1 adds the `calls:` mapping** (`the build specification (not in this mirror)` § Deliverable 2,
row G10): two blocks, `think` and `escalate`, and **no third** — those two configure a model
call and the other two call types configure nothing here, because a spawn's whole process comes
from a kind block, which lives in the `kinds:` container beside them. Each takes `TIER_KEYS` **exactly**, so the containment
the two seats run under resolves for them unchanged rather than being re-declared per block,
and four things refuse **by name** at load: a missing or an eleventh key, a cap that is not
strictly below the manager's, `tools` other than `""`, and `add_dir` other than `False`. The
strictly-below rule reaches those two blocks and nothing else — a spawn is not a cheap advisory
call, and measuring one against the conductor's budget is the wrong comparison (folded: S-A47,
folded: S-A70).

**Build A.1.i adds the `kinds:` container beside it** (`the build specification (not in this mirror)`
§ Deliverables 1, 2 and 5; route row R13). It is **grouped by class** — one sub-mapping per
`config.KIND_CLASSES` name, the class being the sub-mapping and never a key on the block — and each
kind block takes `TIER_KEYS` **exactly** as a `calls:` block does, so the containment resolves for a
spawn unchanged rather than being re-declared per kind. The parsing lives next door in
`protean.cortex.live.kinds` with the licensed capability literals it refuses against; what lives
here is the `runtime:` half it reads. **`RUNTIME_KEYS` therefore carries five more keys**: the four
static bounds `spawn_max_call_usd`, `spawn_timeout_seconds`, `max_wave_members` and
`spawn_max_wave_usd` — a seed missing one is a bound the loader cannot require, which is not a bound
— and **`spawn_writable`**, the list of trees a spawn may write outside the task workspace, every
entry resolved and required to **exist** at load and refused where it resolves **inside** a
`sandbox.deny_write` tree. `SandboxPolicy` gains the per-**spawn** composition those trees feed:
write-denied by default over a per-class allowed set, the seats' own allow-default profile
unchanged.

**Nothing here defaults.** Every key the SPEC's table names is required of every tier, and a
block missing one refuses by name at load time. That is deliberate on a T3 surface: a
half-authored `disallowed_tools` that quietly loaded as the empty list would be a containment
hole authored by omission, and the whole point of putting the containment in a *seed* is that
it is reviewable as data.

**The file is a seed.** It is hashed into the checkpoint through
`protean.brain.folders.seed_hashes()`, so editing it mid-task is a drift refusal and re-making
Q4's model choice on build 2's own numbers is a seed edit under `resume --reseed`.

**`layer:` is what keeps `protean dry` working with no flag and no second factory.** It selects
the scripted seats or the live ones; a root with no `seats.yaml` at all — every build-1 test
root, and the copy `protean dry` makes — has no live block to read and stays scripted.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from protean import config as protean_config
from protean.cortex.calls import REFUSAL_CAP_EXCEEDED
from protean.intake import policy_home
from protean.runtime.paths import BrainPaths
from protean.state.calls import BODY_NAMES, BODY_PRINT
from protean.state.enums import Addressee, CallType, Tier

if TYPE_CHECKING:  # the import runs the other way at call time (see `parse_seats()`)
    from protean.cortex.live.kinds import KindBlock

#: The two values `layer:` may take. Anything else refuses rather than guessing.
LAYER_LIVE = "live"
LAYER_SCRIPTED = "scripted"
LAYERS: tuple[str, ...] = (LAYER_LIVE, LAYER_SCRIPTED)

#: The block that is not a tier: the binary, the `PATH` list, and the environment allow-list.
RUNTIME_BLOCK = "runtime"

#: The other block that is not a tier: the kernel half of the containment (S-45).
SANDBOX_BLOCK = "sandbox"

#: The A.1 block that is not a tier either: the two call types that configure a model call
#: (§ Deliverable 2, folded: S-A30). Its keys are `config.CONFIGURED_CALL_TYPES` exactly.
CALLS_BLOCK = "calls"

#: The only `tools:` and `add_dir:` values a `calls:` block may carry — **tool-less by load-time
#: refusal, not by convention** (row G10). A node asking a short question decides nothing about
#: the workspace, so a tool on this surface is a hole authored by a seed edit; both are refused
#: by name if either moves. The two seats' own values are build 2's and are not policed here.
CALL_TOOLS = ""
CALL_ADD_DIR = False

#: The tier whose two caps every `calls:` block must be **strictly below** (folded: S-A47). The
#: manager is the conductor, and "token cheap" is measured against it rather than against the
#: director, whose own budget is smaller and is not what a node's advisory call is compared to.
CALL_CAP_REFERENCE_TIER = Tier.MANAGER

#: The two cap keys the strictly-below rule reads, named once so the refusal and the check
#: cannot drift apart.
CALL_CAP_KEYS: tuple[str, ...] = ("max_call_usd", "timeout_seconds")

#: Every key the sandbox block must carry. Nothing defaults here either.
SANDBOX_KEYS: tuple[str, ...] = ("binary", "deny_write")

#: The two logical names a `deny_write` entry may be instead of a path. `brain_root` is the root
#: the seed was loaded from; `policy_home` is resolved through `protean.intake.policy_home`, the one
#: module licensed to know where the policy home is — which is why the seed can name that tree
#: without writing its path under `brain/`, where row W4's grep forbids it.
SANDBOX_NAME_BRAIN_ROOT = "brain_root"
SANDBOX_NAME_POLICY_HOME = "policy_home"
SANDBOX_NAMES: tuple[str, ...] = (SANDBOX_NAME_BRAIN_ROOT, SANDBOX_NAME_POLICY_HOME)

#: `sandbox-exec`'s own profile flag. Spelled here rather than beside the CLI's flags because it
#: belongs to the wrapper, not to the binary being wrapped — the two both happen to be `-p`.
SANDBOX_PROFILE_FLAG = "-p"

#: The head a composed **spawn** profile begins with, **retained verbatim** from the seats' landed
#: one (A.1.i § Directional decisions 4): the per-spawn inversion is two clauses appended to a landed
#: literal rather than a second profile language.
#:
#: `SandboxPolicy.profile()` below is **unedited** and still spells its own head inline — the two
#: spellings are deliberate, and they are what makes the retention checkable rather than asserted:
#: `tests/cortex/test_live_config.py` compares the seats' landed string against this constant, which
#: a single shared literal could not do.
PROFILE_HEAD = "(version 1)(allow default)"

#: The permission mode both T3 surfaces run under, and the one they refuse.
#:
#: **MEASURED, S-44 (2026-09-07).** On CLI 2.1.263 under `--permission-mode auto` the positive
#: allow-list does not bind at all: unlisted tools ran and the envelope came back with
#: `permission_denials: []`. Under `dontAsk`, beside an explicit `--tools` set, every unlisted
#: call is denied and named in `permission_denials`. So `auto` is not a weaker mode on a T3
#: surface, it is *no* mode, and the loader refuses it rather than shipping the hole again.
PERMISSION_MODE_BINDING = "dontAsk"
PERMISSION_MODES_REFUSED: tuple[str, ...] = ("auto",)

#: Every key a tier block must carry (§ Deliverable 1's table). Presence is checked; the
#: values are the seed author's.
TIER_KEYS: tuple[str, ...] = (
    "model",
    "effort",
    "permission_mode",
    "allowed_tools",
    "disallowed_tools",
    "tools",
    "add_dir",
    "max_call_usd",
    "timeout_seconds",
    "prompt",
)

#: The four static bounds build A.1.i adds to the `runtime:` block
#: (`the build specification (not in this mirror)` § Deliverable 5, A1-6, folded: S-i16). **All four
#: live here rather than on `manager:`** and that closes K1 by construction: a tier block's shape is
#: the ten `TIER_KEYS`, so an eleventh key there is tolerated by accident rather than required by
#: the loader, and a bound the loader cannot require is not a bound. What they bound is **configured
#: caps, not spend** (folded: S-i25), and the wave arithmetic that reads the last two is the spawn
#: desk's, never this module's.
SPAWN_BOUND_KEYS: tuple[str, ...] = (
    "spawn_max_call_usd",
    "spawn_timeout_seconds",
    "max_wave_members",
    "spawn_max_wave_usd",
)

#: Which of a kind block's own two caps each **spawn** ceiling is the reference for — the map
#: `protean.cortex.live.kinds` refuses a block above at load (§ Deliverable 2's fourth resolution
#: refusal). Named once here, beside the keys, so the refusal and the seed read the same.
SPAWN_CAP_CEILINGS: Mapping[str, str] = {
    "max_call_usd": "spawn_max_call_usd",
    "timeout_seconds": "spawn_timeout_seconds",
}

#: The path list beside the four bounds, which is **not** a bound (folded: S-i20): the trees a spawn
#: may write **outside** the task workspace, read by the composed per-spawn profile below. It is a
#: list of `~`/`/` paths, every entry resolved and required to exist at load — a tree the profile
#: would allow and the machine does not have is a hole authored by typo.
SPAWN_WRITABLE_KEY = "spawn_writable"

#: The per-tick delegate bound (`the build specification (not in this mirror)` § Deliverable 1, row B66): how
#: many `delegate` calls the outer nodes may plan in one tick. **It is applied by the runtime's call
#: policy when the plan is made, in `NODE_ORDER`** — a delegate past it is not planned — and never
#: by a desk; this module only reads it off the seed. A non-negative integer, `0` legal.
DELEGATE_BOUND_KEY = "max_tick_delegates"

#: Every key the runtime block must carry. **`body` joined it in build A.1** (§ Deliverable 5,
#: folded: S-A78): one key for the whole file, whose value is `print` or `terminal` and which
#: applies to the **two cortex seats only**. **The four bounds and `spawn_writable` joined it in
#: A.1.i** (ledger entry V2-2): the keys and their seed values land together, because `_require()`
#: below is what refuses a `runtime:` block missing any one of them. **A.2.i joins one key, the
#: per-tick delegate bound**, required at load on the same rule (§ Scaffold clause item 2(b)).
RUNTIME_KEYS: tuple[str, ...] = (
    "binary",
    "path",
    "bin_links",
    "env_passthrough",
    "body",
    *SPAWN_BOUND_KEYS,
    SPAWN_WRITABLE_KEY,
    DELEGATE_BOUND_KEY,
)

#: The key itself, named once so the refusal below and the `runtime:` block read the same.
#:
#: **It is legal at `runtime.body` and nowhere else in the file** (§ Deliverable 5, row G13). A
#: `body` on a `calls:` block is already refused by `TIER_KEYS`-exactly; this refuses it on a
#: tier block, on `oracle:`, at the top level and on anything build A.1.i later adds — because a
#: body selectable per call is a body that could differ per call, and the whole configuration
#: surface is meant to be one key.
BODY_KEY = "body"

#: The five variables a seat process may inherit (folded: S-31, folded: S-37). The seed names
#: them so the scrub is reviewable, and this tuple is what it is checked against: a `seats.yaml`
#: that added a sixth would be widening the T3 containment, which only the operator does.
#:
#: **`USER` is the fifth, and it is a ruling rather than a builder's default** (S-37): under the
#: four the CLI's keychain lookup answers `Not logged in · Please run /login` before it reaches
#: the API (measured, dispatch-5 ledger D5-8). A username is not a credential — it carries no
#: secret and no path — so the T3 reading decision 19 protects is untouched by it.
ENV_ALLOWED: tuple[str, ...] = ("PATH", "HOME", "LANG", "TERM", "USER")


class SeatConfigError(ValueError):
    """`brain/seats.yaml` is present but does not say what a live seat needs.

    A refusal rather than a default: see the module docstring. It is a `ValueError` and not a
    `ProteanError` because it is a malformed *seed*, caught at layer build, not a refusal the
    operator surface maps to an exit code.
    """


class CallCapExceeded(SeatConfigError):
    """A `calls:` block's own cap, crossed on a live call.

    **Raised at the site that enforces the cap** (`the build specification (not in this mirror)`
    § Resolutions D5-8): this module owns the two caps, so this module is where crossing one is
    named. It is deliberately **not** `SeatUnavailable` — row G10's clause is that a call
    exceeding either of its caps "fabricates no envelope, returning a refusal to the calling
    node", and the other three refusal classes are type-classified in `protean.cortex.calls`
    while this one is produced where the cap lives.

    `reason` is the refusal class the calling node's desk records it under, carried on the
    exception rather than re-typed at the catch site: `NodeCallDesk.refuse()` is public for
    exactly this (`protean.cortex.calls`, "the cap class is produced where the cap is
    enforced"), so a caller reads the class off the fault instead of deciding it.
    """

    #: The `protean.cortex.calls` refusal class this fault is recorded under.
    reason = REFUSAL_CAP_EXCEEDED

    def __init__(self, addressee: str, cap: str, limit: float, detail: str = "") -> None:
        self.addressee = addressee
        self.cap = cap
        self.limit = limit
        super().__init__(
            f"{CALLS_BLOCK}.{addressee}: the call crossed its own {cap} of {limit}"
            + (f" ({detail})" if detail else "")
            + " — no envelope is fabricated and the calling node gets a "
            f"{REFUSAL_CAP_EXCEEDED!r} refusal"
        )


def tools_argument(tools: str | Sequence[str] | None) -> str | None:
    """The seed's `tools:` value → the one `--tools` argument, or `None` to omit the flag.

    Three shapes, because the seed carries three (S-44): `null` omits the flag, `""` is the
    proven toollessness the director and manager ship, and a **list** is the tool set an
    acting surface runs under — joined with commas **in the seed's order**, because that order is
    what a reviewer reads and what the recorded argv has to show back.

    One function shared by the cortex and oracle surfaces, so both serialize the tool set
    through the same path. Kind-specific grants and profiles are resolved separately.
    """
    if tools is None or isinstance(tools, str):
        return tools
    return ",".join(tools)


@dataclass(frozen=True, slots=True)
class TierSeat:
    """One block, as data. Every field is read off the seed; none is computed.

    A tier's block, or — from build A.1 — one of the two `calls:` blocks, which take the same
    ten keys exactly. One dataclass and not two: the containment, the argv and the caps are the
    same facts whether the addressee is a seat or a call type, and a second shape would give
    them a second code path (§ Deliverable 2, decision 10). `tier` holds the block's own name.
    """

    tier: str
    model: str
    effort: str
    permission_mode: str | None
    allowed_tools: tuple[str, ...]
    disallowed_tools: tuple[str, ...]
    tools: str | tuple[str, ...] | None
    add_dir: bool
    max_call_usd: float
    timeout_seconds: float
    prompt: str

    def prompt_path(self, root: Path) -> Path:
        """The tier half of the stable prefix, resolved against the brain root."""
        return root / self.prompt

    def tools_argument(self) -> str | None:
        """What `--tools` is given for this tier, or `None` when the flag is omitted."""
        return tools_argument(self.tools)


@dataclass(frozen=True, slots=True)
class SandboxPolicy:
    """The kernel half of the containment: the trees no spawned process may write (S-45).

    `names` is what the seed said and `deny_write` is what those names resolved to at load time,
    kept side by side so a receipt can show both — the seed is reviewable as data and the profile
    is checkable as paths.

    **What the profile says, and why it says no more.** `(allow default)` with one `deny
    file-write*`: a narrowing of one verb over named trees, not an attempt at a whole-machine
    jail. Denying `process-exec` was measured and is not usable — the deny reaches the sandboxed
    launch itself and nothing runs at all (2026-09-07).
    """

    binary: str
    names: tuple[str, ...]
    deny_write: tuple[Path, ...]

    def profile(self) -> str:
        """The `sandbox-exec -p` profile, built from the resolved trees."""
        subpaths = " ".join(f'(subpath "{tree}")' for tree in self.deny_write)
        return f"(version 1)(allow default)(deny file-write* {subpaths})"

    def spawn_profile(
        self, *, subpaths: Sequence[Path | str], literals: Sequence[str] = ()
    ) -> str:
        """The **inverted** profile one spawn runs under: write-denied by default, then allowed.

        `the build specification (not in this mirror)` § Deliverable 2's kernel half, § Directional
        decisions 4, A1-4 (folded: S-i20, folded: S-i38). The seats' `profile()` above is
        `(allow default)` over a deny list, which is the right shape for a seat and the **wrong**
        shape for a kind: a `dispatch` kind licensed to run `Bash(uv:*)` could write anywhere that
        list did not name — `~/protean/src`, `~/.ssh`, every repo on this machine — and no audit
        list would see it, because all four derive from the granted workspace and the envelope's own
        denials. So a spawn's profile denies `file-write*` outright and allows it back under named
        subpaths only, which makes a tree nobody listed unwritable by construction.

        **Two clauses appended to a landed literal, never a second profile language:** `PROFILE_HEAD`
        is retained verbatim, `file-write*` is re-denied over it, and the allowed set follows —
        directories as `(subpath …)` and devices as `(literal …)`. **`process-exec` is never
        denied**: the deny reaches the sandboxed launch itself and nothing runs at all (measured
        2026-09-07), so it is a break rather than a narrowing.

        **The paths are the caller's to have resolved**, and it matters: `sandbox-exec` matches a
        subpath against the **realpath**, so a clause spelled `/tmp` on a machine where that is a
        symlink to `/private/tmp` matches nothing the kernel is ever asked about (measured by
        `tests/cortex/probe_profile.py`, whose first run watched the stand-in fail to write its own
        allowed directory). `parse_spawn_writable()` and the desk's workspace both resolve.
        """
        allowed = " ".join(
            [f'(subpath "{tree}")' for tree in subpaths]
            + [f'(literal "{device}")' for device in literals]
        )
        return f"{PROFILE_HEAD}(deny file-write*)(allow file-write* {allowed})"

    def wrap(self, argv: Sequence[str]) -> list[str]:
        """`[<sandbox binary>, -p, <profile>, *argv]` — the argv as it is really spawned.

        Every seat call and every measured session goes through here, including the toolless
        tiers: one code path, so a tier that ever gained a tool cannot gain it outside the
        sandbox. The wrapped list is what `SeatCallFacts.argv` records, because it is what ran.
        """
        return [self.binary, SANDBOX_PROFILE_FLAG, self.profile(), *argv]


@dataclass(frozen=True, slots=True)
class SeatsConfig:
    """The whole file: which layer, the two seats, the two `calls:` blocks, the `kinds:`
    container, the spawn bounds, and the child's execution environment.

    `calls` defaults to empty so a surface that builds a containment object directly rather than
    from a seed — `protean.oracle.config`, which carries no seats and no call types — is
    unchanged by A.1. **`kinds` defaults empty for the same reason one build on**: a containment
    object built directly carries no kinds either, and A.1.i's own shipping seed defines none.
    """

    root: Path
    layer: str
    binary: str
    path_entries: tuple[str, ...]
    bin_links: tuple[str, ...]
    env_passthrough: tuple[str, ...]
    tiers: Mapping[str, TierSeat]
    sandbox: SandboxPolicy
    calls: Mapping[str, TierSeat] = field(default_factory=dict)
    #: The `kinds:` container, grouped by class — `{class: {kind: KindBlock}}` (A.1.i
    #: § Deliverable 1, seam contract I1). Empty for `protean.oracle.config`'s reason above, and
    #: **both sub-mappings empty in the shipping seed**, which defines no kind at all.
    kinds: Mapping[str, Mapping[str, "KindBlock"]] = field(default_factory=dict)
    #: `runtime.body` — `print` or `terminal`, applying to the **two cortex seats only**
    #: (§ Deliverable 5, folded: S-A78). It defaults to `print` for the same reason `calls`
    #: defaults to empty: a containment object built directly rather than from a seed
    #: (`protean.oracle.config`) carries no seats and selects no body.
    body: str = BODY_PRINT
    #: A.1.i's four static bounds and the writable list beside them (§ Deliverable 5, A1-6). **The
    #: seed path is strict** — all five are in `RUNTIME_KEYS` — and these defaults are for the same
    #: surface `calls` and `kinds` default empty for: a containment object built directly rather
    #: than from a seed (`protean.oracle.config`) opens no spawn desk and spawns nothing. Zero is
    #: the safe default for exactly that reason: a ceiling of zero refuses every spawn, and an empty
    #: writable list allows no tree at all.
    spawn_max_call_usd: float = 0.0
    spawn_timeout_seconds: float = 0.0
    max_wave_members: int = 0
    spawn_max_wave_usd: float = 0.0
    #: Resolved at load, required to exist, and refused inside any `sandbox.deny_write` tree
    #: (folded: S-i20, folded: S-i43). **What reads it is the composed per-spawn profile**; what
    #: enforces the four bounds above is the spawn desk.
    spawn_writable: tuple[Path, ...] = ()
    #: `runtime.max_tick_delegates`, the per-tick delegate bound (A.2.i § Deliverable 1). **The
    #: seed path is strict** — the key is in `RUNTIME_KEYS` — and zero is the default for the reason
    #: the four bounds default to it: a containment object built directly opens no call desk, and a
    #: bound of zero plans no delegate at all.
    max_tick_delegates: int = 0

    @property
    def is_live(self) -> bool:
        return self.layer == LAYER_LIVE

    def tier(self, tier: Tier | str) -> TierSeat:
        """One tier's block, or a refusal naming the tier the seed did not configure."""
        key = str(Tier(tier))
        if key not in self.tiers:
            raise SeatConfigError(f"seats.yaml configures no {key!r} block")
        return self.tiers[key]

    def call(self, call_type: CallType | str) -> TierSeat:
        """One `calls:` block, or a refusal naming the call type the seed does not configure.

        `delegate` and `dispatch` land here: they are addressees with **no call-type block at
        all**, and the refusal says so rather than implying the seed forgot one — their whole
        process comes from a kind block, which `kind()` below resolves out of the `kinds:`
        container (A.1.i § Deliverable 1, route row R13).
        """
        from protean.cortex.live.kinds import KINDS_BLOCK

        key = str(CallType(call_type))
        if key not in self.calls:
            raise SeatConfigError(
                f"seats.yaml configures no {CALLS_BLOCK}.{key} block — the mapping holds "
                f"{list(protean_config.CONFIGURED_CALL_TYPES)} and nothing else, because a "
                f"spawn's whole process comes from a kind block, which lives at "
                f"`{KINDS_BLOCK}.{key}.<kind>` and is resolved by `kind({key!r}, <kind>)`"
            )
        return self.calls[key]

    def kind(self, kind_class: str, name: str) -> "KindBlock":
        """One kind block, or a refusal naming the class or the kind the seed does not define.

        Beside `tier()` and `call()`, and the **only** resolver that can name WHICH kind:
        `block()` below stays addressee-only because an addressee cannot carry a kind name
        (folded: S-i2), so the spawn desk resolves `(class, kind)` through here.

        A **plain refusal**, never `SeatUnavailable`: a kind the seed does not define is what the
        desk raises `REASON_NO_KIND` from (A.1.i § Deliverable 4), and that class is the desk's.
        """
        from protean.cortex.live.kinds import KINDS_BLOCK

        if kind_class not in protean_config.KIND_CLASSES:
            raise SeatConfigError(
                f"{kind_class!r} is not a kind class — the two are "
                f"{list(protean_config.KIND_CLASSES)}, and the class is the sub-mapping a block "
                f"sits under rather than a key on it (§ Deliverable 1)"
            )
        blocks = self.kinds.get(kind_class, {})
        if name not in blocks:
            raise SeatConfigError(
                f"seats.yaml defines no {KINDS_BLOCK}.{kind_class}.{name} block — "
                f"{KINDS_BLOCK}.{kind_class} holds {sorted(blocks)} and nothing else. A kind is a "
                f"seed, so one is admitted between tasks under `resume --reseed` and never "
                f"mid-task (A1-13)"
            )
        return blocks[name]

    def block(self, addressee: Addressee | str) -> TierSeat:
        """The block one **addressee** is configured by — a tier's, or a call type's.

        One resolver, so the argv, the containment and the caps read the same place whichever
        the addressee is (§ Deliverable 2, decision 10: one port, one code path).
        """
        if isinstance(addressee, CallType):
            return self.call(addressee)
        if isinstance(addressee, Tier):
            return self.tier(addressee)
        name = str(addressee)
        if name in protean_config.CALL_TYPES:
            return self.call(name)
        return self.tier(name)

    def _found_binary(self) -> Path:
        """Where the parent's own `PATH` finds the binary by name, symlink and all."""
        found = shutil.which(self.binary)
        if found is None:
            raise SeatConfigError(
                f"{self.binary!r} is not on this machine's PATH; a live seat cannot be spawned"
            )
        return Path(found)

    def resolved_binary(self) -> Path:
        """The absolute path of the binary, resolved **before** the scrub.

        The child's `PATH` cannot find it — that is the point (folded: S-31) — so the parent
        resolves it once, by name, and spawns it by absolute path. A checkout whose `PATH` has
        no such binary refuses here rather than at the first tick. The **resolved** path is what
        is spawned, so a self-update mid-run cannot swap the binary under a running task; the
        version it reports is recorded on every call either way (decision 13).
        """
        return self._found_binary().resolve()

    def binary_paths(self) -> tuple[Path, ...]:
        """The binary itself, both as found on `PATH` and as resolved through its symlink.

        What a `bin_links` entry may never be. Sharing a *directory* with the seat binary is
        not disqualifying — the link farm exposes names one at a time, so `uv` living beside
        `claude` exposes `uv` and nothing else — but being it, under any name, is.
        """
        found = self._found_binary()
        return tuple({found.resolve(), Path(found)})

    def binary_directories(self) -> tuple[Path, ...]:
        """Every directory the binary can be reached through: the launcher's, and the real one.

        Two, not one, because the name on `PATH` is usually a symlink into a versioned
        directory. Excluding only the resolved parent would leave the launcher directory
        reachable, and excluding only the launcher's would leave the version directory
        reachable; the containment means neither.
        """
        found = self._found_binary()
        return tuple({found.parent.resolve(), found.resolve().parent})

    def child_path(self, extra: Sequence[Path | str] = ()) -> str:
        """The child's `PATH`: the seed's named list, and never the binary's own directory.

        § Deliverable 1: "`PATH` is built from a named list in `brain/seats.yaml` that excludes
        the directory holding the `claude` binary, so a nested `claude` call from inside a
        session fails as command-not-found". The list is the seed's; this **enforces** the
        exclusion rather than trusting the author to have remembered it, because the binary can
        move between machines and a stale list would silently re-open the hole.
        """
        forbidden = set(self.binary_directories())
        entries = [str(item) for item in extra] + list(self.path_entries)
        kept = [entry for entry in entries if Path(entry).resolve() not in forbidden]
        return os.pathsep.join(kept)

    def child_environment(
        self, parent: Mapping[str, str], *, extra_path: Sequence[Path | str] = ()
    ) -> dict[str, str]:
        """The scrubbed environment a seat process inherits: five variables and no more.

        `PATH`, `HOME`, `LANG`, `TERM`, `USER` (folded: S-31, folded: S-37) — **no `RIG_*`, no
        `PROTEAN_*`, no `ANTHROPIC_*`** — so the credentials the workload's own rig reads from
        the maintainer's environment never reach a session. `HOME` stays because the
        subscription credential is resolved through it and `USER` because the keychain lookup
        that resolves it needs the account name: that is what makes `--setting-sources ""` the
        isolation lever and `--bare` the wrong one.

        Built by **allow-list from empty**, never by deleting keys from the parent: a copy that
        removed known-bad prefixes would pass every variable nobody thought of.
        """
        environment: dict[str, str] = {}
        for name in self.env_passthrough:
            if name == "PATH":
                continue
            value = parent.get(name)
            if value is not None:
                environment[name] = value
        environment["PATH"] = self.child_path(extra_path)
        return environment


def _require(block: Mapping[str, Any], keys: Sequence[str], where: str) -> None:
    missing = [key for key in keys if key not in block]
    if missing:
        raise SeatConfigError(f"{where}: seats.yaml carries no {', '.join(sorted(missing))}")


def _strings(value: Any, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise SeatConfigError(f"{where}: expected a list of strings, got {type(value).__name__}")
    return tuple(str(item) for item in value)


def _tools(value: Any, where: str) -> str | tuple[str, ...] | None:
    """`null`, a string, or a list of tool names — the three shapes the seed may carry."""
    if value is None or isinstance(value, str):
        return value
    return _strings(value, where)


def check_permission_mode(mode: str | None, where: str) -> str | None:
    """Refuse a permission mode that was measured not to bind. Shared by both T3 surfaces.

    `None` passes: a tier with no tools is granted nothing and the flag is omitted entirely.
    """
    if mode is not None and mode in PERMISSION_MODES_REFUSED:
        raise SeatConfigError(
            f"{where}: permission_mode {mode!r} does not bind the allow-list — measured on CLI "
            f"2.1.263, every unlisted tool ran and the envelope carried `permission_denials: []` "
            f"(S-44). A T3 surface runs under {PERMISSION_MODE_BINDING!r} beside an explicit "
            f"`tools:` set, or it does not run"
        )
    return mode


def _sandbox_tree(entry: str, root: Path) -> Path:
    """One `deny_write` entry → the absolute tree it names. A path, or one of two logical names."""
    name = entry.strip()
    if name.startswith(("~", "/")):
        return Path(name).expanduser().resolve()
    if name == SANDBOX_NAME_BRAIN_ROOT:
        return root.expanduser().resolve()
    if name == SANDBOX_NAME_POLICY_HOME:
        # Resolved through the one module licensed to know where the policy home is, so the seed
        # can deny that tree without naming it (row W4's grep).
        return policy_home.root()
    raise SeatConfigError(
        f"{SANDBOX_BLOCK}.deny_write names {entry!r}, which is neither a path (it would start "
        f"with `~` or `/`) nor one of the logical names {list(SANDBOX_NAMES)}"
    )


def parse_sandbox(payload: Mapping[str, Any], root: Path) -> SandboxPolicy:
    """The `sandbox:` block → the resolved policy, refusing anything it does not name."""
    block = payload.get(SANDBOX_BLOCK)
    if not isinstance(block, Mapping):
        raise SeatConfigError(
            f"seats.yaml carries no `{SANDBOX_BLOCK}` block — the T3 surfaces are spawned under "
            f"`sandbox-exec` and refuse to run on a default containment (S-45)"
        )
    _require(block, SANDBOX_KEYS, SANDBOX_BLOCK)
    names = _strings(block["deny_write"], f"{SANDBOX_BLOCK}.deny_write")
    if not names:
        raise SeatConfigError(
            f"{SANDBOX_BLOCK}.deny_write is empty — a profile that denies nothing is not a "
            f"sandbox, and an empty list is the hole S-45 exists to close"
        )
    return SandboxPolicy(
        binary=str(block["binary"]),
        names=names,
        deny_write=tuple(_sandbox_tree(name, root) for name in names),
    )


def _number(value: Any, where: str) -> float:
    """One bound's seed value → a number, refusing by name what is not one.

    Nothing here defaults and nothing here guesses: a bound whose value the loader cannot read is
    a bound that does not bind, which is the hole the load-time requirement exists to close.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        raise SeatConfigError(
            f"{where}: {value!r} is not a number — the four spawn bounds are static ceilings read "
            f"off the seed (§ Deliverable 5)"
        ) from None


def _count(value: Any, where: str) -> int:
    """The delegate bound's seed value → a non-negative integer, refusing by name what is not one.

    Its own parse rather than `_number()`, which accepts floats for the spawn bounds (F8): a
    float, a bool, a negative or a non-number refuses at load, and `0` — no delegate planned — is
    legal.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SeatConfigError(
            f"{where}: {value!r} is not a non-negative integer — the per-tick delegate bound is a "
            f"count of delegates the call policy may plan in one tick (`0` plans none)"
        )
    return value


def parse_spawn_writable(runtime: Mapping[str, Any], sandbox: SandboxPolicy) -> tuple[Path, ...]:
    """`runtime.spawn_writable` → the resolved trees, refusing its two holes **by name**.

    `the build specification (not in this mirror)` § Deliverable 5 and row G1's last clauses
    (folded: S-i20, folded: S-i43). Two refusals, and each closes a hole the *composed* profile
    could not:

    * an entry that **does not exist** on this machine — a tree the profile would allow and the
      machine does not have is a hole authored by typo, and it is invisible once composed;
    * an entry that resolves **inside any `sandbox.deny_write` tree** — because a spawn's profile no
      longer carries the deny clause that would win the collision back: `(allow file-write*
      (subpath X))` under a tree the seed denied simply **grants** the write. The seed's two lists
      are made non-overlapping at the only moment either one can be read. The workspace half of the
      same collision is refused at the desk's open, before any process.

    Resolved `~`/`/` like a `deny_write` entry and for the same reason, plus one the kernel adds:
    `sandbox-exec` matches a subpath against the realpath, so an unresolved entry would compose into
    a clause that matches nothing (measured — see `SandboxPolicy.spawn_profile()`).
    """
    where = f"{RUNTIME_BLOCK}.{SPAWN_WRITABLE_KEY}"
    entries = _strings(runtime[SPAWN_WRITABLE_KEY], where)
    trees: list[Path] = []
    for entry in entries:
        name = entry.strip()
        if not name.startswith(("~", "/")):
            raise SeatConfigError(
                f"{where} names {entry!r}, which is not a path — every entry begins with `~` or "
                f"`/`, because the trees a spawn may write are read off the seed and never guessed"
            )
        tree = Path(name).expanduser().resolve()
        # The collision is read FIRST, and deliberately: an entry inside a denied tree is refused
        # for that reason whether or not the directory happens to exist, because "it is not there
        # yet" is the less useful sentence when the entry could never be allowed at all.
        for denied in sandbox.deny_write:
            if tree == denied or tree.is_relative_to(denied):
                raise SeatConfigError(
                    f"{where} names {entry!r}, which resolves to {tree}, inside the "
                    f"`{SANDBOX_BLOCK}.deny_write` tree {denied} — a spawn's profile is "
                    f"write-denied by default and carries no deny clause to win that collision "
                    f"back, so an allowed subpath nested inside a denied tree simply grants the "
                    f"write the seed said no to (folded: S-i43)"
                )
        if not tree.is_dir():
            raise SeatConfigError(
                f"{where} names {entry!r}, which resolves to {tree} and is not a directory on this "
                f"machine — a tree the composed profile would allow and the machine does not have "
                f"is a hole authored by typo (folded: S-i20)"
            )
        trees.append(tree)
    return tuple(trees)


def _tier_seat(tier: str, block: Any, where: str | None = None) -> TierSeat:
    """One block → a `TierSeat`. `where` is what a refusal names it by, when it is not a tier."""
    where = where or tier
    if not isinstance(block, Mapping):
        raise SeatConfigError(f"{where}: a tier block is a mapping, not {type(block).__name__}")
    _require(block, TIER_KEYS, where)
    tools = _tools(block["tools"], f"{where}.tools")
    return TierSeat(
        tier=tier,
        model=str(block["model"]),
        effort=str(block["effort"]),
        permission_mode=check_permission_mode(
            None if block["permission_mode"] is None else str(block["permission_mode"]),
            where,
        ),
        allowed_tools=_strings(block["allowed_tools"], f"{where}.allowed_tools"),
        disallowed_tools=_strings(block["disallowed_tools"], f"{where}.disallowed_tools"),
        tools=tools,
        add_dir=bool(block["add_dir"]),
        max_call_usd=float(block["max_call_usd"]),
        timeout_seconds=float(block["timeout_seconds"]),
        prompt=str(block["prompt"]),
    )


def _calls_block(name: str, block: Any, manager: TierSeat) -> TierSeat:
    """One `calls:` block → a `TierSeat`, refusing the four things row G10 names.

    `TIER_KEYS` **exactly**: `_tier_seat()` refuses a missing key, and the check below refuses an
    eleventh — not a subset and not a superset, so a `calls:` block cannot grow a field the argv
    builder would never read (a `body` key is the worked example; `runtime.body` is one key for
    the whole file, and a body selectable per call is a body that could differ per call).
    """
    where = f"{CALLS_BLOCK}.{name}"
    if not isinstance(block, Mapping):
        raise SeatConfigError(f"{where}: a call-type block is a mapping, not {type(block).__name__}")
    extra = [key for key in block if key not in TIER_KEYS]
    if extra:
        raise SeatConfigError(
            f"{where}: seats.yaml carries {sorted(extra)}, outside the ten keys a block takes "
            f"({list(TIER_KEYS)}) — a `{CALLS_BLOCK}:` block is TIER_KEYS exactly, not a superset"
        )
    seat = _tier_seat(name, block, where=where)
    if seat.tools != CALL_TOOLS:
        raise SeatConfigError(
            f"{where}: tools is {seat.tools!r}, and a `{CALLS_BLOCK}:` block is tool-less by "
            f"load-time refusal — {CALL_TOOLS!r} is the only value it may carry (row G10)"
        )
    if seat.add_dir is not CALL_ADD_DIR:
        raise SeatConfigError(
            f"{where}: add_dir is {seat.add_dir!r}, and a `{CALLS_BLOCK}:` block is tool-less by "
            f"load-time refusal — {CALL_ADD_DIR!r} is the only value it may carry (row G10)"
        )
    for cap in CALL_CAP_KEYS:
        value, ceiling = getattr(seat, cap), getattr(manager, cap)
        if not value < ceiling:
            raise SeatConfigError(
                f"{where}: {cap} is {value}, which is not STRICTLY below the "
                f"{manager.tier}'s {ceiling} — token cheap is a configuration fact, not an "
                f"intention (folded: S-A47)"
            )
    return seat


def parse_calls(payload: Mapping[str, Any], tiers: Mapping[str, TierSeat]) -> dict[str, TierSeat]:
    """The `calls:` mapping → the two blocks, refusing anything it does not name.

    **Exactly `think` and `escalate`** (`config.CONFIGURED_CALL_TYPES`): a missing one refuses by
    name and so does a third, because `delegate` and `dispatch` have no call-type block at all —
    their configuration is a kind block in the `kinds:` container beside this one, parsed by
    `protean.cortex.live.kinds` (A.1.i § Deliverable 1). The third-block refusal is also what makes
    "strictly below reaches those two blocks and nothing else" checkable — a third block never
    reaches the cap comparison, because it never loads.

    Eager like `parse_sandbox()` and unlike the per-tier blocks: the two caps are a containment
    fact, and a mapping that is simply absent would be a cheap-call surface authored by omission.
    """
    block = payload.get(CALLS_BLOCK)
    if not isinstance(block, Mapping):
        raise SeatConfigError(
            f"seats.yaml carries no `{CALLS_BLOCK}` block — think and escalate are configured "
            f"there, and a live root with none has no cheap seam to refuse against (row G10)"
        )
    configured = protean_config.CONFIGURED_CALL_TYPES
    unknown = [name for name in block if name not in configured]
    if unknown:
        raise SeatConfigError(
            f"{CALLS_BLOCK}: names {sorted(unknown)}, outside the two call types that configure "
            f"a model call ({list(configured)}) — delegate and dispatch have no call-type block "
            f"at all, and their kind blocks live in the `kinds:` container instead"
        )
    missing = [name for name in configured if name not in block]
    if missing:
        raise SeatConfigError(
            f"{CALLS_BLOCK}: seats.yaml carries no {', '.join(missing)} block"
        )
    reference = str(CALL_CAP_REFERENCE_TIER)
    if reference not in tiers:
        raise SeatConfigError(
            f"{CALLS_BLOCK}: every block's caps are measured strictly below the {reference}'s, "
            f"and seats.yaml configures no {reference!r} block"
        )
    return {name: _calls_block(name, block[name], tiers[reference]) for name in configured}


def check_body(value: Any) -> str:
    """`runtime.body` → the body name, refusing anything outside its two legal values.

    § Deliverable 5, row G13: "`runtime.body` with value `print` or `terminal`". The refusal
    names the key and both values, because the seed author reads it and a body is a containment
    fact, not a preference.
    """
    name = "" if value is None else str(value)
    if name not in BODY_NAMES:
        raise SeatConfigError(
            f"{RUNTIME_BLOCK}.{BODY_KEY} is {value!r}, which is not one of {list(BODY_NAMES)} — "
            f"a body is a transport and this build has exactly two, the `claude -p` body and "
            f"the runtime-launched terminal session (§ Deliverable 5)"
        )
    return name


def refuse_a_body_key_anywhere_else(
    payload: Mapping[str, Any], where: tuple[str, ...] = ()
) -> None:
    """Refuse **by name** a `body` key anywhere in the file but `runtime.body` (row G13).

    Walked rather than enumerated: the refusal has to reach a tier block, a `calls:` block, the
    `oracle:` block, the top level and **anything build A.1.i later adds**, so it is written
    against the shape of the document instead of against the blocks that exist today.
    **It runs last, after every block has parsed**, so the refusal a reader sees is the most
    specific one: `TIER_KEYS`-exactly already refuses a `calls:` block's `body` **by name**
    (row G10, and § Deliverable 5 says so), and this is what makes the claim true of the rest of
    the file — the tier blocks, `oracle:`, the top level, and whatever A.1.i adds beside them.
    """
    for key, value in payload.items():
        path = (*where, str(key))
        if str(key) == BODY_KEY and where != (RUNTIME_BLOCK,):
            location = ".".join(path)
            raise SeatConfigError(
                f"{location}: a `{BODY_KEY}` key is legal at `{RUNTIME_BLOCK}.{BODY_KEY}` and "
                f"nowhere else in seats.yaml — one key selects the body for the whole file and "
                f"it applies to the two cortex seats only, because a body selectable per call "
                f"is a body that could differ per call (§ Deliverable 5, folded: S-A78)"
            )
        if isinstance(value, Mapping):
            refuse_a_body_key_anywhere_else(value, path)


def parse_seats(payload: Any, root: Path) -> SeatsConfig:
    """One loaded `seats.yaml` mapping → `SeatsConfig`, refusing anything it does not name."""
    if not isinstance(payload, Mapping):
        raise SeatConfigError("seats.yaml is a mapping of blocks, one per tier plus `runtime`")

    layer = str(payload.get("layer", LAYER_SCRIPTED))
    if layer not in LAYERS:
        raise SeatConfigError(f"layer: {layer!r} is not one of {list(LAYERS)}")

    runtime = payload.get(RUNTIME_BLOCK)
    if not isinstance(runtime, Mapping):
        raise SeatConfigError("seats.yaml carries no `runtime` block")
    _require(runtime, RUNTIME_KEYS, RUNTIME_BLOCK)

    passthrough = _strings(runtime["env_passthrough"], "runtime.env_passthrough")
    widened = [name for name in passthrough if name not in ENV_ALLOWED]
    if widened:
        raise SeatConfigError(
            f"runtime.env_passthrough names {sorted(widened)}, outside the five the "
            f"containment allows ({list(ENV_ALLOWED)}) — widening it is the operator's ruling, not a seed edit"
        )

    tiers = {}
    for tier in Tier:
        key = str(tier)
        if key in payload:
            tiers[key] = _tier_seat(key, payload[key])

    sandbox = parse_sandbox(payload, root)
    calls = parse_calls(payload, tiers)
    bounds = {
        key: _number(runtime[key], f"{RUNTIME_BLOCK}.{key}") for key in SPAWN_BOUND_KEYS
    }
    spawn_writable = parse_spawn_writable(runtime, sandbox)
    # The import runs this way at call time and the other way at import time, on
    # `protean.cortex.calls`'s precedent (`calls.py:415`): `cortex.live.kinds` imports this
    # module's helpers, so the kind parser is reached from here rather than from the top.
    from protean.cortex.live.kinds import parse_kinds

    kinds = parse_kinds(
        payload,
        root,
        spawn_writable=spawn_writable,
        ceilings={cap: bounds[key] for cap, key in SPAWN_CAP_CEILINGS.items()},
    )
    # Last, so the most specific refusal is the one a seed author reads (see the function).
    refuse_a_body_key_anywhere_else(payload)

    return SeatsConfig(
        root=root,
        layer=layer,
        binary=str(runtime["binary"]),
        path_entries=_strings(runtime["path"], "runtime.path"),
        bin_links=_strings(runtime["bin_links"], "runtime.bin_links"),
        env_passthrough=passthrough,
        tiers=tiers,
        sandbox=sandbox,
        calls=calls,
        kinds=kinds,
        body=check_body(runtime[BODY_KEY]),
        spawn_max_call_usd=bounds["spawn_max_call_usd"],
        spawn_timeout_seconds=bounds["spawn_timeout_seconds"],
        max_wave_members=int(bounds["max_wave_members"]),
        spawn_max_wave_usd=bounds["spawn_max_wave_usd"],
        spawn_writable=spawn_writable,
        # Its own integer parse, not `_number()`: the bound is a count (A.2.i, F8).
        max_tick_delegates=_count(
            runtime[DELEGATE_BOUND_KEY], f"{RUNTIME_BLOCK}.{DELEGATE_BOUND_KEY}"
        ),
    )


def load_seats(root: Path) -> SeatsConfig | None:
    """`<brain root>/seats.yaml` → `SeatsConfig`, or `None` when the root carries no such file.

    `None` is not an error: a build-1 root and every dry-run copy have no `seats.yaml`, and the
    layer factory reads that as "the scripted seats, exactly as before".
    """
    path = BrainPaths(root=root).seats
    if not path.is_file():
        return None
    return parse_seats(yaml.safe_load(path.read_text(encoding="utf-8")), root)
