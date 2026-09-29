"""The spawn desk — seam contract **I5**, and the bound every wave is checked against.

`the build specification (not in this mirror)` § Deliverable 4 (what "concurrently" means
mechanically, I5's definition, the two openers, the two open-time refusals, the kill and the
torn wave) and § Deliverable 5 (the four static bounds, the **sum** arithmetic, and the bound
check as one function on the desk rather than a lettered contract — I3 is retired).

**One port instance per spawn, not per wave** (folded: S-i13). `LiveSeat` clears its facts list
at the top of every call, so two concurrent members sharing one instance would each erase the
other's receipt: one instance per member is the mechanism and not a preference. The desk yields
that instance, keyed `(class, kind)` and carrying a `member#` where a wave supplies one, and
constructs it with **three** facts — the kind block it resolved by `(class, kind)`, the
workspace it was opened with, and the **calling node**, which is read structurally for a
`dispatch` member and off the `NodeCall` payload for a delegate rather than carried as a
constructor field (§ Resolutions D7-1).

**The desk lives for exactly one tick and the tick has exactly one** (folded: S-i36).
`SpawnDesks` below is the seam `SeatLayer.spawns` holds: it **memoizes per `(task, tick)`** and
hands the same `SpawnDesk` back to every caller, where `tick_calls_of()`'s landed factory mints
a fresh desk per call. That is what lets one `spawns_of()` carry the tick's every spawn — a
wave's members and a node's delegates together — keyed by the journal's own
`(node, call#, member#)` rather than as an ordered stream (folded: S-i42).

**Construction is not the open.** The seam constructs a desk for every tick of a live root,
including the overwhelming majority that spawn nothing, so construction refuses nothing and
probes nothing. `open()` is what the two callers do before their first spawn, and it is where
the two pre-process refusals and the version probe land — so a tick with no wave and no delegate
opens no desk, and a wave that is refused is refused **after** the manager's plan is journalled,
which is what makes the refusal recoverable by `resume` at all (§ Deliverable 5).

**Two callers open it, and only two** (§ Deliverable 4). `runtime.cycle.run_wave` uses it once
per wave — bounds checked over the members before the first spawn, one instance per member
started and joined, the journal's buffered entries written in `member#` order — and the
`node_calls` desk's `delegate` arm uses it once per call, for one spawn with no `member#`.

**The witness is composed here and derived next door** (§ Deliverable 6). The desk takes one
**baseline** per opener call — immediately after `open()`, so for the first opener it is the desk's
own open — and reads it once after the wave joins: one wave, one baseline, one diff, so `wrote` and
`wrote_outside_workspace` are the *wave's* lists and every member's receipt carries them
**identically**, exactly as `dispatch_id` does. The two per-spawn lists come from that spawn's own
denials, and the **process group's live members are read at that spawn's own join**, off the `pgid`
`invoke.py` publishes on its facts (folded: S-i57). The derivations themselves live in
`protean.cortex.live.audit`, which imports build 2's landed classifier and re-derives none of it.

**What is not here.** The receipt's own columns and the schema bump are `protean.state`'s and
`protean.config`'s; this module fills `SeatCallFacts` and the runtime writes the line.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from protean import config as protean_config
from protean.cortex.adapters import SeatDesk
from protean.cortex.calls import CallConfigurationError
from protean.cortex.live import audit as spawn_audit
from protean.cortex.live.config import (
    CallCapExceeded,
    SeatConfigError,
    SeatsConfig,
)
from protean.cortex.live.invoke import LiveSeat, spawn_scaffold_dir
from protean.cortex.live.kinds import KindBlock, spawn_allowance_subpaths
from protean.cortex.live.session import LiveSessionBook
from protean.runtime.errors import SeatUnavailable
from protean.runtime.seat import MemberUnfinished, SeatCallFacts
from protean.state.calls import NodeCall
from protean.state.enums import CallType, NodeName
from protean.state.seats import SeatEnvelope, WaveMember

#: The journal's own key, which is what `spawns_of()` is keyed by: `(node, call#, member#)`, a
#: member's carrying its `member#` and a delegate's carrying none (folded: S-i42).
SpawnKey = tuple[str, int, int | None]

#: **The three named reasons the desk refuses under, and they are reasons rather than classes**
#: (§ Deliverable 4, § Deliverable 5, folded: S-i3). All three travel on A.1's
#: `SeatUnavailable` — its "no configuration" shape, the one `run_wave`'s landed catch already
#: passes to the boundary — so the tick completes, a checkpoint is written and the terminal is
#: `stopped` rather than torn. A.1's four refusal *classes* are unchanged and none moves.
REASON_NO_KIND = "no_kind"
REASON_WAVE_BOUND = "wave_bound"
REASON_NO_WORKSPACE = "no_workspace"

#: The fourth, which is an **assertion that holds structurally** rather than a hole it closes
#: (folded: S-i48): order W3 moved the link farm and the `add_dir: false` cwd into
#: `brain/state/<task>/spawns/<tick>/`, a tree `sandbox.deny_write` names, so a farm inside the
#: allowed set is unreachable by construction. The check stays, because a farm writable by the
#: very process whose `PATH` it defines is a spawn free to repoint its own symlinks and an
#: assertion that cannot fire costs one comparison.
REASON_FARM_WRITABLE = "farm_writable"

#: A load-time `SeatConfigError` met on the spawn path — a payload outside its shape, a
#: `bin_links` entry that resolves to the seat binary — turned into the class the tick can
#: actually catch (§ Resolutions D7-3). **Nothing in the tick catches `SeatConfigError`**, and a
#: torn tick writes no checkpoint and re-refuses on every replay, so it never escapes the desk.
REASON_SPAWN_CONFIG = "spawn_configuration"


def _inside(child: Path, parent: Path) -> bool:
    """Is `child` the tree `parent` names, or under it? One comparison, both callers."""
    return child == parent or parent in child.parents


#: Where the CLI records what its permission layer **refused**, on the `json` envelope's own top
#: level. `SeatEnvelope` is extra-tolerant at the wire (build 1's `ExtraTolerantModel`), so the list
#: arrives exactly as the CLI sent it and is read off the model's extras rather than re-parsed.
DENIALS_KEY = "permission_denials"


def _denials_off(envelope: SeatEnvelope | None) -> tuple[Mapping[str, Any], ...]:
    """The envelope's own `permission_denials`, as received. Empty where it carried none.

    A denial is a **receipt and not a violation** (build 2's S-44): the call was refused, so it did
    not run — which is what makes the list the source both audit lists derive from rather than a
    finding in itself.
    """
    if envelope is None:
        return ()
    found = (envelope.model_extra or {}).get(DENIALS_KEY)
    if not isinstance(found, Sequence) or isinstance(found, (str, bytes)):
        return ()
    return tuple(one for one in found if isinstance(one, Mapping))


@dataclass(slots=True)
class SpawnDesk:
    """**I5** — the tick's one spawner: one port instance per spawn, on one desk.

    `the build specification (not in this mirror)` § Deliverable 4. Constructed by the seam below
    and never directly by the runtime, which reaches it through
    `protean.runtime.seat.spawn_desk_of()` and learns nothing about a kind block.

    `workspace` is the value the **first** caller to resolve the desk this tick handed it —
    `TickContext.workspace_path`, which is where the runtime already keeps it and the one value a
    spawn's `--add-dir` is built from (folded: S-i22). There is no second channel: a member
    payload carrying any key outside `WaveMember`'s three fields is refused before any process by
    order W3's `refuse_a_payload_outside_its_shape()`, and `workspace_for()` reads the
    construction-time value only for a spawn addressee.
    """

    config: SeatsConfig
    root: Path
    task: str
    tick: int
    workspace: str = ""
    #: One `SeatDesk`/`LiveSessionBook` pair for the desk's instances. Neither is read on a spawn
    #: path — a call type is **session-less** (folded: S-A31), so `_invoke()` mints a handle per
    #: invocation and the book is never written — and they are constructed here rather than per
    #: instance so the shape matches what `fake_cli.spawn_seat()` constructs.
    _seats: SeatDesk = field(default_factory=SeatDesk)
    _sessions: LiveSessionBook = field(default_factory=LiveSessionBook)
    _instances: dict[SpawnKey, LiveSeat] = field(default_factory=dict)
    _facts: dict[SpawnKey, SeatCallFacts] = field(default_factory=dict)
    #: The block each spawn resolved, by the same key. It is where `block_ref` and the **effective
    #: caps** are read from at the join, and the journal's `block_ref` column with it.
    _blocks: dict[SpawnKey, KindBlock] = field(default_factory=dict)
    #: The envelope's own `permission_denials` per spawn. Empty for a spawn that returned none — and
    #: for one that returned no envelope at all, which is a refusal rather than a silence.
    _denials: dict[SpawnKey, tuple[Mapping[str, Any], ...]] = field(default_factory=dict)
    #: The **live members of each spawn's process group, read at that spawn's own join**
    #: (folded: S-i21, folded: S-i57). A fact about the group, never a prevention.
    _groups: dict[SpawnKey, tuple[int, ...]] = field(default_factory=dict)
    #: The desk's own working state between an opener's `open()` and its join. **Never persisted**
    #: and never referenced from a receipt (folded: S-i47).
    _baseline: spawn_audit.SpawnBaseline = field(default_factory=spawn_audit.SpawnBaseline)
    _version: str = ""
    _opened: bool = False

    # ----------------------------------------------------------------------------------
    # The open: two refusals, before either caller spawns anything
    # ----------------------------------------------------------------------------------

    def is_open(self) -> bool:
        """Has a caller already opened this desk? What makes the workspace settle once."""
        return self._opened

    def open(self) -> None:
        """Refuse twice, then let a spawn happen. Idempotent, so two openers cost one open.

        **(a)** A desk opened with an **empty or unresolvable** workspace refuses as
        `SeatUnavailable` under `REASON_NO_WORKSPACE` — no process, terminal `stopped`, a
        checkpoint written, and the journalled plan recoverable by `resume` once a workspace is
        supplied. A workspace resolving **inside any `sandbox.deny_write` tree** refuses here too,
        for `parse_spawn_writable()`'s reason one channel over (folded: S-i43).

        **(b)** A desk whose **link-farm directory resolves inside any allowed subpath** refuses
        here as well, now as an assertion that holds structurally (folded: S-i48).
        """
        if self._opened:
            return
        resolved = self._resolved_workspace()
        self._refuse_a_farm_inside_the_allowed_set(resolved)
        self._opened = True

    def take_the_baseline(self) -> None:
        """The baseline this opener's diff is read against — **one wave, one baseline, one diff**.

        Called by each opener immediately after `open()`, so for the **first** opener it is taken at
        the desk's own open and before its first member spawned (§ Deliverable 6). A second opener on
        the same tick's desk takes its own, because `wrote` is "per spawn only for a **delegate**,
        whose wave is one" (folded: S-i24) — one baseline for the whole tick would hand a delegate
        that ran after a wave the wave's own writes, which is per-member attribution faked from a
        diff that cannot supply it (row B52).

        The workspace is the tree `wrote` is of; `allowed_subpaths(None)` is the set
        `wrote_outside_workspace` is asked of — the resolved `runtime.spawn_writable` trees and
        `SPAWN_PROCESS_ALLOWANCES`' own **directories**, the workspace deliberately not among them.
        """
        self._baseline = spawn_audit.take_baseline(
            self._resolved_workspace(), self.allowed_subpaths(None)
        )

    def _resolved_workspace(self) -> Path:
        """The workspace as a resolved directory, or the named refusal (§ Deliverable 4 (a))."""
        named = str(self.workspace or "")
        if not named:
            raise SeatUnavailable(
                tier=str(CallType.DISPATCH),
                reason=REASON_NO_WORKSPACE,
                message=(
                    "the desk was opened with no workspace, and a spawn's `--add-dir` is the "
                    "runtime's task workspace or the spawn does not happen — `protean run "
                    "--workspace <path>` supplies one on a live root, `dry` and the wet probe "
                    "already hand one, and the absence lands here rather than at the parser "
                    "(§ Deliverable 4, decision 3)"
                ),
            )
        candidate = Path(named).expanduser()
        try:
            resolved = candidate.resolve()
        except OSError as fault:  # pragma: no cover — resolve() is non-strict
            raise SeatUnavailable(
                tier=str(CallType.DISPATCH),
                reason=REASON_NO_WORKSPACE,
                message=f"the workspace {named!r} does not resolve ({fault})",
            ) from fault
        if not resolved.is_dir():
            raise SeatUnavailable(
                tier=str(CallType.DISPATCH),
                reason=REASON_NO_WORKSPACE,
                message=(
                    f"the workspace {named!r} resolves to {resolved}, which is not a directory "
                    f"on this machine — a spawn's one writable grant cannot be a path that is "
                    f"not there (§ Deliverable 4)"
                ),
            )
        for denied in self.config.sandbox.deny_write:
            if _inside(resolved, denied):
                raise SeatUnavailable(
                    tier=str(CallType.DISPATCH),
                    reason=REASON_NO_WORKSPACE,
                    message=(
                        f"the workspace {resolved} resolves inside the "
                        f"`sandbox.deny_write` tree {denied} — a spawn's composed profile allows "
                        f"`file-write*` back under the workspace, so a workspace inside a denied "
                        f"tree is the allowed set and the denied one in collision "
                        f"(folded: S-i43)"
                    ),
                )
        return resolved

    def allowed_subpaths(self, workspace: Path | None = None) -> tuple[Path, ...]:
        """Every **directory** a spawn of this desk may be allowed to write.

        The task workspace, the resolved `runtime.spawn_writable` trees and
        `SPAWN_PROCESS_ALLOWANCES`' own directories — its device literals excluded by name,
        because a device is not a directory (folded: S-i49). It is the set refusal (b) compares
        the link farm against, and the one order W5's `wrote_outside_workspace` is asked of.
        """
        trees = [Path(tree) for tree in self.config.spawn_writable]
        trees += [Path(entry).expanduser().resolve() for entry in spawn_allowance_subpaths()]
        if workspace is not None:
            trees.insert(0, workspace)
        return tuple(trees)

    def scaffold(self) -> Path:
        """`brain/state/<task>/spawns/<tick>/` — the runtime-owned home of this tick's spawns.

        Built by `invoke.spawn_scaffold_dir()` rather than spelled here, so the shape has one
        owner: the desk supplies the tick's facts and the builder decides where a spawn's own
        directories sit.
        """
        return spawn_scaffold_dir(self.root, self.task, self.tick)

    def _refuse_a_farm_inside_the_allowed_set(self, workspace: Path) -> None:
        """Refusal (b): the link farm may not resolve inside any allowed subpath."""
        farm = self.scaffold().resolve()
        for allowed in self.allowed_subpaths(workspace):
            if _inside(farm, allowed):
                raise SeatUnavailable(
                    tier=str(CallType.DISPATCH),
                    reason=REASON_FARM_WRITABLE,
                    message=(
                        f"this desk's link farm resolves to {farm}, inside the allowed subpath "
                        f"{allowed} — a farm writable by the very process whose `PATH` it "
                        f"defines is a spawn free to repoint its own symlinks (folded: S-i48)"
                    ),
                )

    # ----------------------------------------------------------------------------------
    # The kind: resolved through the one resolver that can name which kind
    # ----------------------------------------------------------------------------------

    def block_for(self, kind_class: str, name: str) -> KindBlock:
        """`(class, kind)` → the resolved block, or `SeatUnavailable`/`REASON_NO_KIND`.

        `SeatsConfig.kind()` is the only resolver that can name WHICH kind — `block()` stays
        addressee-only, an addressee being unable to carry a kind name (folded: S-i2) — and it
        raises a plain `SeatConfigError`, because the named class is the **desk's**: a kind the
        seed does not define is "no configuration", so it reaches the boundary as
        `SeatUnavailable` exactly as an over-bound wave does, a checkpoint is written and the
        terminal is `stopped`. A seed edit that defines the kind lets `resume --reseed` replay the
        same journalled plan and proceed (folded: S-i3).
        """
        try:
            return self.config.kind(kind_class, name)
        except SeatConfigError as fault:
            raise SeatUnavailable(
                tier=str(kind_class), reason=REASON_NO_KIND, message=str(fault)
            ) from fault

    def block_refs_of(self) -> Mapping[SpawnKey, str]:
        """`kinds.<class>.<name>` per spawn, keyed by the journal's own key.

        The journal's `block_ref` column is filled from here (§ Deliverable 6, folded: S-i51): the
        reference is `KindBlock.block_ref`'s and is **minted nowhere else**, and `protean.runtime`
        may not import `protean.cortex` to build one — so the runtime reads it off the desk exactly
        as it reads `calls_for()` off the node-call desk, through the accessor and never by asking
        the desk what kind of desk it is. A spawn the desk never resolved a block for is absent, and
        an absent key is an entry with no containment to name.
        """
        return {key: block.block_ref for key, block in self._blocks.items()}

    # ----------------------------------------------------------------------------------
    # The bound: one function on the desk, composing its refusal from what it compared
    # ----------------------------------------------------------------------------------

    def refuse_a_wave_outside_its_bounds(self, blocks: Sequence[KindBlock]) -> None:
        """The wave bound, checked **before the first member spawns** (§ Deliverable 5).

        Two comparisons do not earn a persisted model (I3 is retired — folded: S-i16), so this is
        one function that composes its refusal from what it compared: the four resolved bounds,
        the wave's member count, the members' effective caps and their **sum**. The message and
        the arithmetic therefore cannot drift, because one function produces both — which is what
        row G6 reads when it asks the refusal to quote the arithmetic.

        The **sum** is what makes a heterogeneous wave's ceiling well-defined (H4): members carry
        different kinds with different caps, and `members × one cap` describes no wave that
        actually exists. **What the bounds bound is configured caps, not spend** (folded: S-i25):
        `--max-budget-usd` stops the *next* turn, so a member may overshoot its own cap by at
        most one turn and a wave by one turn per member — witnessed on `usage`, counted by
        homeostasis, and never refused in advance (row B46).

        **Delegates are not members** and count against neither bound (folded: S-i13); no
        per-tick delegate bound exists and none is named here.
        """
        count = len(blocks)
        caps = tuple(float(block.max_call_usd) for block in blocks)
        total = math.fsum(caps)
        width = int(self.config.max_wave_members)
        ceiling = float(self.config.spawn_max_wave_usd)
        arithmetic = (
            f"{count} member(s) against `runtime.max_wave_members` {width}; effective "
            f"`max_call_usd` caps {list(caps)} summing to {total} against "
            f"`runtime.spawn_max_wave_usd` {ceiling}; the per-spawn ceilings are "
            f"`runtime.spawn_max_call_usd` {float(self.config.spawn_max_call_usd)} and "
            f"`runtime.spawn_timeout_seconds` {float(self.config.spawn_timeout_seconds)}"
        )
        if count > width:
            raise SeatUnavailable(
                tier=str(CallType.DISPATCH),
                reason=REASON_WAVE_BOUND,
                message=(
                    f"the wave is wider than the bound and no member was spawned — {arithmetic}"
                ),
            )
        if total > ceiling:
            raise SeatUnavailable(
                tier=str(CallType.DISPATCH),
                reason=REASON_WAVE_BOUND,
                message=(
                    f"the wave's caps sum above the bound and no member was spawned — "
                    f"{arithmetic}"
                ),
            )

    # ----------------------------------------------------------------------------------
    # The instances: one per spawn, the version resolved once per desk
    # ----------------------------------------------------------------------------------

    def cli_version(self) -> str:
        """The binary's version, resolved **once per desk** and handed to every instance (A1-14).

        `LiveSeat.cli_version()` caches per instance, so per-member instances would otherwise
        probe once each and double a wave's process count for no new fact — which is why row G7's
        count is "four CLI processes plus one version probe" and not five plus one. The probe
        instance carries no kind, so it is not a spawn and runs unwrapped, exactly as a seat's
        own probe does.
        """
        if not self._version:
            probe = LiveSeat(config=self.config, desk=self._seats, sessions=self._sessions)
            self._version = probe.cli_version()
        return self._version

    def instance(
        self, block: KindBlock, key: SpawnKey, *, unit_intent: str | None = None
    ) -> LiveSeat:
        """**One port instance per spawn**, built from the three facts (§ Deliverable 4).

        Keyed by the journal's own `(node, call#, member#)`, which is unique per spawn — so two
        members naming one kind get two instances and a second read of one spawn gets the one
        instance that served it. The **calling node** is the third fact and is not a field
        (§ Resolutions D7-1): `prefix_node()`'s structural arm answers the cortex for a
        `dispatch` member, and a delegate's travels on the `NodeCall` payload.
        """
        existing = self._instances.get(key)
        if existing is not None:
            return existing
        made = LiveSeat(
            config=self.config,
            desk=self._seats,
            sessions=self._sessions,
            workspace_path=str(self.workspace or ""),
            kind=block,
            spawn_scaffold=self.scaffold(),
            unit_intent=unit_intent,
            _version=self.cli_version(),
        )
        self._instances[key] = made
        return made

    # ----------------------------------------------------------------------------------
    # Opener one: the wave, concurrently, one thread each
    # ----------------------------------------------------------------------------------

    def dispatch_wave(
        self,
        members: Mapping[int, WaveMember],
        *,
        node: str = str(NodeName.CORTEX),
        call_number: int,
        order: Sequence[int] = (),
        units: Mapping[str, str] | None = None,
    ) -> dict[int, Any]:
        """The wave, bounded then spawned: `member# → SeatEnvelope`, or that member's own fault.

        `the build specification (not in this mirror)` § Deliverable 4. The members run **at the same
        time, one port instance per member, each on its own thread**, and the wave **joins only
        after every member has returned or been killed**, so no member process outlives the tick
        that started it. `member#` is assigned by the caller before anything starts, from the
        order the `ManagerPlan` lists the members, so the journal's line order stays the wave's
        order and not the completion order.

        What comes back per member is an envelope or an **exception instance**, never a raised
        one: the caller holds the landed classification — `MemberUnfinished` marks that member
        failed and merges the wave `partial`, and the three named faults and no more are caught
        there. Two things are raised from here instead, because they are facts about the **wave**
        and not about a member: the three pre-process refusals above, and anything unnamed, which
        propagates because a process that died mid-wave is not a fault the runtime caught.

        **The desk re-raises a member's `CallCapExceeded` or timeout as `MemberUnfinished`** —
        the producer A.1 declared and never wrote (folded: S-i41). `CallCapExceeded` is a
        `SeatConfigError`, which nothing in the tick catches, so a kill or a crossed cap would
        otherwise tear the tick instead of failing one member.

        **`units` carries each member's unit `intent`** (`the build specification (not in this mirror)`
        § Deliverable 7, L20): a mapping from unit id to that unit's `intent` — a string per unit,
        so no other field of the unit can travel — read per member as `units[member.unit_id]` and
        handed to that member's instance, whose `system_prompt()` appends it after a fixed delimiter
        line. `None` sends the two seed halves alone, the landed behaviour. On the runtime path
        `run_wave` fills it and guarantees every key; a direct caller builds the mapping from the
        members it hands, and the desk adds no refusal of its own. The sent prompt is therefore
        reconstructable from the seat-call receipt's recorded `argv`, and not from the checkpoint
        alone: a re-plan replaces the unit there, and the delimiter is outside `seed_hashes()`.
        """
        self.open()
        self.take_the_baseline()
        numbers = sorted(members)
        blocks = {
            number: self.block_for(protean_config.CALL_DISPATCH, members[number].kind)
            for number in numbers
        }
        self.refuse_a_wave_outside_its_bounds([blocks[number] for number in numbers])
        run_order = list(order) if order else numbers
        keys = {number: (node, call_number, number) for number in run_order}
        instances = {
            number: self.instance(blocks[number], keys[number])
            if units is None
            else self.instance(
                blocks[number], keys[number], unit_intent=units[members[number].unit_id]
            )
            for number in run_order
        }
        results: dict[int, Any] = {}
        with ThreadPoolExecutor(max_workers=max(len(run_order), 1)) as pool:
            futures = {
                number: pool.submit(
                    self._spawn_one,
                    instances[number],
                    CallType.DISPATCH,
                    members[number],
                    keys[number],
                    blocks[number],
                )
                for number in run_order
            }
        # The `with` block joined every thread, so every member has returned or been killed
        # before a single outcome is classified — which is also the instant the wave's own diff is
        # taken: one baseline before the first member, one diff after the last (§ Deliverable 6).
        self.witness([keys[number] for number in run_order])
        for number in run_order:
            try:
                results[number] = futures[number].result()
            except CallCapExceeded as fault:
                results[number] = MemberUnfinished(
                    f"member {number} ({blocks[number].block_ref}) crossed its own "
                    f"{fault.cap} of {fault.limit}: {fault}"
                )
            except TimeoutError as fault:  # pragma: no cover — a cap arrives as CallCapExceeded
                results[number] = MemberUnfinished(
                    f"member {number} ({blocks[number].block_ref}) ran past its timeout: {fault}"
                )
            except SeatConfigError as fault:
                raise SeatUnavailable(
                    tier=str(CallType.DISPATCH),
                    reason=REASON_SPAWN_CONFIG,
                    message=(
                        f"member {number} ({blocks[number].block_ref}): {fault} — turned into "
                        f"the wave's own class here, because nothing in the tick catches a "
                        f"`SeatConfigError` and a torn tick writes no checkpoint "
                        f"(§ Resolutions D7-3)"
                    ),
                ) from fault
        return results

    # ----------------------------------------------------------------------------------
    # Opener two: one delegate, one spawn, no `member#`
    # ----------------------------------------------------------------------------------

    def delegate(self, call: NodeCall) -> SeatEnvelope:
        """One delegate call → one spawn, keyed by the calling node's own `(node, call#)`.

        The arm resolves `(delegate, payload.kind)` through `SeatsConfig.kind()` and opens **one
        spawn per call** with **no `member#`**, a delegate being no member of any wave: it counts
        against neither wave bound and no per-tick delegate bound exists (folded: S-i13).

        **A delegate's faults are the calling node's signals, not the wave's.** A kind the seed
        does not define is A.1's delegate class — `missing_configuration`, the layer having no
        answer configured for this addressee — rather than `SeatUnavailable`/`REASON_NO_KIND`
        (folded: S-i3); and a delegate's `CallCapExceeded` is left exactly as it is raised,
        because it is the calling node's refusal signal and not a wave fault (folded: S-i41).
        Both reach the calling node through `NodeCallDesk.call()`'s own classification.
        """
        self.open()
        self.take_the_baseline()
        name = str(dict(call.payload).get("kind") or "")
        try:
            block = self.config.kind(protean_config.CALL_DELEGATE, name)
        except SeatConfigError as fault:
            raise CallConfigurationError(str(fault)) from fault
        key: SpawnKey = (str(call.node), int(call.call_number), None)
        try:
            return self._spawn_one(
                self.instance(block, key), CallType.DELEGATE, call, key, block
            )
        finally:
            # **A delegate's wave is one spawn** (folded: S-i24), so its diff is its own and is taken
            # at its own join rather than shared with anything. The `finally` is the refusal path's
            # reason: a delegate that raised still has facts, and a witness only a returning spawn
            # got would be a witness of the successes.
            self.witness([key])

    # ----------------------------------------------------------------------------------
    # What the boundary reads back
    # ----------------------------------------------------------------------------------

    def _spawn_one(
        self,
        instance: LiveSeat,
        addressee: CallType,
        request: Any,
        key: SpawnKey,
        block: KindBlock | None = None,
    ) -> SeatEnvelope:
        """One spawn, with its facts recorded under its journal key whatever it did.

        The facts are read off the instance in a `finally`, so a refused spawn's argv and caps
        reach the boundary exactly as a returned one's do — a receipt composed from the single
        construction-time `LiveSeat` would see no per-spawn instance at all (folded: S-i4).

        **The process group is read in that same `finally`, which is this spawn's own join**
        (folded: S-i21, folded: S-i57): the group's live members are what witness a grandchild that
        named the binary by absolute path, and reading them after the *whole wave* joined would let a
        later member's wall move an earlier one's answer. The `pgid` it reads them off is
        `invoke.py`'s, published on the facts and carried on no receipt column.

        **The denials are read off the returned envelope** — extra-tolerant at the wire, so
        `permission_denials` arrives as the CLI sent it. A spawn that returned no envelope produced
        no denial list, which is a refusal and not a silence.
        """
        if block is not None:
            self._blocks[key] = block
        try:
            envelope = instance(addressee, request)
            self._denials[key] = _denials_off(envelope)
            return envelope
        finally:
            facts = instance.calls()
            if facts:
                self._facts[key] = facts[-1]
                self._groups[key] = spawn_audit.live_process_group_members(facts[-1].pgid)

    def witness(self, keys: Sequence[SpawnKey]) -> None:
        """One diff for the wave, one witness per spawn — read **after the wave joins**.

        `the build specification (not in this mirror)` § Deliverable 6. The two wave-level lists are
        computed **once** from the opener's baseline and handed to every spawn of that opener, so they
        are byte-identical on every member's receipt of the wave exactly as `dispatch_id` is; the two
        per-spawn lists come from that spawn's own denials, its own refusal text and its own process
        group. Per-member attribution is not available from one baseline and one diff and is not
        faked here (row B52).

        This is also where the receipt's other two new columns are filled: the **effective caps as
        they ran**, off the block this spawn resolved. `invoke.py` publishes the `pgid` and nothing
        else, so the facts' four receipt-bound fields are all set here — the one place the block, the
        envelope's denials and the tick's baseline are in hand together.
        """
        shared = spawn_audit.wave_level_diffs(self._baseline)
        for key in keys:
            facts = self._facts.get(key)
            if facts is None:
                continue
            block = self._blocks.get(key)
            denials = self._denials.get(key, ())
            self._facts[key] = replace(
                facts,
                max_call_usd=None if block is None else float(block.max_call_usd),
                timeout_seconds=None if block is None else float(block.timeout_seconds),
                permission_denials=tuple(denials),
                audit=spawn_audit.compose(
                    wave_level=shared,
                    denials=denials,
                    workspace=self._baseline.workspace,
                    bin_links=self.config.bin_links,
                    error=facts.error,
                    pgid=facts.pgid,
                    live_members=self._groups.get(key, ()),
                ),
            )

    def spawns_of(self) -> Mapping[SpawnKey, SeatCallFacts]:
        """The tick's every spawn, **keyed by the journal's own key** (folded: S-i42).

        `(node, call#, member#)` — a member's carrying its `member#`, a delegate's carrying none
        — so the boundary looks each journalled entry's facts up by that key rather than
        positionally. An ordered stream was a rule this build would have invented: the landed
        FIFO-by-tier-string match would meet a pre-cortex delegate's entry with a later
        `dispatch` fact and write that entry empty. The FIFO match stays exactly as it is for
        `calls_of()`; **this** is the spawn's carrier, and it is the desk's own method where
        `spawn_desk_of()` is the layer's accessor, so no machine row reads two things under one
        word (folded: S-i23).
        """
        return dict(self._facts)


@dataclass(slots=True)
class SpawnDesks:
    """`protean.runtime.seat.Spawns` — the fifth optional seam, **memoized per `(task, tick)`**.

    A factory on `CallDesks`' precedent, because a desk cannot outlive the tick that opened it,
    and with the one departure that makes the desk's identity a rule rather than a hope
    (folded: S-i36): it holds the tick's desk and returns the **same object** to every caller,
    where `tick_calls_of()`'s landed factory mints a fresh one per call. A second resolution
    inside one tick therefore opens no second desk, and one `spawns_of()` carries the tick's
    every spawn.

    **One slot, not a registry**: the desk dies with the tick that opened it, so a new
    `(task, tick)` replaces the one before it rather than accumulating beside it.

    `workspace` is honoured on the **first** resolution of a tick and ignored after — which is
    exactly "the desk is handed the tick's workspace at open, from whichever caller opened it"
    (folded: S-i22). It reaches the seam from `TickContext` per tick and never through the
    layer's construction, which is why `build_live_layer()` needs no workspace to attach this.
    """

    config: SeatsConfig
    root: Path
    opened: list[SpawnDesk] = field(default_factory=list)
    _key: tuple[str, int] | None = None
    _desk: SpawnDesk | None = None

    def __call__(self, task: str, tick: int, workspace: str = "") -> SpawnDesk:
        key = (str(task), int(tick))
        if self._desk is not None and self._key == key:
            # **Late-bound, so the resolution order is not load-bearing**: whichever caller first
            # names the tick's workspace is the one that hands it over, even if a caller that had
            # none resolved the desk first. It is set once and never replaced, so the desk cannot be
            # re-pointed at a second directory mid-tick — which is the whole of "one channel".
            if workspace and not self._desk.workspace and not self._desk.is_open():
                self._desk.workspace = str(workspace)
            return self._desk
        desk = SpawnDesk(
            config=self.config,
            root=self.root,
            task=str(task),
            tick=int(tick),
            workspace=str(workspace or ""),
        )
        self._key = key
        self._desk = desk
        self.opened.append(desk)
        return desk
