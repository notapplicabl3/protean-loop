"""A hand-authored source tree shaped like the real one, and a brain root to seed from it.

`the work orders (not in this mirror)` \xa7 W4 Process step 8 — "driven from hand-authored source
fixtures". The fixture tree carries **no** policy-home path, exactly as every other file under
`tests/` does not: `protean.intake.policy_home` is the one module that resolves a root, and the tests
move that root with the variable it reads rather than by naming a location.

The manifest under test is the **shipped seed**, copied from `brain/intake/manifest.yaml`, so a
row added there without a cutter fails here rather than in a run.

`node_tree_hashes()` lives here rather than in either module because both of this battery's
"intake wrote nothing under `brain/nodes/`" claims are made with the same sha256-per-file walk,
and two spellings of one walk is two things to keep true.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from protean.runtime.paths import BrainPaths


def node_tree_hashes(nodes: Path) -> list[tuple[str, str]]:
    """Per-file sha256 over every file under a `nodes/` directory, sorted by relative path."""
    return [
        (path.relative_to(nodes).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest())
        for path in sorted(nodes.rglob("*"))
        if path.is_file()
    ]

#: A doc: an H1, two sections, and a fenced block whose comment line is not a heading.
ALPHA_DOC = """# Alpha — the first document

Opening prose about routing and dispatch.

## Cache discipline

A section about the cache and its receipts.

```bash
# not a heading, a shell comment
echo hello
```

## Seat economics

A section about seats, tiers and spend.
"""

#: A doc with no heading at all: one chunk, per S-22.
BETA_DOC = """Just prose about consolidation, with nothing that opens a section.

A second paragraph about the same thing.
"""

#: A registry: two rows that qualify, and prose that must not become one.
PROJECTS = """# Router

Some prose that opens with no bold marker and carries no Covers line.

**`~demo`** — the demonstration project, a fixture
- Covers: demo \xb7 fixture \xb7 chunking
- Map: its own map file

**`~other`** — the second project
- Covers: other \xb7 retrieval

**A bold line with no Covers bullet**
- Map: this block is not a row
"""

FEEDBACK_FIRST = """---
name: feedback_first
description: "The first feedback memory, about batching decisions"
metadata:
  type: feedback
---

Batch the decisions and answer them in one line.
"""

FEEDBACK_SECOND = """---
name: feedback_second
description: "The second feedback memory, about verification"
metadata:
  type: feedback
---

Show the receipt rather than the reading.
"""

PROJECT_DEMO = """---
name: project_demo
description: "The demo project's state"
metadata:
  type: project
---

The demo project is scaffolded and its store is seeded.
"""

PROJECT_OTHER = """---
name: project_other
description: "A project that is not under task"
metadata:
  type: project
---

This file enters only under its own slug.
"""

#: Neither of these may ever be read: skills and registries are not intake sources (Q5).
SKILL = "# a skill\n\nIt describes a capability and must not enter a store.\n"
REGISTRY = "# a registry\n\nIt indexes the skills and must not enter a store.\n"


@pytest.fixture()
def source_root(tmp_path: Path) -> Path:
    """A tree shaped like the real sources, holding what enters and what must not."""
    root = tmp_path / "sources"
    (root / "docs").mkdir(parents=True)
    (root / "memory").mkdir(parents=True)
    (root / "skills").mkdir(parents=True)
    (root / "docs" / "alpha.md").write_text(ALPHA_DOC, encoding="utf-8")
    (root / "docs" / "beta.md").write_text(BETA_DOC, encoding="utf-8")
    (root / "projects.md").write_text(PROJECTS, encoding="utf-8")
    (root / "memory" / "feedback_first.md").write_text(FEEDBACK_FIRST, encoding="utf-8")
    (root / "memory" / "feedback_second.md").write_text(FEEDBACK_SECOND, encoding="utf-8")
    (root / "memory" / "project_demo.md").write_text(PROJECT_DEMO, encoding="utf-8")
    (root / "memory" / "project_other.md").write_text(PROJECT_OTHER, encoding="utf-8")
    (root / "skills" / "one.md").write_text(SKILL, encoding="utf-8")
    (root / "skills.md").write_text(REGISTRY, encoding="utf-8")
    return root


@pytest.fixture()
def seeded_brain(tmp_path: Path, repo_root: Path) -> BrainPaths:
    """A throwaway brain root carrying the shipped manifest seed and nothing else."""
    root = tmp_path / "brain"
    (root / "intake").mkdir(parents=True)
    shutil.copy(
        repo_root / "brain" / "intake" / "manifest.yaml", root / "intake" / "manifest.yaml"
    )
    return BrainPaths(root=root)


@pytest.fixture()
def occupy(seeded_brain: BrainPaths):
    """Put a task on the root with a committed terminal that is not `done`."""

    def _occupy(task_id: str = "task-fixture", terminal: str | None = None) -> str:
        checkpoint = seeded_brain.task(task_id).checkpoint
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_text(
            '{"state": {"terminal": %s}}' % ("null" if terminal is None else f'"{terminal}"'),
            encoding="utf-8",
        )
        return task_id

    return _occupy
