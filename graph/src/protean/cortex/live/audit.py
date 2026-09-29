"""The four derived audit lists — what one spawn is witnessed by, off disk and off the denials.

`the build specification (not in this mirror)` § Deliverable 6 (the derivation table, the two
wave-level lists and the two per-spawn ones) and § Files it creates.

**Derived, never reported** (S-63). An in-call receipt is never read off the model's narrative: a
session that *says* it wrote nothing and a session that wrote nothing are the same sentence and two
different facts. Every list below comes from the filesystem or from the CLI's own
`permission_denials` bookkeeping, so a stand-in whose narrative claims all four produces four empty
lists — which is the whole content of the phrase.

**This module imports build 2's landed classifier and re-derives none of it** (folded: S-i45).
`shell_segments()` splits a `Bash` denial's command the way a shell would, `wrote_or_left_the_clone()`
judges each segment against the granted workspace and `attempted_to_execute_the_binary()` answers
whether a segment tried to *run* the seat binary rather than merely name it. That is why
`src/protean/oracle/audit.py` is **unedited by this build** and appears in no row of § Files it
changes. **`tool_violations()` is never called** (folded: S-i31): it takes a `stream-json`
transcript's `TranscriptMetrics`, which this path never has, and fed denials alone it answers `[]`
forever.

**The one judgement this module declares itself is the link-farm predicate.** `runtime.bin_links` is
the *runtime's* allow-list of executables a spawn's `PATH` may resolve — it is not the oracle's clone
rule — so the test that a denial tried to run one of those names lives here, over the same
`shell_segments()` output the imported functions read.

**What is not witnessed, and is named rather than implied.** Per-tool USE under `json` envelopes, and
network egress (§ Named assumptions 9): a licensed interpreter's socket raises no denial, reaches no
list here, and leaves nothing on disk. The process-group read at the join witnesses a grandchild
**still alive** and not one that already exited (§ Named assumptions 7, row B51). There is **no
"process record"** to read and this module invents none.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from protean.cortex.live.invoke import SANDBOX_EXEC_FAILURE
from protean.oracle.audit import (
    attempted_to_execute_the_binary,
    shell_segments,
    wrote_or_left_the_clone,
)
from protean.state.calls import (
    SPAWN_CHANGED_PATH_LIMIT,
    SPAWN_CHANGED_TRUNCATED,
    SpawnAudit,
    SpawnTreeDiff,
)

#: The directories a workspace diff does not walk, **by name** (§ Deliverable 6): a workspace
#: carrying a virtualenv would otherwise produce a receipt nobody can read. The set is the SPEC's own
#: three and is not widened here — an exclusion nobody named is a write nobody sees.
DIFF_EXCLUDED_DIRS: Final[frozenset[str]] = frozenset({".venv", "__pycache__", ".pytest_cache"})

#: The **runtime's own scaffolding**, excluded by name on build 2's landed
#: `new_temp_files()`/`OWN_TEMP_MARKERS` precedent (S-51), which excludes the per-session clone and
#: the seat's link farm for exactly this reason: they are the runtime's doing, not the spawn's.
#:
#: A *spawn's* farm and throwaway cwd live under `brain/state/<task>/spawns/<tick>/` and are inside
#: `sandbox.deny_write`, so they are in no allowed subpath at all (folded: S-i48); the two `mkdtemp`
#: prefixes below are the **seats'** landed fallback, which does land under the temp root a
#: `runtime.spawn_writable` seed names.
OWN_SCAFFOLD_MARKERS: Final[tuple[str, ...]] = (
    "protean-seat-bin-",
    "protean-seat-cwd-",
    "protean-oracle-clone-",
)

#: The typed inputs a non-`Bash` denial names a path in. Read **as the field it is** rather than
#: through the shell splitter, because a `Write` denial's `file_path` is a path and not a command
#: (§ Deliverable 6, folded: S-i5).
PATH_INPUT_KEYS: Final[tuple[str, ...]] = ("file_path", "path", "notebook_path")

#: Where a denial keeps the tool's own arguments, and the key a `Bash` denial's command sits under.
TOOL_INPUT_KEY: Final[str] = "tool_input"
TOOL_NAME_KEY: Final[str] = "tool_name"
COMMAND_KEY: Final[str] = "command"

#: What `ps` is asked for a process group's live members, and how long it may take. `ps` rather than
#: a `/proc` walk because this is macOS, and a fixed argv rather than a shell string because nothing
#: here interpolates into a shell.
PS_ARGV: Final[tuple[str, ...]] = ("/bin/ps", "-o", "pid=", "-g")
PS_TIMEOUT_SECONDS: Final[float] = 5.0


# --------------------------------------------------------------------------------------
# The baseline: the desk's own working state between its open and the join
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SpawnBaseline:
    """What the desk holds between its `open()` and the wave's join, and never persists.

    **One wave, one baseline, one diff** (folded: S-i24). It is taken **before the first member
    spawned** and read once after the wave joins, so `wrote` and `wrote_outside_workspace` are the
    *wave's* lists and every member's receipt carries them identically — exactly as `dispatch_id`
    does. A delegate's wave is one spawn, so its lists are its own.

    **Nothing here reaches a receipt** (folded: S-i47): I4 carries no baseline reference, because a
    persisted field with no reader is a field that invites one.
    """

    #: The granted workspace, resolved — or `None` where the desk has none to witness.
    workspace: Path | None = None
    #: The workspace's digest over `(path, mtime, size)` at the open.
    workspace_digest: str = ""
    #: `relative path → (mtime_ns, size)` at the open. The changed-path list's other half.
    workspace_entries: Mapping[str, tuple[int, int]] = field(default_factory=dict)
    #: Every allowed **directory** subpath but the workspace — the resolved `runtime.spawn_writable`
    #: trees and `SPAWN_PROCESS_ALLOWANCES`' own directories, its device literals already excluded by
    #: the desk because a device is not a file (folded: S-i49).
    allowed: tuple[Path, ...] = ()
    #: The wall-clock instant the open happened. The allowed trees are witnessed **against it**
    #: rather than against a snapshot of them: they are machine-shared, so a snapshot of `/tmp` is a
    #: second copy of noise and mtime is the right instrument (build 2's `new_temp_files()`, S-51).
    since: float = 0.0


def take_baseline(workspace: Path | None, allowed: Sequence[Path]) -> SpawnBaseline:
    """The baseline, taken at the desk's open and before the first member spawned."""
    digest, entries = ("", {}) if workspace is None else _tree_state(workspace)
    return SpawnBaseline(
        workspace=workspace,
        workspace_digest=digest,
        workspace_entries=entries,
        allowed=tuple(allowed),
        since=time.time(),
    )


