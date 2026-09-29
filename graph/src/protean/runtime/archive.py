"""The run archive: one directory per terminal, hashed, with the product beside the state.

`the build specification (not in this mirror)` § Deliverable 6 → *The archive*, § Directional decisions 20,
§ Named assumptions 12, § Resolutions A1-17, S-35 and S-41.

**On every terminal, not only `done`** (folded: S-35). A `stopped`, `stuck`, `blocked` or
`interrupted` run is the one whose product is most likely to be lost — the branch lives in a
throwaway clone and the next run overwrites the working tree — so the copy hangs off the driver
the moment a terminal has committed, and the terminal it fired on changes nothing about what is
copied.

**The product is copied as git objects, never as a working tree** (folded: S-35): a
`git bundle` of everything the clone holds, plus the run's own commits as a `format-patch`
series. Between them a reviewer can restore the branch on any machine and read the diff without
one. The clone itself is never written to and never pushed.

**It is a copy, not a backup** (§ Named assumptions 12). It survives a `git clean` and a second
run; nothing here makes it survive losing the machine.

**Gitignored, and never deleted.** `brain/archive/` carries `~/workload` content and real cost
numbers, so it is generated state (`.gitignore`); and each run mints its own
`workload-run-<timestamp>` directory, so a second run adds a directory rather than replacing one.

**Write, then verify** — the shape `protean.runtime.commit` and `protean.brain.jsonl` use. The
manifest is written last, over every file the archive holds; then every path it names is
re-opened and re-hashed. A manifest that describes an archive nobody checked would be the one
artifact in this build whose claim is not a receipt.

**The git seam lives here rather than in `protean.runtime.report`.** The workspace clone is the
archive's subject — it is what the bundle and the patch series are made of — and the report's
*files* group is one projection of the same read. One seam, one place a subprocess is spawned,
and the report imports it.

**No model is called and no binary but `git` is named.** `tests/test_zero_calls.py`'s static
half greps this module like every other one outside the two licensed packages.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from protean import config
from protean.runtime.paths import CHECKPOINT_TEMP_SUFFIX, BrainPaths, TaskPaths
from protean.state.enums import TerminalState

#: `workload-run-<ts>` — microseconds, so two terminals in one second cannot collide.
STAMP_FORMAT = "%Y%m%dT%H%M%S%f"

#: The archive's own files. The manifest is the only one it does not hash.
MANIFEST_FILENAME = "manifest.json"
NOTES_FILENAME = "notes.json"
#: Where the run driver's four before/after tree hashes land (folded: S-41). This module makes
#: the place; order W8 fills it, because the hashes are taken around the *run*, not around the
#: copy — nothing here can observe the four trees S-41 names before a tick happened.
HASHES_FILENAME = "hashes.json"

#: The archive's sub-trees, named once.
STATE_DIRNAME = "state"
NODES_DIRNAME = "nodes"
EPISODES_DIRNAME = "episodes"
ORACLE_DIRNAME = "oracle"
PRODUCT_DIRNAME = "product"
PATCHES_DIRNAME = "patches"
BUNDLE_FILENAME = "product.bundle"

#: The one binary this module spawns.
GIT = "git"

#: Every subprocess is bounded: a hung `git` in the terminal step would hang the run.
GIT_TIMEOUT_SECONDS = 120.0

#: `git bundle create <file> --all` — the whole clone, refs included.
BUNDLE_ARGS: tuple[str, ...] = ("bundle", "create")

#: What `git status --porcelain` prefixes an untracked file with.
UNTRACKED_STATUS = "??"


class ArchiveVerificationFailed(RuntimeError):
    """A manifest that does not describe the archive on disk. Raised, never logged past."""


@dataclass(frozen=True, slots=True)
class GitResult:
    """One `git` invocation: whether it succeeded, and both streams."""

    ok: bool
    out: str
    error: str


@dataclass(frozen=True, slots=True)
class ArchiveResult:
    """What the archive step produced: where it landed, what it hashed, what it could not do."""

    directory: Path
    manifest: dict[str, str]
    notes: tuple[str, ...] = ()

    def paths(self) -> tuple[Path, ...]:
        """Every archived file, absolute."""
        return tuple(self.directory / relative for relative in sorted(self.manifest))


# --------------------------------------------------------------------------------------
# The git seam — the clone is read, never written
# --------------------------------------------------------------------------------------


def run_git(workspace: Path, *arguments: str) -> GitResult:
    """One bounded `git` call inside the clone. A missing binary is a result, not a raise."""
    try:
        completed = subprocess.run(  # noqa: S603 - a fixed binary and a fixed argument list
            [GIT, "-C", str(workspace), *arguments],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return GitResult(ok=False, out="", error=str(exc))
    return GitResult(
        ok=completed.returncode == 0,
        out=completed.stdout.strip(),
        error=completed.stderr.strip(),
    )


def is_repository_root(workspace: Path) -> bool:
    """Whether the path is the **top level** of a git work tree.

    The top level and not merely inside one: a workspace that is a sub-directory of some other
    checkout would otherwise report that checkout's changes as the run's product, which is the
    one way this measurement could lie without failing.
    """
    if not workspace.is_dir():
        return False
    result = run_git(workspace, "rev-parse", "--show-toplevel")
    if not result.ok:
        return False
    return Path(result.out).resolve() == workspace.resolve()


def run_commits(workspace: Path, *, base_ref: str | None = None) -> tuple[str, ...]:
    """The commits the run itself made, oldest first.

    With a `base_ref` the answer is `<base>..HEAD`. Without one it is everything reachable from
    `HEAD` and from no remote — which is exactly the run's own work in a clone, because a clone
    starts with every upstream commit already on a remote-tracking ref. A repository with **no**
    remote and no base ref answers nothing rather than claiming the whole history: "the run's
    commits" is not derivable there, and this module reports rather than guesses.
    """
    if base_ref is not None:
        result = run_git(workspace, "rev-list", "--reverse", f"{base_ref}..HEAD")
        return tuple(result.out.split()) if result.ok else ()
    remotes = run_git(workspace, "remote")
    if not remotes.ok or not remotes.out:
        return ()
    result = run_git(workspace, "rev-list", "--reverse", "HEAD", "--not", "--remotes")
    return tuple(result.out.split()) if result.ok else ()


def _named_path(line: str) -> tuple[str, str] | None:
    """One `--name-status` line as `(status, path)`; a rename reports its destination."""
    parts = line.split("\t")
    if len(parts) < 2:
        return None
    return parts[0].strip(), parts[-1].strip()


def changed_files(
    workspace: Path, *, base_ref: str | None = None
) -> tuple[tuple[str, str], ...]:
    """Every file the run created or changed in the clone, `(status, path)`, sorted by path.

    Two reads, merged, the working tree winning: the run's own commits report what was
    committed, and `git status --porcelain` reports what was left uncommitted. git's own status
    letters are carried through unedited — the exporter-manifest duty is the operator's to discharge, and
    a re-worded status would be this build's judgment standing in for git's fact.
    """
    seen: dict[str, str] = {}
    for commit in run_commits(workspace, base_ref=base_ref):
        shown = run_git(workspace, "show", "--name-status", "--format=", commit)
        if not shown.ok:
            continue
        for line in shown.out.splitlines():
            named = _named_path(line)
            if named is not None:
                seen[named[1]] = named[0]
    status = run_git(workspace, "status", "--porcelain")
    if status.ok:
        for line in status.out.splitlines():
            if not line.strip():
                continue
            code = line[:2].strip() or UNTRACKED_STATUS
            path = line[2:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            seen[path.strip('"')] = code
    return tuple((status_code, path) for path, status_code in sorted(seen.items()))


def write_bundle(workspace: Path, destination: Path) -> str | None:
    """`git bundle create <dest> --all`. Returns a note when there was nothing to bundle."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = run_git(workspace, *BUNDLE_ARGS, str(destination), "--all")
    if result.ok and destination.exists():
        return None
    destination.unlink(missing_ok=True)
    return f"no git bundle: {result.error or result.out or 'git refused'}"


