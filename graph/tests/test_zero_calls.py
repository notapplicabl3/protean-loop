"""M21: the scripted task completes end to end and no model process is ever spawned.

`the build specification (not in this mirror)` § Deliverable 7 -> *The zero-call proof*, and § Directional
decisions 2 ("the build's headline proof is that no model process was spawned").

The row has two halves and this module holds both.

From build A.1.i the licensed exclusion list is still exactly two — `cortex/` (now holding the
tier-three spawn path under `live/`) and `oracle/` — and the shim's silence also proves that no
fixture kind's spawn ever reached the real binary (`the build specification (not in this mirror)`
§ DoD row G9).

* **The dynamic half.** A recording shim named for the model binary sits in `tests/shim/`,
  first on `PATH`, failing loudly and appending a line to a log on every invocation. A run
  passes only when that log is still zero bytes afterwards. Two cases prove it rather than one:
  the control fires the shim on purpose and asserts it records and fails, and the real case
  drives `protean dry dry` in a **subprocess** whose `PATH` starts at the shim, and asserts the
  log did not grow. Without the control an empty log would prove only that the shim is broken.
* **The static half.** No module under `src/protean/` outside the **two licensed packages**
  names the binary at all, so there is no code path to reach it from. The shim and this harness
  live under `tests/` and are outside that grep by construction -- the same shape ruling S-16
  uses to put policy citations outside M24's grep.

Neither half closes B9. That contracts a live cortex will honour are what these seats stand in
for is a judgment on evidence this build cannot produce, and it is the operator's row.

**Build 2 widened the exclusion list from one entry to two** (`the build specification (not in this mirror)`
§ Directional decisions 4, folded: S-1; `the work orders (not in this mirror)` order W6). The rule
did not change and neither did its meaning: *no model call outside the packages licensed to make
one*. There are now two -- `cortex/`, whose live subpackage spawns the seats, and `oracle/`,
whose synthetic dev spawns a measured session -- and the oracle is outside `cortex/` because it
is a measurement rather than a seat. The list is closed at two, and `test_the_grep_is_not_vacuous`
asserts that **each** excluded package really does name the binary, so an entry added to buy
silence fails instead.

**Build A.1 multiplied the callers and the list did not grow** (`the build specification (not in this mirror)` § Deliverable R, row R16; § Deliverable 2, decision 10). A tick is no longer one
call at step five: every outer node may think, escalate and delegate, and the manager dispatches
a wave of subagents — but all of them travel the **one** `(addressee, request) -> SeatEnvelope`,
and `cortex/` still holds every model call, **the tier-three seam included**. So the rule's
meaning is unchanged — *no model call outside the packages licensed to make one* — and the list
is still closed at **two**. A third entry would mean a second package learned to spawn, which is
exactly what decision 10's one port exists to prevent.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from protean import config

REPO_ROOT = Path(__file__).resolve().parents[1]
SHIM_DIR = REPO_ROOT / "tests" / "shim"

#: The binary the three cortex seats stand in for. Written once, here, so the static check
#: below greps for the same token the shim is named after.
BINARY = "claude"

#: The two packages the binary may be named in, and the whole exclusion list (decision 4,
#: folded: S-1). `cortex/` holds the seats -- in build 1 they did not spawn it and in build 2
#: their live subpackage does; `oracle/` holds the synthetic dev, which spawns a measured
#: session and is not a seat. Adding a third entry is a SPEC change, not a test edit.
SEAT_PACKAGE = REPO_ROOT / "src" / "protean" / "cortex"
ORACLE_PACKAGE = REPO_ROOT / "src" / "protean" / "oracle"
LICENSED_PACKAGES = (SEAT_PACKAGE, ORACLE_PACKAGE)

#: What the shim exits with. Deliberately outside every code `protean.config` names.
SHIM_EXIT = 89

DRY_SCENARIO = "dry"


def _modules_outside_the_licensed_packages() -> list[Path]:
    """Every module the static half greps: `src/protean/` less both licensed packages."""
    return [
        path
        for path in sorted((REPO_ROOT / "src" / "protean").rglob("*.py"))
        if not any(package in path.parents for package in LICENSED_PACKAGES)
    ]


def _shimmed_environment(log: Path) -> dict[str, str]:
    """This process's environment, with the shim first on `PATH` and the log pointed at `log`."""
    environment = dict(os.environ)
    environment["PATH"] = f"{SHIM_DIR}{os.pathsep}{environment.get('PATH', '')}"
    environment["PROTEAN_SHIM_LOG"] = str(log)
    return environment


@pytest.fixture()
def shim_log(tmp_path: Path) -> Path:
    """An empty log file, created before the run so `zero bytes` is a read and not an absence."""
    path = tmp_path / "invocations.log"
    path.write_text("", encoding="utf-8")
    return path


