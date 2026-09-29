"""The one module licensed to know where the policy home is, and which of its files enter.

`the build specification (not in this mirror)` § Deliverable 3 ("The one licensed file is
`src/protean/intake/policy_home.py`"), § Directional decisions 5, § Out of scope, § Resolutions
A1-11, S-12, S-20.

**Content enters; structure never does** (decision 5, § Rulings 1). Everything about the policy
home that PROTEAN is allowed to know lives here: the root, and one glob per logical source. Every
other module in the build — the manifest, the chunker, the verb, the tests, the fixtures —
speaks only in the manifest's logical names, which is what keeps the whole tracked tree free of a
policy-home path with a licensed set of exactly one file.

**This is the one file in the build that spells the path**, and `ROOT_DEFAULT` below is the
line the exclusion list of row W4's grep exists for. `PROTEAN_INTAKE_ROOT` overrides it, which is
how the battery drives this module over a hand-authored fixture tree rather than over the live
home. Build 1's M24 module (`tests/test_policy_home_clean.py`) has not yet been re-based on
`git ls-files` and carries no exclusion list, so it fails on this line and on the gitignored
store both; that re-basing is § Resolutions S-20's own ruling and it lands in a file outside this
order's writable set — see the `BLOCKED` entry in the dispatch ledger, which carries the edit.

**What does not enter, by name.** Skills and registries are not intake sources (Q5's default,
§ Out of scope) — not the skill tree, not the parked skill tree, and not the top-level registries
except the project router, which enters as the *project-memory index* the S3 table names and
nothing else. Nor do the agent contracts, the hooks, the commands, the plans, the tools or the
scripts: those are structure, and structure is the thing decision 5 keeps out. `EXCLUDED_TREES`
and `EXCLUDED_FILES` state that refusal as data so a test can assert it instead of trusting the
globs to be narrow by accident.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

#: The environment variable that moves the root — the battery's seam, and an operator's escape
#: hatch. Named for PROTEAN because it is PROTEAN's variable, not the policy home's.
ROOT_ENV = "PROTEAN_INTAKE_ROOT"

#: The root default. The one licensed literal in the build (§ Deliverable 3, folded: A1-11):
#: every other module speaks in the manifest's logical names, and row W4's grep excludes this
#: file and no other.
ROOT_DEFAULT = "~/policy-home"

#: `--project <slug>` is interpolated into a glob, so it is validated before it gets there: a
#: slug is a memory file's suffix, never a path fragment.
SLUG = re.compile(r"[A-Za-z0-9_-]+")

#: One glob per logical source, relative to the root. `{slug}` marks the project-scoped source,
#: whose files enter only under `protean intake --project <slug>` (folded: S-12).
SOURCE_GLOBS: Mapping[str, tuple[str, ...]] = {
    "docs": ("docs/*.md",),
    "projects": ("projects.md",),
    "feedback": ("memory/feedback_*.md",),
    "memory": ("memory/project_{slug}.md",),
}

#: Trees no source glob reaches, stated so the refusal is data rather than an accident of the
#: globs above: the live and parked skill trees, and the structure-bearing directories.
EXCLUDED_TREES: tuple[str, ...] = (
    "skills",
    "skills-storage",
    "agents",
    "commands",
    "hooks",
    "plans",
    "scripts",
    "summary_reading",
    "tools",
)

#: Registries and shells no source glob reaches. The project router is deliberately absent: it
#: enters as the project-memory index (§ Deliverable 3's S3 table, folded: S-9), and it is the
#: only ALLCAPS file that does.
EXCLUDED_FILES: tuple[str, ...] = (
    "admin.md",
    "agents.md",
    "tokens.md",
    "skills-map.md",
    "skills.md",
    "settings.json",
)


class UnknownSource(ValueError):
    """The manifest names a logical source this module has no glob for."""


class BadProjectSlug(ValueError):
    """`--project` was given something that is not a memory file's suffix."""


def root(override: Path | None = None) -> Path:
    """The policy home: the explicit override, else `PROTEAN_INTAKE_ROOT`, else `ROOT_DEFAULT`."""
    if override is not None:
        return Path(override).expanduser().resolve()
    named = os.environ.get(ROOT_ENV)
    if named:
        return Path(named).expanduser().resolve()
    return Path(ROOT_DEFAULT).expanduser()


def check_slug(slug: str) -> str:
    """Refuse anything that is not a bare memory-file suffix before it reaches a glob."""
    if not SLUG.fullmatch(slug):
        raise BadProjectSlug(
            f"--project {slug!r} is not a project slug; expected letters, digits, "
            f"underscores or hyphens"
        )
    return slug


def source_files(
    source: str,
    *,
    project: str | None = None,
    override: Path | None = None,
) -> list[tuple[str, Path]]:
    """Every file one logical source resolves to, as `(logical path, absolute path)` pairs.

    The logical path is relative to the root, and it is what `manifest_revision` hashes (S-13) —
    an absolute path would make the revision machine-specific and two runs on two checkouts
    incomparable, which is the one thing that number exists to allow.

    A project-scoped source with no slug resolves to nothing: its store is still written, empty,
    so the store set does not change shape with a flag (folded: S-12).
    """
    globs = SOURCE_GLOBS.get(source)
    if globs is None:
        raise UnknownSource(f"no glob for logical source {source!r}; the sources are {sorted(SOURCE_GLOBS)}")
    base = root(override)
    found: dict[str, Path] = {}
    for pattern in globs:
        if "{slug}" in pattern:
            if project is None:
                continue
            pattern = pattern.format(slug=check_slug(project))
        for path in sorted(base.glob(pattern)):
            if path.is_file():
                found[path.relative_to(base).as_posix()] = path
    return [(logical, found[logical]) for logical in sorted(found)]


def is_excluded(logical_path: str) -> bool:
    """Whether a logical path is one of the trees or files no source may reach."""
    head = logical_path.split("/", 1)[0]
    return head in EXCLUDED_TREES or logical_path in EXCLUDED_FILES
