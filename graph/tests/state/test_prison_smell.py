"""M23: the ratio is derived by reflection, printed with both field lists, never written down.

`the build specification (not in this mirror)` § Deliverable 7 → *The prison smell metric*.

The row has two halves and this module holds both:

* **derived, not asserted** — the reporter is run and its output is checked for the two field
  lists and the ratio line, with no expected value anywhere; and
* **no hardcoded count anywhere** — every `.py` file under `src/` and `tests/` is parsed and
  its numeric literals are compared against the counts the reporter just derived. A count
  written down would be found even inside a docstring's f-string, because the check is on the
  values, not on a regular expression over the text.

The judgment itself is B7's and it is the operator's. Nothing here asserts a threshold, and nothing here
should ever grow one: the fear is theirs, so the reading is theirs.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from protean.state import MODELS
from tests.state.prison_smell import CONSTRAINED, FREE, STRUCTURAL, classify, derive, render

SCANNED_TREES = ("src", "tests")


@pytest.fixture(scope="module")
def report():
    """One reflection pass for the module: `derive()` walks every exported contract's fields and
    every case below only reads the report it returns."""
    return derive()


@pytest.fixture(scope="session")
def python_sources(repo_root) -> dict[Path, str]:
    """Every `.py` file under `src/` and `tests/`, read once, path → text.

    The two hardcoding checks both need the whole tree; reading it once means one walk and one
    decode rather than one per check, and the `ast.parse` of each text stays where the check
    that needs a syntax tree is.
    """
    return {
        path: path.read_text(encoding="utf-8")
        for tree in SCANNED_TREES
        for path in sorted((repo_root / tree).rglob("*.py"))
    }


def test_every_exported_contract_is_walked(report) -> None:
    total_fields = sum(len(m.model_fields) for m in MODELS)
    assert len(report.constrained) + len(report.free) + len(report.structural) == total_fields


def test_both_field_lists_are_non_empty_and_disjoint(report) -> None:
    assert report.constrained and report.free
    assert set(report.constrained).isdisjoint(report.free)
    assert set(report.constrained).isdisjoint(report.structural)
    assert set(report.free).isdisjoint(report.structural)


def test_the_report_prints_both_lists_and_the_derived_ratio(report, capsys) -> None:
    from tests.state.prison_smell import main

    assert main() == 0
    printed = capsys.readouterr().out
    assert "ENUM / BOOLEAN FIELDS" in printed
    assert "FREE-TEXT / SCORED FIELDS" in printed
    assert "RATIO" in printed
    for name in (report.constrained[0], report.free[0]):
        assert name in printed
    assert f"{len(report.constrained)} : {len(report.free)}" in printed


def test_the_ratio_is_the_quotient_of_the_two_lists(report) -> None:
    assert report.ratio == pytest.approx(len(report.constrained) / len(report.free))
    assert report.rated == len(report.constrained) + len(report.free)


def test_the_classifier_reads_the_leaf_of_a_container() -> None:
    """`list[TrapDetector]` is constrained; `list[str]` is free; `list[WorkUnit]` is neither."""
    from protean.state import ManagerPlan, TrapScalar, WorkUnit

    assert classify(ManagerPlan.model_fields["trap_dismissed"].annotation) == CONSTRAINED
    assert classify(ManagerPlan.model_fields["cited_ids"].annotation) == FREE
    assert classify(ManagerPlan.model_fields["units"].annotation) == STRUCTURAL
    assert classify(WorkUnit.model_fields["irreversible"].annotation) == CONSTRAINED
    assert classify(TrapScalar.model_fields["value"].annotation) == FREE


def numeric_literals(path: Path, text: str) -> list[tuple[str, int, float]]:
    """Every non-boolean numeric constant in one already-read source file."""
    found: list[tuple[str, int, float]] = []
    for node in ast.walk(ast.parse(text)):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
        ):
            found.append((str(path), node.lineno, node.value))
    return found


def test_no_count_or_rendered_ratio_the_reporter_derives_is_written_down_anywhere(
    report, python_sources
) -> None:
    """M23's second half, over `src/` and `tests/` both — the counts *and* the rendered strings.

    Both halves are one walk of the same tree: the four derived counts must appear as no numeric
    literal anywhere, and the three rendered forms (the ratio, the constrained share, the
    `n : m` line) must appear in no text. Two offender lists, asserted empty with their own
    messages, so a failure still names which kind of hardcoding was found.

    A count written down would be found even inside a docstring's f-string, because the check is
    on the values, not on a regular expression over the text.
    """
    derived = {
        len(report.constrained),
        len(report.free),
        len(report.structural),
        report.rated,
    }
    strings = (
        f"{report.ratio:.3f}",
        f"{report.constrained_share:.1%}",
        f"{len(report.constrained)} : {len(report.free)}",
    )

    counts: list[tuple[str, int, float]] = []
    ratios: list[tuple[str, str]] = []
    for path, text in python_sources.items():
        counts.extend(
            (found_path, line, value)
            for found_path, line, value in numeric_literals(path, text)
            if value in derived
        )
        ratios.extend((str(path), needle) for needle in strings if needle in text)

    assert counts == [], f"a derived count is hardcoded: {counts}"
    assert ratios == [], f"a derived ratio is hardcoded: {ratios}"


def test_the_reporter_asserts_no_threshold(report) -> None:
    """The judgment is B7's. A threshold here would close the operator's row with a builder's opinion."""
    source = Path(__import__("tests.state.prison_smell", fromlist=["x"]).__file__)
    text = source.read_text(encoding="utf-8")
    assert "assert " not in text
    assert "No threshold is asserted." in render(report)