# --------------------------------------------------------------------------------------
# List one — `wrote`: the granted workspace's own diff
# --------------------------------------------------------------------------------------


def wrote(baseline: SpawnBaseline) -> list[SpawnTreeDiff]:
    """The workspace as the join found it: one digest per tree, plus the changed paths.

    **One digest per tree and no per-path hashing of the workspace** (§ DoD row G8, folded: S-i47).
    The digest is over the sorted `(relative path, mtime, size)` triples rather than over the
    workspace's bytes: it answers "did this tree move at all", which is what the row asks of it, and
    a receipt that costs a full read of a repository twice per wave is a receipt that changes what
    the wave costs.

    Empty where the desk has no workspace to witness — which is no live wave, the open refusing
    first, but is every unit call of this function that names none.
    """
    tree = baseline.workspace
    if tree is None:
        return []
    digest, entries = _tree_state(tree)
    return [
        SpawnTreeDiff(
            tree=str(tree),
            moved=digest != baseline.workspace_digest,
            digest=digest,
            changed=_changed(baseline.workspace_entries, entries),
        )
    ]


# --------------------------------------------------------------------------------------
# List two — `wrote_outside_workspace`: the half of the containment the profile GRANTS
# --------------------------------------------------------------------------------------


def wrote_outside_workspace(baseline: SpawnBaseline) -> list[SpawnTreeDiff]:
    """Every allowed **directory** subpath, asked the same question by mtime and size.

    It exists because writes **into** the allowed set were witnessed by nothing (folded: S-i39):
    `/tmp` is machine-shared, and the other three lists all derive from the granted workspace or the
    envelope's own denials, so a grant nobody reads is a grant nobody can review.

    **Witnessed by mtime against the open's instant, not against a snapshot** — build 2's landed
    `new_temp_files()` precedent (S-51): "detection only, and mtime-based rather than byte-based:
    these trees are shared with every other process on the machine, so a digest of them would be
    noise". `digest` is therefore `""` on every tree here, and `moved` is "something appeared or
    changed under it".

    **The recursion is pruned by directory mtime, which is a named limit and not a detail.** A
    directory whose own mtime predates the open had no entry added, removed or renamed in it, so
    every *new* file, every rename and every delete is still seen; what is missed is a pre-existing
    file **rewritten in place inside a pruned subdirectory**. The alternative is a full walk of every
    granted tree twice per wave — measured at 1.1 s per pass over this machine's `/tmp`, which is a
    third of the whole battery's wall time for a list whose own precedent calls itself detection.
    """
    diffs: list[SpawnTreeDiff] = []
    for tree in baseline.allowed:
        if not tree.is_dir():
            continue
        changed = _changed_since(tree, baseline.since)
        diffs.append(SpawnTreeDiff(tree=str(tree), moved=bool(changed), changed=changed))
    return diffs


