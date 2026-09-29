"""The operator surface: argument parsing, dispatch, and the exit codes it never writes down.

`the build specification (not in this mirror)` § Deliverable 3 → *The operator surface*, decision 21: a
foreground CLI, per-task, no daemon, four verbs. `dry` is the battery order's and still raises.

**No exit code is written as an integer in `src/protean/cli.py`** — `protean.config` owns the
table — so every assertion below compares against `config`, and one of them checks the source
itself, because "no integer here" is a claim about the module and not about a call.

A checkout whose seat layer cannot be imported (the tests below block the import) makes `run`
and `resume` exit through `SystemExit` with the layer's name (dispatch ledger D5-9) while
`status` still works: no node runs on that path.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from protean import cli, config
from protean.runtime.cycle import run_tick
from protean.runtime.engine import build_context, new_state
from tests.runtime import stubs

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_SOURCE = REPO_ROOT / "src" / "protean" / "cli.py"


def test_the_parser_offers_exactly_the_config_verbs():
    parser = cli.build_parser()
    actions = [
        action for action in parser._actions if getattr(action, "choices", None)
    ]
    verbs = {name for action in actions for name in (action.choices or {})}
    assert verbs == set(config.VERBS)


def test_help_exits_zero_without_touching_a_brain_root(capsys):
    with pytest.raises(SystemExit) as raised:
        cli.main(["--help"])
    assert raised.value.code == 0
    assert "protean" in capsys.readouterr().out


@pytest.mark.parametrize("verb", list(config.VERBS))
def test_each_verbs_help_exits_zero(verb: str, capsys):
    with pytest.raises(SystemExit) as raised:
        cli.main([verb, "--help"])
    assert raised.value.code == 0


def test_no_verb_is_refused_by_argparse():
    with pytest.raises(SystemExit) as raised:
        cli.main([])
    assert raised.value.code != 0


def test_status_reports_an_empty_root_exits_done_and_honours_the_brain_flag(
    brain: Path, capsys
):
    """One `status` on an empty root, read twice: the code and the words, and the root named.

    The `--brain` override was a second `status` over a verbatim copy of this setup, asserting
    that the flagged root is the one the output names.
    """
    code = cli.main(["--brain", str(brain), "status"])
    assert code == config.EXIT_DONE
    out = capsys.readouterr().out
    assert "no task" in out
    assert str(brain) in out


def test_status_reports_a_live_task(brain: Path, workspace: Path, layer, capsys):
    seat_layer, _router, _seat = layer
    context = build_context(brain, "task-cli", seat_layer, workspace_path=str(workspace))
    state = new_state("task-cli", "write out.txt", context)
    state.tick += 1
    run_tick(context, state)

    assert cli.main(["--brain", str(brain), "status"]) == config.EXIT_DONE
    out = capsys.readouterr().out
    assert "task-cli" in out
    assert "tick      1" in out


def test_run_without_a_cortex_layer_exits_naming_it(brain: Path, monkeypatch):
    """No `config` code means "the seat layer is missing", so no integer is invented for it."""
    monkeypatch.setitem(sys.modules, "protean.cortex.layer", None)
    with pytest.raises(SystemExit) as raised:
        cli.main(["--brain", str(brain), "run", "a goal"])
    assert "protean.cortex.layer" in str(raised.value.code)


def test_resume_without_a_cortex_layer_exits_naming_it(
    brain: Path, workspace: Path, layer, monkeypatch
):
    seat_layer, _router, _seat = layer
    context = build_context(brain, "task-cli2", seat_layer, workspace_path=str(workspace))
    state = new_state("task-cli2", "write out.txt", context)
    state.tick += 1
    run_tick(context, state)

    monkeypatch.setitem(sys.modules, "protean.cortex.layer", None)
    with pytest.raises(SystemExit) as raised:
        cli.main(["--brain", str(brain), "resume"])
    assert "protean.cortex" in str(raised.value.code)


def test_resume_on_an_empty_root_returns_a_named_refusal_code(brain: Path, capsys):
    code = cli.main(["--brain", str(brain), "resume"])
    assert code in set(config.REFUSAL_EXIT_CODES.values())
    assert "no task is checkpointed" in capsys.readouterr().err


def test_dry_refuses_a_scenario_that_does_not_exist(brain: Path):
    """W4 filled the verb; an unknown scenario is now refused by name, with the choices."""
    with pytest.raises(SystemExit) as raised:
        cli.main(["--brain", str(brain), "dry", "a-scenario"])
    assert "a-scenario" in str(raised.value)


def test_the_module_writes_no_exit_code_as_an_integer():
    """§ Deliverable 3: `protean.config` owns the table, so the surface cannot drift from it."""
    tree = ast.parse(CLI_SOURCE.read_text(encoding="utf-8"), filename="cli.py")
    numbers = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
    ]
    assert numbers == [], numbers


def test_the_module_names_no_binary():
    """M21's operator-surface half: only `src/protean/cortex/` may name one."""
    assert "claude" not in CLI_SOURCE.read_text(encoding="utf-8").lower()


