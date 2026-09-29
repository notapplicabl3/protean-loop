"""Node -> its cheap firing check, and the runtime's one reading of the answer.

`the build specification (not in this mirror)` § Deliverable 1 (seam contract C3) and § Directional
decisions 3 and 14: "being on the path no longer means doing work". Every outer node gains one
pure function beside its body -- projected input and its own weights in, a `FiringDecision` out
-- and this module is the **only** place the runtime reads that answer.

**The split is deliberate.** The checks live in `src/protean/nodes/`, beside the bodies they
gate, because a check is a pure callable over a node's own projection and its own weights: it
opens no file, spawns nothing, names no binary and imports nothing from `protean.runtime`
(`tests/nodes/test_purity.py` is the enforcement, row M1 the check). What lives *here* is the
runtime's **policy** over those answers -- which map, which key, and which two bodies are
contractual -- because none of that is a node's to know.

**What a decline stops.** A node that declines does no work at its step: it issues none of the
calls its plan named for it, and it runs no body. `NODE_ORDER` is untouched and the node still
writes its own journal entry at the reserved `call# = 0`, carrying the `FiringDecision` as that
entry's `output` -- a skip is a recorded prediction, not an absence (decision 15,
folded: A1-9).

**And the one body a decline cannot stop.** Homeostasis is one of the two contractual
inhibitions: its ceiling evaluation and its `stop` flag **always** run and it always produces its
full `HomeostasisReport`, so **only its think call is skippable** (folded: S-A16). The gate is the
other, and it needs no exception here at all -- its check is structural, so "the veto always runs
when a unit is pending" is the shape of the check rather than an override of it.

**Which nodes carry a threshold key.** Four: homeostasis, hippocampus, thalamus and the anterior
cingulate. `basal_ganglia` is the stated exemption (folded: S-A17) -- it is the one node outside
`config.WEIGHTS_WRITABLE_NODES`, its `weights.yaml` is contractually empty and stays so, and
`WEIGHTS_WRITABLE_NODES` does not move. The cortex is not a firing node either: it is a seat
folder rather than an outer node (folded: S-A63).

**Outer->outer edges, stated and not built** (§ Deliverable 1, decision 5, digest 2.3). They are
**allowed but exceptional**: the ring `homeostasis -> hippocampus -> thalamus -> basal_ganglia ->
cortex -> anterior_cingulate` stays the **default path**, and an off-ring edge is justified per
edge. **The rule for adding one is `the build specification (not in this mirror)` § Deliverable 4, and no
off-ring edge exists** -- it is rule only, so this module names none. Conditional firing is the
other half of the same sentence: the path does not move, what moves is whether being on it means
doing work. **What decides that a fired node also calls is the call policy beside this module**,
`protean.runtime.triggers` (the same SPEC's § Deliverable 1), which reads the node's call check
exactly as this module reads its cheap check.

**The key names are the nodes' own.** `FIRING_KEYS` is built from the constants the node modules
declare, exactly as `nodes/detectors.THRESHOLD_KEYS` is built from `TRAP_WEIGHT_KEYS`, so a key
is spelled in one place and a rename cannot leave this map behind.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Callable, Final, Mapping

from protean import config
from protean.nodes import (
    anterior_cingulate,
    basal_ganglia,
    hippocampus,
    homeostasis,
    thalamus,
)
from protean.state.calls import FiringDecision
from protean.state.enums import NodeName

#: Node name -> its cheap check. Keyed by `config.DETERMINISTIC_NODES`, like the node registry,
#: so a node with no check is an import-time failure rather than a node that silently never skips.
FIRING_CHECKS: Final[Mapping[str, Callable[[Any], FiringDecision]]] = MappingProxyType(
    {
        "homeostasis": homeostasis.firing_check,
        "hippocampus": hippocampus.firing_check,
        "thalamus": thalamus.firing_check,
        "basal_ganglia": basal_ganglia.firing_check,
        "anterior_cingulate": anterior_cingulate.firing_check,
    }
)

#: Node name -> the `weights.yaml` key its threshold is read from. The gate is absent: its check
#: is structural and reads no threshold key at all.
FIRING_KEYS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "homeostasis": homeostasis.WEIGHT_FIRING,
        "hippocampus": hippocampus.WEIGHT_FIRING,
        "thalamus": thalamus.WEIGHT_FIRING,
        "anterior_cingulate": anterior_cingulate.WEIGHT_FIRING,
    }
)

#: The node whose **body** runs whatever its check answered -- homeostasis, whose ceiling
#: evaluation and `stop` flag are contractual. The gate is not in this tuple because it does not
#: need to be: its check fires exactly when a unit is pending.
CONTRACTUAL_BODIES: Final[tuple[str, ...]] = (str(NodeName.HOMEOSTASIS),)

_missing = tuple(name for name in config.DETERMINISTIC_NODES if name not in FIRING_CHECKS)
if _missing:  # pragma: no cover - a module-level contract assertion, not a branch
    raise ImportError(
        f"config.DETERMINISTIC_NODES names {list(_missing)} with no cheap check in "
        f"protean.runtime.firing -- every outer node gains one (SPEC A.1 § Deliverable 1)"
    )
_extra = tuple(name for name in FIRING_CHECKS if name not in config.DETERMINISTIC_NODES)
if _extra:  # pragma: no cover - a module-level contract assertion, not a branch
    raise ImportError(
        f"protean.runtime.firing holds a check for {list(_extra)}, which "
        f"config.DETERMINISTIC_NODES does not name -- a node that is not on the path cannot fire"
    )
_unwritable = tuple(
    name for name in FIRING_KEYS if name not in config.WEIGHTS_WRITABLE_NODES
)
if _unwritable:  # pragma: no cover - a module-level contract assertion, not a branch
    raise ImportError(
        f"{list(_unwritable)} carry a firing threshold key but sleep may not write their "
        f"weights file -- a threshold no learner can move is not adaptation in data"
    )
del _missing, _extra, _unwritable


def decide(node: NodeName | str, payload: Any) -> FiringDecision:
    """Run this node's cheap check over its projected input. The runtime's one call site."""
    return FIRING_CHECKS[str(NodeName(node))](payload)


def body_runs(node: NodeName | str, decision: FiringDecision) -> bool:
    """Whether this node's body runs: because it fired, or because its body is contractual."""
    return decision.fired or str(NodeName(node)) in CONTRACTUAL_BODIES
