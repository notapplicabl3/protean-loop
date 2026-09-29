"""The live seat port: one process per tier per tick, and the envelope it ends at.

`the build specification (not in this mirror)` § Deliverable 1 — S1's invocation half, its decode half, the
failure path and the containment paragraph (folded: A1-9, folded: S-6, folded: S-7,
folded: S-8, folded: S-17, folded: S-18, folded: S-30, folded: S-31, folded: S-32).

**The port is addressed by an addressee, not by a tier** (`the build specification (not in this mirror)`
§ Deliverable 2, decision 10): a `Tier` for a seat call and a **call type** for everything else.
`think` and `escalate` resolve their block out of `brain/seats.yaml`'s `calls:` mapping and take
this module's argv, scrub, sandbox wrap and failure path whole; they are **session-less** — a
fresh `--session-id` per invocation, discarded, with no entry in the book (folded: S-A31) — and
a call that crosses one of its own caps raises `CallCapExceeded` rather than `SeatUnavailable`,
because a cheap advisory call's fault is a signal to the calling node and never a stop.
`delegate` and `dispatch` reach no `calls:` block at all: their process is a **kind block's**,
resolved out of the `kinds:` container and handed to the instance that spawns it (A.1.i
§ Deliverable 3, the Containment paragraph below).

**The adapter's job ends at the envelope**, exactly as `ScriptedSeat`'s does. It parses the
CLI's stdout into a `SeatEnvelope` and hands it back **as received** — the raw envelope is the
envelope of record: it is what the journal holds, what a replay restores, and what the first
wet row captured for the diff. Decoding it into a result model is the runtime's, through
`decode_seat_result()`, so a live call and a journal restore take one code path.

**An error is not an envelope** (decision 11). A non-zero exit, an `is_error` response, a rate
limit or a timeout cannot satisfy `SeatEnvelope`'s four required facts, so this module raises
`SeatUnavailable` and never constructs one out of a failure. The classification happens on the
**raw parsed stdout, before** `SeatEnvelope` validation, so no `pydantic.ValidationError` ever
escapes the adapter into the tick loop.

**A decode failure retries exactly once** — a second live invocation on the same `--resume`
session carrying the validation error on stdin — and a second failure raises `SeatDecodeError`,
which by build 1's own rule is a blocker returned to the session rather than an edit.

**A rejected resume is re-sent once as a mint.** The two seats run in one directory per task,
`brain/state/<task>/seat-cwd/`, and the CLI files a session by the directory it ran in, so a
resumed process finds a session that exists (`the build specification (not in this mirror)`
§ Deliverable 1). The fallback now serves only a handle whose session the CLI was never asked to
create: both seat handles are minted at task open and one tier is invoked per tick, so a
checkpoint can carry one. On the first invocation of a tier whose handle came from a
`restore()`, a non-zero exit is read as "no such session" and the call is re-sent **once** under
the *same* uuid with `--session-id`, which mints it; the handle the checkpoint carries never
changes, and the fallback is recorded on the invocation's own `SeatCallFacts`.

**Every spawn-level failure is classified too.** A missing binary, a non-executable one, an
argument list the kernel refuses — `OSError` in all its shapes — becomes `SeatUnavailable`
under `REASON_SPAWN` rather than an exception the tick loop never expected, and the timeout
kill reaches the child's whole **process group**, so a tool the seat started cannot outlive the
call that started it and keep writing the clone.

**Containment.** The child is spawned by **absolute path**, resolved before the scrub, into an
environment built by allow-list from empty whose `PATH` cannot resolve the binary's own
directory; the tools it may run are a positive list from the seed and the egress verbs are
named as refused. **The same containment shape now resolves for the two `calls:` blocks as well
as for the two seats** (`the build specification (not in this mirror)` § Deliverable 2, row G10,
folded: S-A70) — tool-less by load-time refusal, no `Task`, the positive `child_path()`
exclusion, the `sandbox-exec` wrap and the five-name env allow-list unchanged, because a
`calls:` block takes `TIER_KEYS` exactly and therefore declares no containment of its own.
**And the same containment shape resolves across both bodies** (§ Deliverable 5, row G13,
folded: S-A78): the body is selected by **`runtime.body`**, one key for the whole file, whose
value is `print` or `terminal` and which **applies to the two cortex seats only** — the two
`calls:` blocks and tier three always run under `claude -p`. Containment is identical across
bodies **by construction**, because both bodies are processes the runtime spawns: the same
absolute-path binary, the same `PATH` exclusion, the same `sandbox-exec` wrapper, the same
five-name env allow-list and the same tool set, with the argv differing only by the print flag.
A body the runtime did not launch is refused by name before any session handle is minted.
**A per-kind block, its container and its containment floor are build A.1.i's, and they resolve
here** (`the build specification (not in this mirror)` § Deliverable 2, § Deliverable 3, route row
R12). A spawn's block is resolved out of the `kinds:` container by `SeatsConfig.kind(class,
name)` — the addressee cannot name WHICH kind, so the **resolved block arrives as a parameter**
at every site that reads one — its granted set is its class's own closed licensed **pattern**
set with the tool **names** derived from those patterns, `--permission-mode dontAsk` is required
of it at load, the `sandbox-exec` profile is **composed per spawn** and is **write-denied by
default over a per-class allowed set** (the task workspace for a `dispatch`, the
`runtime.spawn_writable` trees for both), and `--add-dir` is built from the **runtime's own
workspace value**, there being no payload channel for one to arrive on.

§ Named assumptions
10 called that narrowing plus detection *and not a sandbox* — S-44 and S-45 moved both halves:

* the allow-list only binds under `--permission-mode dontAsk` beside an explicit `--tools` set.
  Under `auto` it did not bind at all, and the loader now refuses `auto` (S-44);
* every spawn is wrapped in `sandbox-exec` with a profile that denies `file-write*` under the
  seed's named trees, so a write outside them fails at the kernel with `Operation not
  permitted` (S-45). The wrapped argv is what `SeatCallFacts.argv` records, because it is what
  ran.

Row W7's after-the-fact hash audit stays, as the second reading of the same fact.

**What the grant does not bind, named rather than implied** (A.1.i § Deliverable 2, row R12,
folded: S-i21). Four things reach a spawn from **outside** its granted set, so the profile above
is not a complete capability description: the CLI's **auto-run in-clone read-only class**, `ls`,
`cat` and `head` running under `dontAsk` whatever the prefix list says (S-52); the **link farm**,
`runtime.bin_links` being one global list every spawned child's `PATH` receives and no kind may
narrow; the **interpreter hole**, a licensed `Bash(python:*)` opening a socket that raises no
denial and reaches no audit list, so for the `dispatch` class network egress is neither prevented
nor witnessed; and a **nested session by absolute path**, which none of the three landed barriers
reaches — `--disallowedTools` refuses the tool route, the child `PATH` refuses name resolution
and the wrapper's `execvp` text witnesses an attempt that *failed*, while a grandchild naming the
path itself raises nothing. Prevention is unavailable in-sandbox (denying `process-exec` reaches
the sandboxed launch itself and nothing runs, measured 2026-09-07), so the three-tier ceiling is
**contractual and not enforced** for the `dispatch` class and detection is what there is.
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from protean.cortex.bodies import (  # `PRINT_FLAG` is re-exported: `protean.oracle.session`
    PRINT_FLAG,                      # reads it from this module, and the flag is the body's.
    Body,
    for_addressee,
    refuse_an_unlaunched_body,
    request_on_stdin,
    request_payload,
)
from protean.cortex.live.config import (
    SANDBOX_PROFILE_FLAG,
    CallCapExceeded,
    SeatConfigError,
    SeatsConfig,
    TierSeat,
)
from protean.cortex.live.kinds import CapabilityProfile, KindBlock, resolve_capability
from protean.cortex.live.schema import schema_argument
from protean.cortex.live.session import (
    SESSION_MINT_FLAG,
    SESSION_RESUME_FLAG,
    LiveSessionBook,
    call_session,
)
from protean.runtime.errors import SeatUnavailable
from protean.runtime.paths import TaskPaths
from protean.runtime.seat import (
    OUTCOME_DECODE_RETRY,
    OUTCOME_OK,
    OUTCOME_UNAVAILABLE,
    SeatCallFacts,
    SeatDecodeError,
    addressee_of,
    decode_seat_result,
)
from protean.state.calls import NodeCall
from protean.state.enums import Addressee, CallType, NodeName, Tier
from protean.state.seats import (
    CACHE_READ_KEY,
    STRUCTURED_SUCCESS_STOP_REASON,
    SeatEnvelope,
    WaveMember,
)

#: The wire flags this build pins. Every one was verified present on the resolved binary at
#: build time; the binary itself is unpinned by named exception (§ Rulings 16, decision 13).
#:
#: **`PRINT_FLAG` is the one that moved**: from build A.1 it belongs to a *body* rather than to
#: the call, so `protean.cortex.bodies` owns it and it is imported back above — the name is
#: still `invoke.PRINT_FLAG` for every caller that already reads it there
#: (`protean.oracle.session`), and the print body is the only body that puts it on an argv.
SETTING_SOURCES_FLAG = "--setting-sources"
OUTPUT_FORMAT_FLAG = "--output-format"
OUTPUT_FORMAT_JSON = "json"
SCHEMA_FLAG = "--json-schema"
SYSTEM_PROMPT_FLAG = "--system-prompt"
#: **The line a `dispatch` member's unit `intent` follows on its `--system-prompt`** — the third
#: part `LiveSeat.system_prompt()` appends after the two seed halves, for a dispatch member whose
#: instance carries one (`the build specification (not in this mirror)` § Deliverable 7). It is a code
#: literal outside `seed_hashes()`, which is one of the two reasons a member's sent prompt is
#: reconstructable from the seat-call receipt's recorded `argv` rather than from the checkpoint.
UNIT_DELIMITER = "--- unit ---"
MODEL_FLAG = "--model"
EFFORT_FLAG = "--effort"
PERMISSION_MODE_FLAG = "--permission-mode"
ALLOWED_TOOLS_FLAG = "--allowedTools"
DISALLOWED_TOOLS_FLAG = "--disallowedTools"
TOOLS_FLAG = "--tools"
ADD_DIR_FLAG = "--add-dir"
BUDGET_FLAG = "--max-budget-usd"
VERSION_FLAG = "--version"

#: What `--setting-sources` is given: the empty string, which is the isolation lever. `--bare`
#: is the wrong one — it would take `HOME` with it and the subscription credential with that.
NO_SETTING_SOURCES = ""

#: The envelope keys the classification reads *raw*, before any model validation.
KEY_IS_ERROR = "is_error"
KEY_STOP_REASON = "stop_reason"
KEY_RESULT = "result"
KEY_ERRORS = "errors"
KEY_SUBTYPE = "subtype"
KEY_USAGE = "usage"
KEY_MODEL_USAGE = "modelUsage"
KEY_NUM_TURNS = "num_turns"

#: The tick the shape probe decodes against. `--json-schema` validates **after** the fact
#: (§ Named assumptions 8), so a seat can return a shape its tier's model refuses; the retry
#: exists for exactly that, and finding it means decoding. `tick` carries no constraint, so a
#: result that decodes at zero decodes at every tick — the runtime's own decode, with the real
#: tick, is still the one that counts, and it takes the same code path this probe does.
SHAPE_PROBE_TICK = 0

#: How the CLI says it stopped at `--max-budget-usd`, measured at build 2's first wet row and
#: captured whole in `fixtures/envelopes/live_budget_exhausted.json`: an `is_error` envelope with
#: **no `result` key at all**, this `subtype` and this `terminal_reason`. Read for one purpose —
#: telling a `calls:` block's dollar cap apart from every other `is_error` answer, because the
#: cap is the one fault row G10 names a class for (folded: S-A47, § Resolutions D5-8).
KEY_TERMINAL_REASON = "terminal_reason"
BUDGET_EXHAUSTED_SUBTYPE = "error_max_budget_usd"
BUDGET_EXHAUSTED_REASON = "budget_exhausted"

#: The two cap names a `CallCapExceeded` is raised under — the seed's own key names, so the
#: refusal detail and `brain/seats.yaml` read the same.
CAP_BUDGET = "max_call_usd"
CAP_WALL = "timeout_seconds"

#: `SeatUnavailable.reason`, the closed set this module raises.
REASON_TIMEOUT = "the call exceeded its wall cap"
REASON_EXIT = "the CLI exited non-zero"
REASON_IS_ERROR = "the CLI reported an error response"
REASON_NO_STDOUT = "the CLI returned nothing on stdout"
REASON_SPAWN = "the CLI could not be spawned"

#: Every message this module hands out is held to one bound, because the string reaches the operator
#: through a mailbox interrupt and a CLI that answers ten kilobytes of stack trace must not put
#: ten kilobytes into it.
MESSAGE_LIMIT = 400

#: The marker a fallback leaves on its invocation's facts (`outcome` stays `ok` when the
#: re-sent call succeeds). It is a *name* so a reader greps for one token, not a sentence.
RESUMED_AS_NEW = "resumed_as_new"

#: What `cli_version()` records when the binary cannot be spawned at all. The probe is a spawn
#: like any other, and it runs *inside* the record of a call that is already being refused — so
#: it classifies rather than raising, or the refusal would never reach the tick loop.
VERSION_UNSPAWNABLE = "unknown (the binary could not be spawned)"

#: How `sandbox-exec` reports that it could not start the binary it was given — measured here,
#: 2026-09-07: `sandbox-exec: execvp() of '<path>' failed: No such file or directory`, exit 71.
#:
#: The wrapper moved this failure surface. Before S-45 a missing or non-executable CLI raised
#: `OSError` in the *parent* and was classified `REASON_SPAWN`; wrapped, the parent's spawn
#: succeeds — it is `sandbox-exec` that fails to exec, and it does so by exiting non-zero. The
#: fact underneath is unchanged (**no CLI process ever existed**, so the session handle is still
#: unconfirmed), so the classification is restored from the wrapper's own message rather than
#: allowed to decay into `REASON_EXIT`.
SANDBOX_EXEC_FAILURE = ": execvp() of"

#: How long the drain after a group kill may take before the direct child is killed outright.
#: Everything in the group has already had `SIGKILL`, so this is a formality, not a wait.
KILL_DRAIN_SECONDS = 5.0

#: Where a spawn's **runtime-owned** scaffolding lives: `brain/state/<task>/spawns/<tick>/`, the
#: home of its link farm and of an `add_dir: false` kind's throwaway cwd (A.1.i § Deliverable 3,
#: folded: S-i48). A tree `sandbox.deny_write` already names, so **a spawn cannot rewrite its own
#: `PATH` farm by construction** and no per-user temp root appears in a spawn's profile. The seats'
#: cwd is the per-task directory beside `spawns/` (`SEAT_CWD_DIRNAME`), and their link farm stays a
#: `mkdtemp` one: their profile is `(allow default)` over a deny list, so a `mkdtemp` farm is already
#: a tree they may not write. The `calls:` blocks keep `_throwaway_directory()` for their cwd.
SPAWNS_DIRNAME = "spawns"

#: Where the two seats run: `brain/state/<task>/seat-cwd/`, their empty cwd — one per task, shared
#: by both seats, created on first need and **never removed by the runtime** — so a resumed process
#: files and finds the same session (`the build specification (not in this mirror)` § Deliverable 1). Only
#: the seats take it: the `calls:` blocks are session-less and every spawn keeps its scaffold or its
#: workspace.
SEAT_CWD_DIRNAME = "seat-cwd"

#: The payload **key set** each spawn addressee's request must equal, read off the two contracts
#: rather than restated: a `dispatch` member is `WaveMember`'s three fields and a `delegate` call is
#: the landed C1 `NodeCall` shape, whose `node` key is how a delegate's calling node travels (D3-2).
#: Read off the models so a contract that gains a field cannot leave this check behind.
SPAWN_PAYLOAD_SHAPES: Mapping[str, tuple[str, ...]] = {
    str(CallType.DISPATCH): tuple(WaveMember.model_fields),
    str(CallType.DELEGATE): tuple(NodeCall.model_fields),
}

#: What makes a payload key a **path** key, at any depth. A.1 removed the field a directory would
#: have travelled in (`ExecutorRequest.workspace_path`); this is what stops one arriving anyway in a
#: dumped mapping, so the names are the shapes that field and its neighbours take rather than a
#: guess about content. Exact names plus two suffixes, because `--add-dir` follows whatever value
#: reaches the spawn and a key called `out_path` is the same hole spelled differently.
PATH_KEY_NAMES: tuple[str, ...] = ("workspace_path", "workspace", "path", "paths", "dir", "cwd")
PATH_KEY_SUFFIXES: tuple[str, ...] = ("_path", "_paths", "_dir")


class _DecodeFailure(Exception):
    """Internal: a zero-exit answer that is not a structured success (folded: S-7).

    Never escapes this module. It is caught by the retry, and a second one becomes the public
    `SeatDecodeError`.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True, slots=True)
