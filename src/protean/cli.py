"""The `protean` command: run, resume, status and dry. Exit codes: done 0, stopped 11, interrupted 12."""

from __future__ import annotations

import argparse
import re
import signal
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from protean import dry, loop, mailbox, state
from protean.budget import load_caps
from protean.runner import real_runner
from protean.state import Root

DEFAULT_BRAIN = dry.REPO / "brain" / "protean"
EXIT = {"done": 0, "stopped": 11, "interrupted": 12}
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130


def parse_extend(text: str) -> tuple[float, int]:
    """`N` more ticks or `$X` more dollars, as (dollars, ticks)."""
    if re.fullmatch(r"[1-9]\d*", text):
        return 0.0, int(text)
    match = re.fullmatch(r"\$(\d+(?:\.\d+)?)", text)
    if match and float(match.group(1)) > 0:
        return float(match.group(1)), 0
    if re.fullmatch(r"\d+m", text):
        raise ValueError(f"--extend {text}: there is no wall-clock ceiling to extend; use N (ticks) or $X")
    raise ValueError(f"--extend {text!r}: expected N (ticks) or $X (dollars)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="protean", description="A director plans units, workers do them, a grader decides.")
    parser.add_argument("--brain", metavar="PATH", type=Path, default=DEFAULT_BRAIN,
                        help="the brain root (default: <repo>/brain/protean)")
    verbs = parser.add_subparsers(dest="verb", metavar="VERB", required=True)
    run = verbs.add_parser("run", help="start a task and run it until it is done, stopped or interrupted")
    run.add_argument("goal")
    run.add_argument("--workspace", required=True, metavar="PATH", help="the git clone units branch from")
    run.add_argument("--project", default="_root", metavar="SLUG")
    resume = verbs.add_parser("resume", help="continue the current task")
    resume.add_argument("--extend", metavar="N|$X", action="append",
                        help="widen this task by N ticks or $X; repeat it to widen both at once")
    resume.add_argument("--abandon", action="store_true", help="close its question and stop it for good")
    verbs.add_parser("status", help="show the current task")
    scenario = verbs.add_parser("dry", help="run a scripted scenario on a scratch root; no model is called")
    scenario.add_argument("scenario")
    return parser


def status(root: Root) -> int:
    """Print the current task, or say there is none."""
    task = state.current(root)
    if task is None:
        print(f"no task in {root.path}; start one with `protean run`")
        return 0
    caps = load_caps(root)
    print(f"task: {task.id} ({task.project})\ngoal: {task.goal}\nworkspace: {task.workspace}")
    print(f"tick: {task.tick} of {caps.max_ticks + task.extra_ticks}")
    print(f"terminal: {task.terminal or 'running'}" + (f" — {task.stop_reason}" if task.stop_reason else ""))
    print(f"cost: ${task.cost_usd:.2f} of ${caps.max_usd + task.extra_usd:.2f}")
    print("units:" if task.units else "units: none yet")
    for unit in task.units:
        print(f"  {unit.id:<10} {unit.status:<9} attempts {unit.attempts}  {unit.intent}")
    question = mailbox.open_path(root, task.id)
    if question.exists():
        print(f"question: {question}")
    return 0


def _main(argv: Sequence[str] | None) -> int:
    args = build_parser().parse_args(argv)
    root = Root(args.brain.expanduser().resolve())
    try:
        if args.verb == "status":
            return status(root)
        if args.verb == "dry":
            task = dry.dry(args.scenario, root)
        elif args.verb == "run":
            task = loop.run(args.goal, args.workspace, root, load_caps(root), real_runner, args.project, echo=print)
        else:
            if args.extend and args.abandon:
                raise ValueError("--extend and --abandon do not go together")
            extends = [parse_extend(text) for text in args.extend or []]
            usd, ticks = sum((u for u, _ in extends), 0.0), sum(t for _, t in extends)
            task = loop.resume(root, load_caps(root), real_runner, usd, ticks, args.abandon, echo=print)
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"protean: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        print("protean: interrupted; any spend in flight is booked on the task. `protean resume` continues it.",
              file=sys.stderr)
        return EXIT_INTERRUPTED
    return EXIT.get(task.terminal or "", EXIT_USAGE)


def _interrupt(signum: int, frame: object) -> None:
    """SIGTERM and SIGHUP take the Ctrl-C path, so a closed terminal or a kill still books the spend."""
    raise KeyboardInterrupt


def main(argv: Sequence[str] | None = None) -> int:
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, _interrupt)
    return _main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
