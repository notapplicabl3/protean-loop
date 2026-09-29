"""Seam contract S3: the shipped manifest, its four rows, and the refusals around it.

`the build specification (not in this mirror)` \xa7 Deliverable 3's S3 table, \xa7 Resolutions S-22.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from protean import config
from protean.intake import policy_home
from protean.intake.chunks import CUTTERS
from protean.intake.manifest import IntakeManifest, load_manifest
from protean.state.errors import SchemaVersionMismatch


@pytest.fixture(scope="module")
def shipped(repo_root: Path) -> IntakeManifest:
    """The tracked seed, parsed once: every case below reads it and none of them writes."""
    return load_manifest(repo_root / "brain" / "intake" / "manifest.yaml")


def test_the_shipped_manifest_carries_S3s_four_rows(shipped: IntakeManifest) -> None:
    assert [row.source for row in shipped.sources] == ["docs", "projects", "feedback", "memory"]
    assert shipped.store_names() == ["docs", "projects", "feedback", "memory"]


def test_the_declared_granularity_is_per_source(shipped: IntakeManifest) -> None:
    """S-22: docs per heading, projects per row, feedback and memory per file."""
    declared = {row.source: row.granularity for row in shipped.sources}
    assert declared == {
        "docs": "heading",
        "projects": "row",
        "feedback": "file",
        "memory": "file",
    }


def test_only_the_memory_row_is_project_scoped(shipped: IntakeManifest) -> None:
    """S-12: `--project <slug>` selects which project memories enter, and nothing else."""
    scoped = [row.source for row in shipped.sources if row.project_scoped]
    assert scoped == ["memory"]


def test_every_declared_shape_has_a_cutter(shipped: IntakeManifest) -> None:
    """A shape without a cutter would write an empty store, which looks like success."""
    for row in shipped.sources:
        assert row.shape in CUTTERS


def test_every_declared_source_has_a_glob(shipped: IntakeManifest) -> None:
    for row in shipped.sources:
        assert row.source in policy_home.SOURCE_GLOBS


def test_no_source_glob_reaches_an_excluded_tree_or_file() -> None:
    """\xa7 Out of scope, stated over the globs themselves rather than over one run's output."""
    for patterns in policy_home.SOURCE_GLOBS.values():
        for pattern in patterns:
            assert not policy_home.is_excluded(pattern)


def test_the_manifest_carries_the_version_config_writes(shipped: IntakeManifest) -> None:
    assert shipped.schema_version == config.INTAKE_MANIFEST_SCHEMA_VERSION


def test_a_manifest_of_another_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "manifest.yaml"
    path.write_text("schema_version: 99\nsources: []\n", encoding="utf-8")
    with pytest.raises(SchemaVersionMismatch) as raised:
        load_manifest(path)
    assert "99" in str(raised.value)


def test_an_unknown_shape_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "manifest.yaml"
    path.write_text(
        "schema_version: %d\nsources:\n  - source: docs\n    store: docs\n"
        "    shape: telepathy\n    granularity: heading\n"
        % config.INTAKE_MANIFEST_SCHEMA_VERSION,
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_manifest(path)


def test_an_unknown_logical_source_is_refused() -> None:
    with pytest.raises(policy_home.UnknownSource):
        policy_home.source_files("skills")