def _install(monkeypatch, seat_layer, mailbox) -> None:
    """Stand W3's two packages up in `sys.modules` so the surface can be driven end to end."""
    import sys
    import types

    from protean.runtime.interrupts import MAILBOX_MODULE
    from protean.runtime.seat import SEAT_LAYER_MODULE

    cortex = types.ModuleType(SEAT_LAYER_MODULE)
    cortex.build = lambda: seat_layer
    monkeypatch.setitem(sys.modules, SEAT_LAYER_MODULE, cortex)

    files = types.ModuleType(MAILBOX_MODULE)
    files.build = lambda root: mailbox
    monkeypatch.setitem(sys.modules, MAILBOX_MODULE, files)


def test_run_takes_the_lock_and_releases_it_on_the_interrupt_path(
    brain: Path, mailbox, monkeypatch, capsys
):
    """"released on every exit path — the interrupt path included"."""
    from protean.runtime.paths import BrainPaths

    _install(monkeypatch, stubs.planner_layer(stubs.asking_planner()), mailbox)
    code = cli.main(["--brain", str(brain), "run", "keep going"])

    assert code == config.EXIT_INTERRUPTED
    assert not BrainPaths(root=brain).lock.exists()
    assert "terminal: interrupted" in capsys.readouterr().out


def test_an_unanswered_resume_refuses_inside_the_lock_and_leaves_none_behind(
    brain: Path, mailbox, monkeypatch, capsys
):
    """M13: the lock is taken first, the answer check refuses, and no task state changes."""
    from protean.runtime.paths import BrainPaths

    _install(monkeypatch, stubs.planner_layer(stubs.asking_planner()), mailbox)
    cli.main(["--brain", str(brain), "run", "keep going"])
    capsys.readouterr()

    task_id = BrainPaths(root=brain).task_ids()[0]
    before = BrainPaths(root=brain).task(task_id).checkpoint.read_bytes()

    code = cli.main(["--brain", str(brain), "resume"])

    assert code == config.EXIT_UNANSWERED_INTERRUPT
    assert not BrainPaths(root=brain).lock.exists()
    assert BrainPaths(root=brain).task(task_id).checkpoint.read_bytes() == before
    assert mailbox.open_ids()[0] in capsys.readouterr().err


def test_an_answered_resume_runs_and_the_lock_is_released(
    brain: Path, mailbox, monkeypatch, capsys
):
    from protean.runtime.paths import BrainPaths

    _install(monkeypatch, stubs.planner_layer(stubs.asking_planner()), mailbox)
    cli.main(["--brain", str(brain), "run", "keep going"])
    mailbox.answer(mailbox.open_ids()[0], "use src/")
    capsys.readouterr()

    code = cli.main(["--brain", str(brain), "resume"])
    assert code in set(config.EXIT_CODES.values())
    assert not BrainPaths(root=brain).lock.exists()


def test_abandon_frees_the_root_through_the_surface(brain: Path, mailbox, monkeypatch, capsys):
    from protean.runtime.paths import BrainPaths

    _install(monkeypatch, stubs.planner_layer(stubs.asking_planner()), mailbox)
    cli.main(["--brain", str(brain), "run", "keep going"])
    capsys.readouterr()

    code = cli.main(["--brain", str(brain), "resume", "--abandon"])
    assert code == config.EXIT_DONE
    assert "abandoned" in capsys.readouterr().out
    assert not BrainPaths(root=brain).lock.exists()


def test_a_second_instance_against_a_live_lock_is_refused_by_the_surface(
    brain: Path, mailbox, monkeypatch, capsys
):
    from protean.runtime import lock
    from protean.runtime.paths import BrainPaths

    _install(monkeypatch, stubs.planner_layer(stubs.asking_planner()), mailbox)
    lock.acquire(BrainPaths(root=brain).lock, "task-held")
    with pytest.raises(Exception) as raised:
        cli.main(["--brain", str(brain), "run", "keep going"])
    assert "task-held" in str(raised.value)
