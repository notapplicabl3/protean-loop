"""The grader: predicate vocabulary, validation before execution, and the verdict.

Only a grade can mark a unit passed. A predicate whose evidence is missing is ungradeable, and an
ungradeable predicate blocks a pass exactly as a failed one does.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from protean.state import Predicate, Unit

PREDICATE_KINDS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "file_exists": (frozenset({"path"}), frozenset()),
    "file_contains": (frozenset({"path", "text"}), frozenset()),
    "exit_code": (frozenset({"code"}), frozenset()),
    "command": (frozenset({"cmd"}), frozenset({"expect_exit"})),
}
INT_ARGS = frozenset({"code", "expect_exit"})
FILE_BOUND = 262_144
COMMAND_TIMEOUT = 120
KILL_DRAIN_SECONDS = 5
OUTPUT_TAIL = 400
SHIM_DIR = Path(__file__).resolve().parent / "shim"
SHIM_MESSAGE = "protean: model calls are not allowed from a command predicate"
SANDBOX = "sandbox-exec"
# Where a check command may write besides the clone: tool caches and temp dirs, never the home tree.
SANDBOX_WRITABLE = ("/private/tmp", "/private/var/folders", "/dev")


def _problems(predicate: Predicate) -> list[str]:
    """What is wrong with one predicate's kind and arguments; empty when it is well formed."""
    if not isinstance(predicate.kind, str) or predicate.kind not in PREDICATE_KINDS:
        return [f"unknown kind {predicate.kind!r} (known: {', '.join(PREDICATE_KINDS)})"]
    if not isinstance(predicate.args, dict):
        return ["args must be an object"]
    required, optional = PREDICATE_KINDS[predicate.kind]
    problems = [f"missing required arg {name!r}" for name in sorted(required - predicate.args.keys())]
    for name in sorted(predicate.args):
        value = predicate.args[name]
        if name not in required | optional:
            problems.append(f"unknown arg {name!r}")
        elif name in INT_ARGS:
            if not isinstance(value, int) or isinstance(value, bool):
                problems.append(f"arg {name!r} must be an integer")
        elif not isinstance(value, str) or not value.strip():
            problems.append(f"arg {name!r} must be a non-empty string")
    return problems


def predicate_ids(unit: Unit) -> list[str]:
    """Positional ids for a unit's predicates: p1, p2, ..."""
    return [f"p{index}" for index in range(1, len(unit.predicates) + 1)]


def validate(predicates: list[Predicate]) -> list[str]:
    """One message per problem across a unit's predicates; an empty list means valid."""
    if not predicates:
        return ["a unit needs at least one predicate"]
    messages = []
    for index, predicate in enumerate(predicates, start=1):
        messages += [f"p{index} {predicate.kind}: {problem}" for problem in _problems(predicate)]
    return messages


@dataclass
class Verdict:
    """The grade of one unit. `passed` is true only with no failed and no ungradeable predicate."""

    passed_ids: list[str] = field(default_factory=list)
    failed_ids: list[str] = field(default_factory=list)
    ungradeable_ids: list[str] = field(default_factory=list)
    passed: bool = False
    notes: dict[str, str] = field(default_factory=dict)


def _git(clone: Path, *args: str) -> tuple[bytes | None, str]:
    """One git command in the clone: its stdout, or None with git's own message."""
    try:
        proc = subprocess.run(["git", *args], cwd=clone, capture_output=True)
    except OSError as exc:
        return None, str(exc)
    if proc.returncode != 0:
        return None, proc.stderr.decode("utf-8", "replace").strip()[-200:]
    return proc.stdout, ""


def _branch_entry(clone: Path, rel: str) -> tuple[str | None, str]:
    """What `rel` is on the checked-out commit: file, symlink, directory, submodule or missing.

    File predicates grade the branch's tree objects, never the working tree, so nothing a worker or
    a check command left uncommitted, ignored, inside `.git` or inside a nested repository can count.
    None with the reason when the path cannot be looked up (it escapes the clone, or there is no repo).
    """
    if any(part.lower() == ".git" for part in Path(rel).parts):
        return None, f"path is inside .git, not on the branch: {rel}"
    out, err = _git(clone, "ls-tree", "-z", "HEAD", "--", rel)
    if out is None:
        return None, f"cannot read the branch for {rel}: {err}"
    entries = [entry for entry in out.split(b"\0") if entry]
    if not entries:
        ignored, _ = _git(clone, "check-ignore", "-q", "--", rel)
        if ignored is not None:
            return None, f"path is gitignored, not on the branch: {rel}"
        return "missing", ""
    if len(entries) > 1:
        return "directory", ""
    mode, kind = entries[0].split(b"\t", 1)[0].split(b" ")[:2]
    if kind == b"tree":
        return "directory", ""
    if kind == b"commit":
        return "submodule", ""
    return ("symlink" if mode == b"120000" else "file"), ""


def _file_exists(clone: Path, args: dict) -> tuple[bool | None, str]:
    entry, why_not = _branch_entry(clone, args["path"])
    if entry is None:
        return None, why_not
    if entry == "symlink":
        return None, f"symlink on the branch, not a regular file: {args['path']}"
    if entry == "file":
        return True, f"exists on the branch: {args['path']}"
    return False, (f"missing: {args['path']}" if entry == "missing" else f"not a regular file: {args['path']}")


