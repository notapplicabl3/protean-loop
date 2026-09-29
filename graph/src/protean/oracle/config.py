"""`brain/seats.yaml`'s `oracle:` block → the synthetic dev's invocation and its containment.

`the build specification (not in this mirror)` § Deliverable 4 ("takes the executor's containment whole"),
§ Deliverable 1's containment paragraph (folded: S-30, folded: S-31, folded: S-32, folded: S-37)
and § Directional decisions 19 (folded: S-34) — **the containment is a T3 contract, never a
builder's default**.

**Whole, not re-derived.** The scrub, the `PATH` build, the binary resolution and the
`bin_links` refusal all come from `protean.cortex.live.config.SeatsConfig` and
`protean.cortex.live.invoke.link_farm` — the same objects order W2 wrote for the executor. This
module reads one more block out of the same file and hands it to the shared helpers. The
oracle retains the seat sandbox profile; A.1.i's kind grants and inverted spawn profile apply
to dispatch/delegate workers and do not automatically narrow the oracle.

**Nothing here defaults,** for the same reason nothing in the seat loader does: a half-authored
`disallowed_tools` that quietly loaded as the empty list would be a containment hole authored by
omission. Every key below is required and a block missing one refuses by name at load time.

**Why the block is self-contained rather than inheriting `runtime:`.** The oracle's link farm is
separate from the runtime's — `rig it` shells to `postman`, which this block licenses. Inheriting would
have made that one difference invisible at the seed; copying makes the whole T3 surface
reviewable in one place, and the loader below asserts the parts that must be identical.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import yaml

# `_strings` and `_tools` are imported rather than re-written on purpose: they are the seat
# loader's own parsers, and a second copy here would drift from the ones that validate the
# original seat lists. The same parser still reads both surfaces' lists.
from protean.cortex.live.config import (
    ENV_ALLOWED,
    RUNTIME_BLOCK,
    SandboxPolicy,
    SeatConfigError,
    SeatsConfig,
    _strings,
    _tools,
    check_permission_mode,
    parse_sandbox,
    tools_argument,
)
from protean.runtime.paths import BrainPaths

#: The block this module reads. Beside the three tier blocks, never one of them (§ Deliverable 4:
#: "it is not a cortex seat … it takes no tier").
ORACLE_BLOCK: Final[str] = "oracle"

#: Every key the `oracle:` block must carry. The containment half — `allowed_tools`,
#: `disallowed_tools`, `path`, `bin_links`, `env_passthrough` — is § Deliverable 1's, taken
#: whole; `timeout_seconds` and `max_call_usd` are S-32's two bounds; `model`, `effort` and
#: `permission_mode` are the session's own.
ORACLE_KEYS: Final[tuple[str, ...]] = (
    "model",
    "effort",
    "permission_mode",
    "allowed_tools",
    "disallowed_tools",
    "tools",
    "path",
    "bin_links",
    "env_passthrough",
    "timeout_seconds",
    "max_call_usd",
)


class OracleConfigError(SeatConfigError):
    """`brain/seats.yaml` is present but does not say what a measured session needs.

    A subclass of the seat loader's own error rather than a second exception type: the two T3
    surfaces refuse malformed containment the same way, and a caller catching one catches both.
    """


@dataclass(frozen=True, slots=True)
class OracleSeat:
    """The `oracle:` block as data. Every field is read off the seed; none is computed."""

    model: str
    effort: str
    permission_mode: str
    allowed_tools: tuple[str, ...]
    disallowed_tools: tuple[str, ...]
    tools: str | tuple[str, ...] | None
    path_entries: tuple[str, ...]
    bin_links: tuple[str, ...]
    env_passthrough: tuple[str, ...]
    timeout_seconds: float
    max_call_usd: float

    def tools_argument(self) -> str | None:
        """What `--tools` is given, through the seat loader's own join (S-44)."""
        return tools_argument(self.tools)

    def containment(self, root: Path, binary: str, sandbox: SandboxPolicy) -> SeatsConfig:
        """The shared seat containment object, filled from the oracle block.

        `tiers` is deliberately empty: the oracle takes no tier, so there is no tier block to
        resolve and `SeatsConfig.tier()` refusing by name is the correct behaviour if anything
        ever asks. What this buys is `child_environment()`, `child_path()`,
        `resolved_binary()`, `binary_paths()` and `binary_directories()` — the whole
        containment, unmodified, from the module that already holds it.
        """
        return SeatsConfig(
            root=root,
            layer="live",
            binary=binary,
            path_entries=self.path_entries,
            bin_links=self.bin_links,
            env_passthrough=self.env_passthrough,
            tiers={},
            sandbox=sandbox,
        )


