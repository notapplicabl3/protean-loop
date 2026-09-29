"""The loop: each tick either asks the director or runs one runnable unit; only the grader passes one.

A pass is two writes: the unit is saved `passed` with its candidate commit, then `task/<task>` moves to
that commit and the unit is saved integrated. A tick or resume first finishes any pass cut between them.
"""

from __future__ import annotations

import fcntl
import os
import shutil
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from protean import budget, grade, mailbox, director, state, worker
from protean.budget import Caps
from protean.runner import Charge, Runner, floor_reason
from protean.state import Root, Task, Unit

Echo = Callable[[str], None]
NOTE_LIMIT = 200


def _silent(_: str) -> None:
    pass


def _ask(root: Root, task: Task, question: str, **extra: Any) -> str:
    """Park the task on a question for the operator; `extra` is logged with it."""
    task.question, task.terminal = question, "interrupted"
    path = mailbox.ask(root, task, question)
    state.append_log(root, task.id, {"event": "question", "question": question, "path": str(path), **extra})
    return f"asked the operator: {' '.join(question.split())[:160]}"


def _open_descope(root: Root, task_id: str) -> dict[str, Any] | None:
    """The descope the open question proposes, or None when it is an ordinary question."""
    asked = [event for event in director.read_log(root, task_id) if event.get("event") == "question"]
    return asked[-1] if asked and asked[-1].get("descope") else None


def _is_yes(text: str) -> bool:
    """The answer's first word is `yes`, in any case, trailing punctuation aside."""
    words = text.split()
    return bool(words) and words[0].rstrip(".,;:!").lower() == "yes"


def _answered(root: Root, task: Task, text: str) -> str:
    """Act on the operator's answer and return the note the director gets: a descope applies only on `yes`."""
    descope = _open_descope(root, task.id)
    if descope is None:
        return f"The operator answered your question ({task.question}): {text}"
    ids = ", ".join(descope["descope"])
    if not _is_yes(text):
        return f"The operator did not accept your descope of {ids}: {text}"
    for unit in task.units:
        if unit.id in descope["descope"]:
            unit.status, unit.summary = "descoped", f"descoped: {descope.get('reason', '')}"
    return f"The operator accepted your descope of {ids}."


def _refusals(root: Root, task_id: str) -> int:
    """Refused `done` replies since the operator last answered."""
    count = 0
    for event in director.read_log(root, task_id):
        if event.get("event") == "answer":
            count = 0
        elif event.get("event") == "done_refused":
            count += 1
    return count


def _charger(task: Task, root: Root, seat: str) -> Charge:
    """Book an interrupted call's spend on the task and save it first, so no dollar is lost to a Ctrl-C."""
    def charge(usd: float) -> None:
        task.cost_usd += usd
        state.save(root, task)
        state.append_log(root, task.id, {"event": "interrupted", "seat": seat, "charged_usd": usd})
    return charge


def _director_step(task: Task, caps: Caps, root: Root, runner: Runner) -> str:
    reply = director.plan(task, caps, root, runner, _charger(task, root, "director"))
    task.cost_usd += reply.cost_usd
    task.director_session = reply.session_id or task.director_session
    state.save(root, task)
    state.append_log(root, task.id, {"event": "director", "reply": reply.kind, "cost_usd": reply.cost_usd,
                                     "session_id": reply.session_id, "raw": reply.raw[-2000:]})
    return f"director {_apply(reply, task, caps, root)} (${reply.cost_usd:.2f})"