class _Spawn:
    """What one child process left behind, including the two ways it can leave nothing.

    `spawn_error` is set when no process ever existed (`OSError`), which is a different fact
    from a process that ran and exited non-zero: nothing was invoked, so the session handle it
    would have used is still unconfirmed.
    """

    stdout: bytes = b""
    stderr: bytes = b""
    code: int | None = None
    timed_out: bool = False
    spawn_error: str = ""
    #: The process **group** the child led, off the `start_new_session=True` process created below
    #: (`the build specification (not in this mirror)` § Deliverable 4, folded: S-i57, resolving order
    #: W4's `BLOCKED` D9-3). The group's id is the only fact that survives the frame the pid lives
    #: in, and `SpawnDesk`'s join reads the group's **live members** off it into the exec-attempted
    #: list — the one witness there is of a grandchild that named the binary by absolute path. `0`
    #: is "no process existed", which is what a parent-side `OSError` leaves behind.
    pgid: int = 0


def _capped(text: str) -> str:
    """The one bound every message crossing out of this module is held to."""
    return text[:MESSAGE_LIMIT]


def kill_process_group(process: subprocess.Popen) -> None:
    """`SIGKILL` the child's whole process group, falling back to the child alone.

    The child is spawned `start_new_session=True`, so it leads its own group and the tools it
    started (`uv`, `pytest`, `git`) are in that group with it. `subprocess.run(timeout=)` kills
    the direct child only, which leaves those grandchildren running against the clone after the
    call has been declared unavailable — the one failure a wall cap exists to prevent.
    """
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):  # pragma: no cover
        process.kill()


