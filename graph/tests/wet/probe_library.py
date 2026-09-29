"""B56: A.2's own live receipt — one shipping `editor` spawn on a throwaway root and clone, once.

`the build specification (not in this mirror)` § Deliverable 6's third paragraph ("The one live receipt, and
it is the operator's"), § Deliverable 7's paragraph "The probe reaches the same seam directly", § Named
assumptions 1, 2 and 6, § Resolutions L10 and L11, § DoD rows **B56** and **G7**. Order W6 of
`the work orders (not in this mirror)` lands it and **runs it never**.

**The operator runs this, and no builder does** (row B56, behind their go at **B42**). Every machine row of
A.2 closes on the dry oracle — `tests/cortex/fake_cli.py` as the stand-in binary, the shipping seed
read off disk, the recording shim first on `PATH` with a zero-byte log — so the four facts below are
the only ones the build cannot reach, and they are the only reason to spend. Until the operator runs it there
is **no capture on disk**, and row G7 asserts exactly that: the script exists, is not collected,
refuses without `--force`, has not run, and carries its member's unit statically.

**It is a script, not a test**, the same shape as `tests/wet/probe_spawn.py`: a `live`-marked
pytest module re-spends on every collection, and this file's name matches no `python_files`
pattern, so `pytest` does not collect it at all.

**What it spends.** Exactly one `dispatch`-class spawn of the shipping `editor` kind through the
landed spawn desk — one member, one wave — on the block **as it ships**: its model, effort, grant
and both caps are the seed's, never probe values. That is the one departure from
`probe_spawn.py`, which swaps a fixture kind's model and lowers its caps: here the caps are part of
what is measured, because B56 is the first receipt that can say whether `2.50`/`1800` covers the
work (§ Named assumptions 2).

**Why the root is a throwaway and the kind is the library's.** B49 spends its call on a *fixture*
kind and does not supply the A.2 library, so it cannot say whether a **library** kind works (L10).
This probe copies the tracked seeds — the node folders, `seats/` with both kind prefixes, and
`seats.yaml` byte for byte, its `kinds:` container the shipping one — into a temp directory, splices
nothing, keeps the **real** binary and the real `runtime:` block, and destroys the whole tree on
the way out. `brain/` is read and never written.

**How the work is asked** (§ Deliverable 7; L19, L20). The probe builds no checkpoint and never
passes through `run_wave`, so it hands the desk the unit itself: the desk's `dispatch_wave`
receives, on its `units=` keyword, the one member's unit id — the same `UNIT_ID` its `WaveMember`
carries — mapped to one sentence of work, `INTENT`, which is the keyword `run_wave` fills on the
runtime path. The shipping `editor.md` is not overwritten: the member's system prompt is the cortex
`NODE.md`, the kind's prefix, the delimiter line and the intent, exactly as a runtime wave sends it.

**Four things are measured, and all four are facts row B56 names** — each read off disk or off
`SeatCallFacts` by this process, never off the model's narrative:

1. **A library kind loads, spawns and completes under the composed profile.** The block resolves
   out of the shipping container, the desk composes its profile and opens one process, and
   `envelope_returned`, `stop_reason`, `num_turns` and the facts' `outcome` say whether it came
   back as a valid envelope.
2. **Its four audit lists are read off a real receipt.** `wrote`, `wrote_outside_workspace`,
   `left_the_clone` and `exec_attempted` have never been derived from a real library spawn; the
   capture carries all four beside the file the session was asked to write and the denials the
   envelope really returned, so each list can be read against what happened.
3. **It was told its work, through the channel.** The recorded `--system-prompt` value is read off
   the argv as run and must end in the delimiter line and `INTENT`; the one file the intent names
   is read off the clone by this process before the clone dies. A `wrote` that stays empty is
   therefore a finding, never a design outcome.
4. **A real `-p` session's own state writes do not stop it** (§ Named assumptions 6). The composed
   profile denies `file-write*` outright and allows it back under the task workspace and
   `runtime.spawn_writable` alone — which **excludes the CLI's own state directory under the
   user's home**, where it keeps sessions, caches and settings. `envelope_returned`,
   `stop_reason`, `num_turns` and the facts' `error` are the answer. **If it fails, that is the
   capture**: the pre-stated fallback is the operator's named seed edit adding that directory to
   `spawn_writable` (row B57, L11), never a code change here.

**One call, whatever it returns.** The member's outcome — envelope, refusal or decode failure — is
recorded as it came; nothing is re-asked. The capture is written to `captures/library-probe.json`
and, once it is on disk, this script refuses outright with or without `--force`: that receipt is
the only copy of the only live evidence the library has.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from protean.cortex.live.config import parse_seats
from protean.cortex.live.invoke import SYSTEM_PROMPT_FLAG, UNIT_DELIMITER
from protean.cortex.live.wave import SpawnDesks
from protean.runtime.clone import (
    DEFAULT_WORKLOAD,
    audit as git_audit,
    clone_workload,
    destroy,
)
from protean.runtime.cycle import WAVE_CALL_NUMBER
from protean.runtime.errors import SeatUnavailable
from protean.runtime.seat import SeatDecodeError
from protean.state.enums import NodeName
from protean.state.seats import WaveMember

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The seeds this probe copies and never writes: the node folders (the prefix's first half is
#: `nodes/cortex/NODE.md`), `seats/` (both kind prefixes under `seats/kinds/`) and `seats.yaml`.
TRACKED_BRAIN = REPO_ROOT / "brain"

#: The only copy of the only live library receipt. Written when the operator runs this, beside
#: `spawn-probe.json` and the rest; never overwritten once it exists.
CAPTURE = Path(__file__).resolve().parent / "captures" / "library-probe.json"

#: The kind spawned: the library's one `dispatch` kind (§ Deliverable 1), resolved out of the
#: shipping container. Its model and caps are read off the loaded block, never set here.
PROBE_KIND_CLASS = "dispatch"
PROBE_KIND = "editor"

#: The journal key this one spawn takes — the cortex's own call, the wave's call number, member 1.
TASK_ID = "probe-library"
TICK = 1
MEMBER_NUMBER = 1
UNIT_ID = "u-probe-library-1"
ADMITTED_REF = "admitted"

#: The one small change the intent names: a file the session writes **inside the directory it is
#: working in**, read off the clone by this process. No path component, so the sentence names
#: nothing outside the workspace.
WORK_FILENAME = "library-probe.txt"
WORK_LINE = "written by the editor kind"

#: The unit's `intent` — the one sentence of work (§ Deliverable 6 ¶4, § Deliverable 7). It reaches
#: the member only through the desk's `units=` keyword, keyed by the member's own `unit_id`.
INTENT = (
    f"Create a file named `{WORK_FILENAME}` at the top of the directory you are working in, "
    f"containing exactly the one line `{WORK_LINE}`."
)

#: What the script prints instead of spending.
BLOCK = (
    "REFUSED without --force: this opens ONE live spawn of the shipping `editor` kind — a real "
    "`claude -p` session under the composed per-spawn sandbox profile, on the block's own model "
    "and caps — and spends real money once. It is the operator's to run "
    "(the build specification (not in this mirror) § DoD row B56, behind their go at B42) and it is never "
    "retried."
)


def seed_probe_root(destination: Path) -> Path:
    """A throwaway brain root carrying the tracked seeds as they ship — the library included.

    Nothing is spliced: `seats.yaml` is copied byte for byte, so the `kinds:` container is the
    shipping one, the `runtime:` block is whole (the real `binary`, the child `PATH`, the link farm,
    the five-name passthrough, the four spawn bounds and `spawn_writable`), and the `editor` block's
    model, effort, grant and caps are the seed's. `seats/` is copied whole, so both kind prefixes
    resolve under the throwaway `seats/kinds/` exactly as they do under the tracked one, and neither
    is overwritten. The tracked `brain/` is read and written never.
    """
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(TRACKED_BRAIN / "nodes", destination / "nodes")
    for node in (destination / "nodes").iterdir():
        (node / "trace.jsonl").write_text("", encoding="utf-8")
    shutil.copytree(TRACKED_BRAIN / "seats", destination / "seats")
    for relative in ("mailbox/open", "mailbox/orphaned", "state", "episodes", "projects"):
        (destination / relative).mkdir(parents=True, exist_ok=True)
    shutil.copy2(TRACKED_BRAIN / "seats.yaml", destination / "seats.yaml")
    return destination


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


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


def probe_library() -> dict[str, Any]:
    """One shipping `editor` spawn through the landed desk, on a throwaway root and clone. Spends once.

    The desk is resolved exactly as the runtime resolves it — `SpawnDesks(config, root)` called
    with `(task, tick, workspace)` — and handed **one** member and its unit's intent, **once**: the
    desk keeps one instance per `(node, call#, member#)`, so a second wave on the same key would
    reuse the first instance and its intent. The wave's width is 1 and its cap sum is the block's
    own `max_call_usd`, both inside the seed's bounds, which are checked before anything spawns.

    Every fact below is read off disk or off `SeatCallFacts`, never off the model's narrative: the
    argv as run and the `--system-prompt` value it carried, the file the session wrote inside the
    clone, the envelope's own `permission_denials`, and the four derived audit lists. The narrative
    is captured beside them and stands in for nothing.
    """
    scratch = Path(tempfile.mkdtemp(prefix="protean-library-probe-"))
    root = scratch / "brain"
    clone: Path | None = None
    outcome: dict[str, Any] = {
        "surface": "library",
        "kind_class": PROBE_KIND_CLASS,
        "kind": PROBE_KIND,
        "unit_id": UNIT_ID,
        "intent": INTENT,
        "workload": str(DEFAULT_WORKLOAD),
        "brain_root": str(root),
        "envelope_returned": False,
        "refusal": None,
    }
    try:
        seed_probe_root(root)
        seats = parse_seats(
            yaml.safe_load((root / "seats.yaml").read_text(encoding="utf-8")), root
        )
        block = seats.kind(PROBE_KIND_CLASS, PROBE_KIND)
        outcome.update(
            {
                "block_ref": block.block_ref,
                "model": block.model,
                "effort": block.effort,
                "max_call_usd": block.max_call_usd,
                "timeout_seconds": block.timeout_seconds,
                "allowed_tools": list(block.allowed_tools),
                # The `--tools` argument as it reaches the wire, off the block's own accessor.
                "tools": block.tools_argument(),
                "disallowed_tools": list(block.disallowed_tools),
                "permission_mode": block.permission_mode,
                "add_dir": block.add_dir,
                "spawn_writable": [str(tree) for tree in seats.spawn_writable],
                "deny_write": [str(tree) for tree in seats.sandbox.deny_write],
            }
        )
        clone = clone_workload(DEFAULT_WORKLOAD)
        outcome["workspace"] = str(clone)
        # Read before the call so a file some earlier state left cannot pass for the session's work.
        outcome["work_file_existed_before"] = (clone / WORK_FILENAME).exists()

        desk = SpawnDesks(config=seats, root=root)(TASK_ID, TICK, str(clone))
        outcome["allowed_subpaths"] = [str(path) for path in desk.allowed_subpaths(clone)]
        member = WaveMember(kind=PROBE_KIND, unit_id=UNIT_ID, admitted_ref=ADMITTED_REF)
        try:
            results = desk.dispatch_wave(
                {MEMBER_NUMBER: member},
                call_number=WAVE_CALL_NUMBER,
                units={UNIT_ID: INTENT},
            )
            returned = results[MEMBER_NUMBER]
        except (SeatUnavailable, SeatDecodeError) as refusal:
            outcome["refusal"] = str(refusal)
            returned = None
        if isinstance(returned, BaseException):
            outcome["member_fault"] = f"{type(returned).__name__}: {returned}"
        elif returned is not None:
            # `SeatEnvelope` is extra-tolerant, so `num_turns` and `total_cost_usd` arrive as
            # extras: the dump is the whole envelope as it came back, and the named facts are read
            # out of it rather than off attributes that may not exist.
            envelope = returned.model_dump(mode="json")
            outcome["envelope_returned"] = True
            outcome["envelope"] = envelope
            outcome["stop_reason"] = returned.stop_reason
            outcome["result"] = returned.result
            outcome["num_turns"] = envelope.get("num_turns")
            outcome["total_cost_usd"] = envelope.get("total_cost_usd")

        key = (str(NodeName.CORTEX), WAVE_CALL_NUMBER, MEMBER_NUMBER)
        facts = desk.spawns_of().get(key)
        outcome["spawn_key"] = list(key)
        outcome["facts"] = None if facts is None else _facts_as_json(facts)
        argv = list(facts.argv) if facts is not None else []
        # Fact 3's parent-side half: the prompt as the process was handed it, off the argv as run.
        sent = [
            argv[index + 1]
            for index, one in enumerate(argv)
            if one == SYSTEM_PROMPT_FLAG and index + 1 < len(argv)
        ]
        outcome["sent_prompt_tail"] = sent[0][-400:] if sent else None
        outcome["intent_sent"] = bool(sent) and sent[0].endswith(
            "\n" + UNIT_DELIMITER + "\n" + INTENT
        )
        outcome["permission_denials"] = (
            [dict(one) for one in facts.permission_denials] if facts is not None else None
        )
        outcome["audit"] = (
            None
            if facts is None or facts.audit is None
            else facts.audit.model_dump(mode="json")
        )

        # Fact 3's clone-side half, read off the clone by THIS process while the clone still exists.
        work = clone / WORK_FILENAME
        outcome["work_file_present"] = work.exists()
        outcome["work_file"] = _read_text(work) if work.exists() else None
        outcome["git_audit"] = git_audit(clone)
    finally:
        # Both throwaways die here, however this ended: the clone the session was granted and the
        # brain root the library was copied into. The repo's own `brain/` was never written.
        if clone is not None:
            destroy(clone.parent if clone.name == "clone" else clone)
            outcome["clone_exists_after"] = clone.exists()
        destroy(scratch)
        outcome["brain_root_exists_after"] = root.exists()
    return outcome


def _summarise(capture: dict[str, Any]) -> str:
    """The capture, read back on the terminal: the four facts, in the order B56 names them."""
    denials = capture.get("permission_denials")
    named = [
        (one.get("tool_input") or {}).get("command") or one.get("tool_name")
        for one in (denials or [])
    ]
    audit = capture.get("audit") or {}
    wrote = audit.get("wrote") or []
    changed = [path for tree in wrote for path in (tree.get("changed") or [])]
    facts = capture.get("facts") or {}
    return (
        f"  1. the library kind:  {capture.get('block_ref')} on {capture.get('model')} "
        f"envelope={capture['envelope_returned']} stop_reason={capture.get('stop_reason')!r} "
        f"outcome={facts.get('outcome')!r} refusal={capture.get('refusal')!r} "
        f"fault={capture.get('member_fault')!r}\n"
        f"  2. the four lists:    wrote={changed} "
        f"wrote_outside_workspace={len(audit.get('wrote_outside_workspace') or [])} "
        f"left_the_clone={audit.get('left_the_clone')} "
        f"exec_attempted={audit.get('exec_attempted')} denials={named}\n"
        f"  3. told its work:     intent_sent={capture.get('intent_sent')} "
        f"work_file_present={capture.get('work_file_present')} "
        f"work_file={capture.get('work_file')!r}\n"
        f"  4. the session ran:   turns={capture.get('num_turns')} "
        f"error={facts.get('error')!r}\n"
        f"  cost: ${capture.get('total_cost_usd')} of the block's ${capture.get('max_call_usd')}\n"
        f"  --- the member's narrative, verbatim ---\n{capture.get('result')}\n"
        f"  --- end of narrative ---"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--force",
        action="store_true",
        help="spend: this opens ONE real `editor` spawn on a throwaway root and clone",
    )
    args = parser.parse_args(argv)
    relative = CAPTURE.relative_to(REPO_ROOT)

    if CAPTURE.exists():
        # Not `--force`-able. This probe buys exactly one call and the receipt on disk IS that
        # purchase; re-taking it would destroy the only copy of the only live library evidence.
        print(f"REFUSED: {relative} is already on disk. This receipt is bought exactly once.")
        return 2
    if not args.force:
        print(BLOCK)
        print()
        print(f"the plan: one {PROBE_KIND_CLASS} spawn of the shipping {PROBE_KIND!r} kind")
        print(f"  root:      a throwaway copy of {TRACKED_BRAIN.relative_to(REPO_ROOT)}/, unspliced")
        print("  block:     as it ships — its own model, effort, grant and both caps")
        print(f"  workspace: a throwaway clone of {DEFAULT_WORKLOAD}")
        print(f"  unit:      {UNIT_ID!r} → {INTENT!r}")
        print(f"  capture:   {relative} (absent — this probe has not run)")
        return 0

    capture = probe_library()
    CAPTURE.parent.mkdir(parents=True, exist_ok=True)
    CAPTURE.write_text(json.dumps(capture, indent=1, ensure_ascii=False), encoding="utf-8")
    print(_summarise(capture))
    print(f"written: {relative}")
    return 0


if __name__ == "__main__":  # pragma: no cover - the script's entry point
    sys.exit(main())