def _file_contains(clone: Path, args: dict) -> tuple[bool | None, str]:
    entry, why_not = _branch_entry(clone, args["path"])
    if entry is None:
        return None, why_not
    if entry == "symlink":
        return None, f"symlink on the branch, not a regular file: {args['path']}"
    if entry != "file":
        return None, f"no regular file at {args['path']}"
    size, err = _git(clone, "cat-file", "-s", f"HEAD:{args['path']}")
    if size is None or int(size) > FILE_BOUND:
        return None, f"{args['path']} is over the {FILE_BOUND}-byte bound" if size else f"unreadable {args['path']}: {err}"
    raw, err = _git(clone, "cat-file", "-p", f"HEAD:{args['path']}")
    if raw is None:
        return None, f"unreadable {args['path']}: {err}"
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, f"unreadable {args['path']}: {exc}"
    if args["text"] in content:
        return True, f"{args['path']} contains the text"
    return False, f"{args['path']} does not contain {args['text']!r}"


def _exit_code(exit_code: int | None, args: dict) -> tuple[bool | None, str]:
    if exit_code is None:
        return None, "no exit code was reported"
    return exit_code == args["code"], f"exit {exit_code}, expected {args['code']}"


def _command_env() -> dict[str, str]:
    """The inherited environment without `ANTHROPIC_*` or `CLAUDE_*` variables, the refusing shim first on PATH."""
    env = {name: value for name, value in os.environ.items() if not name.startswith(("ANTHROPIC_", "CLAUDE_"))}
    env["PATH"] = f"{SHIM_DIR}{os.pathsep}{os.environ.get('PATH', '')}"
    return env


def _kill_group(proc: subprocess.Popen) -> None:
    """SIGKILL the command's whole process group."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass


def _quoted(path: str) -> str:
    """A path as a sandbox-profile string literal."""
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _sandbox_profile(clone: Path) -> str:
    """No network at all; writes only inside the clone, the uv caches and the temp dirs."""
    home = Path.home()
    writable = [
        os.path.realpath(clone),
        os.path.realpath(os.environ.get("UV_CACHE_DIR") or home / ".cache" / "uv"),
        os.path.realpath(home / ".local" / "share" / "uv"),
        os.path.realpath(tempfile.gettempdir()),
        *SANDBOX_WRITABLE,
    ]
    allow = " ".join(f"(subpath {_quoted(path)})" for path in dict.fromkeys(writable))
    return f"(version 1)(allow default)(deny network*)(deny file-write*)(allow file-write* {allow})"


def _command(clone: Path, args: dict) -> tuple[bool | None, str]:
    """Run `cmd` in the clone, sandboxed, in its own group; a timeout or any interruption kills the group.

    The sandbox denies every network operation and every write outside the clone, the tool caches and
    the temp dirs, so a check command can neither call a model nor touch the rest of the machine.
    Without the sandbox binary the predicate is ungradeable: a command never runs unconfined.
    """
    expect = args.get("expect_exit", 0)
    sandbox = shutil.which(SANDBOX)
    if sandbox is None:
        return None, f"no sandbox: {SANDBOX} is not on this host, so the command did not run"
    argv = [sandbox, "-p", _sandbox_profile(clone), "/bin/sh", "-c", args["cmd"]]
    try:
        proc = subprocess.Popen(
            argv, cwd=clone, env=_command_env(), start_new_session=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except OSError as exc:
        return None, f"could not start the command: {exc}"
    try:
        out, err = proc.communicate(timeout=COMMAND_TIMEOUT)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        try:
            proc.communicate(timeout=KILL_DRAIN_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        return None, f"timed out after {COMMAND_TIMEOUT}s"
    except BaseException:
        _kill_group(proc)
        try:
            proc.wait(timeout=KILL_DRAIN_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        raise
    if SHIM_MESSAGE in err.decode("utf-8", "replace"):
        return None, f"{SHIM_MESSAGE} (exit {proc.returncode})"
    tail = (out + err).decode("utf-8", "replace").strip()[-OUTPUT_TAIL:]
    return proc.returncode == expect, f"exit {proc.returncode}, expected {expect}: {tail}"


def ungradeable(unit: Unit, note: str) -> Verdict:
    """Every predicate ungradeable for one reason, when there is nothing fit to grade."""
    ids = predicate_ids(unit)
    return Verdict(ungradeable_ids=ids, notes={pid: f"{p.kind}: {note}" for pid, p in zip(ids, unit.predicates)})


def grade(unit: Unit, clone: Path, exit_code: int | None) -> Verdict:
    """Grade every predicate of `unit` against the clone's checked-out branch and the worker's exit code.

    File kinds read the branch's tree objects; `command` runs sandboxed in the working tree.
    """
    verdict = Verdict()
    for pid, predicate in zip(predicate_ids(unit), unit.predicates):
        problems = _problems(predicate)
        if problems:
            result, note = None, "invalid predicate: " + "; ".join(problems)
        elif predicate.kind == "file_exists":
            result, note = _file_exists(clone, predicate.args)
        elif predicate.kind == "file_contains":
            result, note = _file_contains(clone, predicate.args)
        elif predicate.kind == "exit_code":
            result, note = _exit_code(exit_code, predicate.args)
        else:
            result, note = _command(clone, predicate.args)
        if result is None:
            verdict.ungradeable_ids.append(pid)
        elif result:
            verdict.passed_ids.append(pid)
        else:
            verdict.failed_ids.append(pid)
        verdict.notes[pid] = f"{predicate.kind}: {note}"
    verdict.passed = bool(unit.predicates) and not verdict.failed_ids and not verdict.ungradeable_ids
    return verdict
