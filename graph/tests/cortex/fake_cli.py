"""A stand-in CLI the live adapter can be driven against, and the brain root that points at it.

`the build specification (not in this mirror)` § Deliverable 6's battery rule and order W2's restriction:
**drive the battery from fixtures and a recording shim, and reserve real calls for the rows that
require them.** Every scenario the live seat has to survive — a non-zero exit, an `is_error`
response, a rate limit, a timeout, three shapes of decode failure and the one retry — is a shape
on the wire, and a shape on the wire is a file.

**It is not a mock of the adapter; it is a stand-in for the binary.** The adapter under test is
the shipping one: it builds the real argv, scrubs the real environment, spawns a real process
and parses whatever comes back on stdout. Only the process on the other end is ours. That is
what makes an assertion about the argv or the environment worth making — a mocked
`subprocess.run` would let both drift.

**Nothing here is configured through the environment**, because the adapter scrubs it: the fake
reads its script and writes its log beside its own `$0`, which is the one thing a scrubbed child
can still find.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
from collections.abc import Mapping, Sequence
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

from protean.cortex.adapters import SeatDesk
from protean.cortex.calls import CallDesks
from protean.cortex.live.config import (
    BODY_KEY,
    SPAWN_WRITABLE_KEY,
    SeatsConfig,
    parse_seats,
)
from protean.cortex.live.invoke import LiveSeat, spawn_scaffold_dir
from protean.cortex.live.kinds import KINDS_BLOCK, kinds_dir
from protean.cortex.live.session import LiveSessionBook
from protean.cortex.live.wave import SpawnDesks
from protean.runtime.paths import SEAT_PROMPT_SUFFIX
from protean.runtime.seat import SeatLayer

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
TRACKED_BRAIN = REPO_ROOT / "brain"

#: The fixture kind roots' ingredients (S-A22, A.1.i § Out of scope): **a fixture kind is not a
#: library kind.** The shipping seed defines none, so a test that needs a *loadable* kind takes
#: one from here — and no kind name appears anywhere outside `fixtures/` and `tests/`.
FIXTURE_KINDS = REPO_ROOT / "fixtures" / "calls" / "kinds"

#: The containers under `FIXTURE_KINDS`: the loadable pair, one kind per class; the root whose whole
#: subject is a `prompt:` file that is not there; and the **heterogeneous** set a bounded wave is
#: read off, whose kinds differ in exactly the two numbers the bounds compare (A.1.i § Deliverable
#: 5) — `members × one cap` describes no wave that actually exists, so the fixture has to.
KINDS_TWO = "two_kinds.yaml"
KINDS_MISSING_PREFIX = "missing_prefix.yaml"
KINDS_WAVE = "wave_kinds.yaml"

#: The one machine-shared tree a fixture root keeps from the shipping seed: the temp root the child
#: falls back to when no `TMPDIR` reaches it. Everything else a fixture profile allows is a directory
#: the test itself owns (§ Deliverable 7's fixture-`spawn_writable` paragraph).
FIXTURE_WRITABLE_TREE = "/tmp"

#: The name the fake is installed under. Deliberately not the real one: a test that resolved the
#: real binary by accident would spend money, and this name resolves to nothing on a real PATH.
FAKE_BINARY = "protean-fake-seat-cli"

#: The counter the fake advances so a second invocation can answer differently.
COUNTER = "invocations"

#: What the fake says when it is told to refuse a `--resume`. A **stand-in**, not a capture: the
#: adapter classifies a rejected resume structurally (an unconfirmed handle, a process that ran,
#: a non-zero exit) and never reads this sentence, so the fake is free to phrase it plausibly.
RESUME_REJECTED = "No conversation found with session ID"

_SCRIPT = r"""#!/bin/sh
# A stand-in for the seat binary. Answers from files beside itself, records every call.
here=$(dirname "$0")

# The version probe is not an invocation: the adapter resolves `--version` once per process to
# stamp every record with it, and counting it would make "exactly two calls" unreadable.
if [ "$1" = "--version" ]; then printf '%s\n' "0.0.0-fake (stand-in)"; exit 0; fi

