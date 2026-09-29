"""The prison-smell metric: enum/boolean fields against free-text and scored fields.

`the build specification (not in this mirror)` § Deliverable 7 → *The prison smell metric* (folded: A1-8):
"The battery derives by reflection over the state and contract models the ratio of
enum/boolean fields to free-text and scored fields, prints it with both field lists, and closes
an **operator-checkable** row. No threshold is invented — the fear is the operator's (`DIGEST:20`) and so is
the judgment."

**Nothing here is counted by hand and no threshold is asserted.** The reporter walks
`protean.state.MODELS` — which the roster test proves is the whole exported contract set — and
classifies each field by its annotation. The output is the artifact B7 is ruled on; this module
draws no conclusion from it, on purpose.

**How a field is classified.** The annotation is unwrapped through `X | None` and through the
element type of a `list[...]` or the value type of a `dict[...]`, then the leaf decides:

* **constrained** — an `Enum` subclass, a `bool`, or a `Literal`. The schema fixes the values.
* **free** — a `str`, an `int` or a `float`. Free text, or a scored quantity.
* **structural** — a nested contract, or a container of one. Counted separately and reported,
  because its own fields are already counted where that contract is enumerated; folding it
  into either bucket would double-count the schema.

The ratio is over the first two buckets only, which is what "enum/boolean fields to free-text
and scored fields" names.

Run it directly: `uv run python -m tests.state.prison_smell`.
"""

from __future__ import annotations

import types
import typing
from dataclasses import dataclass, field
from enum import Enum

from pydantic import BaseModel, JsonValue

from protean.state import MODELS

CONSTRAINED = "constrained"
FREE = "free"
STRUCTURAL = "structural"


def leaf_annotation(annotation: object) -> object:
    """Unwrap `X | None`, `list[X]` and `dict[K, V]` down to the type that decides."""
    seen = 0
    while seen < 8:
        seen += 1
        origin = typing.get_origin(annotation)
        if origin in (typing.Union, types.UnionType):
            members = [a for a in typing.get_args(annotation) if a is not type(None)]
            if len(members) == 1:
                annotation = members[0]
                continue
            return annotation
        if origin in (list, set, frozenset, tuple):
            args = typing.get_args(annotation)
            if not args:
                return annotation
            annotation = args[0]
            continue
        if origin is dict:
            args = typing.get_args(annotation)
            if len(args) != 2:
                return annotation
            annotation = args[1]
            continue
        return annotation
    return annotation


def classify(annotation: object) -> str:
    """`constrained` · `free` · `structural`, from the annotation alone."""
    leaf = leaf_annotation(annotation)
    if typing.get_origin(leaf) is typing.Literal:
        return CONSTRAINED
    if leaf is JsonValue:
        return STRUCTURAL
    if isinstance(leaf, type):
        if issubclass(leaf, Enum):
            return CONSTRAINED
        if issubclass(leaf, bool):
            return CONSTRAINED
        if issubclass(leaf, BaseModel):
            return STRUCTURAL
        if issubclass(leaf, (int, float, str)):
            return FREE
    return STRUCTURAL


@dataclass
class Report:
    """The three field lists and the ratio derived from the first two."""

    constrained: list[str] = field(default_factory=list)
    free: list[str] = field(default_factory=list)
    structural: list[str] = field(default_factory=list)

    @property
    def rated(self) -> int:
        return len(self.constrained) + len(self.free)

    @property
    def ratio(self) -> float:
        """Constrained per free field. `inf` if nothing is free — which would be the prison."""
        if not self.free:
            return float("inf")
        return len(self.constrained) / len(self.free)

    @property
    def constrained_share(self) -> float:
        if not self.rated:
            return 0.0
        return len(self.constrained) / self.rated


def derive(models: tuple[type, ...] = MODELS) -> Report:
    """Walk every exported contract and classify every field it declares."""
    report = Report()
    buckets = {
        CONSTRAINED: report.constrained,
        FREE: report.free,
        STRUCTURAL: report.structural,
    }
    for model in sorted(models, key=lambda m: m.__name__):
        for name, info in model.model_fields.items():
            buckets[classify(info.annotation)].append(f"{model.__name__}.{name}")
    return report


def render(report: Report) -> str:
    """Both field lists, the third for honesty, and the derived ratio."""
    lines: list[str] = []
    lines.append("PROTEAN — prison-smell metric")
    lines.append("derived by reflection over protean.state.MODELS; no count is written down")
    lines.append("")
    lines.append(f"contracts walked: {len(MODELS)}")
    lines.append("")
    lines.append(f"ENUM / BOOLEAN FIELDS ({len(report.constrained)})")
    lines.append("  the schema fixes the values a field may take")
    for name in report.constrained:
        lines.append(f"  - {name}")
    lines.append("")
    lines.append(f"FREE-TEXT / SCORED FIELDS ({len(report.free)})")
    lines.append("  the schema fixes only the type; the content is the seat's or the measure's")
    for name in report.free:
        lines.append(f"  - {name}")
    lines.append("")
    lines.append(f"STRUCTURAL FIELDS ({len(report.structural)}) — outside the ratio")
    lines.append("  nested contracts and containers of them; their own fields are counted above")
    for name in report.structural:
        lines.append(f"  - {name}")
    lines.append("")
    lines.append("RATIO")
    lines.append(
        f"  enum/boolean : free-text/scored = "
        f"{len(report.constrained)} : {len(report.free)}  "
        f"({report.ratio:.3f} constrained per free field, "
        f"{report.constrained_share:.1%} of {report.rated} rated fields)"
    )
    lines.append("")
    lines.append(
        "No threshold is asserted. DoD row B7 is the operator's: does this read as a schema that "
        "leaves room, or as the prison one layer down?"
    )
    return "\n".join(lines)


def main() -> int:
    print(render(derive()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
