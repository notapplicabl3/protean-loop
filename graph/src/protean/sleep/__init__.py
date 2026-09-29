"""The sixth verb's package: the offline learner, between tasks, making zero model calls.

`the build specification (not in this mirror)` § Deliverable 2, § Directional decisions 4, 10, 15, 16, 17, 18
and 22, § Resolutions A1-3, A1-8, A1-10, A1-11, A1-13, S-6, S-11, S-12, S-13.

**Sleep is a verb for intake's reason, one layer up** (§ Rulings 5: a deterministic node
measures, fetches and vetoes — it never re-values a threshold). The runtime refuses a write to
any seed file, so a weights key cannot be moved at tick time; it is moved offline by
`protean sleep`, refused while a task is in flight, and the next run re-hashes the changed seeds
through the ladder build 1 already ships.

**Six modules, and three of them are later orders'.** `run.py` is the verb's body — the two
refusals, the seed verification, the pipeline and its three seams; `evidence.py` loads a run's
records, joins outcome to prediction by `ref` and applies § Deliverable 1's admissibility tests;
`report.py` assembles P5 and prints the `--dry-run` diff. `weights.py` (the update rule),
`memory.py` (project memory) and `habits.py` (candidate detection and compilation) are filled by
orders W3, W5 and W6 and are resolved from `run.py` by dotted path, so this package runs whole
before any of them exists.

**Zero model calls, and it is a free proof** (decision 4, decision 10): this package sits inside
`tests/test_zero_calls.py`'s walked set and names no binary, so the exclusion list stays at
exactly two packages. An update is a *function* of the trace, never a judgment about it — which
is also what lets the dry oracle be exact equality rather than tolerance.

**It writes four places and prints every file it writes**, and the archive is read, never
written and never pruned (row N8): it is the only copy of build 3's whole input.
"""

from __future__ import annotations

from protean.sleep.evidence import (
    AdmissibleSet,
    Pair,
    RunRecords,
    RunUnreadable,
    admissible_set,
)
from protean.sleep.run import SeedHashHeld, SeedMoved, SleepOutcome, run_sleep

__all__ = [
    "AdmissibleSet",
    "Pair",
    "RunRecords",
    "RunUnreadable",
    "SeedHashHeld",
    "SeedMoved",
    "SleepOutcome",
    "admissible_set",
    "run_sleep",
]
