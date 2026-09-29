"""The fifth verb end to end: the refusal, the printed file list, and idempotence.

`the build specification (not in this mirror)` \xa7 Deliverable 3, \xa7 DoD row W4 and builder rows K4 and K5,
\xa7 Resolutions A1-13, S-12, S-13, S-14, S-28.

**K4 and K5 are this order's own test list, not gates** (`the work orders (not in this mirror)`
\xa7 W4 Process step 8): they close nothing. Row W4's own machine half is asserted here too — the
seed marking, the manifest revision on every line, the untouched `brain/nodes/` tree and the
absence of any skill or registry — and closed on captured execution output, not on this file.

**The untouched-node-tree assertion is now conditional, and the condition is stated where it is
made.** Build 3 takes S-28's seeding half (`the build specification (not in this mirror)` \xa7 Deliverable 3),
so intake writes a weights key when — and only when — `brain/seeds.yaml` names it. This
module's brain root carries no such map, which is what still makes every store the only thing
these runs write; the seeding half's own arms are `tests/intake/test_seeds.py`'s.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from protean import cli, config
from protean.intake import run_intake
from protean.intake.policy_home import BadProjectSlug, ROOT_ENV
from protean.runtime.errors import RootOccupied
from protean.runtime.paths import BrainPaths
from protean.state.semantic import SemanticChunk, load_store
from tests.intake.conftest import node_tree_hashes


def _run(brain: BrainPaths, source_root: Path, **kwargs):
    return run_intake(brain, source_root=source_root, **kwargs)


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# --------------------------------------------------------------------------------------
# Row W4's machine half
# --------------------------------------------------------------------------------------


def test_every_written_record_carries_the_seed_marking_and_the_revision(
    seeded_brain: BrainPaths, source_root: Path
) -> None:
    outcome = _run(seeded_brain, source_root, project="demo")
    written = 0
    for path in outcome.files:
        for record in _lines(path):
            assert record["seed"] is True
            assert record["manifest_revision"] == outcome.manifest_revision
            written += 1
    assert written > 0, "an empty store set would pass every assertion above"


def test_the_seed_marking_is_a_property_of_the_type() -> None:
    """`seed` is `Literal[True]`: an unseeded chunk cannot be constructed, only refused."""
    with pytest.raises(ValueError):
        SemanticChunk(
            schema_version=config.SEMANTIC_CHUNK_SCHEMA_VERSION,
            chunk_id="semantic:0",
            store="docs",
            source="docs",
            text="t",
            seed=False,
            manifest_revision="r",
        )


def test_intake_writes_nothing_under_the_node_tree(
    seeded_brain: BrainPaths, source_root: Path
) -> None:
    """A root with no seeding map opens no weights file, so the node folders are byte-unchanged.

    Build 2 read this as "S-28 is deferred, so there is no map to open". Build 3 lands the map
    and the sentence survives with its condition made explicit: the assertion below is that
    intake writes **no key that `brain/seeds.yaml` does not name**, and here it names none.
    """
    assert not seeded_brain.seeds.exists(), "the condition this assertion rests on"
    nodes = seeded_brain.root / "nodes"
    nodes.mkdir(parents=True)
    for name in config.NODE_ORDER:
        folder = nodes / name
        folder.mkdir()
        (folder / "weights.yaml").write_text(f"# {name}\n", encoding="utf-8")

    before = node_tree_hashes(nodes)
    outcome = _run(seeded_brain, source_root, project="demo")
    assert node_tree_hashes(nodes) == before
    assert all(path.parent == seeded_brain.semantic for path in outcome.files)
    assert outcome.seeds == () and outcome.seed_files == ()


def test_no_chunk_names_a_skill_or_a_registry(
    seeded_brain: BrainPaths, source_root: Path
) -> None:
    """Q5's default: skills and registries are not sources, so they produce no record."""
    outcome = _run(seeded_brain, source_root, project="demo")
    assert not any(read.startswith("skills/") for read in outcome.sources_read)
    assert "skills.md" not in outcome.sources_read
    for path in outcome.files:
        for record in _lines(path):
            assert record["source"] in {"docs", "projects", "feedback", "memory"}
            assert "must not enter a store" not in record["text"]


# --------------------------------------------------------------------------------------
# K4 — the refusal, its exit code, and the printed file list
# --------------------------------------------------------------------------------------


def test_intake_is_refused_while_a_task_occupies_the_root(
    seeded_brain: BrainPaths, source_root: Path, occupy
) -> None:
    task_id = occupy()
    with pytest.raises(RootOccupied) as raised:
        _run(seeded_brain, source_root)
    assert task_id in str(raised.value)
    assert not seeded_brain.semantic.exists(), "a refused intake writes nothing"


