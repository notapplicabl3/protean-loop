# Sleep — offline learning and its review report

Own deterministic consolidation from run evidence. The operator surface is [../../../docs/operations.md](../../../docs/operations.md); this guide describes the writer, not permission to invoke it.

## Inputs

- Reference: `../state/sleep.py`, `../config.py`, `../runtime/paths.py`; build-3 SPEC through [../../../a planning record (not in this mirror)](../../../a planning record (not in this mirror)), including later A-series amendments.
- Working: the selected root's weights and prior `projects/<slug>/memory/<node>/learning.jsonl`, plus an archived run named by `--from` or the live traces/latest committed task. `evidence.py` resolves the actual records.

## Process

1. Enter through `run.py`: check root occupancy and held seed hashes before reading evidence, then verify every recorded weights hash. Neither `--from` nor `--dry-run` bypasses a paused-root refusal.
2. Use `evidence.py` to join predictions and outcomes and exclude inadmissible evidence. Preserve the named signal set, bounded updates and cross-task evidence floor.
3. Run `weights.py` → `habits.py` → `memory.py`, in that order. Memory records what the earlier producers consumed; historical build order is not execution order. `../cortex/habits.py` owns runtime matching, not this package.
4. Use `report.py` for the receipt and proposed diff. No model is called, node identity is unchanged and the source archive remains read-only.

## Outputs

Eligible `nodes/<node>/weights.yaml`, cross-project procedures under `nodes/<node>/procedures/`, project learning and procedures under `projects/<slug>/memory/`, and `reports/sleep/<sleep-id>.json` under the repository. No checkpoint, mailbox, episode or semantic-store writes belong to sleep. `--dry-run` writes only the report and prints the proposed diff; a no-data result is valid.

## Human check

Read the `SleepReport` beside the tracked diff and inspect the project-memory portion that git omits; confirm admissibility and consumed evidence before accepting a change. Use `../../../tests/sleep/` and `../../../fixtures/traces/` for dry verification; [../../the status record (not in this mirror)](../../the status record (not in this mirror)) owns the separate wet-efficacy gate.
