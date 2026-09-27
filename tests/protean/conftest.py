"""Shared fixtures for the protean battery: the model-binary shim on PATH, and a scratch brain root."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from protean.state import Predicate, Root, Task, Unit

SHIM_DIR = Path(__file__).resolve().parent / "shim"


@pytest.fixture(autouse=True)
def shim_on_path(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put the failing `claude` shim first on PATH, so no test can reach a real model."""
    monkeypatch.setenv("PATH", f"{SHIM_DIR}{os.pathsep}{os.environ.get('PATH', '')}")
    return SHIM_DIR


@pytest.fixture
def root(tmp_path: Path) -> Root:
    """An empty brain root under the test's tmp dir."""
    return Root(tmp_path / "brain")


@pytest.fixture
def task() -> Task:
    """A small task with one pending unit."""
    unit = Unit(id="u1", intent="write a.txt", predicates=[Predicate("file_exists", {"path": "a.txt"})])
    return Task(id="task-20260927T120000", goal="make a.txt", workspace="/tmp/ws", units=[unit])
