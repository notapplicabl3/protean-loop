"""`config.py` is the one owner of the node order, the schema versions and the exit codes.

`the build specification (not in this mirror)` § Deliverable 3 ("The order is a literal in `config.py`,
iterated by the runtime, never hardcoded inside a node"), § Deliverable 1 (the brain-root
resolution), decisions 12, 18 and 20.

It lives under `tests/state/` rather than beside a mirrored `tests/test_config.py` because
W1's writable set names no other tests path — recorded in the dispatch ledger as D4-6.

The exit codes are asserted **distinct**, not asserted equal to particular integers: what the
build owes is that an operator and a test can tell five terminals and five refusals apart, not
that `stuck` is 13. `done` is the one number fixed by the platform.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from protean import config


def test_the_six_verbs_are_the_operator_surface() -> None:
    """Re-based by build 3's order W2, on the shape S-39 fixed when build 2 added the fifth.

    The tuple is pinned rather than counted, so a verb added without a SPEC row fails here.
    """
    assert config.VERBS == ("run", "resume", "status", "dry", "intake", "sleep")
    assert config.VERBS[-2:] == (config.INTAKE_VERB, config.SLEEP_VERB)


def test_every_exit_code_is_distinct() -> None:
    codes = config.EXIT_CODES
    assert len(set(codes.values())) == len(codes)


def test_the_five_terminal_states_each_have_a_code_and_done_is_zero() -> None:
    assert sorted(config.TERMINAL_EXIT_CODES) == sorted(config.TERMINAL_STATES)
    assert config.TERMINAL_EXIT_CODES["done"] == 0
    for state in config.TERMINAL_STATES:
        if state != "done":
            assert config.TERMINAL_EXIT_CODES[state] != 0


def test_each_named_refusal_has_its_own_code() -> None:
    """§ Deliverable 3 and § Deliverable 5 name five refusals; each exits as itself."""
    assert sorted(config.REFUSAL_EXIT_CODES) == [
        "contract_refused",
        "lock_held",
        "root_occupied",
        "seed_drift",
        "unanswered_interrupt",
    ]
    assert set(config.REFUSAL_EXIT_CODES.values()).isdisjoint(
        set(config.TERMINAL_EXIT_CODES.values())
    )


def test_each_later_builds_refusals_sit_beside_build_ones_rather_than_inside_it() -> None:
    """Build 2's one and build 3's two are their own tables; `EXIT_CODES` merges all three.

    Extending `REFUSAL_EXIT_CODES` in place would falsify a landed row rather than add a
    literal — the reason the build-2 block gives, applied again one build on.
    """
    assert sorted(config.BUILD2_REFUSAL_EXIT_CODES) == ["intake_refused"]
    assert sorted(config.BUILD3_REFUSAL_EXIT_CODES) == ["sleep_refused", "sleep_seed_refused"]
    assert sorted(config.EXIT_CODES) == sorted(
        {
            **config.TERMINAL_EXIT_CODES,
            **config.REFUSAL_EXIT_CODES,
            **config.BUILD2_REFUSAL_EXIT_CODES,
            **config.BUILD3_REFUSAL_EXIT_CODES,
        }
    )
    for table in (config.BUILD2_REFUSAL_EXIT_CODES, config.BUILD3_REFUSAL_EXIT_CODES):
        assert set(table).isdisjoint(set(config.REFUSAL_EXIT_CODES))
        assert set(table.values()).isdisjoint(set(config.TERMINAL_EXIT_CODES.values()))


def test_build_threes_closed_sets_are_the_specs_own() -> None:
    """The admissible signals and the four exclusion reasons, pinned where they are read.

    Re-based by build A.1 (§ Deliverable 1, decision 18): **nine** signals, two renamed with the
    tiers that minted them and one added — `firing_check`, which is what makes a node's cheap
    firing check learnable rather than invisible to the learner. The exclusion reasons stay at
    four.
    """
    assert config.ADMISSIBLE_SIGNALS == (
        "homeostasis_cost",
        "hippocampus_citation",
        "thalamus_citation",
        "gate_unit_survives",
        "monitor_next_verdict",
        "dispatch_expectations",
        "manager_horizon",
        "director_progress",
        "firing_check",
    )
    assert config.SLEEP_EXCLUSION_REASONS == ("unjoined", "off-list", "ungradeable", "vacuous")
    assert config.WEIGHTS_WRITABLE_NODES == tuple(
        node for node in config.NODE_ORDER if node != "basal_ganglia"
    )


def test_no_exit_code_collides_with_argparses_usage_code() -> None:
    """argparse exits 2 on a usage error; a terminal that shared it would be unreadable."""
    assert 2 not in set(config.EXIT_CODES.values())


def test_terminal_precedence_is_interrupted_over_stuck_over_stopped() -> None:
    """folded: T-6 — `terminal` is one committed field, so the winner is fixed here."""
    order = config.TERMINAL_PRECEDENCE
    assert order["interrupted"] > order["stuck"] > order["stopped"]
    assert max(order, key=order.get) == "interrupted"


def test_every_persisted_artifact_carries_a_version(monkeypatch) -> None:
    assert sorted(config.ARTIFACT_SCHEMA_VERSIONS) == [
        "checkpoint",
        "episode",
        "journal",
        "mailbox",
        "trace",
    ]
    # Build A.1 moved six schema versions together, 1 → 2 — brain state, checkpoint, journal,
    # trace, mailbox and the seat call — and `episode` is the one entry of this table that did
    # not move (§ Scaffold clause item 2, folded: S-A55, folded: S-A85).
    assert config.ARTIFACT_SCHEMA_VERSIONS["episode"] == 1
    assert [
        name for name, version in config.ARTIFACT_SCHEMA_VERSIONS.items() if version == 2
    ] == ["checkpoint", "journal", "trace", "mailbox"]
    assert config.BRAIN_STATE_SCHEMA_VERSION == 2
    # **A.1.i moved this one alone, 2 → 3** (`the build specification (not in this mirror)`
    # § Scaffold clause item 2, A1-9): the receipt gains four columns — the two caps
    # `SPAWN_RECEIPT_FIELDS` had named since A.1 and no column carried, plus `permission_denials`
    # and `audit` — under one bump. The other five stand, which is what the four lines above check.
    assert config.SEAT_CALL_SCHEMA_VERSION == 3


def test_the_brain_root_resolves_to_the_repo_tree_by_default(monkeypatch, repo_root) -> None:
    monkeypatch.delenv(config.BRAIN_ROOT_ENV, raising=False)
    assert config.brain_root() == repo_root / "brain"
    assert config.repo_root() == repo_root


def test_the_environment_override_wins(monkeypatch, tmp_path: Path) -> None:
    """What `protean dry` sets, so the repo's own brain/ is never written by a dry run."""
    monkeypatch.setenv(config.BRAIN_ROOT_ENV, str(tmp_path))
    assert config.brain_root() == tmp_path.resolve()
    assert config.node_dir("cortex") == tmp_path.resolve() / "nodes" / "cortex"