def sandbox_could_not_exec(stderr: bytes, sandbox_binary: str) -> str:
    """The wrapper's "I could not start the CLI" message, or `""` when it is anything else.

    Deliberately narrow: the message must start with the sandbox binary's own name, so a CLI
    that merely *printed* something similar on its own stderr is not read as a spawn failure.
    """
    text = stderr.decode("utf-8", errors="replace").strip()
    marker = f"{Path(sandbox_binary).name}{SANDBOX_EXEC_FAILURE}"
    return text if text.startswith(marker) else ""


def _resume_was_rejected(spawned: _Spawn) -> bool:
    """Did a `--resume` invocation come back the way an unknown session id comes back?

    Structural, deliberately: the exact sentence the CLI prints for an unknown session id is
    not in any capture this build owns and cannot be read without spending a live call, so the
    classification is the one the brief names — the process **ran** (no timeout, no spawn
    failure) and exited non-zero, on the **first** invocation of a tier whose handle came from
    a checkpoint. The caller checks that last condition through `is_unconfirmed()`.
    """
    return not spawned.timed_out and not spawned.spawn_error and spawned.code not in (0, None)


def _throwaway_directory(prefix: str) -> Path:
    """An empty directory that outlives no process. Removed at interpreter exit."""
    path = Path(tempfile.mkdtemp(prefix=prefix))
    atexit.register(shutil.rmtree, str(path), True)
    return path


def spawn_scaffold_dir(root: Path, task_id: str, tick: int) -> Path:
    """`brain/state/<task>/spawns/<tick>/` — a spawn's runtime-owned scaffolding directory.

    The one home of a spawn's link farm and of an `add_dir: false` kind's throwaway cwd
    (A.1.i § Deliverable 3, folded: S-i48). The path is built **here** rather than by the desk that
    hands it in, so its shape has one owner: the desk supplies the tick's facts and this module
    decides where a spawn's own directories sit, which is what makes the open-time check that the
    farm resolves inside no allowed subpath an assertion that holds structurally.
    """
    return TaskPaths(root=root, task_id=task_id).state_dir / SPAWNS_DIRNAME / str(tick)


def seat_cwd_dir(root: Path, task_id: str) -> Path:
    """`brain/state/<task>/seat-cwd/` — the two seats' cwd for one task.

    Built **here**, on `spawn_scaffold_dir()`'s precedent, so the shape has one owner
    (`the build specification (not in this mirror)` § Deliverable 1). `cwd_for()` creates it on a seat's
    first call of the task and nothing removes it: it outlives the process by design, because the
    CLI files a session by the directory it ran in and a resumed process must find it there.
    """
    return TaskPaths(root=root, task_id=task_id).state_dir / SEAT_CWD_DIRNAME


def names_a_path(key: str) -> bool:
    """Does this payload key name a **path**? The one predicate both refusals read."""
    lowered = key.lower()
    return lowered in PATH_KEY_NAMES or lowered.endswith(PATH_KEY_SUFFIXES)


def _path_keys_anywhere(payload: Any, where: str = "") -> list[str]:
    """Every path-naming key in a payload, at any depth, by its dotted position."""
    found: list[str] = []
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            position = f"{where}.{key}" if where else str(key)
            if names_a_path(str(key)):
                found.append(position)
            found.extend(_path_keys_anywhere(value, position))
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        for index, value in enumerate(payload):
            found.extend(_path_keys_anywhere(value, f"{where}[{index}]"))
    return found


