"""The director seat: one call turns the task view into new units, a question, done, or a descope.

The reply is decoded here and never trusted for status: a unit it adds starts `pending` whatever
the reply says, and only the grader can pass it.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from protean import budget, grade
from protean.budget import Caps
from protean.runner import Charge, Runner, RunResult, charged_cap, floor_reason, no_charge, usd_cap
from protean.state import Predicate, Root, Task, Unit

MODEL = "claude-opus-5"
TOOLS = ("Read", "Grep", "Glob")
REPLY_KEYS = ("units", "question", "done", "descope")
UNIT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


@dataclass
class Reply:
    """One decoded director answer: exactly one of units, question, done or descope is set.

    `stop` is set instead when a retry was due but the task had less left than the call floor;
    `errors` then carries what the rejected answer got wrong.
    """

    units: list[Unit] = field(default_factory=list)
    question: str | None = None
    done: bool = False
    descope: list[str] = field(default_factory=list)
    reason: str = ""
    cost_usd: float = 0.0
    session_id: str | None = None
    raw: str = ""
    stop: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def kind(self) -> str:
        if self.stop:
            return "stopped"
        if self.question is not None:
            return "question"
        return "done" if self.done else "descope" if self.descope else "units"


def read_log(root: Root, task_id: str) -> list[dict[str, Any]]:
    """Every event in the task's log, oldest first; an absent log is empty."""
    try:
        lines = root.log_file(task_id).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    return [json.loads(line) for line in lines if line.strip()]


def pending_notes(root: Root, task_id: str) -> list[str]:
    """The `to_director` texts logged since the last director call: the operator's answer, runtime refusals."""
    notes: list[str] = []
    for event in read_log(root, task_id):
        if event.get("event") in ("director", "manager"):
            notes = []
        elif note := event.get("to_director") or event.get("to_manager"):
            notes.append(note)
    return notes


def view(task: Task, caps: Caps, notes: list[str]) -> dict[str, Any]:
    """What the director is shown each call."""
    return {
        "goal": task.goal,
        "workspace": task.workspace,
        "tick": task.tick,
        "budget_left_usd": round(caps.max_usd + task.extra_usd - task.cost_usd, 2),
        "ticks_left": caps.max_ticks + task.extra_ticks - task.tick,
        "max_attempts_per_unit": caps.max_attempts_per_unit,
        "units": [
            {"id": u.id, "intent": u.intent, "status": u.status, "attempts": u.attempts, "needs": u.needs,
             "summary": u.summary, "predicates": [asdict(p) for p in u.predicates]}
            for u in task.units
        ],
        "notes": notes,
    }


def argv(task: Task, caps: Caps, root: Root, session: str | None, spent: float = 0.0) -> list[str]:
    """The director call: no user settings, read-only tools on the workspace, the prompt on every call,
    resumed when it can be."""
    args = [
        "claude", "-p", "--setting-sources", "", "--output-format", "json",
        "--max-budget-usd", usd_cap(caps.director_call_usd, task, caps, spent),
        "--model", MODEL, "--permission-mode", "dontAsk", "--tools", *TOOLS, "--allowedTools", *TOOLS,
        "--add-dir", task.workspace,
    ]
    if session:
        args += ["--resume", session]
    return args + ["--system-prompt", root.director_prompt.read_text(encoding="utf-8")]


def _closers(text: str, start: int) -> str:
    """The closing brackets the JSON value at `start` still owes when the text ends; "" inside a string."""
    stack: list[str] = []
    in_string = escaped = False
    for char in text[start:]:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "{[":
            stack.append("}" if char == "{" else "]")
        elif char in "}]" and stack and stack[-1] == char:
            stack.pop()
    return "" if in_string else "".join(reversed(stack))


