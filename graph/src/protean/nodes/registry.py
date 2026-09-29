"""Node name → the pure callable that is that node. The cycle's only dispatch table.

`the build specification (not in this mirror)` § Deliverable 3: "The order is a literal in `config.py`,
iterated by the runtime, **never hardcoded inside a node**." This module holds the *callables*,
not the order — `protean.config.NODE_ORDER` is the order and this map is keyed by it, so a
divergence between the two is an import-time `KeyError` rather than a silently skipped node.

The cortex is absent on purpose: it is the sixth node folder but its occupant is a seat, not a
deterministic callable, and the runtime reaches it through `protean.runtime.seat`'s port.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Callable, Final, Mapping

from protean import config
from protean.nodes import (
    anterior_cingulate,
    basal_ganglia,
    hippocampus,
    homeostasis,
    thalamus,
)

#: The five deterministic nodes, keyed by the names `config.DETERMINISTIC_NODES` declares.
NODES: Final[Mapping[str, Callable]] = MappingProxyType(
    {
        "homeostasis": homeostasis.run,
        "hippocampus": hippocampus.run,
        "thalamus": thalamus.run,
        "basal_ganglia": basal_ganglia.run,
        "anterior_cingulate": anterior_cingulate.run,
    }
)

_missing = tuple(name for name in config.DETERMINISTIC_NODES if name not in NODES)
if _missing:
    raise ImportError(
        f"config.DETERMINISTIC_NODES names {list(_missing)} with no callable in "
        f"protean.nodes.registry — config.py is the owner of the order, this map follows it"
    )
_extra = tuple(name for name in NODES if name not in config.DETERMINISTIC_NODES)
if _extra:
    raise ImportError(
        f"protean.nodes.registry holds {list(_extra)}, which config.DETERMINISTIC_NODES "
        f"does not name — a node that is not on the path cannot fire"
    )
del _missing, _extra
