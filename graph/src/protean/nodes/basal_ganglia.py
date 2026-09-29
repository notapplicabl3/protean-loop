"""The gate. One verb — veto — and the predicate is catastrophic-only.

`the build specification (not in this mirror)` § Deliverable 2's `SelectionVerdict` row, decision 29, and
`brain/nodes/basal_ganglia/NODE.md`.

**Two arms, and nothing else vetoes** (folded: T-13):

* (a) an `Expectation` argument path in the pending unit lies outside the task workspace root
  as narrowed by any `path_scope` constraint — `WorkUnit.intent` is prose and contributes no
  path (folded: U-12);
* (b) the unit carries `irreversible: true` and no `Constraint` of kind `allow_irreversible`
  names it.

**A `no_go` is inhibition, not a field the seat weighs.** A.1 requires the pending unit's
dispatch wave and delegates to be inhibited while think and escalate remain allowed. The
runtime also suppresses the selected seat through `skip_seat`; the tick still completes.
That broader seat suppression remains the design question recorded in this node's `NODE.md`.

**This node has no weights, deliberately.** `brain/nodes/basal_ganglia/weights.yaml` is the
empty mapping: a tunable on a catastrophic-only gate is an invitation to loosen it, which is
the failure mode Ruling 16(e) names one layer up. The `weights` field is still on the input
model because every node's read slice carries it; this module reads nothing out of it.
"""

from __future__ import annotations

import posixpath
from pathlib import Path, PurePosixPath

from protean.nodes.vocabulary import (
    ALLOW_IRREVERSIBLE_UNIT_IDS,
    PATH_BEARING_KEYS,
    PATH_SCOPE_PATHS,
)
from protean.state.calls import FiringDecision
from protean.state.enums import ConstraintKind, NodeName, SelectionDecision
from protean.state.inputs import BasalGangliaInput
from protean.state.outputs import SelectionVerdict

#: The check this node's cheap firing test runs. It reads **no threshold key at all** — the gate
#: is § Deliverable 1's stated exemption (folded: S-A17): it is the one node outside
#: `WEIGHTS_WRITABLE_NODES`, its `weights.yaml` is contractually empty, and a tunable on a
#: catastrophic-only gate is an invitation to loosen it. So the check is **structural**: a pending
#: unit is present, or it is not.
CHECK_PENDING_UNIT = "pending_unit"


def _scopes(constraints, workspace_root: str) -> list[Path]:
    """The directories a unit may touch: every `path_scope`, else the workspace root itself."""
    root = Path(workspace_root)
    scopes: list[Path] = []
    for constraint in constraints:
        if constraint.kind is not ConstraintKind.PATH_SCOPE:
            continue
        for entry in constraint.arguments.get(PATH_SCOPE_PATHS, []) or []:
            candidate = Path(str(entry))
            scopes.append(candidate if candidate.is_absolute() else root / candidate)
    return scopes or [root]


def _normalized(path: Path) -> PurePosixPath:
    """The path with every `.` and `..` segment collapsed, **lexically**.

    `posixpath.normpath` is a pure string operation: it opens nothing, stats nothing and
    resolves no symlink, so the gate's "touches no filesystem" property is unchanged. Without
    it `<root>/../outside.txt` is `relative_to(<root>)`-containable and arm (a) never fires on
    a traversal, which is the one escape the arm exists to catch.
    """
    return PurePosixPath(posixpath.normpath(str(path)))


def _inside(candidate: Path, scope: Path) -> bool:
    """Containment without touching the filesystem — the gate resolves no symlink and stats
    nothing, so its verdict is a function of the unit and the constraints alone."""
    try:
        _normalized(candidate).relative_to(_normalized(scope))
    except ValueError:
        return False
    return True


def expectation_paths(unit) -> list[str]:
    """Every workspace path the unit's predicates name. `intent` is prose and yields none."""
    paths: list[str] = []
    for expectation in unit.expected:
        for key in PATH_BEARING_KEYS:
            value = expectation.arguments.get(key)
            if isinstance(value, str) and value:
                paths.append(value)
    return paths


def _allowed_irreversible(constraints, unit_id: str) -> bool:
    for constraint in constraints:
        if constraint.kind is not ConstraintKind.ALLOW_IRREVERSIBLE:
            continue
        named = constraint.arguments.get(ALLOW_IRREVERSIBLE_UNIT_IDS, []) or []
        if unit_id in [str(item) for item in named]:
            return True
    return False


def firing_check(payload: BasalGangliaInput) -> FiringDecision:
    """The cheap check, beside the body — structural, and threshold-free (§ Deliverable 1).

    **The veto always runs when a unit is pending**, which is exactly when this fires: the second
    of the build's two contractual inhibitions is honoured by the shape of the check rather than
    by an exception to it (decision 14, folded: A1-5). A tick with **no** pending unit is the
    `NO_SUBJECT` case build 3's admissible set already scores as no evidence
    (`the build specification (not in this mirror):260`), so skipping there deletes nothing that was ever
    graded.

    `key` is `""` and `threshold` is `None` — C3's validator holds a threshold and the key it was
    read from together, and this check carries neither.
    """
    pending = payload.pending_unit is not None
    return FiringDecision(
        tick=payload.tick,
        node=NodeName.BASAL_GANGLIA,
        check=CHECK_PENDING_UNIT,
        value=float(pending),
        fired=pending,
    )


def run(payload: BasalGangliaInput) -> SelectionVerdict:
    """`go` unless one of the two contractual arms fires. Nothing else vetoes."""
    unit = payload.pending_unit
    if unit is None:
        return SelectionVerdict(tick=payload.tick, decision=SelectionDecision.GO)

    root = Path(payload.workspace_root)
    scopes = _scopes(payload.constraints, payload.workspace_root)
    for raw in expectation_paths(unit):
        candidate = Path(raw)
        absolute = candidate if candidate.is_absolute() else root / candidate
        if not any(_inside(absolute, scope) for scope in scopes):
            return SelectionVerdict(
                tick=payload.tick,
                decision=SelectionDecision.NO_GO,
                unit_id=unit.id,
                veto_reason=(
                    f"expectation path {raw!r} lies outside the permitted scope "
                    f"{[str(scope) for scope in scopes]}"
                ),
            )

    if unit.irreversible and not _allowed_irreversible(payload.constraints, unit.id):
        return SelectionVerdict(
            tick=payload.tick,
            decision=SelectionDecision.NO_GO,
            unit_id=unit.id,
            veto_reason=(
                f"unit {unit.id!r} declares irreversible: true and no allow_irreversible "
                f"constraint names it"
            ),
        )

    return SelectionVerdict(
        tick=payload.tick, decision=SelectionDecision.GO, unit_id=unit.id
    )
