"""The argument keys the typed `Constraint` and `Expectation` maps are read under.

`the build specification (not in this mirror)` § Deliverable 2 fixes both `kind` sets as closed enums and
leaves `arguments` an open `dict[str, JsonValue]`. That is the right shape — a constraint's
payload differs by kind — but an open map still needs one vocabulary, or the gate reads a key
the manager never wrote and a catastrophic-only veto silently never fires.

**One place, read by the nodes and written by every fixture.** The keys live here rather than
in the node that reads them so that `src/protean/cortex/`'s seat scripts and the scenario
fixtures import the same names; a fixture that invented its own key would produce a unit the
gate cannot judge, which is exactly the mock-shaping-the-contract failure the build cut exists
to prevent.

**Nothing here is a threshold.** These are key *names*: the numbers they select live in
`brain/nodes/*/weights.yaml` and reach a node on its input model's `weights` field.
"""

from __future__ import annotations

from typing import Final

# --------------------------------------------------------------------------------------
# `Constraint.arguments`, by kind
# --------------------------------------------------------------------------------------

#: `path_scope` — the directories a unit may touch, narrowing the task workspace root.
#: Arm (a) of the gate's veto reads it: an `Expectation` path outside every listed scope is
#: `no_go`. An empty or absent list means "the workspace root, unnarrowed".
PATH_SCOPE_PATHS: Final[str] = "paths"

#: `allow_irreversible` — the unit ids the director has cleared to act irreversibly.
#: Arm (b) reads it: a unit declaring `irreversible: true` and not named here is `no_go`.
ALLOW_IRREVERSIBLE_UNIT_IDS: Final[str] = "unit_ids"

#: `budget` — a per-task narrowing of homeostasis's ceilings. The keys are deliberately the
#: same names the homeostasis `weights.yaml` uses, so a constraint narrows a *named* ceiling
#: rather than introducing a second name for the same limit; the effective ceiling is the
#: lower of the two.

# --------------------------------------------------------------------------------------
# `Expectation.arguments`, by kind
# --------------------------------------------------------------------------------------

#: `file_exists`, `file_absent`, `file_contains` — the workspace path the predicate is about.
#: This is the only key the gate's path arm inspects: `WorkUnit.intent` is prose and
#: contributes no path (folded: U-12).
EXPECTATION_PATH: Final[str] = "path"

#: `file_contains` — the substring the dispatch summary reports having read at that path, and
#: `summary_field_equals` — the value the named field must equal.
EXPECTATION_VALUE: Final[str] = "value"

#: `summary_field_equals` — the `ExecutorSummary` field the predicate compares.
EXPECTATION_FIELD: Final[str] = "field"

#: `exit_code` — the exit code the dispatch summary must have reported.
EXPECTATION_CODE: Final[str] = "code"

#: Every `Expectation` kind whose argument map carries a workspace path — the set arm (a)
#: of the veto walks.
PATH_BEARING_KEYS: Final[tuple[str, ...]] = (EXPECTATION_PATH,)