def refuse_a_payload_outside_its_shape(
    addressee: Addressee | str, payload: Mapping[str, Any]
) -> None:
    """The per-addressee payload refusal, raised **before any process is created**.

    A.1.i § Deliverable 3, row G5 (a) (folded: S-i2, folded: S-i22). A `dispatch` member's payload
    key set must **equal** `WaveMember`'s three fields and a `delegate`'s the landed `NodeCall`
    shape; **any extra key, and any key naming a path under either shape, refuses by name**. It is
    one half of "`--add-dir` is the runtime's task workspace or the spawn does not happen": the
    other is `workspace_for()` reading the construction-time value only for a spawn, so between
    them there is **no second channel for a path to arrive on** — which is why A.1.i asserts no
    runtime identity and reads the recorded `--add-dir` back positively instead.

    A `SeatConfigError`, on `prefix_node()`'s landed precedent one method down: a malformed request
    at this layer is the same class of fault as a call-type prefix naming no node. The desk turns
    it into the wave's named `SeatUnavailable` reason; nothing in the tick catches this class.
    """
    shape = SPAWN_PAYLOAD_SHAPES.get(str(addressee))
    if shape is None:  # pragma: no cover — only the two spawn addressees reach here
        return
    if set(payload) != set(shape):
        extra = sorted(set(payload) - set(shape))
        missing = sorted(set(shape) - set(payload))
        raise SeatConfigError(
            f"{addressee}: a member request's key set is exactly {list(shape)}"
            + (f" — {extra} is outside it" if extra else "")
            + (f" — {missing} is missing" if missing else "")
            + ". A.1 removed the field a directory would have travelled in, and this refusal is "
            "what stops one arriving anyway in a dumped mapping: `--add-dir` is built from the "
            "runtime's own workspace value and from nothing else (§ Deliverable 3, row G5)"
        )
    named = _path_keys_anywhere(payload)
    if named:
        raise SeatConfigError(
            f"{addressee}: the member request names a path at {named} — no key of a spawn's "
            f"request may name one, at any depth, because `--add-dir` follows whatever value "
            f"reaches the spawn and the workspace has exactly one channel: the value the runtime "
            f"handed the desk at open (§ Deliverable 3, decision 3, folded: S-i22)"
        )


def link_farm(
    names: Sequence[str],
    parent_path: str,
    forbidden: Sequence[Path],
    *,
    home: Path | None = None,
) -> Path | None:
    """A directory of symlinks to exactly the executables the seed named, and nothing else.

    The containment says the child's `PATH` excludes the directory holding the binary. On this
    machine that directory also holds `uv`, which the dispatch grant names — so the
    choice is between putting the whole directory back (which re-opens the hole) and naming the
    executables one at a time. This is the second: `runtime.bin_links` is an allow-list of
    *binaries*, strictly narrower than an allow-list of directories, and one name exposes one
    executable rather than a directory's worth.

    `forbidden` is the seat **binary**, not its directory: a link that resolved to it — under
    any name — would put the nested call back, and that is the one thing this refuses.

    `home` is the **location**, and it is the whole of what A.1.i changes here: a spawn's farm is
    built inside the runtime-owned `brain/state/<task>/spawns/<tick>/` rather than under the
    per-user temp root, so a tree every spawn profile already denies is where the `PATH` a spawn
    reads comes from (folded: S-i48). The seats' landed behaviour — a `mkdtemp` farm removed at
    interpreter exit — is what `home=None` keeps.
    """
    if not names:
        return None
    farm = _throwaway_directory("protean-seat-bin-") if home is None else home
    for name in names:
        resolved = shutil.which(name, path=parent_path)
        if resolved is None:
            raise SeatConfigError(f"runtime.bin_links names {name!r}, which is not on PATH")
        target = Path(resolved).resolve()
        if target in set(forbidden) or Path(resolved) in set(forbidden):
            raise SeatConfigError(
                f"runtime.bin_links names {name!r}, which resolves to the seat binary "
                f"itself ({target}) — that would re-open the nested-call hole"
            )
        (farm / name).symlink_to(target)
    return farm


