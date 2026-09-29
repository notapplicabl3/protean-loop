"""`brain/seats.yaml`'s `kinds:` container → one kind block as data, and the refusals around it.

`the build specification (not in this mirror)` § Deliverable 1 (seam contract **I1 `KindBlock`**),
§ Directional decisions 2, § Resolutions A1-3, A1-8, A1-13.

**The class is the sub-mapping, never a key on the block.** `kinds:` holds one sub-mapping per
class — `config.KIND_CLASSES`, the two call types that carry no `calls:` block — and each
sub-mapping holds `<kind> → block`. That is what makes Option A enforceable at *load* rather
than only at return (S-A5): a kind that may write is one the seed author had to put under
`dispatch:`, and the class it sits under is what its licensed set will be looked up by. A block
outside the two sub-mappings, an unknown class name and a `class:` key on a block therefore each
refuse by name.

**A kind block takes `TIER_KEYS` exactly** — the same ten keys a seat block and a `calls:` block
take, not a subset and not a superset. It declares no containment of its own and inherits
`runtime:` and the single top-level `sandbox:` exactly as the seats do: there is no per-kind
`sandbox:`, no workspace key and no writable-path key, because a per-kind containment
declaration is a widening vector (S-A5). A `body` key **on a kind block** is refused by that same
check, as the eleventh key it is — the parser's order rule is that the specific refusal wins —
while the **container** levels `kinds.body` and `kinds.<class>.body` are refused by
`config.refuse_a_body_key_anywhere_else()`, the landed walk this build does not edit (folded:
S-i10). `_refuse_a_body_key_at_this_level()` below is what scopes that walk to the two levels
the block parser never reaches.

**`prompt:` resolves under `brain/seats/kinds/`, by realpath, and the confinement is checked
rather than assumed** (A1-8, folded: S-i26): the resolved path must lie *inside* that directory
and must exist, so a `prompt: ../notes.md`, an absolute path and a symlink whose target leaves
the directory each refuse at load by name. The reason is the hash set rather than the filesystem
— every file a spawn's prefix is assembled from is hashed into the checkpoint through
`protean.brain.folders.seed_hashes()`, whose seat-prefix glob has reached `seats/kinds/*.md`
since D11-4 with no edit here, and a prompt resolved outside the hashed tree is a prefix that can
change under a task with no drift refusal to catch it.

**The containment floor is a POSITIVE GRANT, and this module is the only home of its literals**
(§ Deliverable 2, seam contract **I2 `CapabilityProfile`**, § Directional decisions 1, A1-1, row
M1). Three audit rounds tried to close the floor by naming what a kind may not have and each found
the next hole, because an enumerated refusal grants by default everything nobody thought of —
including every tool the CLI ships next. So each class declares **one** closed licensed **PATTERN**
set here and nowhere else, and its licensed **NAME** set is **derived** from that literal (`X(...)`
or `X` → `X`, first-appearance order): the CLI takes two vocabularies on two flags, but only one of
them has to be authored, and a derived pair cannot drift out of agreement with itself the way two
authored lists can (folded: S-i1, folded: S-i27). `EGRESS_REMOTE` is one literal the runtime
**appends** to every spawn's `--disallowedTools` whatever the block says, so no library kind
carries those eight strings and there is no superset refusal for one to fail (folded: S-i15). And
`SPAWN_PROCESS_ALLOWANCES` is the **third provenance class** beside the handed workspace and
`runtime.spawn_writable` — **measured, never authored**, fixed by
`tests/cortex/captures/spawn-profile.json`, which `tests/cortex/probe_profile.py` wrote.

**Nothing persists a `KindBlock`**, which is why it lives here beside `TierSeat` and
`SandboxPolicy` rather than under `protean.state`: a block-as-data object belongs to the parser
that reads it (folded: S-i28). `SpawnWitness`, the one persisted shape, joins C2 in
`protean.state.calls` instead.

**A kind is a seed** (A1-13). `brain/seats.yaml` and every `brain/seats/**.md` are hashed into
the checkpoint, so admitting a kind mid-task is a drift refusal — a property rather than a
defect: A.2's library grows between tasks, under `resume --reseed` or on a fresh task. **Two
kinds ship**, one per class: the shipping seed's `dispatch` and `delegate` sub-mappings each carry
one block and `brain/seats/kinds/` holds their two prefixes (`the build specification (not in this mirror)`
§ Deliverables 1–3) — seed data this module loads and never names.

**The import runs one way at import time and the other at call time**, on
`protean.cortex.calls`'s own precedent (`calls.py:415`, itself on `habits.py:198`): this module
imports the loader's helpers from `protean.cortex.live.config`, and `parse_seats()` imports
`parse_kinds()` function-locally where it calls it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from protean import config as protean_config
from protean.cortex.live.config import (
    PERMISSION_MODE_BINDING,
    RUNTIME_BLOCK,
    SANDBOX_BLOCK,
    SPAWN_CAP_CEILINGS,
    TIER_KEYS,
    SandboxPolicy,
    SeatConfigError,
    _tier_seat,
    refuse_a_body_key_anywhere_else,
    tools_argument,
)
from protean.runtime.paths import BrainPaths

#: The container's key in `brain/seats.yaml` **and** the `brain/seats/` sub-directory a kind's
#: prefix file lives in — one literal, because the two names are deliberately the same word
#: (§ Deliverable 1: the container in `seats.yaml`, the prefix under `seats/kinds/`).
#:
#: It is authored here rather than in `protean.runtime.paths` because this build's writable set
#: does not reach that module, and a second copy of the word is what row M1 forbids.
KINDS_BLOCK = "kinds"

#: The key that would make the class a property of the block instead of the mapping it sits in.
#: Refused by name: `TIER_KEYS`-exactly already reaches it, and the refusal says *why*.
CLASS_KEY = "class"

#: The two extras a seed author is most likely to reach for, and the sentence each refusal adds.
#: Every other eleventh key is refused by the same check with the ten keys named; these two get a
#: reason, because each is a reading of the container the SPEC rules out for a stated cause.
_NAMED_EXTRAS: Mapping[str, str] = {
    CLASS_KEY: (
        "the class is the sub-mapping a block sits under, never a key on the block — which is "
        "what makes it enforceable at load rather than only at return (S-A5)"
    ),
    SANDBOX_BLOCK: (
        "a kind block declares no containment of its own: it inherits `runtime:` and the single "
        "top-level `sandbox:` exactly as the seats do, because a per-kind containment "
        "declaration is a widening vector (S-A5)"
    ),
}


#: **The one licensed PATTERN set per class, and the only literal either class authors** (row M1,
#: § Deliverable 2, folded: S-i1, folded: S-i27). The licensed NAME sets are DERIVED from these by
#: `derived_names()` below and are authored nowhere.
#:
#: **`delegate`** is exactly three read patterns. **No `Bash` pattern is licensed, so no `Bash`
#: name is derivable and the class cannot carry the shell in any form**: S-A49's enumerated
#: read-only `Bash(...)` list is **retired**, because T2 measured that `Bash(find:*)` executes and
#: deletes and that every prefix admits redirection (`cat a > b`), so no `Bash` prefix is read-only
#: and an enumerated list of them cannot be made one. A delegate returns information or a verdict,
#: and the shell is not how it reads.
#:
#: **`dispatch`** is build 2's landed acting surface — `brain/seats.yaml`'s `oracle:` block's
#: `allowed_tools` **less the rig-specific `Bash(postman:*)`** — taken as the one set this build
#: authors a literal from. The six names it derives reproduce that same block's `tools:` set
#: exactly, so S-44's fact (a `Bash(...)` pattern binds only with the `Bash` name beside it) is
#: inherited by construction rather than restated as a second list. **Note the absences as much as
#: the entries:** no bare `Bash`, no `Task`, no `KillShell`, no `BashOutput`, no `WebFetch`, no
#: `WebSearch`, and no push/fetch/remote verb.
LICENSED_PATTERNS: Mapping[str, tuple[str, ...]] = {
    protean_config.CALL_DISPATCH: (
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
    ),
    protean_config.CALL_DELEGATE: ("Read", "Grep", "Glob"),
}

#: The shell's own tool name. Named once because three refusals read it: a **bare** `Bash` pattern
#: licenses every command and refuses for either class under its own clause; a pattern whose name
#: is `Bash` refuses for a class that licenses none; and the name `Bash` in a delegate's `tools`
#: refuses through the one derived-set comparison.
BASH = "Bash"

#: The three tools a seed author who reached for one is owed a specific message about (T1). Each is
#: **also** outside both licensed sets, so the positive grant already refuses it; what these add is
#: the sentence that says why, because "outside the licensed patterns" is the right refusal and the
#: least useful one when the entry is the tool that spawns a fourth tier.
NAMED_BY_THEIR_OWN_REFUSAL: Mapping[str, str] = {
    "Task": (
        "it spawns a subagent of its own, and three tiers is the ceiling — a kind that could "
        "dispatch would be a fourth"
    ),
    "KillShell": "it reaches processes this kind did not start",
    "BashOutput": "it reads a shell this kind did not start",
}

#: **The egress/remote set: one literal the runtime APPENDS to every spawn's `--disallowedTools`**
#: (§ Deliverable 2, folded: S-i15, row M1). `brain/seats.yaml`'s `oracle:` block names the same
#: eight and is **unedited** — this is the literal the spawn path carries, not a copy of a seed key.
#:
#: A block's own `disallowed_tools` is still one of the ten `TIER_KEYS` and may **add** to this; it
#: is never required to restate it, so no library kind carries these eight strings and there is
#: **no superset refusal** for one to fail. This is the second reading, kept: the positive set
#: already excludes them, and the argv is where a reviewer now reads them (row G4).
EGRESS_REMOTE: tuple[str, ...] = (
    "WebFetch",
    "WebSearch",
    "Bash(curl:*)",
    "Bash(wget:*)",
    "Bash(git push:*)",
    "Bash(git remote:*)",
    "Bash(git fetch:*)",
    "Bash(git pull:*)",
)


@dataclass(frozen=True, slots=True)
class ProcessAllowance:
    """One entry of `SPAWN_PROCESS_ALLOWANCES`: a path, and whether it is a device.

    The distinction is the profile's — a directory enters as `(subpath "…")` and a device as
    `(literal "…")` — and it is also what order W5's fourth audit list reads: `wrote_outside_
    workspace` is asked of the allowed **directories** and never of a device literal.
    """

    path: str
    device: bool


#: **What a `claude -p` needs in order to start at all under the inverted profile — MEASURED, never
#: authored** (§ Deliverable 2, § Directional decisions 4, folded: S-i48, folded: S-i49, ledger
#: entry V2-4). One closed literal with one owner, a **third provenance class** beside the handed
#: workspace and `runtime.spawn_writable`, so row M2's provenance rule, row G3's profile-string
#: assertion and the witness's baseline all reach it instead of meeting a subpath that traces to
#: nothing.
#:
#: **Its receipt is `tests/cortex/captures/spawn-profile.json`**, which `tests/cortex/probe_profile.py`
#: wrote by composing the profile and running the real `claude --version` and the stand-in binary
#: under it (it spends no model call). The ladder is in that capture: with the allowed set and **no**
#: device literal, `claude --version` exited 0 and the kernel refused a write to a third path — and
#: `/bin/sh: /dev/null: Operation not permitted` came back from the stand-in's own `2>/dev/null`,
#: beside `PermissionError: [Errno 1] Operation not permitted: '/dev/null'` from `python3`. A
#: `dispatch` kind is licensed `Bash(uv:*)` and `Bash(python:*)`, so a shell that cannot open
#: `/dev/null` is a surface that only looks contained. With this one literal added, every measured
#: criterion passed.
#:
#: **The per-user temp root is deliberately absent** (folded: S-i48): the child's environment
#: carries no `TMPDIR` among its five names, so the CLI and Python fall back to `/tmp`, which
#: `runtime.spawn_writable` seeds. **The controlling tty is absent because it is UNMEASURED** — the
#: probe ran with no terminal attached, so `(literal "/dev/tty")` has no receipt, and an entry with
#: no receipt would be authored rather than measured (row B49 settles it).
SPAWN_PROCESS_ALLOWANCES: tuple[ProcessAllowance, ...] = (
    ProcessAllowance(path="/dev/null", device=True),
)


def tool_name(pattern: str) -> str:
    """One permission **pattern** → the tool **name** it binds: `X(...)` or `X` → `X`.

    The whole of the derivation (§ Deliverable 2): every name is recoverable from a pattern by
    reading the token before the parenthesis, which is why one list has one owner.
    """
    return pattern.split("(", 1)[0].strip()


def derived_names(patterns: Sequence[str]) -> tuple[str, ...]:
    """The licensed NAME set of a pattern set — deduplicated in **first-appearance order**.

    That order is the derivation's own and is not a contract a seed author is held to: a block's
    `tools` is compared as a **SET** (folded: S-i46). What the order does govern is nothing but
    this tuple's spelling.
    """
    return tuple(dict.fromkeys(tool_name(pattern) for pattern in patterns))


def licensed_patterns(kind_class: str) -> tuple[str, ...]:
    """The class's one authored set, or a refusal naming the two classes there are."""
    if kind_class not in LICENSED_PATTERNS:
        raise SeatConfigError(
            f"{kind_class!r} licenses nothing — the two kind classes are "
            f"{list(protean_config.KIND_CLASSES)} (§ Deliverable 2)"
        )
    return LICENSED_PATTERNS[kind_class]


def licensed_names(kind_class: str) -> tuple[str, ...]:
    """The class's licensed NAME set, **derived** from its patterns and authored nowhere."""
    return derived_names(licensed_patterns(kind_class))


def spawn_allowance_subpaths() -> tuple[str, ...]:
    """`SPAWN_PROCESS_ALLOWANCES`' directory entries — what the fourth audit list is asked of."""
    return tuple(entry.path for entry in SPAWN_PROCESS_ALLOWANCES if not entry.device)


def spawn_allowance_literals() -> tuple[str, ...]:
    """`SPAWN_PROCESS_ALLOWANCES`' device entries — excluded from the audit lists **by name**."""
    return tuple(entry.path for entry in SPAWN_PROCESS_ALLOWANCES if entry.device)


@dataclass(frozen=True, slots=True)
class CapabilityProfile:
    """What a class licenses, what a block granted, and the resolution between them — **I2**.

    § Deliverable 2. **It is the object every refusal is raised from and the object the argv is
    built from**, so a granted set and an argv cannot disagree.

    The **granted pair** is the point: `granted_patterns` goes to `--allowedTools` and
    `granted_names` to `--tools`, and the pair comes off **one** authored list — the block's own
    `allowed_tools`, resolved against the class's licensed patterns, with `tools` checked to equal
    the names derived from it. Never an intersection of the two: the flags do not hold the same
    kind of string, and a floor that refused a bare `Bash` **name** would make every `dispatch`
    kind unloadable while dropping every `Bash(...)` pattern off the argv.

    `allowed_subpaths` is the **kernel** half's per-class set: the task workspace where the class
    licenses it, plus the resolved `runtime.spawn_writable` trees. `SPAWN_PROCESS_ALLOWANCES` is
    **not** a field — it is one literal with one owner, added at composition, which is what keeps
    row M2's three provenance classes three.
    """

    kind_class: str
    name: str
    licensed_patterns: tuple[str, ...]
    licensed_names: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    tools: tuple[str, ...]
    disallowed_tools: tuple[str, ...]
    granted_patterns: tuple[str, ...]
    granted_names: tuple[str, ...]
    permission_mode: str
    allowed_subpaths: tuple[Path, ...]

    def refused_patterns(self) -> tuple[str, ...]:
        """What `--disallowedTools` carries: the block's own set **plus `EGRESS_REMOTE`**.

        Appended by the runtime on every spawn whatever the block says (folded: S-i15), which is
        why a block is never held to the eight and there is no superset refusal to fail. The
        block's own entries come first, so the argv still reads as the seed wrote it.
        """
        return tuple(dict.fromkeys((*self.disallowed_tools, *EGRESS_REMOTE)))

    def sandbox_profile(self, sandbox: SandboxPolicy) -> str:
        """The composed per-spawn profile: the landed head, `file-write*` denied, then allowed.

        The per-class allowed set **plus the measured `SPAWN_PROCESS_ALLOWANCES`** — and nothing
        else, which is what makes a tree nobody listed unwritable by construction. The single
        top-level `sandbox:` block is unedited and its three trees are reached by the default
        deny; an allowed subpath may not nest inside one of them, and that collision is refused at
        load (`spawn_writable`) and at the desk's open (the workspace).
        """
        return sandbox.spawn_profile(
            subpaths=(*(str(tree) for tree in self.allowed_subpaths), *spawn_allowance_subpaths()),
            literals=spawn_allowance_literals(),
        )


def _granted_names(tools: str | Sequence[str] | None) -> tuple[str, ...]:
    """A block's `tools:` value → the names it spells, for the one set comparison.

    `null`, `""` and a string of any other shape spell **no names**, so each meets the derived set
    as the inequality it is (§ Deliverable 2: "no non-empty derived set equals any of them") and is
    refused by the one comparison rather than by a rule of its own.
    """
    if tools is None or isinstance(tools, str):
        return ()
    return tuple(tools)


def _refuse_the_granted_pair(
    block: KindBlock, patterns: tuple[str, ...], where: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """`allowed_tools` + `tools` → the granted pair, refusing everything outside it **by name**."""
    if not block.allowed_tools:
        raise SeatConfigError(
            f"{where}: allowed_tools is empty — a kind exists in order to carry tools, and a "
            f"tool-less one is a think call wearing a kind's prefix. The {block.kind_class} class "
            f"licenses {list(patterns)}, and a block grants a non-empty subset of them "
            f"(§ Deliverable 2)"
        )
    for entry in block.allowed_tools:
        name = tool_name(entry)
        if entry == BASH:
            raise SeatConfigError(
                f"{where}: allowed_tools names a bare {BASH!r} pattern, which licenses every "
                f"command there is — neither class licenses it, and a scoped prefix "
                f"(`{BASH}(uv:*)`) is the only shape a shell reaches a spawn in (§ Deliverable 2)"
            )
        if entry in NAMED_BY_THEIR_OWN_REFUSAL:
            raise SeatConfigError(
                f"{where}: allowed_tools names {entry!r} — {NAMED_BY_THEIR_OWN_REFUSAL[entry]}. It "
                f"is outside the {block.kind_class} class's licensed patterns as every unlisted "
                f"tool is, and it is refused under its own name because a seed author who wrote it "
                f"is owed the specific message (§ Deliverable 2, T1)"
            )
        if name == BASH and BASH not in derived_names(patterns):
            raise SeatConfigError(
                f"{where}: allowed_tools names {entry!r}, and the {block.kind_class} class "
                f"licenses no {BASH} pattern at all — so no {BASH} name is derivable and the class "
                f"cannot carry the shell in any form. S-A49's enumerated read-only `{BASH}(...)` "
                f"list is retired: `{BASH}(find:*)` executes and deletes, and every prefix admits "
                f"redirection (§ Deliverable 2, folded: S-i27)"
            )
        if entry not in patterns:
            raise SeatConfigError(
                f"{where}: allowed_tools names {entry!r}, outside the {block.kind_class} class's "
                f"licensed patterns ({list(patterns)}) — the floor is a positive grant, so an "
                f"unlisted tool is refused by absence rather than by enumeration (§ Deliverable 2, "
                f"A1-1)"
            )

    granted_patterns = tuple(dict.fromkeys(block.allowed_tools))
    granted_names = derived_names(granted_patterns)
    carried = _granted_names(block.tools)
    if set(carried) != set(granted_names):
        missing = sorted(set(granted_names) - set(carried))
        unbound = sorted(set(carried) - set(granted_names))
        raise SeatConfigError(
            f"{where}: tools is {block.tools!r}, which is not the name set derived from this "
            f"block's own allowed_tools ({list(granted_names)})"
            + (f" — missing {missing}, so those patterns never bind (S-44)" if missing else "")
            + (
                f" — {unbound} is granted by no pattern, an unbound tool the seed author believes "
                f"it granted"
                if unbound
                else ""
            )
            + ". The comparison is set equality, not sequence equality: a permuted `tools` "
            "carrying the same names loads, because order is not a capability (folded: S-i46)"
        )
    if block.permission_mode != PERMISSION_MODE_BINDING:
        raise SeatConfigError(
            f"{where}: permission_mode is {block.permission_mode!r}, and a tool-bearing kind has "
            f"no legal mode but the one measured to bind — {PERMISSION_MODE_BINDING!r} (T3, S-44: "
            f"under `auto` the allow-list did not bind at all and the envelope came back with "
            f"`permission_denials: []`)"
        )
    return granted_patterns, granted_names


def _refuse_caps_above_the_spawn_ceiling(
    block: KindBlock, ceilings: Mapping[str, float] | None, where: str
) -> None:
    """A kind block's two caps, refused **above** the `runtime.spawn_*` ceilings (§ Deliverable 5).

    The last of § Deliverable 2's four resolution refusals, and the only one whose reference lives
    in the `runtime:` block rather than in a class's literal: `max_call_usd` against
    `spawn_max_call_usd` and `timeout_seconds` against `spawn_timeout_seconds`. **Above**, not
    strictly-above — the ceiling is a ceiling, and a kind configured exactly at it is configured at
    what the seed allows. The two *wave* bounds are a different question entirely (the width and the
    per-wave sum), checked before the first member spawns and never here.
    """
    if not ceilings:
        return
    for cap, ceiling in ceilings.items():
        value = float(getattr(block, cap))
        if value > ceiling:
            raise SeatConfigError(
                f"{where}: {cap} is {value}, above the seed's "
                f"`{RUNTIME_BLOCK}.{SPAWN_CAP_CEILINGS[cap]}` ceiling of {ceiling} — a kind block's "
                f"caps are refused above the spawn ceilings at load, before anything is spawned "
                f"(§ Deliverable 5, A1-6)"
            )


def resolve_capability(
    block: KindBlock,
    *,
    workspace: Path | None = None,
    spawn_writable: Sequence[Path] = (),
) -> CapabilityProfile:
    """One kind block + its class's licensed set → **I2**, refusing the resolution by name.

    Called twice on two different questions and it is the same resolution both times: once at
    **load**, from `parse_kinds()`, where every refusal above lands and no workspace exists yet;
    and once **per spawn**, from the desk, with the workspace the runtime handed it at open.

    The per-class allowed set is the kernel half (§ Deliverable 2, A1-4): a **`dispatch`** spawn
    gets the task workspace **plus** the `runtime.spawn_writable` trees, because its whole job is
    to change the workspace under the manager's hand and its licensed interpreters need a cache and
    a temp directory to run at all; a **`delegate`** spawn gets those trees **only**, the workspace
    simply **absent** rather than named in a deny list — a stronger statement that needs no clause
    of its own.
    """
    patterns = licensed_patterns(block.kind_class)
    where = block.block_ref
    granted_patterns, granted_names = _refuse_the_granted_pair(block, patterns, where)
    trees = tuple(Path(tree) for tree in spawn_writable)
    workspace_first = (
        (workspace.expanduser().resolve(),)
        if workspace is not None and block.kind_class == protean_config.CALL_DISPATCH
        else ()
    )
    return CapabilityProfile(
        kind_class=block.kind_class,
        name=block.name,
        licensed_patterns=patterns,
        licensed_names=derived_names(patterns),
        allowed_tools=block.allowed_tools,
        tools=_granted_names(block.tools),
        disallowed_tools=block.disallowed_tools,
        granted_patterns=granted_patterns,
        granted_names=granted_names,
        permission_mode=str(block.permission_mode),
        allowed_subpaths=(*workspace_first, *trees),
    )


@dataclass(frozen=True, slots=True)
class KindBlock:
    """One kind block, as data — seam contract **I1** (§ Deliverable 1).

    The `class`, the kind `name`, the ten resolved key values, the resolved `prompt` path and the
    block reference `kinds.<class>.<name>` the journal and the receipt are filled with.

    Every field is read off the seed; the two derived ones are named as such. `prompt_path` is
    the **realpath-confined** resolution of `prompt`, and it is the only path a kind block
    carries — row M2's "no kind-block key but `prompt` is a path". `block_ref` is a property
    rather than a field so the reference cannot drift from the two names it is built out of.
    """

    kind_class: str
    name: str
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
    prompt_path: Path

    @property
    def block_ref(self) -> str:
        """`kinds.<class>.<name>` — what `JournalEntry.block_ref` and `SubagentSpawn.block_ref`
        are filled with (§ Deliverable 6). Minted here and nowhere else."""
        return f"{KINDS_BLOCK}.{self.kind_class}.{self.name}"

    def tools_argument(self) -> str | None:
        """What `--tools` is given for this kind, or `None` when the flag is omitted.

        The same function `TierSeat` answers with, so a spawn's tool set reaches the wire the way
        a seat's does and the seed's order is what the recorded argv shows back (S-44).
        """
        return tools_argument(self.tools)


def kinds_dir(root: Path) -> Path:
    """`<brain root>/seats/kinds/` — the one directory a kind's `prompt:` may resolve inside."""
    return BrainPaths(root=root).seats_dir / KINDS_BLOCK


def _refuse_a_body_key_at_this_level(level: Mapping[str, Any], where: tuple[str, ...]) -> None:
    """The landed `body` walk, scoped to ONE level's keys (§ Deliverable 1, folded: S-i10).

    `refuse_a_body_key_anywhere_else()` is **unedited** and does the refusing; what this adds is
    the scope. It is handed `dict.fromkeys(level)` — the keys with no mapping values — so the
    walk cannot descend past this level: a `body` key on a **kind block** is the eleventh key
    `TIER_KEYS`-exactly refuses, and the parser's order rule is that the specific refusal wins.
    What the walk covers here is the two **container** levels the block parser never reaches,
    `kinds.body` and `kinds.<class>.body`, which is the claim row G1 is the receipt of.
    """
    refuse_a_body_key_anywhere_else(dict.fromkeys(level), where)


def _prompt_path(value: str, root: Path, where: str) -> Path:
    """One block's `prompt:` → the resolved prefix file, refusing anything outside the directory.

    Realpath first, confinement second, existence third (A1-8, folded: S-i26). The order is the
    author's: a path that left the directory is a different mistake from a file that is not there
    yet, and the refusal that names the directory is the more useful one when both are true.
    """
    directory = kinds_dir(root).resolve()
    resolved = (root / value).resolve()
    if not resolved.is_relative_to(directory):
        raise SeatConfigError(
            f"{where}: prompt {value!r} resolves to {resolved}, outside {directory} — a kind's "
            f"prefix lives under `{KINDS_BLOCK}/` and the resolution is by realpath, so `..`, an "
            f"absolute path and a symlink whose target leaves the directory all refuse here. The "
            f"reason is the hash set: a prefix resolved outside the hashed tree can change under "
            f"a task with no drift refusal to catch it (A1-8, folded: S-i26)"
        )
    if not resolved.is_file():
        raise SeatConfigError(
            f"{where}: prompt {value!r} resolves to {resolved}, which is not a file — a kind's "
            f"prefix is a seed on disk and the loader requires it to exist (A1-8)"
        )
    return resolved


def _kind_block(
    kind_class: str,
    name: str,
    block: Any,
    root: Path,
    *,
    spawn_writable: Sequence[Path] = (),
    ceilings: Mapping[str, float] | None = None,
) -> KindBlock:
    """One `kinds.<class>.<kind>` block → a `KindBlock`, refusing everything outside its shape.

    `TIER_KEYS` **exactly**: `_tier_seat()` refuses a missing key and the check below refuses an
    eleventh, which is how a `body` key on a kind block, a `class:` key and a per-kind `sandbox:`
    each refuse **by name** (§ Deliverable 1). The ten values are coerced by the landed tier
    parser rather than re-read here, so a kind block and a `calls:` block cannot drift in what
    `model` or `add_dir` means.

    **The containment floor resolves here too** (§ Deliverable 2): the granted pair, the two caps
    and the permission mode are refused at **load** through `resolve_capability()`, the same
    resolution the desk runs per spawn — so a kind that could not be spawned safely never loads.
    """
    where = f"{KINDS_BLOCK}.{kind_class}.{name}"
    if not isinstance(block, Mapping):
        raise SeatConfigError(
            f"{where}: a kind block is a mapping of the ten keys a block takes, not "
            f"{type(block).__name__}"
        )
    extra = sorted(key for key in block if key not in TIER_KEYS)
    if extra:
        reasons = "".join(f" — {_NAMED_EXTRAS[key]}" for key in extra if key in _NAMED_EXTRAS)
        raise SeatConfigError(
            f"{where}: seats.yaml carries {extra}, outside the ten keys a block takes "
            f"({list(TIER_KEYS)}) — a kind block is TIER_KEYS exactly, not a superset{reasons}"
        )
    seat = _tier_seat(name, block, where=where)
    resolved = KindBlock(
        kind_class=kind_class,
        name=name,
        model=seat.model,
        effort=seat.effort,
        permission_mode=seat.permission_mode,
        allowed_tools=seat.allowed_tools,
        disallowed_tools=seat.disallowed_tools,
        tools=seat.tools,
        add_dir=seat.add_dir,
        max_call_usd=seat.max_call_usd,
        timeout_seconds=seat.timeout_seconds,
        prompt=seat.prompt,
        prompt_path=_prompt_path(seat.prompt, root, where),
    )
    _refuse_caps_above_the_spawn_ceiling(resolved, ceilings, where)
    # The floor, at load: every refusal of § Deliverable 2 is raised from I2, and the object is
    # discarded here on purpose — the desk resolves it again per spawn with the workspace, and a
    # block that carried its own copy would be a second owner of the granted pair.
    resolve_capability(resolved, spawn_writable=spawn_writable)
    return resolved


def parse_kinds(
    payload: Mapping[str, Any],
    root: Path,
    *,
    spawn_writable: Sequence[Path] = (),
    ceilings: Mapping[str, float] | None = None,
) -> dict[str, dict[str, KindBlock]]:
    """The `kinds:` container → `{class: {kind: KindBlock}}`, refusing anything it does not name.

    **Eager like `parse_sandbox()` and `parse_calls()`**, and for their reason: both class
    sub-mappings are present and may be empty, and the container itself may not be absent,
    because a containment surface that is simply missing is a floor authored by omission
    (§ Deliverable 1). **A.1.i ships both empty.**

    **The keys are compared as a SET** (folded: S-i52). `config.KIND_CLASSES`' order is the order
    its derivation produces and scopes that literal alone, never the document — so a seed may
    spell the two classes either way and the SPEC's own `dispatch:`-first block loads.

    Called from `parse_seats()` **before** the landed `body` walk and after the tier walk, so the
    specific refusal still wins and the walk still runs last.

    `spawn_writable` and `ceilings` are the `runtime:` block's own two contributions to a kind's
    refusal — the trees a spawn's allowed set is composed over, and the two caps a block's own are
    refused above (§ Deliverable 5). Both default empty so that a caller reading the container
    alone still gets every refusal that belongs to the container.
    """
    block = payload.get(KINDS_BLOCK)
    if not isinstance(block, Mapping):
        raise SeatConfigError(
            f"seats.yaml carries no `{KINDS_BLOCK}` container — the two class sub-mappings are "
            f"present and may be empty, and the container itself may not be absent, because a "
            f"containment surface that is simply missing is a floor authored by omission "
            f"(§ Deliverable 1). A root that defines no kind still carries "
            f"`{KINDS_BLOCK}:` with {list(protean_config.KIND_CLASSES)} and nothing under them"
        )
    # The container's own level, before its keys are read as class names: the landed walk is what
    # refuses `kinds.body`, and it cannot be reached from `parse_seats()`'s last call if this
    # function has already refused the key as an unknown class.
    _refuse_a_body_key_at_this_level(block, (KINDS_BLOCK,))

    classes = protean_config.KIND_CLASSES
    unknown = sorted(name for name in block if name not in classes)
    if unknown:
        misplaced = sorted(
            name
            for name in unknown
            if isinstance(block[name], Mapping) and any(key in TIER_KEYS for key in block[name])
        )
        detail = (
            f" — {misplaced} reads as a kind block at the container level, and a kind "
            f"block sits under its class sub-mapping, never beside one"
            if misplaced
            else ""
        )
        raise SeatConfigError(
            f"{KINDS_BLOCK}: names {unknown}, outside the two classes a kind may belong to "
            f"({list(classes)}){detail}. The class is the sub-mapping, never a key on the block "
            f"(§ Deliverable 1, S-A5)"
        )
    missing = [name for name in classes if name not in block]
    if missing:
        raise SeatConfigError(
            f"{KINDS_BLOCK}: seats.yaml carries no {', '.join(missing)} sub-mapping — both "
            f"classes are present and may be empty (§ Deliverable 1)"
        )

    parsed: dict[str, dict[str, KindBlock]] = {}
    for kind_class in classes:
        sub = block[kind_class]
        if not isinstance(sub, Mapping):
            raise SeatConfigError(
                f"{KINDS_BLOCK}.{kind_class}: a class sub-mapping holds `<kind>: <block>` and is "
                f"a mapping, not {type(sub).__name__} — an empty one is spelled `{{}}`"
            )
        # The class level, for the same reason and with the same scope: `kinds.<class>.body`.
        _refuse_a_body_key_at_this_level(sub, (KINDS_BLOCK, kind_class))
        parsed[kind_class] = {
            name: _kind_block(
                kind_class,
                str(name),
                sub[name],
                root,
                spawn_writable=spawn_writable,
                ceilings=ceilings,
            )
            for name in sub
        }
    return parsed