# WHICH KEY THIS INVOCATION'S RECORDINGS TAKE, and there are two of them on two paths
# (`the build specification (not in this mirror)` § Deliverable 7's "Dry throughout", folded: S-i53).
#
# A SPAWN keys on the `--session-id` the runtime minted for it: unique per spawn, no shared
# read-modify-write, so four members recording at once against one directory cannot race — which is
# what would make a concurrent wave's fixtures flaky rather than false. EVERY OTHER INVOCATION keeps
# the ordinal counter exactly as it is, because a decode retry and a resumed session share one id
# and `invocations()`' count is what the landed rows read.
#
# A spawn is the invocation that carries `--allowedTools`: a kind block's `allowed_tools` is a
# non-empty subset of its class's licensed patterns BY LOAD-TIME REFUSAL, so every spawn emits the
# flag, while the two seats and the two `calls:` blocks are tool-less — the latter by load-time
# refusal — and emit it never.
session=""
granted=""
previous=""
for arg in "$@"; do
  if [ "$previous" = "--session-id" ]; then session="$arg"; fi
  if [ "$arg" = "--allowedTools" ]; then granted=1; fi
  previous="$arg"
done

if [ -n "$granted" ] && [ -n "$session" ]; then
  key="$session"
else
  count=$(cat "$here/{counter}" 2>/dev/null || echo 0)
  count=$((count + 1))
  printf '%s' "$count" > "$here/{counter}"
  key="$count"
fi

stdin=$(cat)
argv_file="$here/argv-$key.txt"
: > "$argv_file"
# NUL-separated: `--system-prompt` is multi-line, and a newline-separated log would split one
# argument into forty and make every argv assertion below a lie.
for arg in "$@"; do printf '%s\0' "$arg" >> "$argv_file"; done
printf '%s' "$stdin" > "$here/stdin-$key.txt"
printf '%s\n' "$PWD" > "$here/cwd-$key.txt"
env > "$here/env-$key.txt"

# An unknown session id: the CLI cannot join a conversation that was never created, so it
# refuses on stderr with a non-zero exit and answers nothing. Recorded first, so the refused
# invocation still shows up in the argv log.
if [ -f "$here/reject_resume" ]; then
  for arg in "$@"; do
    if [ "$arg" = "--resume" ]; then
      printf '%s: unknown\n' "{rejected}" >&2
      exit 1
    fi
  done
fi

# THE CLI'S SESSION STORE, KEYED BY THE DIRECTORY IT RAN IN (`the build specification (not in this mirror)`
# § Deliverable 5, § Named assumptions 1): a `--session-id` files its id under the invocation's
# `$PWD`, and a `--resume` of an id not filed under the current `$PWD` refuses exactly as the branch
# above refuses. The store sits beside `$0`, never inside `$PWD`, keyed by a checksum of the
# directory string. Opt-in, and after the recordings, so a refused resume is still logged.
if [ -f "$here/cwd_sessions" ]; then
  store="$here/session-store/$(printf '%s' "$PWD" | cksum | tr ' ' '-')"
  if [ -n "$session" ]; then
    mkdir -p "$store"
    : > "$store/$session"
  fi
  resumed=""
  last=""
  for arg in "$@"; do
    if [ "$last" = "--resume" ]; then resumed="$arg"; fi
    last="$arg"
  done
  if [ -n "$resumed" ] && [ ! -f "$store/$resumed" ]; then
    printf '%s: unknown\n' "{rejected}" >&2
    exit 1
  fi
fi

# A tool the seat started: a grandchild of the adapter, in the fake's process group, which
# outlives the fake unless the kill reaches the whole group. It **inherits this call's pipes**,
# which is what a real tool does — so a surviving member's `communicate()` waits the sleep out,
# and the claim this lever serves is the KILL's reach.
child_file="$here/spawn_child"
if [ -f "$child_file" ]; then
  sleep "$(cat "$child_file")" &
  printf '%s' "$!" > "$here/grandchild-$key.pid"
fi