# --------------------------------------------------------------------------------------
# The dynamic half: the shim, its control, and the scripted run
# --------------------------------------------------------------------------------------


def test_the_shim_is_executable_and_is_what_path_resolves_to(shim_log: Path) -> None:
    """The premise of every claim below: with it installed, the name resolves to this file."""
    resolved = shutil.which(BINARY, path=_shimmed_environment(shim_log)["PATH"])
    assert resolved is not None, "the shim has to be found before it can prove anything"
    assert Path(resolved).resolve() == (SHIM_DIR / BINARY).resolve()
    assert os.access(SHIM_DIR / BINARY, os.X_OK)


def test_the_shim_records_and_fails_loudly_when_it_is_invoked(shim_log: Path) -> None:
    """The control. An empty log means nothing unless a real invocation would fill it."""
    completed = subprocess.run(
        [str(SHIM_DIR / BINARY), "-p", "anything"],
        env=_shimmed_environment(shim_log),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == SHIM_EXIT, "loudly: a non-zero exit the caller cannot ignore"
    assert SHIM_EXIT not in set(config.EXIT_CODES.values()), "and not a code this build names"
    assert "ZERO-CALL VIOLATION" in completed.stderr
    assert shim_log.stat().st_size > 0, "recording: the receipt outlives the process"
    assert "-p anything" in shim_log.read_text(encoding="utf-8")


def test_the_scripted_task_runs_end_to_end_with_the_shim_first_on_path(
    shim_log: Path,
) -> None:
    """M21's headline: the whole scenario, in a subprocess, with the shim in front of it."""
    completed = subprocess.run(
        [sys.executable, "-m", "protean.cli", "dry", DRY_SCENARIO],
        env=_shimmed_environment(shim_log),
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    print(completed.stdout)
    assert completed.returncode == config.EXIT_DONE, completed.stderr
    assert "terminal: done" in completed.stdout
    assert shim_log.stat().st_size == 0, (
        f"the shim was invoked: {shim_log.read_text(encoding='utf-8')}"
    )


def test_the_run_that_proves_it_is_the_one_that_completes_the_task(shim_log: Path) -> None:
    """A run that exited early would also leave an empty log; this pins the ticks it ran."""
    completed = subprocess.run(
        [sys.executable, "-m", "protean.cli", "dry", DRY_SCENARIO],
        env=_shimmed_environment(shim_log),
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    ticks = [line for line in completed.stdout.splitlines() if line.startswith("tick ")]
    assert len(ticks) >= 3, "plan, act, close -- an empty log over an empty run proves nothing"
    assert shim_log.stat().st_size == 0


# --------------------------------------------------------------------------------------
# The static half: no module outside the seat package names the binary
# --------------------------------------------------------------------------------------


def test_no_module_outside_the_licensed_packages_names_the_binary() -> None:
    named = [
        f"{path.relative_to(REPO_ROOT)}:{number}"
        for path in _modules_outside_the_licensed_packages()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if BINARY in line
    ]
    assert named == [], f"a module outside the licensed packages names the binary: {named}"


def test_the_exclusion_list_is_exactly_the_two_licensed_packages() -> None:
    """Decision 4's list, closed. A third package would be a SPEC change, not a test edit."""
    assert LICENSED_PACKAGES == (SEAT_PACKAGE, ORACLE_PACKAGE)
    assert [package.name for package in LICENSED_PACKAGES] == ["cortex", "oracle"]
    assert all(package.is_dir() for package in LICENSED_PACKAGES)


def test_the_grep_is_not_vacuous() -> None:
    """It walks real modules, and EACH excluded package is one that does name the binary.

    Per package, not in aggregate: with one entry proving the point for both, an exclusion
    added to silence a failure would ride along on the other one's evidence.
    """
    walked = _modules_outside_the_licensed_packages()
    assert len(walked) > 10, "the static half has to be looking at the package"
    assert all(
        package not in path.parents for path in walked for package in LICENSED_PACKAGES
    )
    for package in LICENSED_PACKAGES:
        inside = [
            path
            for path in sorted(package.rglob("*.py"))
            if BINARY in path.read_text(encoding="utf-8")
        ]
        assert inside, (
            f"{package.name}/ is excluded from the grep but names the binary nowhere -- "
            f"excluding it has to mean something"
        )


def test_the_harness_is_outside_the_grep_by_construction() -> None:
    """Ruling S-16's shape: the shim is named for the binary and lives outside the walked tree."""
    assert (SHIM_DIR / BINARY).exists()
    assert (REPO_ROOT / "src" / "protean") not in (SHIM_DIR / BINARY).parents
    assert all(package not in (SHIM_DIR / BINARY).parents for package in LICENSED_PACKAGES)
