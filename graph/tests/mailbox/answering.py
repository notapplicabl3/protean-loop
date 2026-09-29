"""What the operator does with an editor: write a body under the literal `## Answer` heading.

`the build specification (not in this mirror)` § Deliverable 5 → *The writable set, named*: "**exactly one
path is writable by anything that is not the runtime process — the `## Answer` body of an open
mailbox file**." `src/protean/mailbox/` is the runtime, so it ships no writer for that path; a
battery that needs to stand in for the person at the keyboard supplies one, exactly as W2's own
stub did (`tests/runtime/stubs.py`).

The helper writes **only** below the heading and leaves every byte above it untouched, which is
what makes it a stand-in for a person editing the file rather than a second renderer.
"""

from __future__ import annotations

from pathlib import Path

from protean.state.interrupts import ANSWER_HEADING


def answer(path: Path, text: str) -> Path:
    """Write `text` under the file's `## Answer` heading, changing nothing above it."""
    source = path.read_text(encoding="utf-8")
    head, heading, _ = source.partition(ANSWER_HEADING)
    if not heading:
        raise AssertionError(f"{path} carries no {ANSWER_HEADING!r} heading to answer under")
    path.write_text(f"{head}{ANSWER_HEADING}\n\n{text}\n", encoding="utf-8")
    return path


def leave_unanswered(path: Path) -> Path:
    """Save the file without typing anything — the shape "silence is never assent" is about."""
    return answer(path, "   \n\t ")
