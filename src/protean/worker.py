"""One contained editor call per unit, in a fresh clone with no remote, on branch `unit/<task>/<unit>`.

The branch starts at the tip of `task/<task>`, the work accepted so far, and is fetched back into the
workspace; nothing is ever merged or pushed. Only a clone left clean on its branch, fetched, and
still extending that tip counts as delivered.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from protean import budget, grade
from protean.budget import Caps
from protean.runner import Charge, Runner, RunResult, charged_cap, no_charge, usd_cap
from protean.state import Root, Task, Unit

MODEL = "claude-opus-5"
TOOLS = (
    "Read", "Edit", "Write", "Grep", "Glob", "Bash(uv:*)", "Bash(git status:*)", "Bash(git diff:*)",
    "Bash(git add:*)", "Bash(git commit:*)", "Bash(git checkout:*)", "Bash(git branch:*)",
)
BUILD_OUTPUT = (".venv/", "__pycache__/", "*.pyc", ".pytest_cache/", ".ruff_cache/", ".mypy_cache/",
                "node_modules/", ".DS_Store")
EXIT_LINE = re.compile(r"`?exit_code:\s*(-?\d+)`?")
SUMMARY_LIMIT = 500


class WorkerError(RuntimeError):
    """The clone could not be prepared; no model call was made."""


@dataclass
class WorkerResult:
    """What one unit's call produced. `exit_code` is None unless the worker reported one itself;
    `delivered` is false, with the reason in `delivery_note`, when the workspace did not receive
    exactly what the clone holds. `candidate` is the branch's commit when it extends the accepted tip."""

    exit_code: int | None
    cost_usd: float
    summary: str
    clone: Path
    branch: str
    changed: list[str]
    delivered: bool
    delivery_note: str
    candidate: str = ""


def git(args: list[str], cwd: Path) -> str:
    """Run one git command; a failure raises `WorkerError` with git's own message."""
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise WorkerError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


def accepted_ref(task: Task) -> str:
    """The workspace ref that holds the task's accepted work."""
    return f"refs/heads/task/{task.id}"


def accepted_tip(task: Task) -> str:
    """The commit `task/<task>` points at. The first unit starts the branch at the workspace HEAD; a
    branch a crash left behind before the task was saved is taken as it stands."""
    if task.accepted is None:
        workspace, ref = Path(task.workspace), accepted_ref(task)
        try:
            task.accepted = git(["rev-parse", "--verify", "--quiet", ref], workspace).strip()
        except WorkerError:
            task.accepted = git(["rev-parse", "HEAD"], workspace).strip()
            git(["update-ref", ref, task.accepted, ""], workspace)
    return task.accepted


def argv(task: Task, caps: Caps, root: Root) -> list[str]:
    """The editor call: no user settings, the positive tool grant, the clipped per-call dollar cap, the prompt."""
    return [
        "claude", "-p", "--setting-sources", "", "--output-format", "json",
        "--max-budget-usd", usd_cap(caps.worker_call_usd, task, caps),
        "--model", MODEL, "--permission-mode", "dontAsk", "--allowedTools", *TOOLS,
        "--system-prompt", root.editor_prompt.read_text(encoding="utf-8"),
    ]


def message(unit: Unit) -> str:
    """The editor's user message: the intent and the predicates the grader will check."""
    lines = [f"Unit {unit.id}: {unit.intent}", "", "When you finish, a grader checks these in this directory:"]
    for pid, p in zip(grade.predicate_ids(unit), unit.predicates):
        lines.append(f"- {pid} {p.kind} {json.dumps(p.args)}")
    return "\n".join(lines) + "\n"


def reported_exit(text: str) -> int | None:
    """N when the text's last non-empty line is `exit_code: N`."""
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    match = EXIT_LINE.fullmatch(lines[-1]) if lines else None
    return int(match.group(1)) if match else None


