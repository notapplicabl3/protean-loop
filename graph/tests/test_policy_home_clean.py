"""M24: no file in the build names a path under the two policy-home prefixes.

`the build specification (not in this mirror)` § Rulings 1 and § Directional decisions 7 -- build 1 is
designed from scratch and stays clean of the policy home's structure **and** content: no doc,
memory, registry, skill or agent contract of it is read into a store, copied as a fixture, or
mirrored as a layout. Its *process* governs how the SPEC was written, which is a different
thing.

**Four trees, two prefixes, and that is the whole check.** `src/`, `tests/`, `brain/` and
`fixtures/` (folded: S-16). The contract docs -- `plans/`, `docs/`, `CLAUDE.md`, `README.md`,
`architecture.md`, `architecture-logic.md` -- are outside it by construction: they cite the
process that produced the build, and a citation is not an import.

**From build 2 the check runs over tracked files, with one licensed exception** (build 2's
§ Resolutions S-20 and A1-11): the gitignored semantic store holds source text verbatim by design,
and `src/protean/intake/policy_home.py` is the one file that may name the root.

**This is a path check, not a semantic one, and the SPEC says so** (§ Named assumptions 13): "a
convention absorbed by *imitation* would pass it. The mitigation is the layout being derived
from the node set, and it is a judgment, not a check." So the second half of M24's claim --
that no file *reproduces the content* of one of those documents -- is not asserted anywhere in
this module. It is routed to B9's gate as judgment, which is the only honest place for it.

The prefixes are assembled from parts at import time rather than written as literals, because a
module that spelled them out would be the first file to fail its own check.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The four trees the check walks. Everything else in the checkout is contract or config prose.
TREES = ("src", "tests", "brain", "fixtures")

#: The one file licensed to name a prefix (`the build specification (not in this mirror)` § Deliverable 3,
#: folded: A1-11, folded: S-20). Exactly one entry, and build 2's row W4 asserts that length.
EXCLUSIONS: tuple[str, ...] = ("src/protean/intake/policy_home.py",)

#: The two forbidden path prefixes, assembled so this file does not contain either of them.
HOME = "~/"
PREFIXES = (HOME + "policy-home", HOME + "." + "claude")


def _authored_files() -> list[Path]:
    """Every file under the four trees as git sees it -- the index, plus what is not ignored.

    `git ls-files` rather than `rglob` (folded: S-20): `brain/semantic/*.jsonl` is gitignored and
    licensed to hold source text verbatim, so a working-tree walk would read the store the
    licence exists for. `--others --exclude-standard` beside `--cached` so a file a builder just
    wrote is still checked before it is staged. The one licensed file is excepted by name.
    """
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", *TREES],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [
        REPO_ROOT / relative
        for relative in sorted({line for line in result.stdout.splitlines() if line.strip()})
        if relative not in EXCLUSIONS
    ]


def _hits(prefix: str) -> list[str]:
    """`grep -rn <prefix>` over the four trees, as a list of `path:line` strings."""
    found: list[str] = []
    for path in _authored_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if prefix in line:
                found.append(f"{path.relative_to(REPO_ROOT)}:{number}")
    return found


def test_no_file_in_the_four_trees_names_either_prefix() -> None:
    for prefix in PREFIXES:
        assert _hits(prefix) == [], f"{prefix} is named under one of {TREES}: {_hits(prefix)}"


def test_the_walk_reaches_every_tree_and_is_not_vacuous() -> None:
    """A check that walked nothing would pass too, so pin what it actually opened."""
    walked = _authored_files()
    assert len(walked) > 100, "the four trees hold more than a hundred authored files"
    for tree in TREES:
        assert any(path.parts[len(REPO_ROOT.parts)] == tree for path in walked), tree


def test_the_check_would_catch_a_violation(tmp_path: Path) -> None:
    """The detector, fired on purpose: a line carrying a prefix is found, not stepped over."""
    planted = tmp_path / "planted.md"
    for prefix in PREFIXES:
        planted.write_text(f"a route to {prefix}/docs/anything.md\n", encoding="utf-8")
        text = planted.read_text(encoding="utf-8")
        assert any(prefix in line for line in text.splitlines())


def test_the_content_half_is_not_claimed_here() -> None:
    """M24's second clause is judgment (§ Named assumptions 13) and is routed, never asserted.

    Nothing in this module inspects meaning, and nothing should grow to: an imitation would
    pass a path grep, so a test that claimed the content half would be claiming what it cannot
    see. The mitigation on the record is that the layout is derived from the node set.
    """
    from protean import config

    layout = sorted(path.name for path in (REPO_ROOT / "brain" / "nodes").iterdir())
    assert layout == sorted(config.NODE_ORDER), "the brain's layout derives from the node set"