def first_object(text: str) -> tuple[dict | None, str]:
    """The first `{...}` in `text` that decodes as a JSON object, and why the first `{` did not when it did not.

    An object the text cuts off before its closing brackets is completed and read; the director has
    ended a whole plan one `}` short.
    """
    decoder = json.JSONDecoder()
    problem = ""
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text, index)
        except json.JSONDecodeError as exc:
            problem = problem or f"the object at the first {{ did not parse: {exc.msg} at char {exc.pos}"
            closers = _closers(text, index)
            if not closers:
                continue
            try:
                obj, _ = decoder.raw_decode(text + closers, index)
            except json.JSONDecodeError:
                continue
        if isinstance(obj, dict):
            return obj, problem
    return None, problem


def _decode_units(items: object, task: Task) -> tuple[list[Unit], list[str]]:
    if not isinstance(items, list) or not items:
        return [], ["units must be a non-empty list"]
    seen = {u.id for u in task.units}
    units, errors = [], []
    for n, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            errors.append(f"unit {n}: must be an object")
            continue
        uid, intent, preds, needs = item.get("id"), item.get("intent"), item.get("predicates"), item.get("needs", [])
        label = f"unit {uid!r}" if isinstance(uid, str) else f"unit {n}"
        if not isinstance(needs, list) or not all(isinstance(need, str) for need in needs):
            errors.append(f"{label}: needs must be a list of unit ids")
            needs = []
        if not isinstance(uid, str) or not UNIT_ID.fullmatch(uid):
            errors.append(f"{label}: id must match {UNIT_ID.pattern}")
        elif uid in seen:
            errors.append(f"{label}: id is already used")
        if not isinstance(intent, str) or not intent.strip():
            errors.append(f"{label}: intent must be a non-empty string")
        if not isinstance(preds, list) or not all(isinstance(p, dict) and {"kind", "args"} <= p.keys() for p in preds):
            errors.append(f"{label}: predicates must be a list of {{\"kind\", \"args\"}} objects")
            continue
        predicates = [Predicate(p["kind"], p["args"]) for p in preds]
        errors += [f"{label}: {problem}" for problem in grade.validate(predicates)]
        if isinstance(uid, str):
            seen.add(uid)
            units.append(Unit(id=uid, intent=str(intent), predicates=predicates, needs=list(dict.fromkeys(needs))))
    return units, errors + _need_errors(units, task)


def _need_errors(units: list[Unit], task: Task) -> list[str]:
    """A need naming no unit in the task or this plan, a unit needing itself, and needs that form a cycle."""
    graph = {u.id: u.needs for u in task.units + units}
    legacy = {u.id for u in task.units if u.status == "passed" and not u.candidate}
    errors = []
    for unit in units:
        for need in unit.needs:
            if need == unit.id:
                errors.append(f"unit {unit.id!r}: needs itself")
            elif need not in graph:
                errors.append(f"unit {unit.id!r}: needs {need!r}, which is no unit in the task or this plan")
            elif need in legacy:
                errors.append(f"unit {unit.id!r}: needs {need!r}, which passed before the accepted branch existed "
                              "and cannot be built on")
        path = _cycle(unit.id, graph)
        if path:
            errors.append(f"unit {unit.id!r}: needs form a cycle: {' -> '.join(path)}")
    return errors


def _cycle(start: str, graph: dict[str, list[str]]) -> list[str] | None:
    """A path of needs from `start` back to itself, or None; a unit needing itself is reported apart."""
    stack, seen = [[start]], {start}
    while stack:
        path = stack.pop()
        for need in graph.get(path[-1], []):
            if need == start and len(path) > 1:
                return path + [start]
            if need in graph and need not in seen:
                seen.add(need)
                stack.append(path + [need])
    return None


