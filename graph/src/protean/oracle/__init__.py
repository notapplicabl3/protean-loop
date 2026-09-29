"""The synthetic-dev oracle — the second package licensed to spawn a model, and the second
T3 surface.

`the build specification (not in this mirror)` § Deliverable 4 (folded: A1-8, folded: S-1, folded: S-29,
folded: S-34), § Deliverable 1's containment paragraph (taken whole, folded: S-30, folded: S-31,
folded: S-32, folded: S-37), § Directional decisions 4, 17, 18, 19.

**It is not a seat.** It takes no tier, it never appears in `seat_calls.jsonl`, and the runtime
never calls it: it is a *measurement* that runs beside the build, one `claude -p` session per
canonical task per repeat, each on its own fresh clone which it destroys afterwards. Decision 4
licenses exactly two packages to name the binary — `cortex/` and this one — and
`tests/test_zero_calls.py`'s static grep excludes exactly those two.

**It measures the transcript, never the session's self-report** (decision 18). Every number in
`OracleReport` is derived from `--output-format stream-json` events, from the exit status of the
process the session ran, or from the tree — never from a field a model wrote. `transcript.py`
holds that derivation and `tests/oracle/test_transcript.py` proves it against a captured
fixture whose counts were computed by hand.

**Containment is taken whole, not re-derived.** `config.py` builds a `SeatsConfig` out of the
`oracle:` block in `brain/seats.yaml` and then uses `protean.cortex.live.config`'s own
environment scrub, `PATH` construction and binary resolution, and `protean.cortex.live.invoke`'s
own link farm. There is one implementation of the containment in this build and both T3 surfaces
run it.
"""

from __future__ import annotations

from protean.oracle.config import OracleConfigError, OracleSeat, load_oracle
from protean.oracle.counts import structural_counts
from protean.oracle.predicates import PREDICATES, TaskPredicate, verdict_for
from protean.oracle.tasks import CANONICAL_TASK_SPECS, TaskSpec, task_spec
from protean.oracle.transcript import (
    TranscriptEvent,
    TranscriptMetrics,
    derive_metrics,
    parse_transcript,
)

__all__ = (
    "CANONICAL_TASK_SPECS",
    "PREDICATES",
    "OracleConfigError",
    "OracleSeat",
    "TaskPredicate",
    "TaskSpec",
    "TranscriptEvent",
    "TranscriptMetrics",
    "derive_metrics",
    "load_oracle",
    "parse_transcript",
    "structural_counts",
    "task_spec",
    "verdict_for",
)
