"""The `--tools ""` re-probe order W1 left owed, and the two no-tools records row K1 reads.

`the build specification (not in this mirror)` § Resolutions D3-4 — order W1's probe 3 came back **refused
at the API** on a 21 kB filler prefix (`stop_reason: refusal`, `terminal_reason: api_error`,
`[reasoning_extraction]`), so the flag is *unproven, not disproven*, and the ruling puts one
re-probe on this order: once, on the real model, with the **real** director prefix
(`brain/nodes/cortex/NODE.md` + `brain/seats/director.md`) and a director-shaped request on
stdin. A structured result fixes `--tools ""` into the director and planner argv; anything else
keeps the S-6 fallback that `brain/seats.yaml` already carries.

**It is a script, not a test** — the shape order W1 established and the session adjudicated as
D3-1. A `live`-marked pytest module re-spends on every collection; a script that refuses to
re-spend without `--force` does not, and `tests/cortex/test_live_seat.py` asserts over what it
captured.

**What it spends.** One director call. If that call does not return a structured result, one
more with the fallback configuration — which is not a retry of the probe but the configuration
that actually ships, exercised once so row K1 has a director record at all. Then one planner
call in whichever configuration won. Two calls on the happy path, three on the other.

**Where the spawn happens.** Inside `protean.cortex.live.invoke`, the package licensed to name
the binary: this script drives the real adapter rather than assembling an argv of its own, so
what it proves is the thing that ships and not a hand-rolled lookalike of it.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, replace
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from protean import config
from protean.cortex.adapters import SeatDesk
from protean.cortex.live.config import parse_seats
from protean.cortex.live.invoke import LiveSeat
from protean.cortex.live.session import LiveSessionBook
from protean.runtime.errors import SeatUnavailable
from protean.runtime.seat import SeatDecodeError
from protean.state.enums import Escalation, Tier
from protean.state.primitives import GoalItem
from protean.state.workspace import DirectorRequest, ManagerRequest, Workspace

REPO_ROOT = Path(__file__).resolve().parents[2]
CAPTURE_DIR = Path(__file__).resolve().parent / "captures"
CAPTURE = CAPTURE_DIR / "tools-flag-probe.json"

#: The tiny task the probe seats are given. Small on purpose: the prefix is the expensive half.
GOAL_TEXT = "confirm the seat wiring answers in its own schema"
TASK_ID = "probe-tools-flag"


def _request(tier: Tier) -> DirectorRequest | ManagerRequest:
    workspace = Workspace(
        task_id=TASK_ID,
        tick=1,
        goals=[
            GoalItem(
                id=f"{TASK_ID}-g1",
                text=GOAL_TEXT,
                opened_at_tick=0,
                last_progress_tick=0,
            )
        ],
    )
    if tier is Tier.DIRECTOR:
        return DirectorRequest(workspace=workspace)
    return ManagerRequest(workspace=workspace, escalation=Escalation.EMPTY_UNIT_STACK)


def seats_with(tools: str | None, *, root: Path) -> Any:
    """The real `brain/seats.yaml`, with the two no-tools tiers switched to one realization.

    `tools=""` is the flag under probe; `tools=None` is the `--disallowedTools` fallback the
    seed ships. Nothing else about the file is touched — the models, the caps, the prefixes and
    the containment are the shipping ones, which is the whole point of re-probing here rather
    than in a standalone harness.
    """
    payload = yaml.safe_load((root / "seats.yaml").read_text(encoding="utf-8"))
    for tier in ("director", "planner"):
        payload[tier]["tools"] = tools
        if tools is not None:
            payload[tier]["disallowed_tools"] = []
    return parse_seats(payload, root)


def one_call(
    tier: Tier, tools: str | None, root: Path, widen_env: Sequence[str] = ()
) -> dict[str, Any]:
    """One live call through the real adapter. Records what came back, whatever it was.

    `widen_env` is the probe-only escape hatch the dispatch-5 ledger's D5-8 entry existed for:
    under the containment paragraph's then four-variable scrub the CLI answered "Not logged in"
    before it reached the API, so a probe run under exactly that scrub could not answer the
    `--tools ""` question at all. Naming a variable here widens **this probe** and nothing that
    ships. **S-37 has since ruled the passthrough to five names** and `brain/seats.yaml` carries
    `USER` itself, so the hatch is no longer needed to authenticate; it is kept because the
    stored capture was taken through it and every capture records the environment it ran under.
    """
    seats = seats_with(tools, root=root)
    if widen_env:
        seats = replace(seats, env_passthrough=(*seats.env_passthrough, *widen_env))
    book = LiveSessionBook()
    desk = SeatDesk(sessions=book)
    seat = LiveSeat(config=seats, desk=desk, sessions=book, decode_retries=0)
    book.open_task(f"{TASK_ID}-{tier}")
    outcome: dict[str, Any] = {
        "tier": str(tier),
        "tools": tools,
        "env_passthrough": list(seats.env_passthrough),
        "structured": False,
        "refusal": None,
    }
    try:
        envelope = seat(tier, _request(tier))
        outcome["structured"] = True
        outcome["stop_reason"] = envelope.stop_reason
        outcome["result"] = envelope.result
    except (SeatUnavailable, SeatDecodeError) as refusal:
        outcome["refusal"] = str(refusal)
    facts = [asdict(fact) for fact in seat.calls()]
    outcome["facts"] = facts
    outcome["stdout"] = seat.last_stdout.decode("utf-8", errors="replace")
    return outcome


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--force",
        action="store_true",
        help="spend again even though a capture already exists",
    )
    parser.add_argument(
        "--widen-env",
        nargs="*",
        default=[],
        metavar="NAME",
        help=(
            "run the probe with these variables added to the scrub. Probe-only, recorded in "
            "the capture, and never what `brain/seats.yaml` ships — see ledger D5-8"
        ),
    )
    args = parser.parse_args(argv)

    if CAPTURE.exists() and not args.force:
        print(f"{CAPTURE.relative_to(REPO_ROOT)} exists; every call here spends real money.")
        print("Pass --force to re-probe.")
        return 0

    root = config.brain_root()
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    calls: list[dict[str, Any]] = []

    widen = list(args.widen_env)
    probe = one_call(Tier.DIRECTOR, "", root, widen)
    calls.append(probe)
    if probe["structured"]:
        chosen: str | None = ""
    else:
        chosen = None
        calls.append(one_call(Tier.DIRECTOR, None, root, widen))
    calls.append(one_call(Tier.MANAGER, chosen, root, widen))

    capture = {
        "cli_version": calls[0]["facts"][0]["cli_version"] if calls[0]["facts"] else "",
        "env_widened_for_the_probe": widen,
        "tools_flag_returns_structured_result": probe["structured"],
        "realization": "--tools ''" if chosen == "" else "--disallowedTools (S-6 fallback)",
        "calls": calls,
    }
    CAPTURE.write_text(json.dumps(capture, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in capture.items() if k != "calls"}, indent=1))
    for call in calls:
        print(
            f"  {call['tier']:9s} tools={call['tools']!r:6s} structured={call['structured']} "
            f"num_turns={[f['num_turns'] for f in call['facts']]} "
            f"refusal={(call['refusal'] or '')[:90]}"
        )
    print(f"written: {CAPTURE.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
