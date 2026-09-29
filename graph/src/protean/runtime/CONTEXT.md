# Runtime — tick, commit and continuation

Own the task loop and committed state. This is a maintainer guide, not an extra graph stage. [../../../architecture.md](../../../architecture.md) owns the full structural map.

## Inputs

- Reference: `../config.py` for order, versions and terminal codes; `../state/` for contracts; `../brain/folders.py` for seed checks; [../../../a planning record (not in this mirror)](../../../a planning record (not in this mirror)) for controlling SPECs.
- Working: the selected root's `state/<task-id>/checkpoint.json`, `journal-<tick>.jsonl`, seed files and mailbox items, addressed through `paths.py`.
- Callers and ports: `../cli.py`, `../nodes/registry.py`, `seat.py`, `../cortex/layer.py` and `interrupts.py`.

## Process

1. Start at `engine.py` for lifecycle or `cycle.py` for a tick; load only the implicated contract and producer. Use `projections.py` for node inputs, `firing.py` for firing decisions and `triggers.py` for a node's per-tick call plan.
2. Follow `journal.py` → `commit.py` for per-call records and the boundary checkpoint; follow `resume.py` and `lock.py` for replay, refusal and exclusive execution. A journal is crash evidence, not a second committed resume point.
3. Follow `predictions.py` and `outcomes.py` for graded evidence, `observations.py` for observed workspace facts, and `terminal.py` for terminal precedence. Model requests cross the seat port; concrete live invocation remains in `../cortex/live/`.
4. Keep path construction in `paths.py`; use `report.py` and `archive.py` for terminal evidence. A maintainer change does not license manual edits to generated state or weaken a schema/seed refusal.

## Outputs

The selected root's checkpoints, journals, traces, episodes, call receipts, habit hits, run report and terminal archive. `../mailbox/` implements mailbox files through the runtime's port. Package code remains separate from generated brain artifacts.

## Human check

Compare the changed behavior with the applicable SPEC and captured evidence from the relevant `../../../tests/runtime/` or `../../../tests/dry/` case; verify replay and committed output as well as the happy path. Live/reset authority comes from [../../the status record (not in this mirror)](../../the status record (not in this mirror)), not a dry receipt.
