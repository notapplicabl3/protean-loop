"""The `NODE.md` `## Reads` contract: what each node folder must declare, and the parser.

`the build specification (not in this mirror)` § Deliverable 4 → *`NODE.md` is prose, and the model is the
contract*: "A startup check asserts each `NODE.md`'s `## Reads` list names exactly the fields
its input model declares — no more, no fewer — and a drift is a refusal, not a warning."

Both halves of that check live here so there is one of each. The model side is
`declared_reads()`; the file side is `parse_reads_section()`, which fixes the format the seed
files are written in:

    ## Reads

    - `field_name`
    - `another_field`

Every line under the `## Reads` heading matching a single backticked identifier is a field;
the section ends at the next `## ` heading. Nothing else in the file is parsed — that is the
point of § Deliverable 4's "without turning prose into a parsed contract".

**The cortex folder reads the union of the two seat request models.** The five outer
nodes have one input model each; the cortex folder serves director and manager. Its `## Reads`
list names the union of `DirectorRequest` and `ManagerRequest` fields. A.1 retires
`ExecutorRequest`; `WaveMember` is a call request, not a third seat input, and is excluded from
this union. `declared_reads()` below is the executable definition.

The runtime's brain-folder layer calls `check_reads()`; it does not re-implement the parse.
"""

from __future__ import annotations

import re
from types import MappingProxyType
from typing import Final, Mapping

from pydantic import BaseModel

from protean.state.enums import NodeName
from protean.state.errors import ReadsDrift
from protean.state.inputs import (
    BasalGangliaInput,
    HippocampusInput,
    HomeostasisInput,
    MonitorInput,
    ThalamusInput,
)
from protean.state.workspace import DirectorRequest, ManagerRequest

#: The heading the list sits under, and the pattern one entry matches.
READS_HEADING: Final[str] = "## Reads"
_ENTRY = re.compile(r"^\s*[-*]\s+`([A-Za-z_][A-Za-z0-9_]*)`\s*$")
_HEADING = re.compile(r"^##\s+\S")

#: Node folder → the input model(s) its `## Reads` list must name exactly.
NODE_INPUT_MODELS: Final[Mapping[NodeName, tuple[type[BaseModel], ...]]] = MappingProxyType(
    {
        NodeName.HOMEOSTASIS: (HomeostasisInput,),
        NodeName.HIPPOCAMPUS: (HippocampusInput,),
        NodeName.THALAMUS: (ThalamusInput,),
        NodeName.BASAL_GANGLIA: (BasalGangliaInput,),
        NodeName.ANTERIOR_CINGULATE: (MonitorInput,),
        #: Two seats, two request models (`the build specification (not in this mirror)` § Deliverable
        #: 3). `ExecutorRequest` is retired with its tier, and a `WaveMember` is not a seat
        #: request — a dispatch member is filled by the runtime, so the cortex reads nothing
        #: for it.
        NodeName.CORTEX: (DirectorRequest, ManagerRequest),
    }
)


def declared_reads(node: NodeName | str) -> tuple[str, ...]:
    """The field names the node's input model(s) declare, sorted."""
    models = NODE_INPUT_MODELS[NodeName(node)]
    return tuple(sorted({name for model in models for name in model.model_fields}))


def parse_reads_section(text: str) -> tuple[str, ...]:
    """The field names a `NODE.md`'s `## Reads` list names, in file order."""
    fields: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.strip() == READS_HEADING:
            inside = True
            continue
        if inside and _HEADING.match(line):
            break
        if inside:
            match = _ENTRY.match(line)
            if match:
                fields.append(match.group(1))
    return tuple(fields)


def check_reads(node: NodeName | str, text: str) -> None:
    """Raise `ReadsDrift` unless the list names exactly the model's fields — no more, no fewer."""
    declared = set(declared_reads(node))
    listed = set(parse_reads_section(text))
    if declared != listed:
        raise ReadsDrift(
            node=str(NodeName(node)),
            missing=tuple(sorted(declared - listed)),
            extra=tuple(sorted(listed - declared)),
        )