@dataclass(slots=True)
class LiveSeat:
    """`protean.runtime.seat.SeatPort` over a real CLI session. **This one spawns processes.**

    `desk` is build 1's router → port channel, carrying the open task and the router's
    selection; `sessions` is the live book the desk opens. `calls()` is the second seam on
    `SeatLayer`: the invocations *this* port call made, cleared at the top of every call so a
    boundary read is never a running total.
    """

    config: SeatsConfig
    desk: Any
    sessions: LiveSessionBook
    workspace_path: str = ""
    decode_retries: int = 1
    #: The body handed in rather than resolved from `runtime.body` — the seam the operator's attach
    #: would arrive through, and therefore the seam that has to refuse one (§ Deliverable 5,
    #: row G13). `None` is the ordinary case: the seed selects the body.
    body: Body | None = None
    #: **The resolved kind block this instance spawns** — the first of the three facts the spawn
    #: desk constructs an instance with, beside the tick's workspace above and the calling node,
    #: which `prefix_node()` reads structurally (A.1.i § Deliverable 3). `None` is every other
    #: instance: a seat's and a `calls:` block's, whose block the addressee resolves. The block
    #: arrives already resolved because `SeatsConfig.block()` is addressee-only and an addressee
    #: cannot name WHICH kind (folded: S-i2) — so the *type* of the resolved block is what tells a
    #: spawn from a seat call everywhere below, rather than a second code path.
    kind: KindBlock | None = None
    #: `brain/state/<task>/spawns/<tick>/`, from `spawn_scaffold_dir()` — the runtime-owned home of
    #: this spawn's link farm and of its `add_dir: false` cwd. Required of a spawn instance and
    #: `None` for a seat and a `calls:` block: a `calls:` block's cwd and a seat's farm are the
    #: landed `mkdtemp` ones, and a seat's cwd is the per-task `seat_cwd_dir()`.
    spawn_scaffold: Path | None = None
    #: **The member's unit `intent`**, which `system_prompt()` appends after `UNIT_DELIMITER` as the
    #: third part of a `dispatch` member's prompt (`the build specification (not in this mirror)`
    #: § Deliverable 7). Instance state, one per spawn, handed in by the desk from `units=`.
    #: `None` is every other instance, and a member no intent was handed for: two halves.
    unit_intent: str | None = None
    _facts: list[SeatCallFacts] = field(default_factory=list)
    _version: str = ""
    _empty_cwd: Path | None = None
    _bin_farm: Path | None = None
    _farm_built: bool = False
    last_stdout: bytes = b""

    # ----------------------------------------------------------------------------------
    # The seam the runtime reads at the boundary
    # ----------------------------------------------------------------------------------

    def calls(self) -> tuple[SeatCallFacts, ...]:
        """One `SeatCallFacts` per invocation made during the last port call; a retry is two."""
        return tuple(self._facts)

    # ----------------------------------------------------------------------------------
    # The body: one key, the two cortex seats only (§ Deliverable 5, row G13)
    # ----------------------------------------------------------------------------------

    def body_of(self, addressee: Addressee | str) -> Body:
        """The body this addressee runs under, refusing one the runtime did not launch.

        A handed-in body wins over the seed — that is the seam an attach would arrive through —
        and is refused here if the runtime did not launch it. Otherwise `runtime.body` selects,
        and it **applies to the two cortex seats only**: every other addressee takes the
        `claude -p` body, tier three always included.
        """
        chosen = addressee_of(addressee)
        if self.body is not None:
            refuse_an_unlaunched_body(self.body)
            if isinstance(chosen, Tier):
                return self.body
        return for_addressee(self.config, chosen)

    # ----------------------------------------------------------------------------------
    # The block: one resolver, the kind block for a spawn (A.1.i § Deliverable 3)
    # ----------------------------------------------------------------------------------

    def block_for(self, addressee: Addressee | str) -> TierSeat | KindBlock:
        """The resolved block an addressee is configured by — **the kind block for a spawn**.

        `SeatsConfig.block()` stays addressee-only and refuses `dispatch` and `delegate` by design,
        because an addressee cannot name WHICH kind (folded: S-i2). A spawn instance is constructed
        with its kind block already resolved through `SeatsConfig.kind(class, name)`, so this is
        the one place the two meet — and the reason every site below takes the block as a
        **parameter** rather than resolving it a second time and risking two answers.
        """
        if self.kind is None:
            return self.config.block(addressee)
        if str(addressee) != self.kind.kind_class:
            raise SeatConfigError(
                f"{addressee}: this port instance was constructed for {self.kind.block_ref} and a "
                f"spawn instance serves exactly one spawn — one instance per spawn, two openers, "
                f"one builder (§ Deliverable 4, folded: S-i13)"
            )
        return self.kind

    def capability_of(
        self, block: TierSeat | KindBlock, workspace: str = ""
    ) -> CapabilityProfile | None:
        """I2 for a spawn's block, resolved **per spawn** with the workspace it was handed.

        `None` for a seat or a `calls:` block: neither declares a containment of its own, so the
        landed `sandbox.wrap()` profile and the block's own tool lists are the whole of what they
        carry. For a kind block this is the object the argv is built from *and* the object every
        refusal was raised from at load, which is what keeps a granted set and an argv in agreement
        (A.1.i § Deliverable 2, seam contract I2).
        """
        if not isinstance(block, KindBlock):
            return None
        return resolve_capability(
            block,
            workspace=Path(workspace) if workspace else None,
            spawn_writable=self.config.spawn_writable,
        )

    # ----------------------------------------------------------------------------------
    # The environment the child gets, and the binary it is
    # ----------------------------------------------------------------------------------

    def binary(self) -> Path:
        """The absolute path of the CLI, resolved from the **parent's** PATH, before the scrub."""
        return self.config.resolved_binary()

    def _runtime_owned(self, name: str, prefix: str) -> Path:
        """A spawn's own directory inside `brain/state/<task>/spawns/<tick>/`, or a throwaway.

        The `None` branch keeps the landed `mkdtemp` cwd of a `calls:` block; a seat's cwd comes
        from the per-task `seat_cwd_dir()`, through `cwd_for()`, and a seat's farm stays
        `link_farm()`'s own `mkdtemp`. A spawn instance
        **must** have been handed a scaffold: its profile allows the workspace and the
        `runtime.spawn_writable` trees and nothing else, so a farm or a cwd under the per-user temp
        root would be a directory the spawn's own profile never named (folded: S-i48).
        """
        if self.spawn_scaffold is None:
            if self.kind is not None:
                raise SeatConfigError(
                    f"{self.kind.block_ref}: a spawn's {name} directory is runtime-owned — "
                    f"`brain/state/<task>/spawns/<tick>/`, which every spawn profile already "
                    f"denies — and this instance was constructed without one, so the farm and the "
                    f"cwd would sit under the per-user temp root no spawn profile names "
                    f"(§ Deliverable 3, folded: S-i48)"
                )
            return _throwaway_directory(prefix)
        path = self.spawn_scaffold / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _farm(self) -> Path | None:
        if not self._farm_built:
            home = (
                self._runtime_owned("bin", "protean-seat-bin-")
                if self.kind is not None and self.config.bin_links
                else None
            )
            self._bin_farm = link_farm(
                self.config.bin_links,
                os.environ.get("PATH", ""),
                self.config.binary_paths(),
                home=home,
            )
            self._farm_built = True
        return self._bin_farm

    def environment(self) -> dict[str, str]:
        """The scrubbed environment one call inherits — five variables, `PATH` rebuilt."""
        farm = self._farm()
        return self.config.child_environment(
            os.environ, extra_path=() if farm is None else (farm,)
        )

    def cli_version(self) -> str:
        """The resolved `claude --version` at call time, recorded on every call (decision 13).

        Resolved once per process and cached: the binary cannot change between two calls of one
        tick, and a version probe per call would double the process count for no new fact. A
        mid-**run** change is still seen, because a resume is a new process.
        """
        if not self._version:
            try:
                completed = subprocess.run(
                    [str(self.binary()), VERSION_FLAG],
                    capture_output=True,
                    text=True,
                    check=False,
                    env=self.environment(),
                )
            except OSError:
                # A binary that cannot be spawned cannot be version-probed either, and this
                # probe runs from inside `record()` — raising here would replace the classified
                # `SeatUnavailable` with a raw `OSError` on the way out of the adapter.
                self._version = VERSION_UNSPAWNABLE
            else:
                self._version = (completed.stdout or completed.stderr or "").strip()
        return self._version

    # ----------------------------------------------------------------------------------
    # The invocation half of S1
    # ----------------------------------------------------------------------------------

    def prefix_node(self, addressee: Addressee | str, node: NodeName | str | None = None) -> str:
        """Whose `NODE.md` is the assembled prefix's **first** half, for this addressee.

        A seat call's is the **cortex**'s, unchanged since build 2. A `calls:` block's is the
        **calling node's own** (`the build specification (not in this mirror)` § Deliverable 2,
        folded: S-A66): the question belongs to the node, so the node's contract is what frames
        it — and a body that substituted a different first half would change the result while
        passing a file-level comparison (§ Deliverable 5).

        **A `dispatch` member's is the cortex's, with no payload key at all** — exactly as a `Tier`
        is, because the wave is the cortex's own call (A.1.i § Deliverable 3, A1-8, folded: S-i2).
        A **delegate**'s calling node keeps travelling on the `NodeCall` payload as A.1 landed it,
        so the refusal below still stands for one.
        """
        chosen = addressee_of(addressee)
        if isinstance(chosen, Tier) or chosen is CallType.DISPATCH:
            return str(NodeName.CORTEX)
        if node is None:
            raise SeatConfigError(
                f"{addressee}: a call-type prefix begins with the CALLING node's NODE.md and "
                f"this call names no node — the addressee resolves the second half, the "
                f"`NodeCall` the first (folded: S-A66)"
            )
        return str(NodeName(node))

    def system_prompt(
        self,
        addressee: Addressee | str,
        node: NodeName | str | None = None,
        *,
        block: TierSeat | KindBlock | None = None,
    ) -> str:
        """The stable cached prefix: a `NODE.md` **first**, then the block's own prefix file.

        Concatenated **verbatim**, no templating (folded: S-4) — both are seed files hashed into
        the checkpoint, so a seat call's prompt stays recoverable from the checkpoint.

        **A `dispatch` member's prompt takes a third part** (`the build specification (not in this mirror)`
        § Deliverable 7): when the addressee is `CallType.DISPATCH` and the instance carries its
        unit's `intent` (`unit_intent`), the two halves are followed by a newline, the
        `UNIT_DELIMITER` line, a newline and the intent **verbatim**. A delegate's prompt and a seat
        call's gain nothing. So a dispatch member's sent prompt is reconstructable from the
        seat-call receipt's recorded `argv` — the whole `--system-prompt` value — and **not** from
        the checkpoint alone, for two reasons: a re-plan replaces the unit in the checkpoint, which
        holds only its current revision, and the delimiter is a code literal outside
        `seed_hashes()`.

        **Two halves in a fixed order** (§ Deliverable 5, folded: S-A30, folded: S-A66), and the
        first half is the cortex `NODE.md` for a seat and for a **dispatch** member, and the
        **calling node's** for a think, an escalate or a delegate; the second is
        `brain/seats/<seat>.md`, `brain/seats/calls/<type>.md` or the kind's own prefix file.

        **For a spawn the second half is read from the `KindBlock`'s own resolved,
        confinement-checked path and never from `prompt_path()`** (A.1.i § Deliverable 3, A1-8,
        folded: S-i35), which joins a seed-relative string to the brain root at call time:
        resolving there would re-admit the `prompt: ../notes.md`, the absolute path and the
        escaping symlink the loader refuses at load, so the path confined **once, at load** is the
        only one a spawn ever reads.
        """
        resolved = self.block_for(addressee) if block is None else block
        root = self.config.root
        folder = self.prefix_node(addressee, node)
        node_md = (root / "nodes" / folder / "NODE.md").read_text(encoding="utf-8")
        prefix = (
            resolved.prompt_path
            if isinstance(resolved, KindBlock)
            else resolved.prompt_path(root)
        )
        halves = node_md + "\n" + prefix.read_text(encoding="utf-8")
        if addressee_of(addressee) is CallType.DISPATCH and self.unit_intent is not None:
            return halves + "\n" + UNIT_DELIMITER + "\n" + self.unit_intent
        return halves

    def argv(
        self,
        addressee: Addressee | str,
        *,
        session_flag: tuple[str, str],
        workspace: str = "",
        node: NodeName | str | None = None,
        block: TierSeat | KindBlock | None = None,
    ) -> list[str]:
        """S1's argv for one addressee, as it is run — **wrapped**. Recorded on `SeatCallFacts`.

        The list this returns starts at the sandbox binary, not at the CLI: `sandbox-exec -p
        <profile>` then the resolved binary and its flags (S-45). Wrapping happens here rather
        than in `_spawn` so the recorded argv is the argv that ran, wrapper included.

        One builder for both kinds of addressee: a `calls:` block declares no containment of its
        own, so a think call's argv differs from a seat's only in the block it read.

        **One builder for both bodies too** (§ Deliverable 5, row G13). The body contributes its
        own flags and nothing else — `(-p,)` for the print body, and **none** for the terminal
        body, whose interactive list A.1 does not fix (§ Named assumptions 1) — so the two argvs
        differ by the print flag alone and the wrapper, the scrub, the tool set and the session
        flag are the same list built by the same code.

        **One builder for a spawn too, parameterized by the block** (A.1.i § Deliverable 3, row G4,
        folded: S-i32). The resolved block arrives as a parameter — the kind block for a spawn,
        `block(addressee)` for a seat or a `calls:` block — and the only things that change for a
        spawn are read off I2 beside it: `--allowedTools` takes the granted **patterns**,
        `--disallowedTools` the block's own list **plus the appended `EGRESS_REMOTE` literal**, and
        the wrapper carries the **composed per-spawn profile** in place of the seats' landed one.
        `--tools` is the block's own `tools_argument()` either way, so a spawn's names reach the
        wire in **the block's own seed order** — the loader's check being set equality, the
        emission order is the flag's (folded: S-i46) — and they are the names derived from the very
        patterns beside them, so the two flags cannot disagree.
        """
        seat = self.block_for(addressee) if block is None else block
        profile = self.capability_of(seat, workspace)
        body = self.body_of(addressee)
        flag, handle = session_flag
        argv = [
            str(self.binary()),
            *body.flags(),
            SETTING_SOURCES_FLAG,
            NO_SETTING_SOURCES,
            flag,
            handle,
            MODEL_FLAG,
            seat.model,
            EFFORT_FLAG,
            seat.effort,
            OUTPUT_FORMAT_FLAG,
            OUTPUT_FORMAT_JSON,
            SCHEMA_FLAG,
            schema_argument(addressee),
            SYSTEM_PROMPT_FLAG,
            # Through the **body**, which is what carries it — and which resolves it by calling
            # `system_prompt()` below, so there is one assembler and the body adds nothing. A
            # body that substituted a different first half would show up here, on the wire,
            # which is what row G9's positive control drives.
            body.system_prompt_prefix(self, addressee, node, block=seat).decode("utf-8"),
        ]
        if seat.permission_mode is not None:
            argv += [PERMISSION_MODE_FLAG, seat.permission_mode]
        # The granted pair for a spawn, the block's own two lists for everything else. A kind's
        # `allowed_tools` is non-empty by load-time refusal and the runtime appends `EGRESS_REMOTE`
        # to every spawn whatever the block says (folded: S-i15), so both flags are always emitted
        # for a spawn and both stay conditional for a block that declares nothing.
        allowed = seat.allowed_tools if profile is None else profile.granted_patterns
        refused = seat.disallowed_tools if profile is None else profile.refused_patterns()
        if allowed:
            argv += [ALLOWED_TOOLS_FLAG, *allowed]
        if refused:
            argv += [DISALLOWED_TOOLS_FLAG, *refused]
        tools = seat.tools_argument()
        if tools is not None:
            # One argument, comma-joined in the seed's order: `--tools Bash,Read,Edit,…` for a
            # tier that acts, `--tools ""` for one that does not (S-44, D3-4).
            argv += [TOOLS_FLAG, tools]
        if seat.add_dir and workspace:
            argv += [ADD_DIR_FLAG, workspace]
        argv += [BUDGET_FLAG, f"{seat.max_call_usd}"]
        sandbox = self.config.sandbox
        if profile is None:
            return sandbox.wrap(argv)
        # The same wrapper and the same flag, carrying the **composed** per-spawn profile in place
        # of the seats' `(allow default)` one: `wrap()` reads `profile()`, which is the seats' shape
        # by construction, and it is unedited by this build (A.1.i § Deliverable 2's kernel half).
        return [
            sandbox.binary,
            SANDBOX_PROFILE_FLAG,
            profile.sandbox_profile(sandbox),
            *argv,
        ]

    def workspace_for(
        self, payload: Mapping[str, Any], block: TierSeat | KindBlock | None = None
    ) -> str:
        """The task workspace, off the request that carries it — or, for a spawn, off neither.

        A request that carries a `workspace_path` is where the runtime already puts it, so the
        live seat reads the request rather than a second source; `workspace_path` on the seat
        itself is the explicit override a probe or a battery hands in. **No A.1 seat request
        carries one** — `ExecutorRequest` is retired and `WaveMember` has no path field — so
        this resolves to the seat's own value for both seats today.

        **For a spawn addressee the payload arm is not reachable at all** (A.1.i § Deliverable 3,
        decision 3, row G5 (b), folded: S-i22): the value is the **construction-time** one the desk
        was handed at open and nothing else, so there is no second channel for a path to arrive on
        even in a payload that carries one — and with `refuse_a_payload_outside_its_shape()`
        closing the other channel, what A.1.i asserts is a positive read-back of the recorded
        `--add-dir` rather than a runtime identity between one value and itself. The seats' arm is
        left exactly as it is: their batteries and probes legitimately hand a workspace that way.
        """
        if isinstance(block, KindBlock):
            return str(self.workspace_path or "")
        return str(payload.get("workspace_path") or self.workspace_path or "")

    def cwd_for(
        self, block: TierSeat | KindBlock, workspace: str = "", *, seat_call: bool = False
    ) -> Path:
        """A block with `add_dir` uses the supplied workspace; other blocks use an empty cwd.

        "cwd a throwaway empty directory, no `--add-dir`" (folded: S-6), **as A.3 amends it for the
        two seats** (`the build specification (not in this mirror)` § Scaffold clause 2(a)): a seat's cwd is
        empty, runtime-owned and per task — `seat_cwd_dir()` for the task open in its own session
        book, read at call time, created on first need and never removed — so a resumed process
        finds the session the CLI filed there. "Cannot see the repo" is carried by the seats'
        `--tools ""`. `seat_call` is `_invoke()`'s: set exactly for a `Tier` addressee, and the
        seat arm applies only on a non-spawn instance. **A `calls:` block keeps the landed
        per-instance throwaway, and a kind with `add_dir: false` takes the throwaway rule with its
        directory runtime-owned** inside `brain/state/<task>/spawns/<tick>/` (folded: S-i48).
        """
        if block.add_dir and workspace:
            return Path(workspace)
        if seat_call and self.kind is None:
            path = seat_cwd_dir(self.config.root, self.sessions.task_id)
            path.mkdir(parents=True, exist_ok=True)
            return path
        if self._empty_cwd is None:
            self._empty_cwd = self._runtime_owned("cwd", "protean-seat-cwd-")
        return self._empty_cwd

    # ----------------------------------------------------------------------------------
    # The port
    # ----------------------------------------------------------------------------------

    def _spawn(self, argv: Sequence[str], stdin: str, cwd: str, timeout: float) -> _Spawn:
        """One child, in its own process group, and whatever it left behind.

        `Popen` rather than `subprocess.run` for one reason: `run`'s timeout path kills the
        direct child and nothing it started. Here the timeout kills the **group**, so the seat's
        tools die with the seat call.
        """
        try:
            process = subprocess.Popen(
                list(argv),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=self.environment(),
                start_new_session=True,
            )
        except OSError as error:
            # A missing binary, one without the execute bit, an argv the kernel refuses
            # (`E2BIG`), no process slots (`EAGAIN`). No process exists, so there is nothing to
            # classify off stdout — the OS text *is* the message (decision 11).
            return _Spawn(spawn_error=_capped(str(error)))
        # The group the child leads, read once while it is certainly alive: `start_new_session=True`
        # makes the child its own group leader, so the id is its pid — read through `getpgid` rather
        # than assumed, which is `kill_process_group()`'s own reading of the same fact.
        try:
            pgid = os.getpgid(process.pid)
        except OSError:  # pragma: no cover — the child cannot have been reaped yet
            pgid = process.pid
        with process:
            try:
                stdout, stderr = process.communicate(
                    input=stdin.encode("utf-8"), timeout=timeout
                )
            except subprocess.TimeoutExpired as expired:
                kill_process_group(process)
                try:
                    stdout, stderr = process.communicate(timeout=KILL_DRAIN_SECONDS)
                except subprocess.TimeoutExpired:  # pragma: no cover
                    process.kill()
                    stdout, stderr = expired.stdout, expired.stderr
                return _Spawn(
                    stdout=stdout or b"", stderr=stderr or b"", timed_out=True, pgid=pgid
                )
            if process.returncode != 0:
                # The wrapper could not exec the CLI: no CLI process ever existed, which is a
                # different fact from one that ran and exited non-zero (S-45; see
                # `SANDBOX_EXEC_FAILURE`).
                failure = sandbox_could_not_exec(stderr or b"", self.config.sandbox.binary)
                if failure:
                    return _Spawn(spawn_error=_capped(failure), pgid=pgid)
            return _Spawn(
                stdout=stdout or b"",
                stderr=stderr or b"",
                code=process.returncode,
                pgid=pgid,
            )

    def __call__(self, addressee: Addressee | str, request: Any) -> SeatEnvelope:
        """One live call: `(addressee, request) → SeatEnvelope`. One port, one decode path.

        A `Tier` for a seat call and a **call type** for everything else (§ Deliverable 2,
        decision 10). `delegate` and `dispatch` reach a **kind block** rather than a `calls:` one:
        A.1.i constructs one instance per spawn with the block already resolved, and an instance
        that carries none refuses here through `SeatsConfig.call()` exactly as A.1 left it.

        **The body is resolved first, and a body the runtime did not launch is refused here** —
        before `call_session()` mints a handle for a call type and before the book is read for a
        seat (§ Deliverable 5, row G13). The operator attaches to the runtime-launched session, never the
        reverse.

        **The block is resolved once, here, and travels as a parameter** (A.1.i § Deliverable 3):
        the retry re-sends the same call, so resolving per attempt would allow two answers to one
        question.
        """
        chosen = addressee_of(addressee)
        self.body_of(chosen)
        self._facts = []
        block = self.block_for(chosen)
        payload = request_payload(request)
        stdin = request_on_stdin(payload)
        attempt = 0
        while True:
            try:
                return self._invoke(chosen, payload, stdin, retry_index=attempt, block=block)
            except _DecodeFailure as failure:
                if attempt >= self.decode_retries:
                    raise SeatDecodeError(
                        f"{chosen}: {failure.detail} — twice, so the addressee's contract and "
                        f"the model disagree; that is a blocker, not a third call"
                    ) from failure
                attempt += 1
                stdin = (
                    f"{request_on_stdin(payload)}\n\n"
                    f"Your previous answer did not validate against the schema you were "
                    f"given: {failure.detail}\n"
                    f"Answer the same request again as one JSON object that matches it."
                )

    def _invoke(
        self,
        tier: Addressee,
        payload: Mapping[str, Any],
        stdin: str,
        *,
        retry_index: int,
        block: TierSeat | KindBlock | None = None,
    ) -> SeatEnvelope:
        """One process. Records its facts whatever happens, then classifies what came back.

        **The resolved block arrives as a parameter** — the kind block for a spawn — and for a spawn
        this is where the **per-addressee payload refusal** lands, **before any process is created**
        (A.1.i § Deliverable 3, row G5 (a)).
        """
        seat = self.block_for(tier) if block is None else block
        if isinstance(seat, KindBlock):
            refuse_a_payload_outside_its_shape(tier, payload)
        # **Session-less for a call type** (folded: S-A31): a fresh handle per invocation,
        # discarded, with no entry in the book and nothing checkpointed — `seat_sessions` is
        # keyed by tier and refuses anything else, and A.1 does not widen it. A seat call's
        # handle is the book's, unchanged.
        call_block = isinstance(tier, CallType)
        node = payload.get("node") if call_block else None
        session_flag = (
            (SESSION_MINT_FLAG, call_session())
            if call_block
            else self.sessions.session_flag(tier)
        )
        workspace = self.workspace_for(payload, seat)
        cwd = str(self.cwd_for(seat, workspace, seat_call=not call_block))
        argv = self.argv(
            tier, session_flag=session_flag, workspace=workspace, node=node, block=seat
        )
        # A handle adopted by `restore()` that no invocation has run against yet: the session
        # may never have been created, so this one call is allowed a fallback. A session-less
        # call has no handle to have been carried, so it never falls back.
        unconfirmed_resume = (
            not call_block
            and session_flag[0] == SESSION_RESUME_FLAG
            and self.sessions.is_unconfirmed(tier)
        )
        started = time.monotonic()
        # `_spawn` kills the whole process group at the wall cap; the cap is the one bound that
        # holds when the dollar cap cannot (it bounds the *next* turn, which W1 measured).
        spawned = self._spawn(argv, stdin, cwd, seat.timeout_seconds)
        fallback = ""
        if unconfirmed_resume and _resume_was_rejected(spawned):
            # Re-send **once**, under the same uuid, with the flag that mints. The checkpointed
            # handle stays the handle in use, so the next call resumes what this one created —
            # which is the whole reason the fallback is not "mint a new one".
            fallback = (
                f"{RESUMED_AS_NEW}: {SESSION_RESUME_FLAG} {session_flag[1]} was rejected "
                f"(exit {spawned.code}); re-sent as {SESSION_MINT_FLAG}"
            )
            session_flag = (SESSION_MINT_FLAG, session_flag[1])
            argv = self.argv(
                tier, session_flag=session_flag, workspace=workspace, node=node, block=seat
            )
            spawned = self._spawn(argv, stdin, cwd, seat.timeout_seconds)
        wall = time.monotonic() - started
        stdout, stderr = spawned.stdout, spawned.stderr
        code, timed_out = spawned.code, spawned.timed_out
        self.last_stdout = stdout
        if not spawned.spawn_error and not call_block:
            # An invocation happened, so the handle is confirmed and the next call resumes it.
            # A spawn that never produced a process leaves it exactly as it was (the same rule
            # `session_flag()` states: a call that never left the adapter strands nothing).
            # A session-less call's handle was discarded the moment it was minted.
            self.sessions.mark_opened(tier)

        def record(outcome: str, parsed: Mapping[str, Any] | None, error: str = "") -> None:
            body = parsed or {}
            detail = "; ".join(part for part in (fallback, error) if part)
            self._facts.append(
                SeatCallFacts(
                    tier=str(tier),
                    argv=tuple(argv),
                    cli_version=self.cli_version(),
                    session_handle=session_flag[1],
                    model=seat.model,
                    effort=seat.effort,
                    permission_mode=seat.permission_mode,
                    request=dict(payload),
                    wall_seconds=round(wall, 3),
                    outcome=outcome,
                    usage=dict(body.get(KEY_USAGE) or {}),
                    model_usage=dict(body.get(KEY_MODEL_USAGE) or {}),
                    num_turns=body.get(KEY_NUM_TURNS),
                    error=detail,
                    # **The pgid's publication, and the whole of this module's part in the witness**
                    # (folded: S-i57): the desk cannot read a group whose id nothing publishes, and
                    # the facts are the only carrier between the spawn and the boundary. The four
                    # receipt columns are the desk's to fill; this is not one of them.
                    pgid=spawned.pgid,
                    cwd=cwd,
                )
            )

        def unavailable(reason: str, message: str, parsed: Mapping[str, Any] | None) -> None:
            record(OUTCOME_UNAVAILABLE, parsed, error=f"{reason}: {message}" if message else reason)
            raise SeatUnavailable(
                tier=str(tier), reason=reason, message=message, exit_code=code
            )

        def cap_exceeded(cap: str, limit: float, message: str, parsed: Mapping[str, Any] | None):
            """A `calls:` block crossed one of its **own** two caps (row G10, D5-8).

            The call's facts are recorded exactly as any other refusal's, and then the fault is
            raised from the site that owns the cap — **no `SeatEnvelope` is constructed**, which
            is the clause "a call exceeding either of its caps fabricates no envelope". The
            calling node's desk turns it into a refusal and the tick carries on.
            """
            record(OUTCOME_UNAVAILABLE, parsed, error=f"{cap} {limit}: {message}".strip())
            raise CallCapExceeded(str(tier), cap, limit, detail=message)

        def decode_failure(detail: str, parsed: Mapping[str, Any] | None) -> None:
            outcome = OUTCOME_DECODE_RETRY if retry_index < self.decode_retries else OUTCOME_UNAVAILABLE
            record(outcome, parsed, error=detail)
            raise _DecodeFailure(detail)

        text = stdout.decode("utf-8", errors="replace")
        if spawned.spawn_error:
            unavailable(REASON_SPAWN, spawned.spawn_error, None)
        if timed_out:
            if call_block:
                cap_exceeded(CAP_WALL, seat.timeout_seconds, REASON_TIMEOUT, None)
            unavailable(REASON_TIMEOUT, f"{seat.timeout_seconds}s", None)

        parsed: Any = None
        try:
            parsed = json.loads(text) if text.strip() else None
        except ValueError:
            parsed = None

        if not isinstance(parsed, Mapping):
            message = (stderr.decode("utf-8", errors="replace") or text).strip()
            if code not in (0, None):
                unavailable(REASON_EXIT, message, None)
            decode_failure(f"stdout is not a JSON object: {_capped(message)!r}", None)

        if parsed.get(KEY_IS_ERROR):
            if call_block and crossed_the_budget(parsed):
                cap_exceeded(CAP_BUDGET, seat.max_call_usd, _message_of(parsed), parsed)
            unavailable(REASON_IS_ERROR, _message_of(parsed), parsed)
        if code not in (0, None):
            unavailable(REASON_EXIT, _message_of(parsed), parsed)
        if not text.strip():
            unavailable(REASON_NO_STDOUT, "", None)

        # Everything below is a *decode* question, not an availability one: the call happened,
        # it exited clean and it said it was not an error — the shape is what is wrong.
        if parsed.get(KEY_STOP_REASON) != STRUCTURED_SUCCESS_STOP_REASON:
            decode_failure(
                f"stop_reason is {parsed.get(KEY_STOP_REASON)!r}, not "
                f"{STRUCTURED_SUCCESS_STOP_REASON!r}",
                parsed,
            )
        result = parsed.get(KEY_RESULT)
        if not isinstance(result, str):
            decode_failure(f"result is {type(result).__name__}, not a JSON string", parsed)
        try:
            json.loads(result)
        except ValueError as exc:
            decode_failure(f"result does not parse as JSON: {exc}", parsed)
        if CACHE_READ_KEY not in (parsed.get(KEY_USAGE) or {}):
            decode_failure(f"usage carries no {CACHE_READ_KEY!r}", parsed)

        try:
            envelope = SeatEnvelope.model_validate(parsed)
        except ValidationError as exc:
            # The four facts were checked above, so reaching here means the wire moved under
            # the contract — B9 answering in the negative. It is still classified rather than
            # raised raw: no `ValidationError` leaves this adapter (folded: S-7).
            decode_failure(f"the envelope does not validate: {exc}", parsed)
        else:
            try:
                decode_seat_result(tier, envelope, SHAPE_PROBE_TICK)
            except SeatDecodeError as exc:
                # Row K2's first shape. The envelope is well formed and the *answer inside it*
                # is not what the tier's model accepts — which `--json-schema` cannot prevent,
                # only report. The probe runs through `decode_seat_result()` rather than beside
                # it, so there is still exactly one decode path; the envelope handed back is
                # untouched, and the runtime decodes it again with the real tick.
                decode_failure(str(exc), parsed)
            record(OUTCOME_OK, parsed)
            return envelope
        raise AssertionError("unreachable: every branch above raises")  # pragma: no cover


