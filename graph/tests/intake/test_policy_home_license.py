"""Row W4's license half: exactly one tracked file may know where the policy home is.

`the build specification (not in this mirror)` \xa7 DoD row W4, \xa7 Directional decisions 5, \xa7 Out of scope,
\xa7 Resolutions A1-11, S-20.

**This is build 1's M24 grep re-based on `git ls-files`**, which is what row W4 asks for: the
store under `brain/semantic/` holds source text verbatim and is gitignored, so a walk of the
working tree would read the licensed store and a walk of the *index* cannot (folded: S-20). The
exclusion list is one entry long and that length is itself asserted, because "one file is
licensed" is the claim and a list that grew would be the way it stopped being true.

**The content half of the row is not asserted here.** Row W4's claim that no tracked file
*reproduces* the policy home content is judgment, not a grep — an imitation passes any path check — and it
is routed to the operator's gate B15, exactly as build 1 routed M24's second clause to B9
(`tests/test_policy_home_clean.py`, the closing test of that module).

The two prefixes are assembled from parts at import time rather than written as literals, for the
same reason build 1's module does it: a file that spelled them out would be the first to fail the
check it runs.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from protean.intake import policy_home
from tests.conftest import PREFIXES

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The four trees row W4 names.
TREES = ("src", "tests", "brain", "fixtures")

#: The licensed set. **Exactly one entry**, and the assertion below is what keeps it that way.
EXCLUSIONS: tuple[str, ...] = ("src/protean/intake/policy_home.py",)


def tracked_files() -> list[str]:
    """The four trees as git sees them: what is in the index, plus what is not ignored.

    `--others --exclude-standard` beside `--cached` because a file this build just wrote is not
    in the index until the session stages it, and a grep that could not see a new file would
    pass for the one commit where it mattered. Ignored paths stay out either way, which is what
    keeps the licensed store under `brain/semantic/` outside the check by construction (S-20).
    """
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", *TREES],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted({line for line in result.stdout.splitlines() if line.strip()})


def walk(
    prefixes: Sequence[str], files: Sequence[str] | None = None, root: Path = REPO_ROOT
) -> dict[str, list[str]]:
    """Every `path:line` naming each prefix, the licensed file excluded — in **one** pass.

    The detector reads each file once and tests every prefix against each line, because reading
    403 tracked files once per prefix is the same walk twice for the same answer. `files` and
    `root` are parameters so the detector can be fired at a planted violation on a throwaway
    tree — the vacuity guard at the bottom of this module — rather than re-implemented there.
    """
    found: dict[str, list[str]] = {prefix: [] for prefix in prefixes}
    for relative in tracked_files() if files is None else files:
        if relative in EXCLUSIONS:
            continue
        path = root / relative
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError, FileNotFoundError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for prefix in prefixes:
                if prefix in line:
                    found[prefix].append(f"{relative}:{number}")
    return found


def hits(prefix: str, files: Sequence[str] | None = None, root: Path = REPO_ROOT) -> list[str]:
    """Every `path:line` under the four trees naming this prefix, the licensed file excluded."""
    return walk((prefix,), files, root)[prefix]


@pytest.fixture(scope="module")
def tracked() -> list[str]:
    """One `git ls-files` for the module: the surface every grep below is taken over."""
    return tracked_files()


@pytest.fixture(scope="module")
def found(tracked: list[str]) -> dict[str, list[str]]:
    """One walk of that surface for both prefixes, rather than one walk per prefix."""
    return walk(PREFIXES, tracked)


def test_the_exclusion_list_has_exactly_one_entry() -> None:
    """The second grep row W4 names: the license is one file wide, and stays that way."""
    assert len(EXCLUSIONS) == 1
    assert EXCLUSIONS == ("src/protean/intake/policy_home.py",)
    assert (REPO_ROOT / EXCLUSIONS[0]).is_file()


@pytest.mark.parametrize("prefix", PREFIXES, ids=("policy_home", "harness_home"))
def test_no_tracked_file_but_the_licensed_one_names_either_prefix(
    prefix: str, found: dict[str, list[str]]
) -> None:
    assert found[prefix] == [], f"{prefix} is named under one of {TREES}: {found[prefix]}"


def test_the_walk_reaches_every_tree_and_is_not_vacuous(tracked: list[str]) -> None:
    """A grep over nothing passes too, so pin what `git ls-files` actually returned."""
    assert len(tracked) > 100
    for tree in TREES:
        assert any(path.startswith(f"{tree}/") for path in tracked), tree
    assert EXCLUSIONS[0] in tracked, "the licensed file is in the surface the grep excludes from"


@pytest.mark.parametrize("prefix", PREFIXES, ids=("policy_home", "harness_home"))
def test_the_manifest_seed_names_neither_prefix(prefix: str) -> None:
    """S3 names logical sources, which is what keeps the grep true over the whole brain tree."""
    manifest = (REPO_ROOT / "brain" / "intake" / "manifest.yaml").read_text(encoding="utf-8")
    assert prefix not in manifest


#: What resolving a root looks like in source, read off the licensed module rather than written
#: here — this file may not spell the prefix either. Either token in a second module would mean
#: two files know where the sources are, which is the failure the one-entry license exists to stop.
ROOT_RESOLUTION = (policy_home.ROOT_DEFAULT, policy_home.ROOT_ENV)


@pytest.mark.parametrize("token", ROOT_RESOLUTION, ids=("root_default", "root_env"))
def test_no_other_intake_module_resolves_a_root(token: str) -> None:
    """The license is a property of the package, not only of the grep: one module has the root."""
    package = REPO_ROOT / "src" / "protean" / "intake"
    resolvers = [
        path.name
        for path in sorted(package.glob("*.py"))
        if token in path.read_text(encoding="utf-8")
    ]
    assert resolvers == ["policy_home.py"], f"{token} appears in {resolvers}"


def test_the_check_would_catch_a_violation(tmp_path: Path) -> None:
    """The detector, fired on purpose, so a passing run is not a vacuous one.

    **Strengthened.** This case used to re-implement `prefix in line` over a file it had just
    written, which proves Python's `in` operator and says nothing about `hits()`. It now plants
    the violation inside a walk the *detector itself* performs — the same `walk()` the module's
    `found` fixture runs, pointed at a throwaway root — and asserts that `hits(prefix)` names
    the planted file and its line. The module's whole value rests on the detector not being
    vacuous, so it is the detector that has to be fired.
    """
    planted = tmp_path / "planted.md"
    for prefix in PREFIXES:
        planted.write_text(
            f"unrelated first line\na route to {prefix}/docs/anything.md\n", encoding="utf-8"
        )
        assert any(prefix in line for line in planted.read_text(encoding="utf-8").splitlines())
        assert hits(prefix, [planted.name], tmp_path) == ["planted.md:2"], (
            "the detector did not name the violation planted inside its own walk"
        )
        other = next(one for one in PREFIXES if one != prefix)
        assert hits(other, [planted.name], tmp_path) == [], (
            "and it named only the prefix that is actually there"
        )


def test_skills_and_registries_are_excluded_by_name() -> None:
    """\xa7 Out of scope: skills and registries are not intake sources, stated as data."""
    assert "skills" in policy_home.EXCLUDED_TREES
    assert "skills-storage" in policy_home.EXCLUDED_TREES
    assert "skills.md" in policy_home.EXCLUDED_FILES
    assert policy_home.is_excluded("skills/anything.md")
    assert policy_home.is_excluded("skills.md")
    assert not policy_home.is_excluded("docs/building.md")