def write_patch_series(
    workspace: Path, directory: Path, *, base_ref: str | None = None
) -> tuple[list[Path], str | None]:
    """The run's commits as a `format-patch` series. Returns the patches and any note."""
    commits = run_commits(workspace, base_ref=base_ref)
    if not commits:
        return [], "no patch series: the run's own commits are not derivable in this clone"
    directory.mkdir(parents=True, exist_ok=True)
    oldest = commits[0]
    has_parent = run_git(workspace, "rev-parse", "--verify", "--quiet", f"{oldest}^").ok
    span = ["--root", "HEAD"] if not has_parent else [f"{oldest}^..HEAD"]
    result = run_git(workspace, "format-patch", "--output-directory", str(directory), *span)
    if not result.ok:
        return [], f"no patch series: {result.error or result.out or 'git refused'}"
    return sorted(directory.glob("*.patch")), None


# --------------------------------------------------------------------------------------
# The archive itself
# --------------------------------------------------------------------------------------


def sha256(path: Path) -> str:
    """One file's digest, streamed — an archived bundle is the one file that can be large."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def mint_directory(root: Path, stamp: str | None = None) -> Path:
    """`brain/archive/workload-run-<ts>/`, never an existing one — a previous run is never deleted."""
    brain = BrainPaths(root=root)
    minted = stamp or datetime.now(timezone.utc).strftime(STAMP_FORMAT)
    candidate = brain.archive_run(minted)
    suffix = 0
    while candidate.exists():
        suffix += 1
        candidate = brain.archive_run(f"{minted}-{suffix}")
    candidate.mkdir(parents=True)
    return candidate


def _copy(source: Path, destination: Path) -> bool:
    if not source.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True


def _copy_state(paths: TaskPaths, directory: Path) -> list[str]:
    """The task's checkpoints, journals, `seat_calls.jsonl` and the run report beside them."""
    notes: list[str] = []
    if not paths.state_dir.is_dir():
        return [f"no state directory to copy at {paths.state_dir.name}"]
    for entry in sorted(paths.state_dir.iterdir()):
        if entry.is_file() and not entry.name.endswith(CHECKPOINT_TEMP_SUFFIX):
            _copy(entry, directory / STATE_DIRNAME / entry.name)
    if not paths.checkpoint.exists():
        notes.append("no checkpoint: the task committed no tick")
    if not paths.seat_calls.exists():
        notes.append("no seat_calls.jsonl: the run made no live invocation")
    return notes