# A grandchild that DETACHES from this call's pipes, which is the other shape entirely
# (`the build specification (not in this mirror)` § Named assumptions 7, § Deliverable 4's join): a
# nested session, still running when the spawn returns. The redirect is the whole difference — with
# the pipes released the call returns at once and the group outlives it, which is the only state the
# desk's join-time group read has anything to see. `/dev/null` is in `SPAWN_PROCESS_ALLOWANCES`
# (D5-1, measured), so the redirect works under the per-spawn profile.
detach_file="$here/detach_child"
if [ -f "$detach_file" ]; then
  sleep "$(cat "$detach_file")" >/dev/null 2>&1 &
  printf '%s' "$!" > "$here/grandchild-$key.pid"
fi

# THE RESPONSE IS SELECTED BY THE MEMBER REQUEST ON STDIN — the `kind` and the `unit_id` the wave
# sent — because a session id is minted by the runtime and unknowable to the test that authored the
# answer, so keying responses by it would leave the fixtures with no selector at all. The ordinal
# and the single fallback are unchanged behind it.
# THE MEMBER SELECTOR IS A SPAWN'S ONLY, on the same `--allowedTools` test the recording key uses.
# A SEAT's request carries the compressed workspace, and from the tick after a wave that workspace
# echoes the manager's own previous plan — `"kind": "<a kind name>"` beside `"unit_id"` — so an
# ungated selector would hand the MANAGER a member's `ExecutorSummary` and the decode would fail
# twice. A seat is tool-less by load-time refusal, so the gate is exact rather than heuristic.
member=""
if [ -n "$granted" ]; then
  member=$(printf '%s' "$stdin" | sed -n 's/.*"kind": *"\([^"]*\)".*"unit_id": *"\([^"]*\)".*/\1-\2/p')
fi
response="$here/response-$member.json"
[ -n "$member" ] || response="$here/response-$key.json"
[ -f "$response" ] || response="$here/response-$key.json"
[ -f "$response" ] || response="$here/response.json"
code_file="$here/exit-$key"
[ -f "$code_file" ] || code_file="$here/exit"

# A MEMBER THAT REALLY WRITES, in the directory `--add-dir` granted it. A.1's scripted members
# wrote nothing, so no A.1 fixture could show a torn wave re-applying its returned members' writes
# (`the build specification (not in this mirror)` § Deliverable 4, § Named assumptions 12). It appends,
# so a wave that re-runs whole shows two lines where one stood. Only a SPAWN writes: a seat's cwd
# is a throwaway directory and its write would say nothing about a member.
writes_file="$here/writes_in_cwd"
if [ -f "$writes_file" ] && [ -n "$granted" ]; then
  printf '%s\n' "$key" >> "$PWD/$(cat "$writes_file")"
fi

# THE WALL A MEMBER CROSSES IS SELECTED THE WAY ITS RESPONSE IS — by the member request on stdin —
# because a concurrent wave needs its members to finish in an order the plan did not list them in,
# and the ordinal key a spawn does not have is the only other selector there was.
sleep_file="$here/sleep-$member"
[ -n "$member" ] || sleep_file="$here/sleep-$key"
[ -f "$sleep_file" ] || sleep_file="$here/sleep-$key"
[ -f "$sleep_file" ] || sleep_file="$here/sleep"
[ -f "$sleep_file" ] && sleep "$(cat "$sleep_file")"