def test_an_empty_override_falls_back_rather_than_resolving_to_the_cwd(
    monkeypatch, repo_root
) -> None:
    monkeypatch.setenv(config.BRAIN_ROOT_ENV, "")
    assert config.brain_root() == repo_root / "brain"


def test_the_literal_tables_are_read_only() -> None:
    """A mutable literal table is a literal anyone can edit at runtime."""
    for table in (
        config.EXIT_CODES,
        config.TERMINAL_EXIT_CODES,
        config.REFUSAL_EXIT_CODES,
        config.ARTIFACT_SCHEMA_VERSIONS,
        config.TERMINAL_PRECEDENCE,
        config.BUILD2_REFUSAL_EXIT_CODES,
        config.BUILD3_REFUSAL_EXIT_CODES,
        config.BUILD3_ARTIFACT_SCHEMA_VERSIONS,
    ):
        with pytest.raises(TypeError):
            table["injected"] = 99


def test_config_imports_nothing_from_the_state_package() -> None:
    """The dependency runs one way: `state` reads `config`, never the reverse.

    Read off the import statements rather than the file text — the module's docstring names
    `protean.state` precisely to explain why it does not import it.
    """
    import ast

    tree = ast.parse(Path(config.__file__).read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert not [name for name in imported if name.startswith("protean")], imported
