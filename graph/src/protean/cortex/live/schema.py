"""The narrowed `--json-schema`: a tier's result model minus the fields the runtime owns.

`the build specification (not in this mirror)` § Deliverable 1 → *The narrowed schema*, and § Directional
decisions 10 (folded: A1-14, folded: S-17, folded: S-36).

**Derived, never hand-written.** The schema is the tier's result model's own
`model_json_schema()` with two properties deleted. Pydantic puts a sibling `type` on every
constraint keyword it emits, which is the case the CLI's ajv strict-types compile accepts; a
hand-written overlay is the case that fails, so there is none — and `strict_types_violations()`
below is the offline probe that says so before a call is ever made.

**Exactly two properties leave, and they are the runtime's own:** `tick`, which is the
runtime's fact and not the seat's, and `emitter`, which is a `Literal` the tier already fixes.
Asking a model to invent either is asking it to guess a number the caller already knows.
`protean.runtime.seat.decode_seat_result()` fills both back **before** validation, so what the
runtime validates is the unchanged contract and what the seat was asked is a strictly smaller
shape (row K1 asserts the property sets differ by exactly these two).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from protean.runtime.seat import result_model
from protean.state.enums import Tier

#: The two properties the narrowing removes, and there are no others (row K1).
RUNTIME_OWNED_FIELDS: tuple[str, ...] = ("tick", "emitter")

#: The type-specific keywords ajv's `strictTypes` wants a sibling `type` beside. The probe is
#: that rule reproduced locally: the compile itself happens inside the CLI, and reaching it
#: costs a real call, so the shape is checked here where checking is free.
TYPE_SPECIFIC_KEYWORDS: frozenset[str] = frozenset(
    {
        "maximum",
        "minimum",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "multipleOf",
        "maxLength",
        "minLength",
        "pattern",
        "items",
        "prefixItems",
        "maxItems",
        "minItems",
        "uniqueItems",
        "properties",
        "patternProperties",
        "maxProperties",
        "minProperties",
    }
)

#: Where a `$ref` may point. Anything else is a schema the CLI would have to fetch.
DEFS_PREFIX = "#/$defs/"


def narrowed_schema(tier: Tier | str) -> dict[str, Any]:
    """One tier's `--json-schema`: its result model's schema less the runtime-owned fields."""
    schema = result_model(tier).model_json_schema()
    properties = {
        name: value
        for name, value in schema.get("properties", {}).items()
        if name not in RUNTIME_OWNED_FIELDS
    }
    required = [
        name for name in schema.get("required", []) if name not in RUNTIME_OWNED_FIELDS
    ]
    narrowed = {**schema, "properties": properties}
    if required:
        narrowed["required"] = required
    else:
        narrowed.pop("required", None)
    return narrowed


def schema_argument(tier: Tier | str) -> str:
    """The narrowed schema as the one argv token `--json-schema` takes."""
    return json.dumps(narrowed_schema(tier), separators=(",", ":"), ensure_ascii=False)


def _walk(node: Any, path: str, found: list[str]) -> None:
    if isinstance(node, Mapping):
        keywords = TYPE_SPECIFIC_KEYWORDS.intersection(node)
        composed = any(key in node for key in ("$ref", "anyOf", "oneOf", "allOf"))
        if keywords and "type" not in node and not composed:
            raise_at = ", ".join(sorted(keywords))
            found.append(f"{path or '<root>'}: {raise_at} with no sibling `type`")
        ref = node.get("$ref")
        if isinstance(ref, str) and not ref.startswith(DEFS_PREFIX):
            found.append(f"{path or '<root>'}: $ref {ref!r} points outside $defs")
        for key, value in node.items():
            _walk(value, f"{path}.{key}" if path else str(key), found)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _walk(value, f"{path}[{index}]", found)


def strict_types_violations(schema: Mapping[str, Any]) -> list[str]:
    """Every place the schema would fail an ajv strict-types compile, by path. Empty is a pass.

    Offline by construction — it reads the schema and spawns nothing, which is what makes row
    K1's "a schema-compile probe over all three tiers passes offline" a check the default
    battery can run with no model call and no money.
    """
    found: list[str] = []
    _walk(schema, "", found)
    try:
        json.dumps(schema)
    except (TypeError, ValueError) as exc:
        found.append(f"<root>: not JSON-serializable ({exc})")
    return found


def compile_probe() -> dict[str, list[str]]:
    """The probe over both seat tiers: tier → its violations. Every list empty is the pass."""
    return {str(tier): strict_types_violations(narrowed_schema(tier)) for tier in Tier}