def decode(text: str, task: Task) -> tuple[Reply | None, list[str]]:
    """Decode the reply text against the task; a list of problems when it is not a valid plan."""
    obj, problem = first_object(text)
    if obj is None:
        return None, [problem or "the reply holds no JSON object"]
    present = [key for key in REPLY_KEYS if key in obj]
    if len(present) != 1:
        carried = f"it carried {present or 'none'}" + (f" ({problem})" if problem else "")
        return None, [f"the reply must carry exactly one of {', '.join(REPLY_KEYS)}; {carried}"]
    key, value = present[0], obj[present[0]]
    if key == "units":
        units, errors = _decode_units(value, task)
        return (None, errors) if errors else (Reply(units=units), [])
    if key == "question":
        ok = isinstance(value, str) and value.strip()
        return (Reply(question=value.strip()), []) if ok else (None, ["question must be a non-empty string"])
    if key == "done":
        return (Reply(done=True), []) if value is True else (None, ["done must be true"])
    known = {u.id for u in task.units}
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v in known for v in value):
        return None, [f"descope must be a non-empty list of existing unit ids ({', '.join(sorted(known)) or 'none'})"]
    passed = [u.id for u in task.units if u.id in value and u.status == "passed"]
    if passed:
        return None, [f"{uid} has passed and cannot be descoped" for uid in passed]
    return Reply(descope=list(value), reason=str(obj.get("reason", ""))), []


def _receipt(res: RunResult, timeout: int) -> tuple[dict | None, list[str]]:
    """The call's stdout receipt (None when it left none), and what makes it unusable as a reply."""
    if res.timed_out:
        return None, [f"the call timed out after {timeout}s"]
    try:
        receipt = json.loads(res.stdout)
    except json.JSONDecodeError:
        receipt = None
    if not isinstance(receipt, dict):
        return None, [f"stdout was not one JSON object (exit {res.returncode}): {res.stderr.strip()[-300:]}"]
    if receipt.get("is_error"):
        return receipt, [f"the call ended in error: {receipt.get('subtype', '')} {receipt.get('errors', '')}".strip()]
    if not isinstance(receipt.get("result"), str):
        return receipt, ["the receipt carries no result text"]
    return receipt, []


def plan(task: Task, caps: Caps, root: Root, runner: Runner, charge: Charge = no_charge) -> Reply:
    """Call the director once, retry once with the errors, and park on a question after two failures.

    The retry is skipped, and the reply carries `stop`, when the first call left less than the call floor.
    A call that leaves no receipt is charged the `--max-budget-usd` it carried. A call interrupted
    before it returns is charged the same way through `charge`, before the interruption propagates.
    """
    seat = root.seat_dir(task.id).resolve()
    seat.mkdir(parents=True, exist_ok=True)
    message = json.dumps(view(task, caps, pending_notes(root, task.id)), indent=2)
    session, cost, errors, raw = task.director_session, 0.0, [], ""
    for attempt in range(2):
        stdin = message
        if attempt:
            stop = floor_reason(task, caps, cost)
            if stop:
                return Reply(stop=stop, errors=errors, cost_usd=cost, session_id=session, raw=raw)
            stdin += "\n\nYour previous answer was rejected:\n- " + "\n- ".join(errors)
            stdin += "\nAnswer again with exactly one JSON object."
        call = None
        try:
            call = argv(task, caps, root, session, cost)
            res = runner(call, stdin, seat, caps.director_wall_seconds)
        except BaseException:
            charge(cost + (charged_cap(call) if call else float(usd_cap(caps.director_call_usd, task, caps, cost))))
            raise
        receipt, errors = _receipt(res, caps.director_wall_seconds)
        cost += charged_cap(call) if receipt is None else budget.cost_of(receipt)
        receipt = receipt or {}
        if isinstance(receipt.get("session_id"), str):
            session = receipt["session_id"]
        raw = receipt.get("result") if isinstance(receipt.get("result"), str) else res.stdout[-2000:]
        if not errors:
            reply, errors = decode(raw, task)
            if reply is not None:
                reply.cost_usd, reply.session_id, reply.raw = cost, session, raw
                return reply
    return Reply(
        question=f"The director returned an invalid plan twice: {'; '.join(errors)}",
        cost_usd=cost, session_id=session, raw=raw, errors=errors,
    )
