"""Seam contract S4: `SemanticChunk`, its id, its terms and the store it round-trips through.

`the build specification (not in this mirror)` \xa7 Deliverable 3's S4 field list, \xa7 Directional decisions 6
and 15, \xa7 Resolutions A1-10, S-13, S-14, S-20.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from protean import config
from protean.state.errors import SchemaVersionMismatch
from protean.state.semantic import (
    CHUNK_ID_PREFIX,
    SemanticChunk,
    chunk_id_of,
    load_store,
    load_stores,
    terms_of,
    write_store,
)


def make(text: str = "a chunk of seeded text about retrieval", **kwargs) -> SemanticChunk:
    payload = {
        "store": "docs",
        "source": "docs",
        "text": text,
        "manifest_revision": "abc123def456",
    }
    payload.update(kwargs)
    return SemanticChunk.of(**payload)


# --------------------------------------------------------------------------------------
# The field list
# --------------------------------------------------------------------------------------


def test_S4s_nine_fields_are_present_beside_the_schema_version() -> None:
    """The nine S4 names, plus `schema_version` — the sibling shape every persisted record has."""
    assert set(SemanticChunk.model_fields) == {
        "schema_version",
        "chunk_id",
        "store",
        "source",
        "heading",
        "text",
        "terms",
        "project",
        "seed",
        "manifest_revision",
    }


def test_an_unknown_field_is_refused() -> None:
    with pytest.raises(ValidationError):
        SemanticChunk.model_validate(make().model_dump() | {"path": "somewhere"})


def test_seed_is_true_and_cannot_be_anything_else() -> None:
    """Decision 6: build 3 weakens a seeded prior, which needs the marking to be unforgeable."""
    assert make().seed is True
    with pytest.raises(ValidationError):
        SemanticChunk.model_validate(make().model_dump() | {"seed": False})


def test_the_revision_is_required() -> None:
    payload = make().model_dump()
    payload.pop("manifest_revision")
    with pytest.raises(ValidationError):
        SemanticChunk.model_validate(payload)


def test_project_is_none_outside_the_project_scoped_store() -> None:
    assert make().project is None
    assert make(project="demo").project == "demo"


# --------------------------------------------------------------------------------------
# `chunk_id` and `terms`
# --------------------------------------------------------------------------------------


def test_the_id_is_the_prefixed_digest_of_the_text() -> None:
    chunk = make()
    assert chunk.chunk_id == chunk_id_of(chunk.text)
    assert chunk.chunk_id.startswith(CHUNK_ID_PREFIX)
    assert len(chunk.chunk_id) == len(CHUNK_ID_PREFIX) + 16


def test_the_id_is_deterministic_and_content_derived() -> None:
    assert chunk_id_of("same text") == chunk_id_of("same text")
    assert chunk_id_of("same text") != chunk_id_of("same text.")


def test_terms_are_lower_cased_deduplicated_and_sorted() -> None:
    terms = terms_of("Cache Discipline", "the cache holds; the CACHE reads")
    assert terms == sorted(set(terms))
    assert terms == [term.lower() for term in terms]
    assert terms.count("cache") == 1


def test_terms_drop_the_words_that_separate_nothing() -> None:
    assert "the" not in terms_of("the seat and the tier")
    assert "seat" in terms_of("the seat and the tier")


def test_terms_are_drawn_from_every_part_it_is_given() -> None:
    """The heading and a memory's `description` score even when the body never repeats them."""
    assert "consolidation" in terms_of("consolidation", "", "a body about nothing else")


# --------------------------------------------------------------------------------------
# The store
# --------------------------------------------------------------------------------------


def test_a_store_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "docs.jsonl"
    chunks = [make("first chunk"), make("second chunk")]
    assert write_store(path, chunks) == 2
    assert load_store(path) == chunks


def test_writing_a_store_twice_is_byte_identical(tmp_path: Path) -> None:
    """S-14: replaced wholesale, never appended to — the property idempotence rests on."""
    path = tmp_path / "docs.jsonl"
    chunks = [make("first chunk"), make("second chunk")]
    write_store(path, chunks)
    first = path.read_bytes()
    write_store(path, chunks)
    assert path.read_bytes() == first


def test_a_store_is_replaced_not_grown(tmp_path: Path) -> None:
    path = tmp_path / "docs.jsonl"
    write_store(path, [make("first chunk"), make("second chunk")])
    write_store(path, [make("only chunk")])
    assert [chunk.text for chunk in load_store(path)] == ["only chunk"]


def test_a_write_that_dies_midway_leaves_the_previous_store_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A store lands by temp-then-replace, as the checkpoint does (AUDIT 2026-09-19 D3)."""
    path = tmp_path / "docs.jsonl"
    write_store(path, [make("first chunk")])
    before = path.read_bytes()
    real_write = Path.write_text

    def dies_halfway(self: Path, data: str, *args, **kwargs):
        real_write(self, data[: len(data) // 2], *args, **kwargs)
        raise OSError("killed mid-write")

    monkeypatch.setattr(Path, "write_text", dies_halfway)
    with pytest.raises(OSError):
        write_store(path, [make("second chunk"), make("third chunk")])
    monkeypatch.undo()
    assert path.read_bytes() == before
    assert [one.text for one in load_store(path)] == ["first chunk"]


def test_an_absent_store_reads_as_no_chunks(tmp_path: Path) -> None:
    assert load_store(tmp_path / "missing.jsonl") == []


def test_load_stores_reads_the_files_it_is_given(tmp_path: Path) -> None:
    one, two = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    write_store(one, [make("first")])
    write_store(two, [make("second")])
    assert [chunk.text for chunk in load_stores([one, two])] == ["first", "second"]


def test_a_store_of_another_version_is_refused(tmp_path: Path) -> None:
    """Versioning is a refusal in build 2 as in build 1: no migration, both numbers quoted."""
    path = tmp_path / "docs.jsonl"
    write_store(path, [make(schema_version=99)])
    with pytest.raises(SchemaVersionMismatch) as raised:
        load_store(path)
    message = str(raised.value)
    assert "99" in message
    assert str(config.SEMANTIC_CHUNK_SCHEMA_VERSION) in message


def test_the_store_line_is_the_shared_jsonl_encoding(tmp_path: Path) -> None:
    """One document per line, no spaces — the same encoding every appended artifact uses."""
    path = tmp_path / "docs.jsonl"
    write_store(path, [make("a chunk")])
    line = path.read_text(encoding="utf-8")
    assert line.endswith("\n")
    assert ", " not in line.split('"text"')[0]
