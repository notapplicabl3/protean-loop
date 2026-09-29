"""The fifth verb's package: policy-home intake, offline, between tasks.

`the build specification (not in this mirror)` § Deliverable 3, § Directional decisions 5, 6, 14, 15,
§ Rulings 1, 5, 7, 12, § Named assumptions 9, § Resolutions A1-10, A1-11, A1-13, S-12, S-13,
S-14, S-20, S-22, S-28.

**Intake is a verb because seeding a store is none of the three things a deterministic node may
do** (§ Rulings 5: measure, fetch, veto). `weights.yaml` is sleep-writes-only and the runtime
refuses a write to any seed file, so the store cannot be filled at tick time; it is filled
offline by `protean intake`, refused while a task occupies the root, and the next run re-hashes
the changed seeds through the ladder build 1 already ships (decision 14, folded: A1-13).

**Five modules, and exactly one of them knows where the policy home is.** `policy_home.py` holds the
root and the per-source globs; `manifest.py` reads the tracked manifest that maps a *logical*
source to a store; `chunks.py` cuts a document at the granularity the manifest declares;
`seeds.py` is build 3's addition — it reads `brain/seeds.yaml` and holds S-21's collision rule;
`run.py` is the verb's body. No module but `policy_home.py` may name the policy home.

**Build 3 takes S-28's seeding half** (`the build specification (not in this mirror)` § Deliverable 3, folded:
S-10, S-15). Build 2's sentence here read "none of them writes anything under `brain/nodes/`";
that is now true of every module but `seeds.py`, and true of it too for every key
`brain/seeds.yaml` does not name — the map is sparse, hand-authored, and names only keys the
node files already carry, so `was_seeded` has a subject and sleep has a seed it can weaken.
"""

from __future__ import annotations

from protean.intake.manifest import IntakeManifest, ManifestSource, load_manifest
from protean.intake.run import IntakeOutcome, run_intake
from protean.intake.seeds import (
    BadSeedMap,
    SeedPlan,
    SeedRow,
    SeedWrite,
    load_seed_map,
    plan_seeds,
)

__all__ = [
    "BadSeedMap",
    "IntakeManifest",
    "IntakeOutcome",
    "ManifestSource",
    "SeedPlan",
    "SeedRow",
    "SeedWrite",
    "load_manifest",
    "load_seed_map",
    "plan_seeds",
    "run_intake",
]