def _apply(reply: director.Reply, task: Task, caps: Caps, root: Root) -> str:
    """Act on one decoded reply; a unit it adds starts pending, and `done` is checked, not believed."""
    if reply.stop:
        task.terminal, task.stop_reason = "stopped", reply.stop
        note = "Your previous answer was rejected: " + "; ".join(reply.errors)
        state.append_log(root, task.id, {"event": "stopped", "reason": reply.stop, "to_director": note})
        return f"answer rejected, no retry: {reply.stop}"
    if reply.question is not None:
        return _ask(root, task, reply.question)
    if reply.descope:
        reason = reply.reason.strip().rstrip(".") or "no reason given"
        question = (f"The director wants to descope {', '.join(reply.descope)}: {reason}. "
                    "Answer `yes` to accept, anything else is sent back to the director.")
        return _ask(root, task, question, descope=reply.descope, reason=reply.reason)
    if reply.done:
        if state.all_verified(task):
            task.terminal = "done"
            return "said done: every unit verified"
        open_ids = [u.id for u in task.units if u.status not in ("passed", "descoped")]
        note = f"not all units verified: {', '.join(open_ids) or 'no unit has passed'}"
        state.append_log(root, task.id, {"event": "done_refused", "unverified": open_ids, "to_director": note})
        refused = _refusals(root, task.id)
        if refused > caps.max_replans:
            question = (f"The director said done {refused} times while units were unverified "
                        f"({', '.join(open_ids) or 'none passed'}). Descope them, redirect, or abandon?")
            return f"said done, refused; {_ask(root, task, question)}"
        return f"said done, refused: {note}"
    task.units.extend(reply.units)
    return f"added {', '.join(u.id for u in reply.units)}"


def _rechecks(task: Task, clone: Path) -> dict[str, str]:
    """Every integrated unit's re-checkable predicates graded again in this clone: `<unit> <pid>` -> note
    for each one that no longer holds."""
    broke = {}
    for other in task.units:
        if other.integrated:
            verdict = grade.grade(other, clone, None, grade.RECHECKABLE)
            for pid in verdict.failed_ids + verdict.ungradeable_ids:
                broke[f"{other.id} {pid}"] = verdict.notes[pid]
    return broke


def _integrate(task: Task, unit: Unit, root: Root) -> bool:
    """The second write of a pass: move `task/<task>` from the accepted tip to the unit's candidate, then
    record it. `update-ref` checks the old value; a ref already at the candidate is only recorded. A ref
    moved anywhere else outside the loop parks the task on a question (once) and returns False."""
    workspace, ref = Path(task.workspace), worker.accepted_ref(task)
    try:
        found = worker.git(["rev-parse", "--verify", "--quiet", ref], workspace).strip()
    except worker.WorkerError:
        found = "missing"
    if found not in (unit.candidate, task.accepted):
        if task.terminal != "interrupted":
            question = (f"task/{task.id} was moved outside the loop: it should be at {task.accepted} "
                        f"(the accepted tip before {unit.id}) but is {found[:12]}. Reset it with "
                        f"`git update-ref {ref} {task.accepted}` in {task.workspace}, then `protean resume` "
                        "continues the task; `protean resume --abandon` closes it.")
            _ask(root, task, question, stale_tip=unit.id)
            state.save(root, task)
        return False
    if found != unit.candidate:
        worker.git(["update-ref", ref, str(unit.candidate), str(task.accepted)], workspace)
    task.accepted, unit.integrated = unit.candidate, True
    state.save(root, task)
    state.append_log(root, task.id, {"event": "integrated", "unit": unit.id, "accepted": unit.candidate})
    return True


def _repair(task: Task, root: Root) -> bool:
    """Finish every pass a kill cut between its two writes; the unit's worker never runs again.
    False when a tip moved outside the loop leaves a pass unfinished."""
    for unit in task.units:
        if unit.status == "passed" and unit.candidate and not unit.integrated and not _integrate(task, unit, root):
            return False
    return True


def _stale_tip_asked(root: Root, task_id: str) -> bool:
    """The open question is the runtime's own, about a tip moved outside the loop."""
    asked = [event for event in director.read_log(root, task_id) if event.get("event") == "question"]
    return bool(asked) and "stale_tip" in asked[-1]


_BLOCKED_BY = {"failed": "failed", "descoped": "was descoped", "blocked": "is blocked"}


def _block(task: Task, root: Root) -> None:
    """Block every pending unit whose need failed, was descoped or is blocked, and tell the director."""
    for unit, need in state.block_dependents(task):
        note = (f"{unit.id} is blocked: it needs {need.id}, which {_BLOCKED_BY[need.status]}. "
                f"Descope {unit.id}; plan a new unit if its work is still wanted.")
        state.append_log(root, task.id, {"event": "blocked", "unit": unit.id, "need": need.id, "to_director": note})


