"""M1's static half: the two trees, the three flat modules, the pins, and the CLI skeleton.

`the build specification (not in this mirror)` § Deliverable 1's fenced block and its pinning rule, and
§ Deliverable 3's operator surface.

It lives under `tests/state/` because W1's writable set names no other tests path — recorded in
the dispatch ledger as D4-6.

**The pin assertions read `pyproject.toml`, not the lockfile.** A lockfile reproduces what is
already pinned without re-resolving, so a lockfile alone would pass while `pyproject.toml`
carried a floating specifier — which is exactly the hole the SPEC's pinning rule names. The
rule is asserted where it can be violated.

No policy file is cited by path anywhere under `tests/`. M24 greps this tree for the two home
prefixes it forbids, and ruling S-16 puts policy citations in the discovery surface — the
plans, the docs, the architecture doc and the README — never in the source or the battery.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from protean import cli, config

#: § Deliverable 1's fenced block, transcribed.
SOURCE_PACKAGES = ("state", "runtime", "nodes", "cortex", "mailbox", "brain")
FLAT_MODULES = ("__init__.py", "cli.py", "config.py")
TREE_DIRS = (
    "src/protean",
    "brain",
    "brain/nodes",
    "brain/mailbox/open",
    "brain/state",
    "brain/episodes",
    "brain/projects",
    "fixtures",
    "tests",
)


@pytest.mark.parametrize("relative", TREE_DIRS)
def test_every_folder_the_fenced_block_draws_exists(repo_root, relative: str) -> None:
    assert (repo_root / relative).is_dir()


@pytest.mark.parametrize("package", SOURCE_PACKAGES)
def test_every_source_sub_package_exists_with_its_marker(repo_root, package: str) -> None:
    folder = repo_root / "src" / "protean" / package
    assert folder.is_dir()
    assert (folder / "__init__.py").is_file()


@pytest.mark.parametrize("package", [p for p in SOURCE_PACKAGES if p != "state"])
def test_the_markers_a_later_order_lands_beside_are_still_empty(repo_root, package) -> None:
    """W1 ships package markers; the modules beside them are the later orders'."""
    marker = repo_root / "src" / "protean" / package / "__init__.py"
    assert marker.read_text(encoding="utf-8") == ""


def test_no_module_sits_flat_at_the_package_root_but_the_three(repo_root) -> None:
    found = sorted(p.name for p in (repo_root / "src" / "protean").glob("*.py"))
    assert found == sorted(FLAT_MODULES)


def test_the_tests_tree_mirrors_the_source_package(repo_root) -> None:
    assert (repo_root / "tests" / "state").is_dir()
    assert (repo_root / "tests" / "__init__.py").is_file()
    assert (repo_root / "tests" / "conftest.py").is_file()


def pyproject(repo_root: Path) -> dict:
    return tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))


def test_python_is_at_least_3_13(repo_root) -> None:
    assert pyproject(repo_root)["project"]["requires-python"] == ">=3.13"
    assert sys.version_info >= (3, 13)


def declared_requirements(repo_root: Path) -> list[str]:
    data = pyproject(repo_root)
    requirements = list(data["project"]["dependencies"])
    for group in data.get("dependency-groups", {}).values():
        requirements.extend(group)
    requirements.extend(data["build-system"]["requires"])
    return requirements


def test_every_dependency_is_pinned_to_an_exact_version(repo_root) -> None:
    """The SPEC's pinning rule: only an exact version is a pin — no `^`, no `latest`."""
    for requirement in declared_requirements(repo_root):
        assert re.fullmatch(r"[A-Za-z0-9_.\-]+==[0-9][0-9A-Za-z.\-]*", requirement), (
            f"{requirement}: not an exact pin. The `fullmatch` excludes every floating "
            "specifier by construction — `^`, `~=`, `>=`, `<`, `*`, `latest`."
        )


def test_the_dependency_set_is_the_tiny_one_the_spec_names(repo_root) -> None:
    """pydantic, PyYAML, pytest, a build backend. Nothing else."""
    names = sorted(r.split("==")[0].lower() for r in declared_requirements(repo_root))
    assert names == ["hatchling", "pydantic", "pytest", "pyyaml"]


def test_the_lockfile_is_committed_and_not_ignored(repo_root) -> None:
    assert (repo_root / "uv.lock").is_file()
    ignored = subprocess.run(
        ["git", "check-ignore", "uv.lock"], cwd=repo_root, capture_output=True
    )
    assert ignored.returncode != 0, "uv.lock is gitignored; the pin would not travel"


def test_the_console_script_points_at_the_cli(repo_root) -> None:
    assert pyproject(repo_root)["project"]["scripts"]["protean"] == "protean.cli:main"


def test_the_parser_carries_the_five_verbs_and_nothing_else() -> None:
    parser = cli.build_parser()
    subparsers = [
        action for action in parser._actions if hasattr(action, "choices") and action.choices
    ]
    verbs = sorted(next(a for a in subparsers if a.dest == "verb").choices)
    assert verbs == sorted(config.VERBS)


UNFILLED_VERBS: tuple[str, ...] = ()  # build 1 filled the four; build 2 filled intake


def test_no_verb_body_is_left_unwritten(repo_root: Path) -> None:
    """`intake` was the last body owed. Nothing on the operator surface is a stub any more."""
    assert UNFILLED_VERBS == ()
    source = (repo_root / "src" / "protean" / "cli.py").read_text(encoding="utf-8")
    assert "NotImplementedError" not in source


def test_help_exits_zero(capsys) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["--help"])
    assert raised.value.code == 0
    assert "protean" in capsys.readouterr().out


@pytest.mark.parametrize("verb", config.VERBS)
def test_each_verbs_help_exits_zero(verb: str) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main([verb, "--help"])
    assert raised.value.code == 0


def test_resume_carries_its_three_operator_flags() -> None:
    args = cli.build_parser().parse_args(["resume", "--abandon", "--reseed", "--extend", "20"])
    assert (args.abandon, args.reseed, args.extend) == (True, True, "20")


def test_an_unknown_verb_is_refused() -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["consolidate"])
    assert raised.value.code != 0
