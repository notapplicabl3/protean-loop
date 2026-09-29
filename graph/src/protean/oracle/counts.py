"""The three structural counts — computed from the tree, never from a session.

`the build specification (not in this mirror)` § Deliverable 4: "Structural counts are computed from the
tree, not the session: docs on the path, commands to know, README lines before the first
runnable line." § Deliverable 5 fixes *which* tree: the **tracked** surface, because
`~/workload/.gitignore` makes `plans/`, `CLAUDE.md`, `architecture-logic.md`, `docs/` and `tools/`
maintainer-local and a clone carries none of them (folded: A1-15).

**The definitions are a builder's default and they are written down here** (dispatch-14 ledger
D14-5) so that order W8 recomputes the same three numbers after the change rather than three
differently-defined ones. Each is a count a coworker would recognise:

* **docs on the path** — the markdown a new developer is routed to: every tracked `*.md` that is
  not inside `.notes/` (that is the data corpus, not documentation) and not inside a Python
  package (a prompt contract living beside its stage is not a document on the path).
* **commands to know** — distinct command *signatures* named in fenced code blocks of those
  docs. A signature is `python -m <module>` where the line runs a module, else the first two
  tokens. Shell navigation is not a command to know.
* **README lines before the first runnable line** — how far a reader gets before the README
  shows something to type. The first fenced line whose first token is a runnable, minus one.

Nothing here reads a transcript, and nothing here is a threshold.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final

from protean.state.oracle import OracleStructuralCounts

#: The corpus directory. Data a coworker is handed, not documentation about the tree.
DATA_DIRNAME: Final[str] = ".notes"

#: What marks a directory as a Python package, and therefore its markdown as source-adjacent.
PACKAGE_MARKER: Final[str] = "__init__.py"

#: Executables a reader is expected to type. `cd`, `export` and friends are deliberately absent:
#: navigating is not a command to know.
RUNNABLES: Final[tuple[str, ...]] = (
    "uv",
    "python",
    "python3",
    "pytest",
    "git",
    "postman",
    "make",
    "npm",
    "node",
)

#: A fenced block's delimiter, and the prompt characters a doc may prefix a command with.
_FENCE = re.compile(r"^\s*(```|~~~)")
_PROMPT = re.compile(r"^\s*[$>]\s+")
_MODULE = re.compile(r"(^|\s)-m\s+(?P<module>[\w.]+)")


def tracked_files(tree: Path) -> list[str]:
    """Every path `git ls-files` reports — the surface a clone actually carries."""
    completed = subprocess.run(
        ["git", "-C", str(tree), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in completed.stdout.splitlines() if line]


def _in_package(tree: Path, relative: str) -> bool:
    parent = (tree / relative).parent
    while parent != tree and tree in parent.parents:
        if (parent / PACKAGE_MARKER).exists():
            return True
        parent = parent.parent
    return (tree / PACKAGE_MARKER).exists()


def docs_on_the_path(tree: Path, tracked: Iterable[str] | None = None) -> list[str]:
    """The markdown a new developer is routed to, sorted. The count is `len()` of this."""
    listed = list(tracked) if tracked is not None else tracked_files(tree)
    return sorted(
        relative
        for relative in listed
        if relative.endswith(".md")
        and Path(relative).parts[0] != DATA_DIRNAME
        and not _in_package(tree, relative)
    )


def fenced_lines(text: str) -> list[tuple[int, str]]:
    """Every line inside a fenced code block, with its one-based line number in the file."""
    inside = False
    lines: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        if _FENCE.match(line):
            inside = not inside
            continue
        if inside:
            lines.append((number, line))
    return lines


def _tokens(line: str) -> list[str]:
    return _PROMPT.sub("", line).strip().split()


def is_runnable(line: str) -> bool:
    """True when the line's first token is something a reader would type to run the project."""
    tokens = _tokens(line)
    return bool(tokens) and tokens[0] in RUNNABLES


def signature(line: str) -> str:
    """One command line → the signature it teaches. `python -m X` when it runs a module."""
    tokens = _tokens(line)
    if not tokens:
        return ""
    module = _MODULE.search(" ".join(tokens))
    if module is not None:
        return f"python -m {module.group('module')}"
    return " ".join(tokens[:2])


def commands_to_know(tree: Path, docs: Iterable[str] | None = None) -> list[str]:
    """Distinct command signatures the docs on the path name, sorted."""
    listed = list(docs) if docs is not None else docs_on_the_path(tree)
    found: set[str] = set()
    for relative in listed:
        text = (tree / relative).read_text(encoding="utf-8", errors="replace")
        for _, line in fenced_lines(text):
            if is_runnable(line):
                found.add(signature(line))
    return sorted(one for one in found if one)


def readme_lines_before_first_runnable(tree: Path, readme: str = "README.md") -> int:
    """How far a reader gets before the README shows a command. The whole file when it never does."""
    path = tree / readme
    if not path.is_file():
        return 0
    text = path.read_text(encoding="utf-8", errors="replace")
    for number, line in fenced_lines(text):
        if is_runnable(line):
            return number - 1
    return len(text.splitlines())


def structural_counts(tree: Path) -> OracleStructuralCounts:
    """The three counts, over one tree. The whole of § Deliverable 4's structural half."""
    docs = docs_on_the_path(tree)
    return OracleStructuralCounts(
        docs_on_the_path=len(docs),
        commands_to_know=len(commands_to_know(tree, docs)),
        readme_lines_before_first_runnable=readme_lines_before_first_runnable(tree),
    )


__all__: Sequence[str] = (
    "DATA_DIRNAME",
    "PACKAGE_MARKER",
    "RUNNABLES",
    "commands_to_know",
    "docs_on_the_path",
    "fenced_lines",
    "is_runnable",
    "readme_lines_before_first_runnable",
    "signature",
    "structural_counts",
    "tracked_files",
)
