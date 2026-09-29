"""`build()` — the entry point the runtime resolves a seat layer from, and its explicit sibling.

`the build specification (not in this mirror)` § Deliverable 6. `protean.runtime.seat.resolve_seat_layer()`
imports this module by dotted path and calls `build()`, expecting a `SeatLayer` — a router and a
port, both this package's. The import is lazy on the runtime's side because `src/protean/cortex/`
is a separate order's package; this module is the other end of that seam.

**`build()` takes no arguments, so it resolves its two inputs the way the rest of the build
does.** The brain root is `protean.config.brain_root()` — `$PROTEAN_BRAIN` else `<repo>/brain`,
which is where the ladder's counts and the monitor's streak threshold are read from, the same
two files the runtime reads. The seat script is `$PROTEAN_SEAT_SCRIPT` if it is set, else the
packaged default; `protean dry` exports both before it runs a scenario, which is how a scripted
scenario reaches a zero-argument factory without the operator surface growing a flag.

**`build_layer()` is the explicit form**, and it is what a battery and a scenario runner call:
root and script in, layer out, nothing resolved from the environment.

**One session book per layer.** The router opens the task on it every tick, so both seat
handles are minted together the first time a task is seen and handed back unchanged for the
rest of it (§ Deliverable 6, *fresh per task, cached within task*, amended by A.1). The book is
the layer's `sessions` seam: the runtime checkpoints those two handles and restores them on
resume. Non-seat call types do not retain a handle.

**The runtime's model processes spawn through this package; oracle is separately licensed.**
The scripted path survives beside the live one. `the build specification (not in this mirror)` § Deliverable 1: `build()` still takes
no arguments (D7-3) and `brain/seats.yaml` selects — `layer: live` builds the seats in
`protean.cortex.live`, `layer: scripted` and a root with no such file build the hand-authored
ones. Two things keep `protean dry` and the whole default battery at zero model calls without a
flag and without a second factory: `_dry` calls `build_layer()` with an explicit script rather
than `build()`, and `$PROTEAN_SEAT_SCRIPT` — which a scenario run exports — selects the scripted
layer whatever the seed says, because naming a script is naming what answers.

**A live layer is built only where a live layer was asked for.** Nothing here spawns anything at
build time; the first process is the first port call of the first tick.

**A.1 adds the fourth optional seam** (`the build specification (not in this mirror)` § Deliverable 2):
`node_calls` is the per-tick desk an outer node's think, escalate and delegate are made through,
and the scripted layer carries it with the script's own `calls:` plan — empty for every landed
script, so the tick every landed fixture runs is unchanged. **What decides that a node calls is
not this module's**: the plan comes from the runtime's call policy
(`the build specification (not in this mirror)` § Deliverable 1), handed to the desk per tick, and a
fixture's static plan outranks it for a node it names. The seam stays optional, so a hand-built
layer without it makes no call at all.

**A.1.i adds the fifth optional seam** (`the build specification (not in this mirror)`
§ Deliverable 4, seam contract I5): `spawns` is the desk one tick's tier-three spawns are opened
on, memoized per `(task, tick)` so the tick has exactly one. **The live layer attaches
`node_calls` over the same `SpawnDesks` as `spawns`** (A.2.i § Deliverable 1), with an empty
static plan and the seed's per-tick delegate bound — so a live root's wave can spawn, and a
delegate reaches the same desk once a trigger plans one; with every trigger off, none is planned.
It needs no workspace at build time: the workspace reaches the desk per tick from `TickContext`.
"""

from __future__ import annotations

import os
from pathlib import Path

from protean import config
from protean.cortex.adapters import ScriptedSeat, SeatDesk
from protean.cortex.calls import CallDesks
from protean.cortex.ladder import LadderWeights
from protean.cortex.live.config import (
    LAYER_LIVE,
    LAYER_SCRIPTED,
    SeatConfigError,
    load_seats,
)
from protean.cortex.live.invoke import LiveSeat
from protean.cortex.live.session import LiveSessionBook
from protean.cortex.live.wave import SpawnDesks
from protean.cortex.router import LadderRouter
from protean.cortex.scenario import script_path
from protean.cortex.scripts import SeatScript, load_script
from protean.runtime.seat import SeatLayer

