"""The one subprocess seam for model calls, and the dollar cap each call may carry.

A Runner takes argv, stdin, cwd and a wall timeout and returns a RunResult. Every call's
`--max-budget-usd` is its configured cap clipped to what the task has left; below the call floor
no call is made at all.
"""

from __future__ import annotations

import math
import os
import signal
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from protean.budget import Caps
from protean.state import Task

KILL_DRAIN_SECONDS = 5
CALL_FLOOR_USD = 0.50


@dataclass
class RunResult:
    """What one process left behind. `timed_out` means the wall cap killed its process group."""

    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


Runner = Callable[[list[str], str | None, Path, int], RunResult]
Charge = Callable[[float], None]


def no_charge(usd: float) -> None:
    """The default `charge`: a caller that keeps no books."""


def usd_left(task: Task, caps: Caps, spent: float = 0.0) -> float:
    """Dollars left under the task's ceiling, after `spent` more."""
    return caps.max_usd + task.extra_usd - task.cost_usd - spent


def _cents(value: float) -> str:
    """Dollars rounded down to the cent, never below zero."""
    return f"{max(math.floor(value * 100 + 1e-9) / 100, 0.0):.2f}"


def floor_reason(task: Task, caps: Caps, spent: float = 0.0) -> str | None:
    """Why no call may be made: less left than the call floor. None while a call may be made."""
    left = usd_left(task, caps, spent)
    if left < CALL_FLOOR_USD:
        return f"max_usd: remaining ${_cents(left)} below the ${CALL_FLOOR_USD:.2f} call floor"
    return None


def usd_cap(configured: float, task: Task, caps: Caps, spent: float = 0.0) -> str:
    """The `--max-budget-usd` value: the configured cap clipped to what is left, down to the cent."""
    return _cents(min(configured, usd_left(task, caps, spent)))


def charged_cap(argv: list[str]) -> float:
    """The `--max-budget-usd` a call carried: what it costs when it leaves no usable receipt."""
    return float(argv[argv.index("--max-budget-usd") + 1])


def _kill_group(proc: subprocess.Popen) -> None:
    """SIGKILL the child's whole process group, so the tools it started die with it."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except OSError:
        proc.kill()


def real_runner(argv: list[str], stdin: str | None, cwd: Path, timeout: int) -> RunResult:
    """Run `argv` in its own session; on timeout kill the group and report `timed_out`.

    Any other interruption (Ctrl-C included, which the child's own session never sees) kills the
    group too before it propagates.
    """
    try:
        proc = subprocess.Popen(
            argv, cwd=cwd, text=True, start_new_session=True,
            stdin=subprocess.DEVNULL if stdin is None else subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except OSError as exc:
        return RunResult(127, "", f"could not start {argv[0]}: {exc}")
    try:
        out, err = proc.communicate(stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        try:
            out, err = proc.communicate(timeout=KILL_DRAIN_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = "", ""
        return RunResult(proc.returncode if proc.returncode is not None else -9, out or "", err or "", True)
    except BaseException:
        _kill_group(proc)
        try:
            proc.wait(timeout=KILL_DRAIN_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        raise
    return RunResult(proc.returncode, out, err)
