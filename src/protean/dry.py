"""Scripted seats for the dry path, so the battery and `protean dry` never reach a model."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from protean import loop
from protean.budget import load_caps
from protean.runner import RunResult
from protean.state import Root, Task

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "fixtures" / "protean"
SEED_FILES = ("director.md", "editor.md", "config.json")
GIT_ID = ["-c", "user.name=protean dry", "-c", "user.email=dry@protean.invalid"]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """One object per non-blank line; a missing file is an empty script."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *GIT_ID, *args], cwd=cwd, check=True, capture_output=True, text=True)


class ScriptedRunner:
    """A Runner that answers from two queues and records every call it is given.

    A director entry is the whole stdout object the CLI would print. A worker entry acts inside
    the clone it is started in: `write` files, `delete` paths, `commit` them, then report `result` with an
    `exit_code: N` line and `total_cost_usd`.
    """

    def __init__(self, director: list[dict[str, Any]], worker: list[dict[str, Any]]) -> None:
        self.director, self.worker = list(director), list(worker)
        self.calls: list[tuple[list[str], str | None, Path, int]] = []

    def __call__(self, argv: list[str], stdin: str | None, cwd: Path, timeout: int) -> RunResult:
        if not argv or argv[0] != "claude":
            raise ValueError(f"the scripted runner only answers model calls, got {argv[:1]}")
        self.calls.append((argv, stdin, cwd, timeout))
        seat, queue = ("worker", self.worker) if "Write" in argv else ("director", self.director)
        if not queue:
            raise RuntimeError(f"the scripted {seat} has no reply left")
        entry = queue.pop(0)
        return RunResult(0, json.dumps(entry), "") if seat == "director" else self._work(entry, Path(cwd))

    @staticmethod
    def _work(entry: dict[str, Any], clone: Path) -> RunResult:
        for rel, content in entry.get("write", {}).items():
            path = clone / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        for rel in entry.get("delete", []):
            (clone / rel).unlink()
        if entry.get("commit"):
            _git(["add", "-A"], clone)
            _git(["commit", "--quiet", "--allow-empty", "-m", "dry: scripted worker"], clone)
        if entry.get("timed_out"):
            return RunResult(-9, "", "", True)
        result = entry.get("result", "")
        if "exit_code" in entry:
            result += f"\nexit_code: {entry['exit_code']}"
        receipt = {"type": "result", "is_error": False, "session_id": "dry-worker", "result": result,
                   "total_cost_usd": entry.get("total_cost_usd", 0.0)}
        return RunResult(entry.get("returncode", 0), json.dumps(receipt), "")


def scenario_runner(scenario: str) -> ScriptedRunner:
    """The scripted runner for `fixtures/protean/<scenario>/`."""
    folder = FIXTURES / scenario
    if not (folder / "director.jsonl").is_file():
        known = sorted(p.name for p in FIXTURES.iterdir() if (p / "director.jsonl").is_file())
        raise ValueError(f"unknown scenario {scenario!r} (known: {', '.join(known)})")
    return ScriptedRunner(read_jsonl(folder / "director.jsonl"), read_jsonl(folder / "worker.jsonl"))


def make_workspace(path: Path) -> Path:
    """A one-commit git repository to run a scenario against."""
    path.mkdir(parents=True)
    (path / "README.md").write_text("# dry workspace\n", encoding="utf-8")
    _git(["init", "--quiet", "-b", "main"], path)
    _git(["add", "-A"], path)
    _git(["commit", "--quiet", "-m", "dry: seed"], path)
    return path


def dry(scenario: str, root_template: Root, echo: loop.Echo = print) -> Task:
    """Run a scenario on a scratch root and workspace, both removed afterwards."""
    runner = scenario_runner(scenario)
    scratch = Path(tempfile.mkdtemp(prefix="protean-dry-"))
    try:
        root = Root(scratch / "brain")
        root.path.mkdir()
        for name in SEED_FILES:
            shutil.copy2(root_template.path / name, root.path / name)
        workspace = make_workspace(scratch / "workspace")
        echo(f"dry {scenario}: scripted seats on a scratch root")
        return loop.run(f"dry scenario: {scenario}", workspace, root, load_caps(root), runner, echo=echo)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