#: The environment variable `protean dry` sets to point a run at one scenario's responders.
#: It takes either a bare stem under `fixtures/seat_scripts/` or a path to a script file.
SEAT_SCRIPT_ENV = "PROTEAN_SEAT_SCRIPT"

#: The script a run falls back to when nothing names one: plan a unit, do it, close the goal.
DEFAULT_SCRIPT_STEM = "plan_and_execute"


def resolve_script(reference: str | None = None) -> SeatScript:
    """A stem, a path, or `$PROTEAN_SEAT_SCRIPT`, else the packaged default — in that order."""
    named = reference if reference is not None else os.environ.get(SEAT_SCRIPT_ENV)
    if not named:
        return load_script(script_path(DEFAULT_SCRIPT_STEM))
    candidate = Path(named)
    if candidate.suffix and candidate.exists():
        return load_script(candidate)
    return load_script(script_path(named))


def build_layer(
    *, root: Path | None = None, script: SeatScript | None = None
) -> SeatLayer:
    """The explicit form: one brain root's ladder counts, one script, one session book."""
    brain = root if root is not None else config.brain_root()
    desk = SeatDesk()
    chosen = script if script is not None else resolve_script()
    seat = ScriptedSeat(script=chosen, desk=desk)
    return SeatLayer(
        router=LadderRouter(weights=LadderWeights.load(brain), on_tick=desk.open_tick),
        port=seat,
        sessions=desk.sessions,
        node_calls=CallDesks(port=seat, plan=chosen.calls),
    )


def build_live_layer(*, root: Path | None = None, workspace_path: str = "") -> SeatLayer:
    """The live form: the same router and desk, over the seats `brain/seats.yaml` configures.

    The router, the desk and the `sessions` seam are build 1's unchanged — only the port and
    the session book are new, which is the whole content of "the port does not change". The
    layer carries the second seam too: `calls` is the live seat's own, so the runtime reads one
    `SeatCallFacts` per invocation at the boundary (folded: S-18).
    """
    brain = root if root is not None else config.brain_root()
    seats = load_seats(brain)
    if seats is None or not seats.is_live:
        raise SeatConfigError(f"{brain}/seats.yaml does not select the live layer")
    book = LiveSessionBook()
    desk = SeatDesk(sessions=book)
    seat = LiveSeat(config=seats, desk=desk, sessions=book, workspace_path=workspace_path)
    # **Both seams are attached, over one `SpawnDesks`** (`the build specification (not in this mirror)`
    # § Deliverable 1, the live attachment): the desk a tick's tier-three spawns are opened on
    # rides `spawns`, and `node_calls` holds **the same instance** as its own `spawns` seam — so
    # the per-`(task, tick)` memoization still gives the tick exactly one spawn desk, and the
    # wave's opener and the delegate arm meet it. The node-call desks carry an **empty static
    # plan** — the runtime's call policy hands each node its plan per tick — and the per-tick
    # delegate bound read off the seed, which each tick's desk publishes.
    #
    # **It needs no workspace** (folded: S-i22): the workspace reaches the desk **per tick**
    # from `TickContext`, which is why `workspace_path=""` above stays exactly as it is.
    spawns = SpawnDesks(config=seats, root=brain)
    return SeatLayer(
        router=LadderRouter(weights=LadderWeights.load(brain), on_tick=desk.open_tick),
        port=seat,
        sessions=book,
        calls=seat.calls,
        node_calls=CallDesks(
            port=seat, spawns=spawns, delegate_bound=seats.max_tick_delegates
        ),
        spawns=spawns,
    )


def selected_layer(root: Path) -> str:
    """Which layer this brain root asks for — the one place that decision is made.

    `$PROTEAN_SEAT_SCRIPT` wins over the seed: naming a script is naming what answers, and it is
    what `protean dry` and every scripted scenario export. Otherwise `seats.yaml`'s `layer:`
    decides, and a root with no `seats.yaml` is scripted, exactly as build 1 was.
    """
    if os.environ.get(SEAT_SCRIPT_ENV):
        return LAYER_SCRIPTED
    seats = load_seats(root)
    return LAYER_SCRIPTED if seats is None else seats.layer


def build() -> SeatLayer:
    """What `protean.runtime.seat.resolve_seat_layer()` calls. No arguments, by that contract."""
    root = config.brain_root()
    if selected_layer(root) == LAYER_LIVE:
        return build_live_layer(root=root)
    return build_layer(root=root)
