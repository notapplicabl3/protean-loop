"""The keyed-append primitive every runtime-written `.jsonl` file goes through.

`the build specification (not in this mirror)` § Deliverable 3 → *Idempotent replay is a physical rule*:
"every appended artifact is append-only; before appending, a writer reads the file's tail for
this tick's existing keys and treats a key collision as a **silent no-op**".

**Append-only is physical here, not asserted.** The module offers no path that truncates or
rewrites, so what is checked below is the property that follows: the bytes already in a file are
a prefix of the bytes after any write, whatever the payload was.
"""

from __future__ import annotations

import json
from pathlib import Path

from protean.brain.jsonl import (
    append_keyed,
    encode_line,
    existing_keys,
    iter_lines,
    read_lines,
)


def _key(payload: dict) -> tuple:
    return (payload["task"], payload["tick"])


def test_a_line_is_one_compact_json_document(tmp_path: Path):
    line = encode_line({"b": 1, "a": [1, 2]})
    assert line.endswith("\n")
    assert " " not in line
    assert json.loads(line) == {"b": 1, "a": [1, 2]}


def test_a_line_is_byte_stable_for_a_payload():
    assert encode_line({"a": 1}) == encode_line({"a": 1})


def test_non_ascii_survives_unescaped():
    assert "é" in encode_line({"a": "é"})


def test_a_missing_file_reads_as_no_records(tmp_path: Path):
    assert read_lines(tmp_path / "absent.jsonl") == []
    assert existing_keys(tmp_path / "absent.jsonl", _key) == set()


def test_blank_lines_are_skipped(tmp_path: Path):
    path = tmp_path / "f.jsonl"
    path.write_text('{"a":1}\n\n  \n{"a":2}\n', encoding="utf-8")
    assert read_lines(path) == [{"a": 1}, {"a": 2}]
    assert list(iter_lines(path)) == [{"a": 1}, {"a": 2}]


def test_the_parent_directory_is_created_on_demand(tmp_path: Path):
    path = tmp_path / "generated" / "f.jsonl"
    assert append_keyed(path, {"task": "t", "tick": 1}, key_fn=_key) is not None
    assert path.exists()


def test_a_key_collision_returns_none_and_writes_nothing(tmp_path: Path):
    path = tmp_path / "f.jsonl"
    payload = {"task": "t", "tick": 1}
    assert append_keyed(path, payload, key_fn=_key) == payload
    before = path.read_bytes()
    assert append_keyed(path, {"task": "t", "tick": 1, "extra": True}, key_fn=_key) is None
    assert path.read_bytes() == before


def test_a_distinct_key_lands(tmp_path: Path):
    path = tmp_path / "f.jsonl"
    append_keyed(path, {"task": "t", "tick": 1}, key_fn=_key)
    assert append_keyed(path, {"task": "t", "tick": 2}, key_fn=_key) is not None
    assert [record["tick"] for record in read_lines(path)] == [1, 2]


def test_the_existing_bytes_are_always_a_prefix_of_the_new_file(tmp_path: Path):
    path = tmp_path / "f.jsonl"
    seen = b""
    for tick in range(1, 6):
        append_keyed(path, {"task": "t", "tick": tick}, key_fn=_key)
        current = path.read_bytes()
        assert current.startswith(seen)
        seen = current


def test_existing_keys_is_the_tail_read_that_makes_a_replay_idempotent(tmp_path: Path):
    path = tmp_path / "f.jsonl"
    for tick in (1, 2):
        append_keyed(path, {"task": "t", "tick": tick}, key_fn=_key)
    assert existing_keys(path, _key) == {("t", 1), ("t", 2)}