# --------------------------------------------------------------------------------------
# List three — `left-the-clone`: two pure functions over the denials, and nothing else
# --------------------------------------------------------------------------------------


def left_the_clone(
    denials: Iterable[Mapping[str, Any]], workspace: Path | None
) -> list[str]:
    """Why each refused call wrote, or reached outside the granted workspace.

    **Two pure functions over the denials and nothing else** (folded: S-i5, folded: S-i31): no
    transcript and no `TranscriptMetrics` exist on this path. A `Bash` denial's command goes through
    the imported `shell_segments()` and `wrote_or_left_the_clone()`; every other denial's
    `file_path`/`path` input is read **as the typed field it is**, because a `Write` denial's path is
    a path and splitting it like a command would say nothing.

    Every path is resolved against the **granted workspace** — which is what "the clone" is on this
    path. `None` is the conservative arm the imported function already owns: with no granted tree,
    every absolute path counts as outside.

    **The refusal is the fact.** The CLI refuses leaving the clone (S-52) and what the model says
    about it is not evidence; a denial list is therefore a receipt rather than a violation (S-44).
    """
    reasons: list[str] = []
    for denial in denials:
        tool = str(denial.get(TOOL_NAME_KEY, "")) or "?"
        command = _denial_command(denial)
        if command:
            why = wrote_or_left_the_clone(command, workspace)
            if why:
                reasons.append(f"{tool}: {why}")
            continue
        for named in _denial_paths(denial):
            if not _inside_the_workspace(named, workspace):
                reasons.append(
                    f"{tool}: the denial names an absolute path outside the granted "
                    f"workspace ({named})"
                )
    return reasons


# --------------------------------------------------------------------------------------
# List four — `exec-attempted`: the denials, the wrapper's own text, and the group at join
# --------------------------------------------------------------------------------------


def exec_attempted(
    denials: Iterable[Mapping[str, Any]],
    *,
    bin_links: Sequence[str] = (),
    error: str = "",
    pgid: int = 0,
    live_members: Sequence[int] = (),
) -> list[str]:
    """Every fact that this spawn tried to **run** a binary rather than to name one.

    Four sources, and § Deliverable 6 names all four: the denials through the imported
    `attempted_to_execute_the_binary()`; **the local link-farm predicate** over the same
    `shell_segments()` output; the wrapper's own `execvp` failure text, which the port already
    recorded on this spawn's facts as its refusal message; and **the process group's live members
    read at the join**.

    Naming the binary is a reported fact and an exec that *ran* is a consequential one (S-55, S-56).
    The group read is a fact about the group and **not a prevention** — `process-exec` cannot be
    denied without breaking the launch, measured 2026-09-07 — and it is the only witness of the
    nested-session route: a grandchild still alive at the join appears here, one that exited before
    it does not (§ Named assumptions 7, row B51).

    **`live_members` is read by the caller, at that spawn's own join, and this function does no
    I/O.** The desk reads the group through `live_process_group_members()` in the `finally` that
    records the spawn's facts — which is the instant "as it joins each spawn" names — so this stays a
    pure function over what was measured, and a wave's later members cannot move an earlier one's
    answer.
    """
    reasons: list[str] = []
    for denial in denials:
        tool = str(denial.get(TOOL_NAME_KEY, "")) or "?"
        command = _denial_command(denial)
        if not command:
            continue
        why = attempted_to_execute_the_binary(command)
        if why:
            reasons.append(f"{tool}: {why}")
        farmed = attempted_to_execute_a_farmed_binary(command, bin_links)
        if farmed:
            reasons.append(f"{tool}: {farmed}")
    if error and SANDBOX_EXEC_FAILURE in error:
        reasons.append(f"the wrapper could not exec the CLI: {error}")
    alive = tuple(live_members)
    if alive:
        reasons.append(
            f"the spawn's process group {pgid} still had live members at the join "
            f"{list(alive)} — a grandchild the kill would have reached and the audit lists "
            f"would not (§ Named assumptions 7, row B51)"
        )
    return reasons