[ -f "$response" ] && cat "$response"
exit "$(cat "$code_file" 2>/dev/null || echo 0)"
"""


def install(
    directory: Path,
    responses: Sequence[Mapping[str, Any] | str] = (),
    *,
    exit_codes: Sequence[int] = (),
    sleep_seconds: float | None = None,
    reject_resume: bool = False,
    cwd_sessions: bool = False,
    spawn_child_seconds: float | None = None,
    detached_child_seconds: float | None = None,
    answer: Mapping[str, Any] | str | None = None,
    members: Sequence[tuple[tuple[str, str], Mapping[str, Any] | str]] = (),
    member_sleeps: Sequence[tuple[tuple[str, str], float]] = (),
    writes_in_cwd: str | None = None,
) -> Path:
    """Write the fake and its scripted answers into `directory`. Returns the directory.

    `reject_resume` makes every `--resume` invocation refuse the way an unknown session id
    refuses; `spawn_child_seconds` makes each invocation leave a sleeping grandchild behind and
    record its pid, which is how the group kill is proven.

    **`cwd_sessions` is the CLI's session store, keyed by the directory it ran in**
    (`the build specification (not in this mirror)` § Deliverable 5, § Named assumptions 1): every
    `--session-id` files its id under a store beside `$0`, keyed by the invocation's `$PWD`, and
    a `--resume` of an id not filed under the current `$PWD` refuses exactly as `reject_resume`
    refuses. The store never sits inside `$PWD`. It is opt-in, and every landed case runs
    without it: it is how a resume from a second process in another directory reproduces dry.

    **`detached_child_seconds` is that grandchild with this call's pipes released**
    (`the build specification (not in this mirror)` § Deliverable 4's join, § Named assumptions 7): the
    two levers serve two different claims and neither substitutes for the other. A grandchild holding
    the pipes makes a *surviving* member's `communicate()` wait the sleep out, so the group is gone by
    the time anything joins — which is why `spawn_child_seconds` proves the **kill's** reach on a
    member that is killed. A **detached** one returns the call at once and stays alive in the group,
    which is the one state the desk's join-time group read witnesses (row B51). Both record the pid
    under the same `grandchild-<key>.pid`, so `grandchild_pid()` reads either.

    **`answer` and `members` are the spawn path's two ways of authoring a response**
    (`the build specification (not in this mirror)` § Deliverable 7): a spawn's *recordings* are keyed
    by a session id the runtime minted, which no test can name in advance, so its *response* is
    selected by the member request on stdin instead. `members` keys one answer per `(kind,
    unit_id)`, which is how a wave's members answer differently; `answer` is the one fallback every
    invocation with no keyed file of its own reads.

    **`member_sleeps` is that same key over the wall rather than over the answer**
    (§ Deliverable 4): it is how one member of a concurrent wave crosses its own `timeout_seconds`
    while the others return, and how a wave's **completion** order is made the reverse of its
    `member#` order — which is what "the entries are written in `member#` order regardless of
    completion order" needs in order to be a claim with two sides.

    **`writes_in_cwd` names a file every spawn appends its own key to**, inside the directory
    `--add-dir` granted it: the torn-wave fixture's members really writing, which A.1's scripted
    ones could not (§ Named assumptions 12).
    """
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / FAKE_BINARY
    script.write_text(
        _SCRIPT.format(counter=COUNTER, rejected=RESUME_REJECTED), encoding="utf-8"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    for index, response in enumerate(responses, 1):
        body = response if isinstance(response, str) else json.dumps(response)
        (directory / f"response-{index}.json").write_text(body, encoding="utf-8")
    if answer is not None:
        body = answer if isinstance(answer, str) else json.dumps(answer)
        (directory / "response.json").write_text(body, encoding="utf-8")
    for (kind, unit_id), response in members:
        body = response if isinstance(response, str) else json.dumps(response)
        (directory / f"response-{kind}-{unit_id}.json").write_text(body, encoding="utf-8")
    for index, code in enumerate(exit_codes, 1):
        (directory / f"exit-{index}").write_text(str(code), encoding="utf-8")
    if sleep_seconds is not None:
        (directory / "sleep").write_text(str(sleep_seconds), encoding="utf-8")
    if reject_resume:
        (directory / "reject_resume").write_text("", encoding="utf-8")
    if cwd_sessions:
        (directory / "cwd_sessions").write_text("", encoding="utf-8")
    for (kind, unit_id), seconds in member_sleeps:
        (directory / f"sleep-{kind}-{unit_id}").write_text(str(seconds), encoding="utf-8")
    if writes_in_cwd is not None:
        (directory / "writes_in_cwd").write_text(writes_in_cwd, encoding="utf-8")
    if spawn_child_seconds is not None:
        (directory / "spawn_child").write_text(str(spawn_child_seconds), encoding="utf-8")
    if detached_child_seconds is not None:
        (directory / "detach_child").write_text(str(detached_child_seconds), encoding="utf-8")
    return directory


def unspawnable(directory: Path, kind: str = "missing") -> Path:
    """Leave the fake resolvable on `PATH` and refused by the kernel at `execv`.

    `shutil.which` is satisfied by the execute bit, so the adapter resolves the binary exactly
    as it always does and the refusal lands at the spawn — which is the shape a binary that was
    deleted, replaced or unmounted between resolution and spawn takes, and the shape a wrong
    `runtime.binary` takes on a machine that has one. The shebang is the lever: an interpreter
    that does not exist gives `FileNotFoundError`, one without the execute bit gives
    `PermissionError`. Both are `OSError`, which is what the adapter classifies.
    """
    script = directory / FAKE_BINARY
    if kind == "missing":
        script.write_text("#!/nonexistent/interpreter\n", encoding="utf-8")
    elif kind == "permission":
        blocked = directory / "not-executable-interpreter"
        blocked.write_text("#!/bin/sh\n", encoding="utf-8")
        blocked.chmod(0o644)
        script.write_text(f"#!{blocked}\n", encoding="utf-8")
    else:  # pragma: no cover
        raise ValueError(f"no such unspawnable shape: {kind!r}")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


def invocations(directory: Path) -> int:
    """How many times the fake was called. Zero when the file was never written."""
    counter = directory / COUNTER
    return int(counter.read_text(encoding="utf-8")) if counter.exists() else 0


def argv_of(directory: Path, index: int | str = 1) -> list[str]:
    """One invocation's argv from `$@`, exactly as the adapter passed it — argv[0] excluded.

    **`index` is the recording's key, and there are two kinds** (§ Deliverable 7): the ordinal for a
    seat or a `calls:` invocation, and the minted **`--session-id`** for a spawn, which a test reads
    off `SeatCallFacts.session_handle`.
    """
    path = directory / f"argv-{index}.txt"
    body = path.read_text(encoding="utf-8")
    return body.split("\0")[:-1] if body else []


def spawn_recordings(directory: Path) -> list[str]:
    """Every **spawn's** recording key: the `--session-id`-keyed argv files, ordinals excluded.

    `the build specification (not in this mirror)` § DoD row G7 reads a wave's process count exactly
    this way — "the number of the stand-in's `--session-id`-keyed spawn recording files beside the
    seats' own ordinal counter" (folded: S-i53) — because a spawn's key is a uuid the runtime
    minted and a seat's is the shared counter. An empty list is therefore "no process was created",
    which is what every pre-process refusal closes on.
    """
    prefix, suffix = "argv-", ".txt"
    keys = [path.name[len(prefix) : -len(suffix)] for path in sorted(directory.glob("argv-*.txt"))]
    return [key for key in keys if not key.isdigit()]


def grandchild_pid(directory: Path, index: int | str = 1) -> int:
    """The pid of the sleeping process one invocation left behind, as the fake recorded it."""
    return int((directory / f"grandchild-{index}.pid").read_text(encoding="utf-8"))


def stdin_of(directory: Path, index: int | str = 1) -> str:
    return (directory / f"stdin-{index}.txt").read_text(encoding="utf-8")


def cwd_of(directory: Path, index: int | str = 1) -> str:
    return (directory / f"cwd-{index}.txt").read_text(encoding="utf-8").strip()


def environment_of(directory: Path, index: int | str = 1) -> dict[str, str]:
    """The environment the child actually saw, captured from inside the call."""
    found: dict[str, str] = {}
    for line in (directory / f"env-{index}.txt").read_text(encoding="utf-8").splitlines():
        name, _, value = line.partition("=")
        if name:
            found[name] = value
    return found


@lru_cache(maxsize=None)
def _parsed(path: Path) -> Mapping[str, Any]:
    """One tracked YAML file, parsed **once** per process and never handed out directly.

    The tracked `seats.yaml` is 23 KB against yaml's pure-Python loader, and a root seeding used
    to parse it — and the fixture container beside it — on every call. Both are read-only inputs,
    so the parse is paid once and every caller takes a `deepcopy`: the file on disk is still the
    only source, and a battery that seeds ~170 roots pays one parse rather than ~500.
    """
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _live_payload() -> dict[str, Any]:
    """The tracked seed's payload with the three keys a fake-backed root rewrites."""
    payload = deepcopy(_parsed(TRACKED_BRAIN / "seats.yaml"))
    payload["runtime"]["binary"] = FAKE_BINARY
    payload["runtime"]["path"] = ["/usr/bin", "/bin"]
    payload["runtime"]["bin_links"] = []
    return payload


def _seed_tree(destination: Path) -> None:
    """The tracked node folders and seat prefixes, plus the runtime's own empty directories."""
    shutil.copytree(TRACKED_BRAIN / "nodes", destination / "nodes")
    for node in (destination / "nodes").iterdir():
        (node / "trace.jsonl").write_text("", encoding="utf-8")
    shutil.copytree(TRACKED_BRAIN / "seats", destination / "seats")
    for relative in ("mailbox/open", "mailbox/orphaned", "state", "episodes", "projects"):
        (destination / relative).mkdir(parents=True, exist_ok=True)


def _write_seats(root: Path, payload: Mapping[str, Any]) -> None:
    """One `safe_dump` per seeded root — the only write either seeder makes to `seats.yaml`."""
    (root / "seats.yaml").write_text(yaml.safe_dump(payload, sort_keys=False), "utf-8")


def seed_live_root(destination: Path) -> Path:
    """A brain root carrying the tracked seeds, pointed at the fake binary.

    The node folders, `seats.yaml` and `seats/*.md` are the **tracked** ones — the models, the
    caps, the tool lists and the prefixes a run would really use — with two keys rewritten: the
    binary's name, and the `PATH` list, which is narrowed to the two system directories the fake
    needs. Everything the containment turns on is left exactly as the seed ships it.
    """
    _seed_tree(destination)
    _write_seats(destination, _live_payload())
    return destination


def select_body(root: Path, body: str) -> Path:
    """Rewrite one seeded root's `runtime.body`. The rest of the seed is the tracked file's.

    Both body batteries need exactly this and nothing else — `test_bodies.py`'s replay seeds a
    root and names a body, `test_live_invoke.py`'s `bodied` flips the key on the **same** root so
    "the same containment under both bodies" is a fact about one seed rather than about two.
    """
    seats = root / "seats.yaml"
    payload = yaml.safe_load(seats.read_text(encoding="utf-8"))
    payload["runtime"][BODY_KEY] = body
    seats.write_text(yaml.safe_dump(payload, sort_keys=False), "utf-8")
    return root


def flags_of(argv: Sequence[str]) -> set[str]:
    """Every flag the **CLI** saw. The wrapper's own `-p` is excluded by construction: this reads
    the fake's `$@`, which is the argv `sandbox-exec` handed on."""
    return {item for item in argv if item.startswith("-")}


def seed_kinds_root(
    destination: Path, container: str = KINDS_TWO, *, evidence: Path | None = None
) -> Path:
    """`seed_live_root()`'s own tree and payload, plus a `kinds:` container the loader resolves.

    The tracked seed ships both class sub-mappings **empty** — naming a kind is build A.2's — so
    a root that needs a loadable kind gets its container from `fixtures/calls/kinds/` instead: the
    fixture's `kinds:` replaces the seed's empty one, every prefix file beside it is copied into
    `seats/kinds/`, and the stand-in stays the binary. Everything else is `seed_live_root()`'s —
    the same `_seed_tree()` and the same `_live_payload()`, applied once rather than written and
    then rewritten — so "everything the containment turns on is left exactly as the seed ships it"
    holds of both.

    `container` selects which fixture container is seeded: `KINDS_TWO`, or
    `KINDS_MISSING_PREFIX`, whose `prompt:` names a file this directory deliberately does not
    carry.

    **`evidence` names the stand-in's own directory as a `runtime.spawn_writable` entry**
    (`the build specification (not in this mirror)` § Deliverable 7, folded: S-i37). Under the inverted
    per-spawn profile the stand-in writes its argv, stdin, cwd and env files beside `$0`, so without
    that entry every row closing on those files would be closing on files the kernel refused to let
    it write. **A fixture seed is test-authored, so this is a seed entry and not a widening of the
    shipping seed**, which names `/tmp` and uv's cache and nothing else — the fixture's own list is
    replaced outright rather than appended to, so a fixture profile carries the two trees a test owns
    and no machine-wide tree it does not. What it costs is one clause in row G3: the write that must
    be **refused** has to target a third path, outside the workspace, outside `spawn_writable` and
    outside this directory. It is resolved for the kernel's reason — `sandbox-exec` matches a
    subpath against the realpath, and a pytest tmp directory under `/var` is a symlink.
    """
    _seed_tree(destination)
    payload = _live_payload()
    payload[KINDS_BLOCK] = deepcopy(_parsed(FIXTURE_KINDS / container)[KINDS_BLOCK])
    if evidence is not None:
        payload["runtime"][SPAWN_WRITABLE_KEY] = [
            FIXTURE_WRITABLE_TREE,
            str(evidence.resolve()),
        ]
    _write_seats(destination, payload)
    prefixes = kinds_dir(destination)
    prefixes.mkdir(parents=True, exist_ok=True)
    for entry in sorted(FIXTURE_KINDS.glob(f"*{SEAT_PROMPT_SUFFIX}")):
        shutil.copy2(entry, prefixes / entry.name)
    return destination


def seats_of(root: Path) -> SeatsConfig:
    """The `SeatsConfig` a fake-backed root loads to."""
    return parse_seats(yaml.safe_load((root / "seats.yaml").read_text(encoding="utf-8")), root)


def on_path(monkeypatch, binary_dir: Path) -> None:
    """Put the fake first on the **parent's** PATH, which is where the adapter resolves it."""
    monkeypatch.setenv("PATH", f"{binary_dir}{os.pathsep}{os.environ.get('PATH', '')}")


def live_seat(root: Path, *, workspace_path: str = "", decode_retries: int = 1) -> LiveSeat:
    """A `LiveSeat` over a fake-backed root, with its task already open."""
    book = LiveSessionBook()
    desk = SeatDesk(sessions=book)
    return LiveSeat(
        config=seats_of(root),
        desk=desk,
        sessions=book,
        workspace_path=workspace_path,
        decode_retries=decode_retries,
    )


def spawn_seat(
    root: Path,
    kind_class: str,
    name: str,
    *,
    workspace: Path | str = "",
    task: str = "task",
    tick: int = 1,
) -> LiveSeat:
    """**One port instance per spawn**, the three facts and all — what the desk constructs.

    `the build specification (not in this mirror)` § Deliverable 3: the resolved kind block, the tick's
    workspace, and the calling node, which `prefix_node()` reads structurally (the cortex for a
    `dispatch` member) or off the `NodeCall` payload (for a delegate). The scaffolding directory is
    built by `invoke.spawn_scaffold_dir()` rather than spelled here, so its shape keeps one owner.

    The spawn desk that hands the workspace in production is order W4's; **here the test hands it at
    construction**, which is the whole of what row G5 (b)'s positive read-back needs.
    """
    book = LiveSessionBook()
    desk = SeatDesk(sessions=book)
    config = seats_of(root)
    return LiveSeat(
        config=config,
        desk=desk,
        sessions=book,
        workspace_path=str(workspace),
        kind=config.kind(kind_class, name),
        spawn_scaffold=spawn_scaffold_dir(root, task, tick),
    )


def live_layer(root: Path, router, *, workspace_path: str = "") -> SeatLayer:
    """A whole `SeatLayer` whose port is a fake-backed live seat — the runtime's own seam."""
    seat = live_seat(root, workspace_path=workspace_path)
    return SeatLayer(
        router=router,
        port=seat,
        sessions=seat.sessions,
        calls=seat.calls,
    )


def spawn_layer(
    root: Path, router, *, workspace_path: str = "", plan: Mapping[str, Any] | None = None
) -> SeatLayer:
    """A layer carrying **both** the fourth seam and the fifth, with a fixture `calls:` plan.

    `the build specification (not in this mirror)` § Deliverable 4, row G3's last clause (D5-3) proved
    the delegate path here before any live layer carried `node_calls`; since A.2.i
    (`the build specification (not in this mirror)` § Deliverable 1) `build_live_layer()` attaches it too, over
    one `spawns` seam, with the shipping triggers off. This helper keeps a fixture plan so a case can
    drive the delegate arm without turning a trigger on.

    One `SpawnDesks` serves both seams, which is the point: the memoization is per `(task, tick)`,
    so the wave's opener and the delegate arm meet the same desk.
    """
    seat = live_seat(root, workspace_path=workspace_path)
    spawns = SpawnDesks(config=seat.config, root=root)
    return SeatLayer(
        router=router,
        port=seat,
        sessions=seat.sessions,
        calls=seat.calls,
        node_calls=CallDesks(port=seat, plan=dict(plan or {}), spawns=spawns),
        spawns=spawns,
    )


# --------------------------------------------------------------------------------------
# The wire shapes, as data
# --------------------------------------------------------------------------------------


def envelope(result: Mapping[str, Any], **extra: Any) -> dict[str, Any]:
    """A structured success carrying all four of `SeatEnvelope`'s measured facts."""
    body = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "num_turns": 2,
        "session_id": "fake-session",
        "stop_reason": "tool_use",
        "result": json.dumps(result),
        "modelUsage": {
            "claude-haiku-4-5-20251001": {"inputTokens": 9, "outputTokens": 1},
            "claude-opus-5": {"inputTokens": 4, "outputTokens": 7},
        },
        "usage": {
            "input_tokens": 4,
            "output_tokens": 7,
            "cache_creation_input_tokens": 40000,
            "cache_read_input_tokens": 0,
        },
        "total_cost_usd": 0.5,
    }
    body.update(extra)
    return body