def _outcome(res: RunResult, timeout: int, cap: float) -> tuple[int | None, float, str]:
    """Exit code, dollars and summary from one run. Only the worker's own `exit_code: N` line is
    evidence of an exit code; the CLI's return code never stands in for it. A run that left no
    receipt costs `cap`, the dollar cap it was given."""
    if res.timed_out:
        return None, cap, f"timed out after {timeout}s"
    try:
        receipt = json.loads(res.stdout)
    except json.JSONDecodeError:
        receipt = None
    if not isinstance(receipt, dict):
        return None, cap, f"no receipt (exit {res.returncode}): {res.stderr.strip()[-300:]}"
    cost = budget.cost_of(receipt)
    if receipt.get("is_error"):
        return None, cost, f"ended in error: {receipt.get('subtype', '')} {receipt.get('errors', '')}".strip()
    text = receipt.get("result") if isinstance(receipt.get("result"), str) else ""
    return reported_exit(text), cost, " ".join(text.split())[-SUMMARY_LIMIT:]


def _undelivered(clone: Path, branch: str) -> list[str]:
    """Why the clone's working tree is not the branch it hands back: uncommitted files, another branch."""
    try:
        dirty = [line[3:] for line in git(["status", "--porcelain"], clone).splitlines() if line.strip()]
        current = git(["branch", "--show-current"], clone).strip()
    except WorkerError as exc:
        return [f"the clone's state could not be read: {exc}"]
    problems = [f"uncommitted changes in the clone: {', '.join(dirty)}"] if dirty else []
    if current != branch:
        problems.append(f"clone is on {f'branch {current}' if current else 'a detached HEAD'}, not {branch}")
    return problems


def clone_changes(clone: Path, candidate: str) -> str:
    """Why the clone no longer holds exactly the candidate once the check commands have run; "" when it does.
    A moved HEAD or a file left behind would let a later check read something other than what is accepted."""
    try:
        head = git(["rev-parse", "HEAD"], clone).strip()
        dirty = git(["status", "--porcelain"], clone).strip()
    except WorkerError as exc:
        return f"check commands changed the clone: {exc}"
    problems = (["check commands changed the clone: HEAD moved"] if head != candidate else [])
    return "; ".join(problems + (["check commands left the clone dirty"] if dirty else []))


def run_unit(task: Task, unit: Unit, caps: Caps, root: Root, runner: Runner, charge: Charge = no_charge) -> WorkerResult:
    """Clone, branch from the accepted tip, drop the remote, exclude build output, run the editor, check
    delivery, fetch the branch into the workspace, list what changed. A branch with no change on it
    delivered nothing; one that no longer contains the accepted tip rewrote history.
    A call interrupted before it returns is charged its cap through `charge` before propagating."""
    workspace, branch = Path(task.workspace), f"unit/{task.id}/{unit.id}"
    base = accepted_tip(task)
    clone = root.clones_dir(task.id).resolve() / unit.id
    if clone.exists():
        shutil.rmtree(clone)
    clone.parent.mkdir(parents=True, exist_ok=True)
    git(["clone", "--quiet", "--local", "--no-hardlinks", str(workspace), str(clone)], clone.parent)
    git(["checkout", "--quiet", "-B", branch, base], clone)
    git(["remote", "remove", "origin"], clone)
    exclude = clone / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("\n".join(BUILD_OUTPUT) + "\n", encoding="utf-8")
    call = argv(task, caps, root)
    try:
        res = runner(call, message(unit), clone, caps.worker_wall_seconds)
    except BaseException:
        charge(charged_cap(call))
        raise
    exit_code, cost, summary = _outcome(res, caps.worker_wall_seconds, charged_cap(call))
    try:
        problems = _undelivered(clone, branch)
        try:
            git(["fetch", "--quiet", str(clone), f"+{branch}:{branch}"], workspace)
        except WorkerError as exc:
            problems.append(f"fetch into the workspace failed: {exc}")
        try:
            changed = git(["diff", "--name-only", f"{base}..{branch}"], clone).splitlines()
        except WorkerError:
            changed = []
        try:
            candidate = git(["rev-parse", "--verify", branch], clone).strip()
            git(["merge-base", "--is-ancestor", base, candidate], clone)
        except WorkerError:
            candidate = ""
            problems.append(f"the branch does not extend the accepted tip {base[:12]}: history was rewritten")
    except BaseException:
        charge(cost)
        raise
    if not problems and not changed:
        problems.append("no change on the branch: nothing was delivered")
    return WorkerResult(exit_code, cost, summary, clone, branch, changed, not problems, "; ".join(problems), candidate)