def attempted_to_execute_a_farmed_binary(command: str, bin_links: Sequence[str]) -> str:
    """Why this command tried to run a name on the link farm, or `""` — **this module's own**.

    `runtime.bin_links` is the *runtime's* allow-list of executables a spawn's `PATH` may resolve
    (A1-12: global, never per kind), which is not the oracle's clone rule — so the predicate lives
    here rather than in `src/protean/oracle/audit.py`, and that module stays unedited by this build
    (folded: S-i45). What binds is still the granted set: a binary on `PATH` no granted tool can
    invoke is reachable by nothing, and **this list is what would see it used**.

    The test is `attempted_to_execute_the_binary()`'s own, one name set wider: a segment whose
    **first token resolves to** a farmed name. A command that merely mentions one named it.
    """
    names = {str(one) for one in bin_links if str(one)}
    if not names:
        return ""
    for segment in shell_segments(command):
        argv = segment.argv
        if argv and Path(argv[0]).name in names:
            return (
                f"the command attempts to execute {Path(argv[0]).name!r}, a name on the "
                f"runtime's link farm ({argv[0]})"
            )
    return ""


def live_process_group_members(pgid: int) -> tuple[int, ...]:
    """The pids still in this process group, read at the join. Empty is "the group is gone".

    Two steps, cheapest first: `os.killpg(pgid, 0)` sends no signal and answers only whether the
    group exists, so a group that already exited costs one syscall rather than a `ps` fork — which
    is every spawn of every fixture that leaves no grandchild behind. Only a group that *is* there
    is enumerated.

    **`pgid <= 1` is refused before either step.** `killpg(0, …)` addresses the **caller's own**
    group, and a witness that reported the runtime's own process as a spawn's grandchild would be
    worse than no witness at all; `0` is exactly what a spawn that never created a process leaves on
    its facts.
    """
    if pgid <= 1:
        return ()
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError, OSError):
        return ()
    try:
        completed = subprocess.run(
            [*PS_ARGV, str(pgid)],
            capture_output=True,
            text=True,
            check=False,
            timeout=PS_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):  # pragma: no cover — `ps` is on every macOS
        return ()
    found: list[int] = []
    for line in completed.stdout.split("\n"):
        text = line.strip()
        if text.isdigit():
            found.append(int(text))
    return tuple(sorted(found))


# --------------------------------------------------------------------------------------
# The composition: one witness per spawn, two of its lists shared by the wave
# --------------------------------------------------------------------------------------


def compose(
    *,
    wave_level: SpawnAudit,
    denials: Iterable[Mapping[str, Any]],
    workspace: Path | None,
    bin_links: Sequence[str] = (),
    error: str = "",
    pgid: int = 0,
    live_members: Sequence[int] = (),
) -> SpawnAudit:
    """One spawn's four lists: the wave's two carried through, its own two derived.

    `wave_level` is the wave's one diff pair, computed once after the join and handed to **every**
    member of that wave, so the two lists are byte-identical on every receipt of it exactly as
    `dispatch_id` is (folded: S-i24, folded: S-i39). Per-member attribution is not available from one
    baseline and one diff and is not faked here. The wave-level list stands because A.2 upheld row
    B52's default — the manager plans at most one writing member per wave, and no disjoint writable
    sets are held — and a later narrowing is still one function's change on the landed hook, the
    profile composed per spawn (`the build specification (not in this mirror)` L5).
    """
    captured = list(denials)
    return SpawnAudit(
        wrote=list(wave_level.wrote),
        wrote_outside_workspace=list(wave_level.wrote_outside_workspace),
        left_the_clone=left_the_clone(captured, workspace),
        exec_attempted=exec_attempted(
            captured,
            bin_links=bin_links,
            error=error,
            pgid=pgid,
            live_members=live_members,
        ),
    )


def wave_level_diffs(baseline: SpawnBaseline) -> SpawnAudit:
    """The wave's two lists, computed **once** after the join. The other two stay empty here."""
    return SpawnAudit(
        wrote=wrote(baseline),
        wrote_outside_workspace=wrote_outside_workspace(baseline),
    )


# --------------------------------------------------------------------------------------
# The walks
# --------------------------------------------------------------------------------------


def _excluded(name: str) -> bool:
    """Is this directory name one of the named exclusions, or the runtime's own scaffolding?"""
    return name in DIFF_EXCLUDED_DIRS or any(
        marker in name for marker in OWN_SCAFFOLD_MARKERS
    )