def _copy_traces(paths: TaskPaths, directory: Path) -> list[str]:
    """All six `trace.jsonl` files, under the node names `config.NODE_ORDER` fixes."""
    notes: list[str] = []
    for node in config.NODE_ORDER:
        source = paths.trace(node)
        if not _copy(source, directory / NODES_DIRNAME / node / source.name):
            notes.append(f"no trace.jsonl for {node}")
    return notes


def archive_run(
    root: Path,
    task_id: str,
    *,
    terminal: TerminalState | str | None = None,
    workspace_path: str = "",
    base_ref: str | None = None,
    oracle_report: Path | None = None,
    hashes: Mapping[str, str] | None = None,
    stamp: str | None = None,
) -> ArchiveResult:
    """Copy one terminated run into `brain/archive/workload-run-<ts>/`, hash it, and verify it.

    Everything § Deliverable 6 names: the task's checkpoints, journals, `seat_calls.jsonl`, all
    six `trace.jsonl` files, the task's episodes, the `OracleReport` when the run has one, the
    `WorkloadRunReport` (copied with the rest of the state directory, where the report writer put
    it), and the product as a `git bundle` plus its `format-patch` series.

    **A run with no workspace archives the rest and says so.** A dry or scripted run has no
    clone, so there is no branch to bundle; that is an ordinary shape, recorded in `notes.json`
    and in the returned `notes`, never a refusal.
    """
    brain = BrainPaths(root=root)
    paths = brain.task(task_id)
    directory = mint_directory(root, stamp)

    notes: list[str] = []
    notes.extend(_copy_state(paths, directory))
    notes.extend(_copy_traces(paths, directory))
    if not _copy(paths.episodes, directory / EPISODES_DIRNAME / paths.episodes.name):
        notes.append("no episodes.jsonl: the task recorded no episode")

    if oracle_report is not None:
        if not _copy(oracle_report, directory / ORACLE_DIRNAME / oracle_report.name):
            notes.append(f"no oracle report at {oracle_report.name}")
    else:
        notes.append("no oracle report for this run")

    notes.extend(_archive_product(workspace_path, directory, base_ref=base_ref))

    if hashes is not None:
        (directory / HASHES_FILENAME).write_text(
            json.dumps(dict(hashes), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    (directory / NOTES_FILENAME).write_text(
        json.dumps(
            {
                "task": task_id,
                "terminal": None if terminal is None else str(terminal),
                "directory": directory.name,
                "workspace": workspace_path,
                "notes": notes,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = write_manifest(directory)
    verify(directory, manifest)
    return ArchiveResult(directory=directory, manifest=manifest, notes=tuple(notes))


def _archive_product(
    workspace_path: str, directory: Path, *, base_ref: str | None = None
) -> list[str]:
    """The run's only reviewable product: the branch, as objects rather than as a tree."""
    if not workspace_path:
        return ["no workspace: this run had no clone, so there is no product to bundle"]
    workspace = Path(workspace_path)
    if not is_repository_root(workspace):
        return [f"no product: {workspace_path} is not the root of a git work tree"]
    product = directory / PRODUCT_DIRNAME
    notes: list[str] = []
    note = write_bundle(workspace, product / BUNDLE_FILENAME)
    if note is not None:
        notes.append(note)
    patches, patch_note = write_patch_series(
        workspace, product / PATCHES_DIRNAME, base_ref=base_ref
    )
    if patch_note is not None:
        notes.append(patch_note)
    elif not patches:
        notes.append("the patch series is empty: the run committed nothing")
    return notes


def attach(directory: Path, files: Mapping[str, Path]) -> dict[str, str]:
    """Copy post-terminal facts into an archive that already exists, then re-manifest it.

    `the build specification (not in this mirror)` § Resolutions D16-8 and S-41; folded as the run driver's
    half of order W8 (session ruling S-58).

    **Why an archive gains files after it is written.** `engine._drive()` calls `close_out()`
    the moment a terminal commits, and D16-8 made the four hashes and the `OracleReport` the
    *driver's* to pass — but neither exists at that moment. The after-hashes are taken after the
    terminal, and the post-change grading runs on the product the terminal produced. So the
    driver attaches them once they exist, and this is the one door through which an archive
    changes after it is minted.

    **The manifest is rewritten, not appended to** — `verify()` refuses a file the manifest
    never named, so a copy without a re-manifest would leave the archive failing its own check.
    Write, then verify: the shape the module already uses, applied to the second write.

    `files` maps archive-relative destination to source path. A source that does not exist is a
    `FileNotFoundError` rather than a silent omission: this function's whole job is to put a
    named receipt where the archive can be read back, and a missing one is not a shape the
    caller should learn about from a short manifest.
    """
    if not directory.is_dir():
        raise ArchiveVerificationFailed(f"{directory}: no archive to attach to")
    for relative, source in files.items():
        if not source.exists():
            raise FileNotFoundError(f"{source} does not exist: nothing to attach as {relative}")
        _copy(source, directory / relative)
    manifest = write_manifest(directory)
    verify(directory, manifest)
    return manifest


def archived_files(directory: Path) -> list[Path]:
    """Every file in the archive except the manifest, sorted — what the manifest describes."""
    return sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.name != MANIFEST_FILENAME
    )


def write_manifest(directory: Path) -> dict[str, str]:
    """The per-file sha256 manifest (decision 20), keyed by archive-relative path."""
    manifest = {
        str(path.relative_to(directory)): sha256(path) for path in archived_files(directory)
    }
    (directory / MANIFEST_FILENAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def read_manifest(directory: Path) -> dict[str, str]:
    """The manifest as written. A missing one is a verification failure, not an empty dict."""
    path = directory / MANIFEST_FILENAME
    if not path.exists():
        raise ArchiveVerificationFailed(f"{directory}: no {MANIFEST_FILENAME}")
    return json.loads(path.read_text(encoding="utf-8"))


def verify(directory: Path, manifest: Mapping[str, str] | None = None) -> dict[str, str]:
    """Every file the manifest names exists and re-hashes to the digest it recorded.

    Both directions: a named file that is gone or has changed fails, and a file in the archive
    the manifest never named fails too — an archive is only evidence if it is the whole of what
    was copied.
    """
    recorded = dict(read_manifest(directory) if manifest is None else manifest)
    present = {str(path.relative_to(directory)) for path in archived_files(directory)}
    missing = sorted(set(recorded) - present)
    if missing:
        raise ArchiveVerificationFailed(f"{directory}: manifest names missing files {missing}")
    unlisted = sorted(present - set(recorded))
    if unlisted:
        raise ArchiveVerificationFailed(f"{directory}: unmanifested files {unlisted}")
    changed = sorted(
        name for name, digest in recorded.items() if sha256(directory / name) != digest
    )
    if changed:
        raise ArchiveVerificationFailed(f"{directory}: digests do not re-compute for {changed}")
    return recorded


def archives(root: Path) -> list[Path]:
    """Every archived run under this brain root, oldest first. Nothing here deletes one."""
    directory = BrainPaths(root=root).archive
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.iterdir() if path.is_dir())
