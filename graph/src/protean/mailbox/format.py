"""The mailbox file's rendering and its parse — binding contract 4's file format.

`the build specification (not in this mirror)` § Deliverable 5 → *Format* (folded: A1-5):
`brain/mailbox/open/<interrupt-id>.md`, YAML front matter (`schema_version`, `id`,
`raised_by`, `task`, `tick`, `raised_at`, `kind`) over a markdown question body, and **the
answer is written into the same file beneath a literal `## Answer` heading**.

Nothing in this module is a builder's default: the file format and the answer path are one of
the five contracts build 2 inherits unchanged (§ Scaffold clause).

**The front matter carries exactly the seven keys the SPEC names, and the evidence rides the
body.** `Interrupt.evidence` is not one of the seven, and a `stuck` item is required to carry
"which signals fired, on which units, for how many ticks" in a form the operator can rule on — so it is
rendered as a JSON block under an `## Evidence` heading between the question and the answer.
JSON rather than more YAML because `evidence` is a `dict[str, JsonValue]` and JSON round-trips
it exactly, and pretty-printed because the reader is a person.

**The answer heading is written at raise time with an empty body.** It is the one path any
non-runtime writer may touch (§ Deliverable 5's writable set), so the file has to show where
that is; an absent *or empty* body is unanswered, which is what makes silence never assent.

**Parsing is line-anchored on the headings, never a substring search.** A question body that
happens to quote `## Answer` inside a sentence must not be mistaken for the heading, because
the mistake would read the operator's silence as an answer.
"""

from __future__ import annotations

import json

import yaml

from protean.state.interrupts import ANSWER_HEADING, Interrupt

#: The document separator that opens and closes the YAML front matter.
FRONT_MATTER_FENCE = "---"

#: The seven front-matter keys § Deliverable 5 names, in the order it names them.
FRONT_MATTER_KEYS: tuple[str, ...] = (
    "schema_version",
    "id",
    "raised_by",
    "task",
    "tick",
    "raised_at",
    "kind",
)

#: The heading the evidence block sits under. The question is the body above it.
EVIDENCE_HEADING = "## Evidence"

#: The fence the evidence JSON is written inside, so a markdown reader renders it as a block.
EVIDENCE_FENCE = "```json"


class MailboxFormatError(ValueError):
    """A file under `mailbox/open/` that is not a mailbox item.

    Raised rather than tolerated: the mailbox is the one place a human writes into the brain,
    and a file the runtime cannot parse is a state it must not guess at.
    """


def render(interrupt: Interrupt) -> str:
    """One `Interrupt` → the file's whole text, answer body included when it has one."""
    payload = interrupt.model_dump(mode="json")
    front = {key: payload[key] for key in FRONT_MATTER_KEYS}
    lines = [
        FRONT_MATTER_FENCE,
        yaml.safe_dump(
            front, sort_keys=False, allow_unicode=True, default_flow_style=False
        ).rstrip("\n"),
        FRONT_MATTER_FENCE,
        "",
        interrupt.question.strip(),
        "",
    ]
    if interrupt.evidence:
        lines += [
            EVIDENCE_HEADING,
            "",
            EVIDENCE_FENCE,
            json.dumps(payload["evidence"], indent=2, ensure_ascii=False),
            "```",
            "",
        ]
    lines += [ANSWER_HEADING, "", (interrupt.answer or "").strip(), ""]
    return "\n".join(lines)


def _split_front_matter(text: str) -> tuple[str, str]:
    """`(front matter source, the body below it)`, or `MailboxFormatError`."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONT_MATTER_FENCE:
        raise MailboxFormatError(
            f"a mailbox file opens with a {FRONT_MATTER_FENCE!r} front-matter fence"
        )
    for index in range(1, len(lines)):
        if lines[index].strip() == FRONT_MATTER_FENCE:
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1 :])
    raise MailboxFormatError("the front matter is never closed")


def _section(body: str, heading: str) -> tuple[str, str]:
    """`(everything above the heading, everything below it)`; the heading match is line-anchored."""
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == heading:
            return "\n".join(lines[:index]), "\n".join(lines[index + 1 :])
    return body, ""


def _evidence_from(block: str) -> dict:
    """The JSON inside the evidence fence. An empty section is the empty mapping."""
    inside = block.strip()
    if not inside:
        return {}
    if inside.startswith(EVIDENCE_FENCE):
        inside = inside[len(EVIDENCE_FENCE) :]
    inside = inside.strip().removesuffix("```").strip()
    if not inside:
        return {}
    try:
        loaded = json.loads(inside)
    except ValueError as exc:
        raise MailboxFormatError(f"the evidence block is not JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise MailboxFormatError("the evidence block is a JSON object")
    return loaded


def parse(text: str) -> Interrupt:
    """The file's text → one `Interrupt`. The inverse of `render`, and refuses anything else.

    An absent or whitespace-only `## Answer` body becomes `answer=None`, so
    `Interrupt.is_answered()` reads the same way for a file the operator never opened and one they saved
    without typing.
    """
    front_source, body = _split_front_matter(text)
    try:
        front = yaml.safe_load(front_source)
    except yaml.YAMLError as exc:
        raise MailboxFormatError(f"the front matter is not YAML: {exc}") from exc
    if not isinstance(front, dict):
        raise MailboxFormatError("the front matter is a mapping of the seven named keys")
    missing = [key for key in FRONT_MATTER_KEYS if key not in front]
    if missing:
        raise MailboxFormatError(f"the front matter is missing {missing}")

    above_answer, answer_body = _section(body, ANSWER_HEADING)
    question_body, evidence_block = _section(above_answer, EVIDENCE_HEADING)

    payload = {key: front[key] for key in FRONT_MATTER_KEYS}
    payload["question"] = question_body.strip()
    payload["evidence"] = _evidence_from(evidence_block)
    payload["answer"] = answer_body.strip() or None
    try:
        return Interrupt.model_validate(payload)
    except ValueError as exc:
        raise MailboxFormatError(str(exc)) from exc
