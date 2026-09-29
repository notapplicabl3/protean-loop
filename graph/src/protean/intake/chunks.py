"""Cutting one source document at the granularity its manifest row declares.

`the build specification (not in this mirror)` § Deliverable 3's S4 granularity rule (folded: S-22): docs
per heading, projects per row, feedback and memory per file — and a heading-less file is one
chunk.

**Three cutters, no guessing.** The manifest says which one runs; nothing here sniffs a document
to decide. A shape the manifest declares and a document that does not match it produces one
whole-file chunk rather than a silent zero, because an empty store is the failure mode that
looks like success.

**Fences are not headings.** Every policy document in the sources carries fenced code blocks
whose lines begin with `#`, so the section cutter tracks fences and a comment inside one never
opens a chunk. That is the single non-obvious rule in this module and the reason it is a module
rather than three regexes at the call site.

Nothing here reads a file or names a path: it takes text and returns pieces of it, which is what
keeps the licensed set at one file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import yaml

#: An ATX heading at column zero, any level.
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")

#: A fence opener or closer — three or more backticks or tildes at column zero.
_FENCE = re.compile(r"^(```+|~~~+)")

#: The frontmatter delimiter, and the two keys a memory document carries that are worth scoring
#: on: its `name` is the document's heading and its `description` is the one-line summary the
#: body never restates.
_FRONTMATTER = "---"

#: A registry row opens with a bold line at column zero and carries a `Covers:` bullet. Both
#: halves are required: bold text alone appears in prose, and a row without `Covers:` is not one.
_ROW_HEAD = re.compile(r"^\*\*")
_ROW_COVERS = re.compile(r"^-\s*\*{0,2}Covers:")

#: The label of a registry row: its first backticked token, else its bold text.
_ROW_LABEL_TICKED = re.compile(r"`([^`]+)`")
_ROW_LABEL_BOLD = re.compile(r"^\*\*(.+?)\*\*")


@dataclass(frozen=True, slots=True)
class Piece:
    """One cut of a document: what becomes one `SemanticChunk`.

    `extra` is text that scores but is not part of the chunk's body — a memory document's
    frontmatter `description`, which summarises the file better than any line inside it and
    which the store has no reason to hold verbatim.
    """

    heading: str
    text: str
    extra: str = ""


def markdown_sections(text: str) -> list[Piece]:
    """One piece per markdown heading, the heading line included in its own text.

    The heading rides inside `text` rather than beside it so that `chunk_id` is the digest of the
    section *as written* and a seat that receives the body also receives what it is a section of.
    Text before the first heading is its own heading-less piece when it holds anything.
    """
    pieces: list[Piece] = []
    heading = ""
    body: list[str] = []
    fenced = False

    def flush() -> None:
        joined = "\n".join(body).strip("\n")
        if joined.strip():
            pieces.append(Piece(heading=heading, text=joined))

    for line in text.splitlines():
        if _FENCE.match(line):
            fenced = not fenced
        match = None if fenced else _HEADING.match(line)
        if match is None:
            body.append(line)
            continue
        flush()
        heading = match.group(2).strip()
        body = [line]
    flush()
    return pieces or whole_document(text)


def registry_rows(text: str) -> list[Piece]:
    """One piece per registry row: a bold opening line and the bullets beneath it.

    A block is a row when it opens bold **and** carries a `Covers:` bullet, which is the shape
    the register itself documents. Everything else in the file — the protocol prose, the section
    headings, the HTML comment — is structure, and structure does not enter (decision 5).
    """
    pieces: list[Piece] = []
    for block in _blocks(text):
        first = block[0]
        if not _ROW_HEAD.match(first):
            continue
        if not any(_ROW_COVERS.match(line) for line in block[1:]):
            continue
        pieces.append(Piece(heading=_row_label(first), text="\n".join(block)))
    return pieces


def frontmatter_document(text: str) -> list[Piece]:
    """The whole document as one piece, its YAML frontmatter lifted off the body (S-22).

    The frontmatter is layout, so it does not enter the store's text; its `name` becomes the
    piece's heading and its `description` becomes text the terms are drawn from, because it is
    the one line that says what the whole file is for.
    """
    heading, description, body = split_frontmatter(text)
    stripped = body.strip("\n")
    if not stripped.strip():
        stripped = text.strip("\n")
    return [Piece(heading=heading, text=stripped, extra=description)]


def whole_document(text: str) -> list[Piece]:
    """The fallback every cutter shares: a document with no cut points is one chunk."""
    stripped = text.strip("\n")
    return [Piece(heading="", text=stripped)] if stripped.strip() else []


#: The manifest's `shape` → the cutter that runs. A closed table: `manifest.py`'s `Shape`
#: literal and this mapping are asserted equal by the battery, so a shape cannot be declared
#: without a cutter.
CUTTERS = {
    "markdown_sections": markdown_sections,
    "registry_rows": registry_rows,
    "frontmatter_document": frontmatter_document,
}


def cut(shape: str, text: str) -> list[Piece]:
    """Run the cutter the manifest's shape names."""
    return CUTTERS[shape](text)


def split_frontmatter(text: str) -> tuple[str, str, str]:
    """`(name, description, body)` — an absent or malformed frontmatter yields two empty strings."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER:
        return "", "", text
    for index in range(1, len(lines)):
        if lines[index].strip() != _FRONTMATTER:
            continue
        block = "\n".join(lines[1:index])
        body = "\n".join(lines[index + 1 :])
        try:
            payload = yaml.safe_load(block) or {}
        except yaml.YAMLError:
            return "", "", text
        if not isinstance(payload, dict):
            return "", "", text
        name = payload.get("name")
        description = payload.get("description")
        return (
            str(name) if isinstance(name, str) else "",
            str(description) if isinstance(description, str) else "",
            body,
        )
    return "", "", text


def _blocks(text: str) -> list[list[str]]:
    """The document as blank-line-separated blocks of non-empty lines."""
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.strip():
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def _row_label(line: str) -> str:
    """A row's own name: the first backticked token, else the bold text, else the line."""
    ticked = _ROW_LABEL_TICKED.search(line)
    if ticked is not None:
        return ticked.group(1).strip()
    bold = _ROW_LABEL_BOLD.match(line)
    return bold.group(1).strip() if bold is not None else line.strip()