def crossed_the_budget(parsed: Mapping[str, Any]) -> bool:
    """Did this `is_error` envelope come back because the dollar cap was reached?

    Measured, not guessed: `fixtures/envelopes/live_budget_exhausted.json` is the CLI's own bytes
    at the cap. Either marker is enough — the subtype is the classified name and
    `terminal_reason` is the same fact said twice — so a wire that drops one still classifies.
    """
    return (
        str(parsed.get(KEY_SUBTYPE) or "") == BUDGET_EXHAUSTED_SUBTYPE
        or str(parsed.get(KEY_TERMINAL_REASON) or "") == BUDGET_EXHAUSTED_REASON
    )


def _message_of(parsed: Mapping[str, Any]) -> str:
    """The CLI's own words for a failure — what the mailbox interrupt carries, bounded.

    Verbatim up to `MESSAGE_LIMIT`, the same 400-character bound the unparseable-stdout branch
    above holds: the string travels into an interrupt a human reads, and a CLI that answers a
    ten-kilobyte stack trace must not put ten kilobytes there.

    `errors` first because the budget and rate-limit shapes put the sentence there and leave
    `result` out entirely; `result` next, because a refusal puts the API's text there.
    """
    errors = parsed.get(KEY_ERRORS)
    if isinstance(errors, Sequence) and not isinstance(errors, str) and errors:
        return _capped("; ".join(str(item) for item in errors))
    result = parsed.get(KEY_RESULT)
    if isinstance(result, str) and result.strip():
        return _capped(result.strip())
    subtype = parsed.get(KEY_SUBTYPE)
    return _capped(str(subtype)) if subtype else ""
