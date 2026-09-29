"""The three cutters, at the granularity S-22 declares.

`the build specification (not in this mirror)` \xa7 Deliverable 3's S4 granularity rule.
"""

from __future__ import annotations

from protean.intake.chunks import (
    CUTTERS,
    cut,
    frontmatter_document,
    markdown_sections,
    registry_rows,
    split_frontmatter,
)
from tests.intake.conftest import ALPHA_DOC, BETA_DOC, FEEDBACK_FIRST, PROJECTS


def test_a_doc_is_cut_once_per_heading() -> None:
    pieces = markdown_sections(ALPHA_DOC)
    assert [piece.heading for piece in pieces] == [
        "Alpha — the first document",
        "Cache discipline",
        "Seat economics",
    ]


def test_a_comment_inside_a_fence_is_not_a_heading() -> None:
    """The one non-obvious rule: every source document fences shell, and shell comments start `#`."""
    pieces = markdown_sections(ALPHA_DOC)
    cache = next(piece for piece in pieces if piece.heading == "Cache discipline")
    assert "not a heading, a shell comment" in cache.text
    assert not any(piece.heading.startswith("not a heading") for piece in pieces)


def test_a_section_carries_its_own_heading_line() -> None:
    """`chunk_id` is the digest of the section as written, heading included."""
    pieces = markdown_sections(ALPHA_DOC)
    assert pieces[1].text.startswith("## Cache discipline")


def test_a_heading_less_document_is_one_chunk() -> None:
    """S-22, stated exactly: a file with no heading is one chunk, never zero."""
    pieces = markdown_sections(BETA_DOC)
    assert len(pieces) == 1
    assert pieces[0].heading == ""
    assert "consolidation" in pieces[0].text


def test_a_registry_is_cut_once_per_row() -> None:
    pieces = registry_rows(PROJECTS)
    assert [piece.heading for piece in pieces] == ["~demo", "~other"]


def test_prose_and_a_bold_line_without_covers_are_not_rows() -> None:
    """Both halves of the row shape are required, so structure does not enter as content."""
    texts = "\n".join(piece.text for piece in registry_rows(PROJECTS))
    assert "not a row" not in texts
    assert "opens with no bold marker" not in texts


def test_a_row_carries_its_covers_line() -> None:
    """S3: a project row's `Covers:` terms are the index the lexical match runs over."""
    demo = registry_rows(PROJECTS)[0]
    assert "- Covers: demo" in demo.text


def test_a_frontmatter_document_is_one_piece_without_its_frontmatter() -> None:
    pieces = frontmatter_document(FEEDBACK_FIRST)
    assert len(pieces) == 1
    assert pieces[0].heading == "feedback_first"
    assert "metadata" not in pieces[0].text
    assert pieces[0].text.startswith("Batch the decisions")


def test_the_description_scores_but_is_not_stored() -> None:
    """The one line that says what a memory is for feeds `terms`, never the verbatim text."""
    piece = frontmatter_document(FEEDBACK_FIRST)[0]
    assert "batching decisions" in piece.extra
    assert "batching decisions" not in piece.text


def test_a_document_with_no_frontmatter_survives_whole() -> None:
    name, description, body = split_frontmatter(BETA_DOC)
    assert (name, description) == ("", "")
    assert body == BETA_DOC


def test_a_malformed_frontmatter_is_not_a_crash() -> None:
    text = "---\n: : :\n---\nbody\n"
    name, description, body = split_frontmatter(text)
    assert (name, description) == ("", "")
    assert body == text


def test_cut_dispatches_on_the_manifests_shape() -> None:
    assert cut("markdown_sections", ALPHA_DOC) == markdown_sections(ALPHA_DOC)
    assert set(CUTTERS) == {"markdown_sections", "registry_rows", "frontmatter_document"}