def _worker_step(task: Task, unit: Unit, caps: Caps, root: Root, runner: Runner) -> str:
    unit.attempts += 1
    res = worker.run_unit(task, unit, caps, root, runner, _charger(task, root, "worker"))
    task.cost_usd += res.cost_usd
    state.save(root, task)
    if res.delivered:
        verdict = grade.grade(unit, res.clone, res.exit_code)
        broke = _rechecks(task, res.clone) if verdict.passed else {}
        tampered = worker.clone_changes(res.clone, res.candidate)
        if tampered:
            verdict, broke = grade.ungradeable(unit, tampered), {}
    else:
        verdict, broke = grade.ungradeable(unit, res.delivery_note), {}
    passed = verdict.passed and not broke
    if passed:
        unit.status, unit.candidate = "passed", res.candidate
    elif unit.attempts >= caps.max_attempts_per_unit:
        unit.status = "failed"
    misses = [f"{pid} {verdict.notes[pid]}"[:NOTE_LIMIT] for pid in verdict.failed_ids + verdict.ungradeable_ids]
    misses += [f"broke {key}: {note}"[:NOTE_LIMIT] for key, note in broke.items()]
    grade_line = "passed" if passed else "; ".join(misses)
    unit.branch, unit.summary = res.branch, f"{res.summary} [grade: {grade_line}]"
    shutil.rmtree(res.clone, ignore_errors=True)
    event = {
        "event": "verdict", "unit": unit.id, "attempt": unit.attempts, "status": unit.status,
        "passed": passed, "passed_ids": verdict.passed_ids, "failed_ids": verdict.failed_ids,
        "ungradeable_ids": verdict.ungradeable_ids, "notes": verdict.notes, "exit_code": res.exit_code,
        "cost_usd": res.cost_usd, "branch": res.branch, "changed": res.changed, "delivered": res.delivered,
    }
    if broke:
        event["broke"] = broke
        event["to_director"] = (f"{unit.id} broke accepted work and was not accepted (attempt {unit.attempts}): "
                                + "; ".join(misses))
    state.append_log(root, task.id, event)
    state.save(root, task)
    if passed:
        _integrate(task, unit, root)
    parts = [f"{label} {' '.join(ids)}" for label, ids in
             (("failed", verdict.failed_ids), ("ungradeable", verdict.ungradeable_ids), ("broke", list(broke))) if ids]
    detail = f" ({'; '.join(parts)})" if parts else ""
    return f"{unit.id} attempt {unit.attempts}: {unit.status}{detail} (${res.cost_usd:.2f})"


def ceiling(task: Task, caps: Caps) -> str | None:
    """The ceiling the task has reached, or the call floor it is under; None while a call may be made."""
    return budget.stop_reason(task, caps) or floor_reason(task, caps)


def run_tick(task: Task, caps: Caps, root: Root, runner: Runner, echo: Echo = _silent) -> Task:
    """One tick: finish a cut pass, block units whose needs died, stop at a ceiling or the call floor, else
    ask the director (no runnable unit) or work one unit."""
    _repair(task, root)
    if task.terminal is not None:
        return task
    _block(task, root)
    reason = ceiling(task, caps)
    if reason:
        task.terminal, task.stop_reason = "stopped", reason
        state.append_log(root, task.id, {"event": "stopped", "reason": reason})
        state.save(root, task)
        return task
    unit = state.pending_unit(task)
    line = _director_step(task, caps, root, runner) if unit is None else _worker_step(task, unit, caps, root, runner)
    _block(task, root)
    task.tick += 1
    state.save(root, task)
    echo(f"tick {task.tick}: {line}")
    return task


def terminal_line(root: Root, task: Task) -> str:
    """One line naming where the task ended."""
    if task.terminal == "interrupted":
        return f"terminal: interrupted — question at {mailbox.open_path(root, task.id)}"
    if task.terminal == "stopped":
        return f"terminal: stopped — {task.stop_reason}"
    passed = sum(u.status == "passed" for u in task.units)
    return f"terminal: {task.terminal} — {passed} unit(s) verified, ${task.cost_usd:.2f}, {task.tick} ticks"


def _drive(task: Task, caps: Caps, root: Root, runner: Runner, echo: Echo) -> Task:
    while task.terminal is None:
        task = run_tick(task, caps, root, runner, echo)
    echo(terminal_line(root, task))
    return task


