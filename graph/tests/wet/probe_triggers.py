"""B69: A.2.i's own live receipt — one planned `think` and one `reader` delegate, once.

`the build specification (not in this mirror)` § Deliverable 7's second paragraph ("The one live receipt, and
it is the operator's"), § Named assumptions 1, 8 and 9, § Resolutions E20, § DoD rows **B69** and **G14**.
Order W6 of `the work orders (not in this mirror)` lands it and **runs it never**.

**The operator runs this, and no builder does** (row B69, behind their go at **B42**). Every machine row of
A.2.i closes on the dry oracle — `tests/cortex/fake_cli.py` as the stand-in binary, fixture roots
turning a trigger key on, the recording shim first on `PATH` with a zero-byte log — so the four
facts below are the only ones the build cannot reach, and they are the only reason to spend. Until
The operator runs it there is **no capture on disk**, and row G14 asserts exactly that: the script exists,
is not collected, refuses without `--force` naming B69 and B42, has not run, and — parsed with
`ast`, never imported — makes exactly one call addressed `think` and one through the desk's
delegate arm.

**It is a script, not a test**, the same shape as `tests/wet/probe_library.py`: a `live`-marked
pytest module re-spends on every collection, and this file's name matches no `python_files`
pattern, so `pytest` does not collect it at all.

**What it spends.** Two calls on one tick's node-call desk, each on its block **as it ships** —
model, effort, grant and caps are the seed's, never probe values:

1. **One planned `think`** for `homeostasis`, through the tool-less `calls.think` block. The plan
   is the runtime's own — `triggers.plan()` over the node's projected input, its weights and its
   own `NODE.md` — and the probe refuses to spend unless that plan is exactly one `think`. The live
   seat's decode retry can make it `1 + decode_retries` processes (§ Named assumptions 9).
2. **One `reader` delegate** through the same desk's delegate arm, which opens one spawn on the
   tick's landed `SpawnDesk` under the shipping `kinds.delegate.reader` block, granted a throwaway
   clone of the default workload and nothing else.

**Why the root is a throwaway.** The probe copies the tracked seeds — the node folders, `seats/`
and `seats.yaml` byte for byte — into a temp directory, keeps the **real** binary and the real
`runtime:` block, and changes exactly one line: homeostasis's shipping `think_threshold: null`
becomes `PROBE_ON_VALUE`. That value lives and dies with the throwaway root; the shipping seed stays
off, and B63's go condition — the node and its on-value named as the operator's own seed edit on the root a
run uses — is untouched. The tracked `brain/` is read and never written.

**How the desk is reached** (§ Deliverable 1, the live attachment). The layer is
`build_live_layer()` over the throwaway root, so `node_calls` is the `CallDesks` the live layer
attaches over the same `SpawnDesks` it attaches as `spawns`, with an empty static plan and the
seed's per-tick delegate bound. The tick's spawn desk is resolved first, handed the clone as its
workspace, and the tick's node-call desk second — the order and the accessors `runtime/cycle.py`
uses — so the delegate arm meets a desk that already carries the one workspace a spawn may reach.

**Four things are measured, and all four are facts row B69 names** — each read off `SeatCallFacts`,
the desk's own records or disk by this process, never off a model's narrative:

1. **A live think answers as a valid `ThinkResult`** — the desk decodes it on the one
   `decode_seat_result()` path, and a refusal is recorded under its class.
2. **Under the tool-less `calls.think` block, with the node's `NODE.md` as its first prompt half.**
   The recorded `--system-prompt` value off the argv as run is compared with the throwaway root's
   `nodes/homeostasis/NODE.md` and `seats/calls/think.md`, and the `--tools` value off that argv
   is recorded beside the block's own.
3. **A live `reader` delegate spawns and returns a `DelegateReturn`**, its facts keyed on the spawn
   desk by the calling node's own `(node, call#)` with no `member#`.
4. **It is witnessed: its four audit lists** — `wrote`, `wrote_outside_workspace`,
   `left_the_clone` and `exec_attempted` — read off the spawn's own receipt, beside the envelope's
   `permission_denials` and the README heading this process reads off the clone itself, so the
   delegate's answer can be checked against the file rather than against itself.

**Two calls, whatever they return.** Each outcome — answer, refusal or decode failure — is recorded
as it came; nothing is re-asked. The capture is written to `captures/triggers-probe.json` and,
once it is on disk, this script refuses outright with or without `--force`: that receipt is the
only copy of the only live evidence A.2.i has. A check that fails **before** the first call spends
nothing and writes nothing, so the probe can be run again once the seed is put right.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from protean import config
from protean.brain.folders import read_all_folders
from protean.cortex.layer import build_live_layer
from protean.cortex.live.config import load_seats
from protean.cortex.live.invoke import SYSTEM_PROMPT_FLAG
from protean.nodes import homeostasis
from protean.runtime import firing, triggers
from protean.runtime.clone import (
    DEFAULT_WORKLOAD,
    audit as git_audit,
    clone_workload,
    destroy,
)
from protean.runtime.seat import spawn_desk_of, tick_calls_of
from protean.state.enums import CallType, NodeName
from protean.state.inputs import HomeostasisInput
from protean.state.primitives import CeilingOverrides, CostCounters
from protean.state.seats import DelegateReturn, ThinkResult

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The seeds this probe copies and never writes: the node folders (a think's and a delegate's first
#: prompt half is the calling node's `NODE.md`), `seats/` (`calls/think.md` and `kinds/reader.md`)
#: and `seats.yaml`.
TRACKED_BRAIN = REPO_ROOT / "brain"

#: The only copy of the only live A.2.i receipt. Written when the operator runs this, beside
#: `library-probe.json` and the rest; never overwritten once it exists.
CAPTURE = Path(__file__).resolve().parent / "captures" / "triggers-probe.json"

#: The authored node whose think is planned — a builder's default (§ Scaffold clause item 4). Its
#: score is `ceiling_pressure`, which its projection reaches from the cost counters alone, with no
#: unit, summary or wave to fabricate. The delegate is this node's second call on the same desk.
NODE = NodeName.HOMEOSTASIS

#: The node's trigger key, as the call policy reads it, and the shipping line it is switched off on.
TRIGGER_KEY = triggers.TRIGGER_KEYS[str(NODE)]
OFF_LINE = f"{TRIGGER_KEY}: null\n"

#: The on-value written into the **throwaway** root only. The projection below is built to reach
#: it, so the value decides nothing about what is spent: one think, whatever it is.
PROBE_ON_VALUE = 0.5

#: The library's one `delegate` kind (A.2 § Deliverable 1), resolved out of the shipping container.
#: Its model and caps are read off the loaded block, never set here.
DELEGATE_KIND = "reader"

#: The one question the delegate is asked. It names a file inside the granted directory and no
#: path at all, and its answer is checkable: this process reads the same heading off the clone.
README_NAME = "README.md"
DELEGATE_QUESTION = (
    f"What is the first Markdown heading of the `{README_NAME}` at the top of the directory you "
    "were granted? Quote it verbatim and cite the file you read it from."
)

#: The task key both calls are journalled under, were they journalled: the probe opens no task.
TASK_ID = "probe-triggers"

#: What the script prints instead of spending.
BLOCK = (
    "REFUSED without --force: this makes TWO live calls — one planned `think` for `homeostasis` "
    "through the tool-less `calls.think` block, and one `reader` delegate spawned under its "
    "shipping kind block — each a real `claude -p` session on the seed's own model and caps, and "
    "spends real money once. It is the operator's to run (the build specification (not in this mirror) § DoD row "
    "B69, behind their go at B42) and it is never retried."
)


class ProbeNotSpent(RuntimeError):
    """A check before the first call failed: nothing was spent, and no capture is written."""


def seed_probe_root(destination: Path) -> Path:
    """A throwaway brain root carrying the tracked seeds as they ship, with one trigger key on.

    `seats.yaml` is copied byte for byte, so the `calls:` and `kinds:` blocks are the shipping ones
    and the `runtime:` block is whole — the real `binary`, the child `PATH`, the link farm, the
    five-name passthrough, the four spawn bounds, the per-tick delegate bound and `spawn_writable`.
    The one change is the node's `think_threshold: null` line, rewritten to `PROBE_ON_VALUE`; every
    other byte of every seed is the tracked one. The tracked `brain/` is read and written never.
    """
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(TRACKED_BRAIN / "nodes", destination / "nodes")
    for node in (destination / "nodes").iterdir():
        (node / "trace.jsonl").write_text("", encoding="utf-8")
    shutil.copytree(TRACKED_BRAIN / "seats", destination / "seats")
    for relative in ("mailbox/open", "mailbox/orphaned", "state", "episodes", "projects"):
        (destination / relative).mkdir(parents=True, exist_ok=True)
    shutil.copy2(TRACKED_BRAIN / "seats.yaml", destination / "seats.yaml")

    weights = config.node_dir(str(NODE), destination) / "weights.yaml"
    text = weights.read_text(encoding="utf-8")
    if text.count(OFF_LINE) != 1:
        raise ProbeNotSpent(
            f"{NODE}'s weights.yaml does not carry its shipping `{OFF_LINE.strip()}` line exactly "
            f"once — the seed moved, and the probe turns on a key it can find, or nothing"
        )
    weights.write_text(
        text.replace(OFF_LINE, f"{TRIGGER_KEY}: {PROBE_ON_VALUE}\n"), encoding="utf-8"
    )
    return destination


def projected_input(weights: Mapping[str, Any]) -> HomeostasisInput:
    """Homeostasis's read slice on a tick whose ceiling pressure has reached `PROBE_ON_VALUE`.

    The one cost counter moved is `ticks`, set from the root's own `max_ticks` so the pressure
    reaches the on-value whatever ceiling the seed carries; the projection's `tick` is the next one.
    The carrier is unset, as the policy always sees it.
    """
    ticks = math.ceil(PROBE_ON_VALUE * float(weights[homeostasis.CEILING_TICKS]))
    return HomeostasisInput(
        task_id=TASK_ID,
        tick=ticks + 1,
        weights=dict(weights),
        cost=CostCounters(ticks=ticks),
        ceiling_overrides=CeilingOverrides(),
    )


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _first_heading(path: Path) -> str | None:
    """The first Markdown heading line of a file, read by this process — or `None`."""
    text = _read_text(path)
    if text is None:
        return None
    return next((line for line in text.splitlines() if line.startswith("#")), None)


def _facts_as_json(facts: Any) -> dict[str, Any]:
    """`SeatCallFacts` as a JSON-writable mapping: its one pydantic field dumped, not left whole.

    `asdict()` recurses into dataclasses and leaves a pydantic model alone, so `audit` — I4's four
    lists — would reach `json.dumps` as an object it cannot serialise and take the whole capture
    with it (`probe_spawn.py`'s own reason).
    """
    body = asdict(facts)
    audit = body.get("audit")
    body["audit"] = None if audit is None else audit.model_dump(mode="json")
    return body


def _flag_values(argv: list[str], flag: str) -> list[str]:
    """Every value the argv as run carried after `flag`."""
    return [
        argv[index + 1] for index, one in enumerate(argv) if one == flag and index + 1 < len(argv)
    ]


def _answer(returned: Any, record: Any) -> dict[str, Any]:
    """One call's outcome as it came back: the decoded result, or the refusal and its class."""
    body: dict[str, Any] = {
        "call_number": None if record is None else record.call.call_number,
        "result": None,
        "refusal": None,
        "envelope": None,
    }
    if record is not None and record.envelope is not None:
        body["envelope"] = record.envelope.model_dump(mode="json")
    if isinstance(returned, (ThinkResult, DelegateReturn)):
        body["result"] = returned.model_dump(mode="json")
    elif returned is not None:
        body["refusal"] = {
            "reason": getattr(returned, "reason", None),
            "detail": getattr(returned, "detail", str(returned)),
        }
    return body


def probe_triggers() -> dict[str, Any]:
    """One planned think and one `reader` delegate on one tick's live desk. Spends twice.

    Every check that can fail before a call is made runs first — the throwaway root loads and
    passes the call policy's task-start refusal, the node's firing check fires, and the policy
    plans exactly one `think` with its payload — and a failure there raises `ProbeNotSpent`, which
    spends nothing and writes nothing. After the first call nothing raises past this function: a
    fault while reading the receipts back is recorded beside them, so the capture of what was
    bought is still written.
    """
    scratch = Path(tempfile.mkdtemp(prefix="protean-triggers-probe-"))
    root = scratch / "brain"
    clone: Path | None = None
    outcome: dict[str, Any] = {
        "surface": "triggers",
        "node": str(NODE),
        "trigger_key": TRIGGER_KEY,
        "on_value": PROBE_ON_VALUE,
        "delegate_kind": DELEGATE_KIND,
        "delegate_question": DELEGATE_QUESTION,
        "workload": str(DEFAULT_WORKLOAD),
        "brain_root": str(root),
        "think_answered": False,
        "delegate_returned": False,
    }
    try:
        seed_probe_root(root)
        folders = read_all_folders(root)
        # `engine.build_context()`'s own refusal, run over the throwaway root: an on key with no
        # `## Calls` line, or a value outside the key's domain, stops the probe before it spends.
        triggers.check_seeds(folders)
        folder = folders[NODE]
        seats = load_seats(root)
        if seats is None or not seats.is_live:
            raise ProbeNotSpent(f"{root}/seats.yaml does not select the live layer")
        think_block = seats.call(CallType.THINK)
        reader = seats.kind(config.CALL_DELEGATE, DELEGATE_KIND)
        think_prefix = think_block.prompt_path(root).read_text(encoding="utf-8")
        outcome["think_block"] = {
            "block": think_block.tier,
            "model": think_block.model,
            "effort": think_block.effort,
            "max_call_usd": think_block.max_call_usd,
            "timeout_seconds": think_block.timeout_seconds,
            "allowed_tools": list(think_block.allowed_tools),
            "tools": think_block.tools_argument(),
            "add_dir": think_block.add_dir,
        }
        outcome["delegate_block"] = {
            "block_ref": reader.block_ref,
            "model": reader.model,
            "effort": reader.effort,
            "max_call_usd": reader.max_call_usd,
            "timeout_seconds": reader.timeout_seconds,
            "allowed_tools": list(reader.allowed_tools),
            "tools": reader.tools_argument(),
            "disallowed_tools": list(reader.disallowed_tools),
            "permission_mode": reader.permission_mode,
            "add_dir": reader.add_dir,
        }

        projection = projected_input(folder.weights)
        tick = projection.tick
        outcome["tick"] = tick
        outcome["ceiling_pressure"] = homeostasis.ceiling_pressure(projection)
        decision = firing.decide(NODE, projection)
        outcome["fired"] = decision.fired
        if not decision.fired:
            raise ProbeNotSpent(
                f"{NODE}'s firing check declined ({decision.value} < {decision.threshold}), and a "
                f"node that declines issues none of its calls"
            )

        layer = build_live_layer(root=root)
        clone = clone_workload(DEFAULT_WORKLOAD)
        outcome["workspace"] = str(clone)
        outcome["readme_first_heading"] = _first_heading(clone / README_NAME)
        # **cycle.py's order**: the tick's one spawn desk first, handed the workspace, then the
        # tick's node-call desk, whose delegate arm reaches that same memoized desk.
        spawn_desk = spawn_desk_of(layer, TASK_ID, tick, str(clone))
        desk = tick_calls_of(layer, TASK_ID, tick)
        if spawn_desk is None or desk is None:
            raise ProbeNotSpent("the live layer attached no `spawns` or no `node_calls` seam")
        outcome["delegate_bound"] = getattr(desk, "delegate_bound", None)
        planned = triggers.plan(
            NODE, projection, folder.node_md, getattr(desk, "delegate_bound", None), 0
        )
        outcome["plan"] = [
            {"type": str(item.type), "payload": dict(item.payload), "model": item.payload_model}
            for item in planned
        ]
        if [item.type for item in planned] != [CallType.THINK]:
            raise ProbeNotSpent(f"the policy planned {outcome['plan']}, not exactly one think")
        (think,) = planned
        question = str(think.payload["question"])
        context = str(think.payload["context"])

        # ---- the spend: two calls, each once, whatever it returns ----
        answered = desk.think(NODE, question=question, context=context)
        # Read at once: the port's facts are its **last** call's, and the delegate spawns on a
        # per-spawn instance of its own, so nothing below overwrites them.
        think_facts = tuple(layer.calls()) if layer.calls is not None else ()
        delegated = desk.delegate(
            NODE, kind=DELEGATE_KIND, question=DELEGATE_QUESTION, context=context
        )

        try:
            records = list(desk.records)
            think_record = next(
                (item for item in records if item.call.type == CallType.THINK), None
            )
            delegate_record = next(
                (item for item in records if item.call.type == CallType.DELEGATE), None
            )
            outcome["think_answered"] = isinstance(answered, ThinkResult)
            outcome["think"] = _answer(answered, think_record)
            outcome["think_facts"] = [_facts_as_json(one) for one in think_facts]
            argv = list(think_facts[-1].argv) if think_facts else []
            sent = _flag_values(argv, SYSTEM_PROMPT_FLAG)
            outcome["think_tools_sent"] = _flag_values(argv, "--tools")
            outcome["node_md_first"] = bool(sent) and sent[0].startswith(folder.node_md)
            outcome["prompt_is_node_md_then_think_md"] = bool(sent) and (
                sent[0] == folder.node_md + "\n" + think_prefix
            )

            outcome["delegate_returned"] = isinstance(delegated, DelegateReturn)
            outcome["delegate"] = _answer(delegated, delegate_record)
            call_number = None if delegate_record is None else delegate_record.call.call_number
            key = (str(NODE), call_number, None)
            facts = spawn_desk.spawns_of().get(key)
            outcome["spawn_key"] = list(key)
            outcome["delegate_facts"] = None if facts is None else _facts_as_json(facts)
            spawn_argv = list(facts.argv) if facts is not None else []
            outcome["recorded_add_dir"] = _flag_values(spawn_argv, "--add-dir")
            outcome["permission_denials"] = (
                [dict(one) for one in facts.permission_denials] if facts is not None else None
            )
            outcome["audit"] = (
                None
                if facts is None or facts.audit is None
                else facts.audit.model_dump(mode="json")
            )
            outcome["git_audit"] = git_audit(clone)
        except Exception as fault:  # noqa: BLE001 — the calls are bought; the capture still lands
            outcome["probe_fault"] = f"{type(fault).__name__}: {fault}"
    finally:
        # Both throwaways die here, however this ended: the clone the delegate was granted and the
        # brain root the key was turned on in. The repo's own `brain/` was never written.
        if clone is not None:
            destroy(clone.parent if clone.name == "clone" else clone)
            outcome["clone_exists_after"] = clone.exists()
        destroy(scratch)
        outcome["brain_root_exists_after"] = root.exists()
    return outcome


def _summarise(capture: dict[str, Any]) -> str:
    """The capture, read back on the terminal: the four facts, in the order B69 names them."""
    think = capture.get("think") or {}
    delegate = capture.get("delegate") or {}
    audit = capture.get("audit") or {}
    denials = capture.get("permission_denials")
    named = [
        (one.get("tool_input") or {}).get("command") or one.get("tool_name")
        for one in (denials or [])
    ]
    answer = (think.get("result") or {}).get("answer")
    information = (delegate.get("result") or {}).get("information")
    return (
        f"  1. the think:        answered={capture.get('think_answered')} "
        f"refusal={think.get('refusal')!r}\n"
        f"  2. its block:        tools_sent={capture.get('think_tools_sent')} "
        f"node_md_first={capture.get('node_md_first')} "
        f"two_halves={capture.get('prompt_is_node_md_then_think_md')}\n"
        f"  3. the delegate:     returned={capture.get('delegate_returned')} "
        f"key={capture.get('spawn_key')} refusal={delegate.get('refusal')!r} "
        f"add_dir={capture.get('recorded_add_dir')}\n"
        f"  4. the four lists:   wrote={len(audit.get('wrote') or [])} "
        f"wrote_outside_workspace={len(audit.get('wrote_outside_workspace') or [])} "
        f"left_the_clone={audit.get('left_the_clone')} "
        f"exec_attempted={audit.get('exec_attempted')} denials={named}\n"
        f"  the README heading, read here: {capture.get('readme_first_heading')!r}\n"
        f"  fault: {capture.get('probe_fault')!r}\n"
        f"  --- the think's answer, verbatim ---\n{answer}\n"
        f"  --- the delegate's information, verbatim ---\n{information}\n"
        f"  --- end ---"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--force",
        action="store_true",
        help="spend: this makes ONE planned think and ONE `reader` delegate on a throwaway root",
    )
    args = parser.parse_args(argv)
    relative = CAPTURE.relative_to(REPO_ROOT)

    if CAPTURE.exists():
        # Not `--force`-able. This probe buys exactly two calls and the receipt on disk IS that
        # purchase; re-taking it would destroy the only copy of the only live A.2.i evidence.
        print(f"REFUSED: {relative} is already on disk. This receipt is bought exactly once.")
        return 2
    if not args.force:
        print(BLOCK)
        print()
        print(f"the plan: one planned think for {NODE}, one {DELEGATE_KIND!r} delegate, one desk")
        print(
            f"  root:      a throwaway copy of {TRACKED_BRAIN.relative_to(REPO_ROOT)}/, "
            f"{NODE}.{TRIGGER_KEY} turned on at {PROBE_ON_VALUE} there and nowhere else"
        )
        print("  blocks:    as they ship — calls.think and kinds.delegate.reader, their own caps")
        print(f"  workspace: a throwaway clone of {DEFAULT_WORKLOAD}")
        print(f"  capture:   {relative} (absent — this probe has not run)")
        return 0

    try:
        capture = probe_triggers()
    except ProbeNotSpent as refusal:
        print(f"NOT SPENT: {refusal}. Nothing was called and no capture was written.")
        return 2
    CAPTURE.parent.mkdir(parents=True, exist_ok=True)
    CAPTURE.write_text(
        json.dumps(capture, indent=1, ensure_ascii=False, default=str), encoding="utf-8"
    )
    print(_summarise(capture))
    print(f"written: {relative}")
    return 0


if __name__ == "__main__":  # pragma: no cover - the script's entry point
    sys.exit(main())