def parse_oracle(payload: Any, root: Path) -> tuple[OracleSeat, SeatsConfig]:
    """One loaded `seats.yaml` mapping → the oracle block and its containment object."""
    if not isinstance(payload, Mapping):
        raise OracleConfigError("seats.yaml is a mapping of blocks, one per tier plus `runtime`")

    runtime = payload.get(RUNTIME_BLOCK)
    if not isinstance(runtime, Mapping) or "binary" not in runtime:
        raise OracleConfigError(
            "seats.yaml carries no `runtime.binary` — the oracle resolves the same binary the "
            "seats do, from the same seed, rather than naming a second one"
        )

    block = payload.get(ORACLE_BLOCK)
    if not isinstance(block, Mapping):
        raise OracleConfigError(
            f"seats.yaml carries no `{ORACLE_BLOCK}` block — the synthetic dev is a T3 surface "
            f"and refuses to run on a default containment"
        )
    missing = [key for key in ORACLE_KEYS if key not in block]
    if missing:
        raise OracleConfigError(
            f"{ORACLE_BLOCK}: seats.yaml carries no {', '.join(sorted(missing))}"
        )

    passthrough = _strings(block["env_passthrough"], f"{ORACLE_BLOCK}.env_passthrough")
    widened = [name for name in passthrough if name not in ENV_ALLOWED]
    if widened:
        raise OracleConfigError(
            f"{ORACLE_BLOCK}.env_passthrough names {sorted(widened)}, outside the five the "
            f"containment allows ({list(ENV_ALLOWED)}) — widening it is the operator's ruling, not a "
            f"seed edit"
        )
    if not block["allowed_tools"]:
        raise OracleConfigError(
            f"{ORACLE_BLOCK}.allowed_tools is empty — the allow-list is POSITIVE, so an empty "
            f"one is a session that can do nothing, never a session that may do anything"
        )

    # The two checks this module shares with the seat loader: the mode that was measured not to
    # bind (S-44) and the sandbox profile (S-45). Both are the seat loader's own functions — the
    # containment is taken whole — and both are re-raised under this module's error, because a
    # caller catching `OracleConfigError` has to catch every way a measured session refuses.
    try:
        mode = str(check_permission_mode(str(block["permission_mode"]), ORACLE_BLOCK))
        sandbox = parse_sandbox(payload, root)
    except OracleConfigError:
        raise
    except SeatConfigError as refusal:
        raise OracleConfigError(str(refusal)) from refusal

    seat = OracleSeat(
        model=str(block["model"]),
        effort=str(block["effort"]),
        permission_mode=mode,
        allowed_tools=_strings(block["allowed_tools"], f"{ORACLE_BLOCK}.allowed_tools"),
        disallowed_tools=_strings(block["disallowed_tools"], f"{ORACLE_BLOCK}.disallowed_tools"),
        tools=_tools(block["tools"], f"{ORACLE_BLOCK}.tools"),
        path_entries=_strings(block["path"], f"{ORACLE_BLOCK}.path"),
        bin_links=_strings(block["bin_links"], f"{ORACLE_BLOCK}.bin_links"),
        env_passthrough=passthrough,
        timeout_seconds=float(block["timeout_seconds"]),
        max_call_usd=float(block["max_call_usd"]),
    )
    return seat, seat.containment(root, str(runtime["binary"]), sandbox)


def load_oracle(root: Path) -> tuple[OracleSeat, SeatsConfig]:
    """`<brain root>/seats.yaml` → the oracle block, or a refusal naming what is missing.

    Unlike `load_seats`, a missing file is an **error** rather than `None`: a scripted layer is
    a meaningful fallback for a tick and there is no meaningful fallback for a measurement.
    """
    path = BrainPaths(root=root).seats
    if not path.is_file():
        raise OracleConfigError(
            f"{path} does not exist — the oracle's containment is a seed, and it refuses to "
            f"spawn a tool-bearing session without one"
        )
    return parse_oracle(yaml.safe_load(path.read_text(encoding="utf-8")), root)


__all__: Sequence[str] = (
    "ORACLE_BLOCK",
    "ORACLE_KEYS",
    "OracleConfigError",
    "OracleSeat",
    "load_oracle",
    "parse_oracle",
)