def test_the_refusal_exits_on_its_own_code(
    seeded_brain: BrainPaths, source_root: Path, occupy, monkeypatch, capsys
) -> None:
    occupy()
    monkeypatch.setenv(ROOT_ENV, str(source_root))
    code = cli.main(["--brain", str(seeded_brain.root), "intake"])
    assert code == config.EXIT_INTAKE_REFUSED
    assert code == config.EXIT_CODES["intake_refused"]
    assert "already holds task" in capsys.readouterr().err


def test_a_done_task_does_not_occupy_the_root(
    seeded_brain: BrainPaths, source_root: Path, occupy
) -> None:
    occupy(terminal="done")
    assert _run(seeded_brain, source_root).files


def test_the_verb_prints_every_file_it_writes(
    seeded_brain: BrainPaths, source_root: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv(ROOT_ENV, str(source_root))
    code = cli.main(["--brain", str(seeded_brain.root), "intake", "--project", "demo"])
    assert code == config.EXIT_DONE
    printed = capsys.readouterr().out
    written = sorted(path for path in seeded_brain.semantic.glob("*.jsonl"))
    assert written, "the run wrote no store at all"
    for path in written:
        assert f"wrote {path}" in printed
    assert printed.count("wrote ") == len(written)


def test_a_bad_project_slug_is_refused_before_it_reaches_a_glob(
    seeded_brain: BrainPaths, source_root: Path
) -> None:
    with pytest.raises(BadProjectSlug):
        _run(seeded_brain, source_root, project="../escape")


# --------------------------------------------------------------------------------------
# K5 — determinism, byte-identity, and a revision that moves with the sources
# --------------------------------------------------------------------------------------


def test_a_second_intake_leaves_each_store_byte_identical(
    seeded_brain: BrainPaths, source_root: Path
) -> None:
    """S-14: replaced wholesale, so the second run is identical rather than doubled.

    Byte-identity is the stronger claim, and a weakening of it must not silently drop the
    weaker one: the same file set with the same bytes **implies** the same chunk-id set, which
    is why `test_the_same_source_produces_the_same_chunk_id_set` was removed here (audit row
    W6). If either assertion below is ever relaxed to something short of byte equality, the
    chunk-id claim has to come back as its own test.
    """
    first = _run(seeded_brain, source_root, project="demo")
    before = {path: path.read_bytes() for path in first.files}
    second = _run(seeded_brain, source_root, project="demo")
    assert second.files == first.files
    assert {path: path.read_bytes() for path in second.files} == before


def test_the_revision_changes_when_one_source_byte_changes(
    seeded_brain: BrainPaths, source_root: Path
) -> None:
    """S-13: content-derived, so two records carrying it were made from the same bytes.

    The manifest is the other input the revision is derived from, and its arm was an identical
    test modulo which file gets the byte (audit row W15): one baseline run, a byte appended to a
    source doc, a comment appended to the manifest, and a `!=` after each.
    """
    before = _run(seeded_brain, source_root, project="demo").manifest_revision

    doc = source_root / "docs" / "beta.md"
    doc.write_text(doc.read_text(encoding="utf-8") + "x", encoding="utf-8")
    after_source = _run(seeded_brain, source_root, project="demo").manifest_revision
    assert after_source != before

    manifest = seeded_brain.intake_manifest
    manifest.write_text(manifest.read_text(encoding="utf-8") + "\n# a comment\n", encoding="utf-8")
    assert _run(seeded_brain, source_root, project="demo").manifest_revision != after_source


# --------------------------------------------------------------------------------------
# S-12 — the project filter, applied at intake
# --------------------------------------------------------------------------------------


def test_only_the_named_project_memory_enters(
    seeded_brain: BrainPaths, source_root: Path
) -> None:
    _run(seeded_brain, source_root, project="demo")
    chunks = load_store(seeded_brain.semantic_store("memory"))
    assert [chunk.heading for chunk in chunks] == ["project_demo"]
    assert {chunk.project for chunk in chunks} == {"demo"}


def test_with_no_slug_the_project_store_is_written_empty(
    seeded_brain: BrainPaths, source_root: Path
) -> None:
    """The store set does not change shape with a flag: the file is written, with no lines."""
    outcome = _run(seeded_brain, source_root)
    store = seeded_brain.semantic_store("memory")
    assert store in outcome.files
    assert store.read_bytes() == b""
    assert load_store(store) == []


def test_the_project_tag_rides_only_on_the_project_scoped_store(
    seeded_brain: BrainPaths, source_root: Path
) -> None:
    outcome = _run(seeded_brain, source_root, project="demo")
    for path in outcome.files:
        for record in _lines(path):
            expected = "demo" if record["store"] == "memory" else None
            assert record["project"] == expected