@contextmanager
def _task_lock(root: Root, task_id: str) -> Iterator[None]:
    """Hold `state/<task>/lock` while this process drives the task; a second process is refused."""
    path = root.state_dir(task_id) / "lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.seek(0)
            holder = handle.read().strip() or "unknown"
            raise RuntimeError(f"task {task_id} is already running (pid {holder})") from None
        handle.truncate(0)
        handle.write(f"{os.getpid()}\n")
        handle.flush()
        yield


def run(goal: str, workspace: str | Path, root: Root, caps: Caps, runner: Runner,
        project: str = "_root", echo: Echo = _silent) -> Task:
    """Start a task on `workspace` and run it to a terminal state."""
    if not Path(workspace).is_dir():
        raise ValueError(f"workspace {workspace} is not a directory")
    worker.git(["rev-parse", "--git-dir"], Path(workspace))
    existing = state.current(root)
    if existing is not None and existing.terminal in (None, "interrupted"):
        raise ValueError(f"task {existing.id} is still open ({existing.terminal or 'running'}); "
                         "resume or abandon it first")
    now = datetime.now(timezone.utc)
    task = Task(id=state.new_task_id(now), goal=goal, workspace=str(Path(workspace).resolve()),
                project=project, created=now.isoformat(timespec="seconds"))
    if root.task_file(task.id).exists():
        raise ValueError(f"task {task.id} already exists; start again in a second")
    with _task_lock(root, task.id):
        state.save(root, task)
        state.set_current(root, task.id)
        state.append_log(root, task.id, {"event": "start", "goal": goal, "workspace": task.workspace})
        echo(f"task {task.id}: {goal}")
        return _drive(task, caps, root, runner, echo)


def resume(root: Root, caps: Caps, runner: Runner, extend_usd: float = 0.0, extend_ticks: int = 0,
           abandon: bool = False, echo: Echo = _silent) -> Task:
    """Continue the current task: after the operator's answer, after an `--extend`, or abandon it."""
    task = state.current(root)
    if task is None:
        raise ValueError(f"no task in {root.path}")
    with _task_lock(root, task.id):
        return _resume(state.load(root, task.id), root, caps, runner, extend_usd, extend_ticks, abandon, echo)


def _resume(task: Task, root: Root, caps: Caps, runner: Runner, extend_usd: float, extend_ticks: int,
            abandon: bool, echo: Echo) -> Task:
    if task.terminal == "done" or task.stop_reason == "abandoned":
        echo(terminal_line(root, task))
        return task
    if abandon:
        mailbox.close(root, task.id, "abandoned")
        shutil.rmtree(root.clones_dir(task.id), ignore_errors=True)
        task.terminal, task.stop_reason, task.question = "stopped", "abandoned", None
        state.append_log(root, task.id, {"event": "abandoned"})
        state.save(root, task)
        echo(terminal_line(root, task))
        return task
    if not _repair(task, root):
        echo(terminal_line(root, task))
        return task
    if task.terminal == "interrupted" and _stale_tip_asked(root, task.id):
        mailbox.close(root, task.id, "repaired")
        state.append_log(root, task.id, {"event": "repaired", "question": task.question})
        task.terminal, task.question = None, None
        state.save(root, task)
    extend = bool(extend_usd or extend_ticks)
    if task.terminal == "stopped":
        reason = ceiling(replace(task, extra_usd=task.extra_usd + extend_usd,
                                 extra_ticks=task.extra_ticks + extend_ticks), caps)
        if not extend or reason:
            echo(f"still stopped ({reason or task.stop_reason}); "
                 + ("this --extend was not saved; " if extend else "") + "widen it with --extend")
            return task
    if extend:
        task.extra_usd += extend_usd
        task.extra_ticks += extend_ticks
        state.append_log(root, task.id, {"event": "extend", "usd": extend_usd, "ticks": extend_ticks})
        state.save(root, task)
    if task.terminal == "interrupted":
        text = mailbox.answer(root, task.id)
        if text is None:
            echo(f"no answer yet: write it under ## Answer in {mailbox.open_path(root, task.id)}")
            return task
        note = _answered(root, task, text)
        mailbox.close(root, task.id, "answered")
        state.append_log(root, task.id, {"event": "answer", "question": task.question, "text": text,
                                         "to_director": note})
        task.terminal, task.question = None, None
    elif task.terminal == "stopped":
        task.terminal, task.stop_reason = None, ""
    state.save(root, task)
    return _drive(task, caps, root, runner, echo)