def _tree_state(tree: Path) -> tuple[str, dict[str, tuple[int, int]]]:
    """One tree's digest and its `relative path → (mtime_ns, size)` map, in one walk.

    The digest is over the sorted triples and never over the files' bytes (§ DoD row G8, "no
    per-path hashing of the workspace"). A symlink contributes its own `lstat`, never its target's:
    following one would take the digest outside the tree it is a digest of.
    """
    entries: dict[str, tuple[int, int]] = {}
    if not tree.is_dir():
        return f"absent:{tree}", entries
    for directory, subdirectories, filenames in os.walk(tree, onerror=lambda _fault: None):
        subdirectories[:] = [one for one in subdirectories if not _excluded(one)]
        for name in filenames:
            path = Path(directory) / name
            try:
                status = path.lstat()
            except OSError:  # pragma: no cover — a file that vanished mid-walk
                continue
            entries[str(path.relative_to(tree))] = (status.st_mtime_ns, status.st_size)
    digest = hashlib.sha256()
    for relative in sorted(entries):
        mtime, size = entries[relative]
        digest.update(f"{relative}\0{mtime}\0{size}\0".encode())
    return digest.hexdigest(), entries


def _changed(
    before: Mapping[str, tuple[int, int]], after: Mapping[str, tuple[int, int]]
) -> list[str]:
    """Every path that appeared, vanished or moved in mtime or size. Bounded and sorted."""
    found = sorted(
        name
        for name in set(before) | set(after)
        if before.get(name) != after.get(name)
    )
    return _bounded(found)


def _changed_since(tree: Path, since: float) -> list[str]:
    """Every file under `tree` whose mtime is at or after `since`, pruned by directory mtime.

    The prune is stated in `wrote_outside_workspace()`'s own docstring, which is where the limit it
    carries belongs. The runtime's own scaffolding is excluded **by name** on build 2's
    `OWN_TEMP_MARKERS` precedent (S-51).
    """
    found: list[str] = []
    pending = [tree]
    while pending:
        current = pending.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            if _excluded(entry.name):
                continue
            try:
                status = entry.stat(follow_symlinks=False)
                if entry.is_dir(follow_symlinks=False):
                    if status.st_mtime >= since:
                        pending.append(Path(entry.path))
                    continue
                if status.st_mtime >= since:
                    found.append(entry.path)
            except OSError:  # pragma: no cover — an entry that vanished mid-walk
                continue
        if len(found) > SPAWN_CHANGED_PATH_LIMIT:
            break
    return _bounded(sorted(found))


def _bounded(found: Sequence[str]) -> list[str]:
    """The list, capped, saying so where it was capped (`SPAWN_CHANGED_PATH_LIMIT`)."""
    if len(found) <= SPAWN_CHANGED_PATH_LIMIT:
        return list(found)
    return [*found[:SPAWN_CHANGED_PATH_LIMIT], SPAWN_CHANGED_TRUNCATED]


# --------------------------------------------------------------------------------------
# Reading one denial
# --------------------------------------------------------------------------------------


def _tool_input(denial: Mapping[str, Any]) -> Mapping[str, Any]:
    found = denial.get(TOOL_INPUT_KEY)
    return found if isinstance(found, Mapping) else {}


def _denial_command(denial: Mapping[str, Any]) -> str:
    """The `Bash` command a denial refused, or `""` for a denial that is not one.

    The shape is **measured**, not guessed: `tests/cortex/captures/containment-dontask.json`'s three
    denials each carry `tool_name`, `tool_use_id` and a `tool_input` holding `command`.
    """
    found = _tool_input(denial).get(COMMAND_KEY)
    return found if isinstance(found, str) else ""


def _denial_paths(denial: Mapping[str, Any]) -> list[str]:
    """Every typed path input a non-`Bash` denial names, read as the field it is."""
    arguments = _tool_input(denial)
    return [
        value
        for key in PATH_INPUT_KEYS
        if isinstance(value := arguments.get(key), str) and value
    ]


def _inside_the_workspace(named: str, workspace: Path | None) -> bool:
    """Is this named path inside the granted workspace? `None` is the conservative arm.

    The same reading `wrote_or_left_the_clone()` takes with no clone (ledger S1-6): with no granted
    tree, every absolute path counts as outside, because the list's whole claim is that it is empty.
    A **relative** path is inside by construction — it is resolved against the spawn's own cwd, which
    is the workspace or the runtime-owned throwaway directory.
    """
    candidate = Path(named).expanduser()
    if not candidate.is_absolute():
        return True
    if workspace is None:
        return False
    root = Path(workspace).resolve()
    return candidate == root or root in candidate.parents
