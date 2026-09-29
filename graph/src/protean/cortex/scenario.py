"""A scenario: the goal a scripted run opens with, and the seat script that answers it.

`the build specification (not in this mirror)` § Deliverable 7 — `protean dry <scenario>` — and this order's
own output row, "the stuck scenario | `fixtures/scenarios/stuck/**` | goal + responders that
climb unit → planner → director to `stuck`".

**Two files, because they are two different things.** A seat script under
`fixtures/seat_scripts/` is a set of request-keyed responders and is reusable; a scenario under
`fixtures/scenarios/<name>/` is one goal plus the name of the script it drives. Keeping the goal
out of the script is what lets a second scenario reuse a responder set without copying it, and
keeping the script out of the scenario is what stops a scenario from becoming a turn list.

**A scenario names its script by stem, never by path.** `seat_script: stuck_ladder` resolves to
`fixtures/seat_scripts/stuck_ladder.yaml` under the repo the package was installed from, so a
scenario cannot reach outside the fixture tree and cannot be made machine-specific.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from protean import config
from protean.cortex.scripts import SeatScript, load_script

#: `fixtures/`, relative to the checkout `protean.config.repo_root()` resolves.
FIXTURES_DIR = "fixtures"

#: Where a hand-authored seat script lives, and the suffix it carries.
SEAT_SCRIPTS_DIR = "seat_scripts"
SCENARIOS_DIR = "scenarios"
FIXTURE_SUFFIX = ".yaml"

#: The one file a scenario directory must hold.
SCENARIO_FILENAME = f"scenario{FIXTURE_SUFFIX}"


class ScenarioError(ValueError):
    """A scenario directory that does not describe a scenario."""


def fixtures_root(repo: Path | None = None) -> Path:
    """`<repo>/fixtures` — every hand-authored fixture in the build lives under it."""
    return (repo or config.repo_root()) / FIXTURES_DIR


def script_path(stem: str, repo: Path | None = None) -> Path:
    """`fixtures/seat_scripts/<stem>.yaml`. A stem, so no scenario carries a machine path."""
    return fixtures_root(repo) / SEAT_SCRIPTS_DIR / f"{stem}{FIXTURE_SUFFIX}"


def scenario_path(name: str, repo: Path | None = None) -> Path:
    """`fixtures/scenarios/<name>/scenario.yaml`."""
    return fixtures_root(repo) / SCENARIOS_DIR / name / SCENARIO_FILENAME


@dataclass(frozen=True, slots=True)
class Scenario:
    """One scripted run: what it is called, what it is asked to do, and who answers."""

    name: str
    goal: str
    script: SeatScript


def load_scenario(name: str, repo: Path | None = None) -> Scenario:
    """Read `fixtures/scenarios/<name>/scenario.yaml` and the seat script it names."""
    path = scenario_path(name, repo)
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise ScenarioError(f"{path}: a scenario is a mapping")
    for key in ("goal", "seat_script"):
        if key not in loaded:
            raise ScenarioError(f"{path}: a scenario names its {key!r}")
    return Scenario(
        name=str(loaded.get("name", name)),
        goal=str(loaded["goal"]),
        script=load_script(script_path(str(loaded["seat_script"]), repo)),
    )
