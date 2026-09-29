"""The file format: seven front-matter keys, a question body, an evidence block, one answer.

`the build specification (not in this mirror)` § Deliverable 5 → *Format* (folded: A1-5). This is **binding
contract 4**, so the assertions below are about the bytes on disk and the named heading, not
about a round-trip through a model that could agree with itself.
"""

from __future__ import annotations

import json

import pytest
import yaml

from protean import config
from protean.mailbox.format import (
    EVIDENCE_HEADING,
    FRONT_MATTER_FENCE,
    FRONT_MATTER_KEYS,
    MailboxFormatError,
    parse,
    render,
)
from protean.state.interrupts import ANSWER_HEADING, Interrupt

from tests.mailbox.conftest import item

#: What this module's item says over the battery's shared shape: a later tick, a `raised_at` with
#: microseconds, and a question long enough to be found in a rendered body.
FORMAT_DEFAULTS = {
    "id": "task-x-t3-planner",
    "tick": 3,
    "raised_at": "2026-09-06T21:23:00.123456+00:00",
    "question": "which ledger is authoritative?",
}


def _item(**overrides) -> Interrupt:
    """The shared factory under this module's own defaults."""
    return item(**{**FORMAT_DEFAULTS, **overrides})


def test_the_front_matter_carries_exactly_the_seven_keys_the_spec_names():
    text = render(_item())
    lines = text.splitlines()
    assert lines[0] == FRONT_MATTER_FENCE
    closing = lines.index(FRONT_MATTER_FENCE, 1)
    front = yaml.safe_load("\n".join(lines[1:closing]))
    assert list(front) == list(FRONT_MATTER_KEYS)
    assert front == {
        "schema_version": config.MAILBOX_SCHEMA_VERSION,
        "id": "task-x-t3-planner",
        "raised_by": "manager",
        "task": "task-x",
        "tick": 3,
        "raised_at": "2026-09-06T21:23:00.123456+00:00",
        "kind": "question",
    }


def test_the_question_is_the_body_and_the_answer_heading_is_literal():
    text = render(_item())
    assert "which ledger is authoritative?" in text
    assert f"\n{ANSWER_HEADING}\n" in text, "the one writable path is named in the file"


def test_an_item_with_no_evidence_carries_no_evidence_heading():
    assert EVIDENCE_HEADING not in render(_item())


def test_the_evidence_rides_the_body_as_a_json_block_and_round_trips():
    evidence = {"goal_id": "g-1", "fired": [{"detector": "dislodging", "value": 3.0}]}
    text = render(_item(evidence=evidence))
    assert EVIDENCE_HEADING in text
    block = text.split(EVIDENCE_HEADING, 1)[1].split(ANSWER_HEADING, 1)[0]
    inner = block.strip().removeprefix("```json").removesuffix("```").strip()
    assert json.loads(inner) == evidence
    assert parse(text).evidence == evidence


def test_a_rendered_item_parses_back_to_the_same_model():
    original = _item(evidence={"a": 1}, answer="the primary one")
    assert parse(render(original)) == original


def test_an_absent_or_empty_answer_body_is_unanswered():
    """Silence is never assent — and neither is a file saved without typing."""
    unanswered = parse(render(_item()))
    assert unanswered.answer is None and unanswered.is_answered() is False

    text = render(_item()).replace(f"{ANSWER_HEADING}\n\n\n", f"{ANSWER_HEADING}\n\n   \n\t\n")
    assert parse(text).is_answered() is False


def test_an_answer_written_under_the_heading_is_read_back():
    text = render(_item()) + "the primary ledger, always\n"
    item = parse(text)
    assert item.is_answered() is True
    assert item.answer == "the primary ledger, always"


def test_the_answer_heading_is_matched_on_its_own_line_not_as_a_substring():
    """A question that quotes the heading must not be read as its own answer."""
    quoted = _item(question="do not write your reply as `## Answer` inline; use the heading")
    item = parse(render(quoted))
    assert item.is_answered() is False
    assert item.question == quoted.question


def test_a_file_with_no_front_matter_is_refused():
    with pytest.raises(MailboxFormatError):
        parse("just a markdown file\n")


def test_front_matter_that_is_never_closed_is_refused():
    with pytest.raises(MailboxFormatError):
        parse("---\nid: x\n")


def test_a_missing_front_matter_key_is_refused_by_name():
    text = render(_item()).replace("raised_at:", "raised_when:")
    with pytest.raises(MailboxFormatError, match="raised_at"):
        parse(text)


def test_a_third_kind_is_refused_at_the_file_boundary():
    """`kind` accepts only `question` and `stuck` — the closed set is enforced on read."""
    text = render(_item()).replace("kind: question", "kind: escalate")
    with pytest.raises(MailboxFormatError):
        parse(text)


def test_a_question_the_runtime_raised_is_refused_by_the_licensing_rule():
    """Two licensed raisers: the runtime is licensed for `stuck` and for no other kind."""
    text = render(_item()).replace("raised_by: manager", "raised_by: runtime")
    with pytest.raises(MailboxFormatError):
        parse(text)


def test_an_evidence_block_that_is_not_json_is_refused():
    text = render(_item(evidence={"a": 1})).replace('"a": 1', "a: 1,,")
    with pytest.raises(MailboxFormatError):
        parse(text)