def director_result(tick: int | None = None) -> dict[str, Any]:
    """What a live director answers under the narrowed schema: no `tick`, no `emitter`."""
    payload: dict[str, Any] = {"goals_pushed": [], "goals_closed": [], "cited_ids": []}
    if tick is not None:
        payload["tick"] = tick
    return payload


def planner_result(unit_id: str, goal_id: str) -> dict[str, Any]:
    return {
        "units": [
            {
                "id": unit_id,
                "goal_id": goal_id,
                "intent": "write the file",
                "expected": [
                    {"id": "e1", "kind": "file_exists", "arguments": {"path": "out.txt"}}
                ],
            }
        ],
        "goals_satisfied": [],
        "cited_ids": [],
    }


def wave_plan(unit_id: str, goal_id: str, kinds: Sequence[str]) -> dict[str, Any]:
    """The manager's answer: one unit, and a wave naming these kinds **in this order**.

    `member#` is assigned from the plan's order before anything starts, which is what makes the
    journal's line order the wave's order whatever the completion order turns out to be.
    """
    result = planner_result(unit_id, goal_id)
    result["wave"] = [
        {"kind": kind, "unit_id": unit_id, "admitted_ref": "admitted"} for kind in kinds
    ]
    return envelope(result)


def member_answers(
    kinds: Sequence[str],
    unit_id: str,
    *,
    narrative: str | None = None,
    denials: Sequence[Mapping[str, Any]] = (),
) -> list[tuple[tuple[str, str], dict[str, Any]]]:
    """One scripted return per member, keyed the way a spawn's response has to be keyed.

    A spawn's *recordings* are keyed by a session id the runtime minted, which no test can name in
    advance, so its *response* is selected by the `(kind, unit_id)` on stdin instead. `narrative`
    and `denials` are what a witness case needs on top: the prose each member answers with, and
    the `permission_denials` list the receipt's audit half is derived from.
    """
    extra = {"permission_denials": list(denials)} if denials else {}
    answers = []
    for kind in kinds:
        result = executor_result(unit_id)
        if narrative is not None:
            result["narrative"] = narrative
        answers.append(((kind, unit_id), envelope(result, **extra)))
    return answers


def executor_result(unit_id: str) -> dict[str, Any]:
    return {
        "unit_id": unit_id,
        "narrative": "wrote it",
        "observations": [
            {"path": "out.txt", "exists": True, "size_bytes": 11, "content_hash": "hash-1"}
        ],
        "exit_code": 0,
        "cited_ids": [],
    }
