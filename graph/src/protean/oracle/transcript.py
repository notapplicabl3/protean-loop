"""The `stream-json` transcript, and every metric derived from it.

`the build specification (not in this mirror)` § Deliverable 4 — "**Every metric is derived from the
transcript, never self-reported**" — and § Directional decisions 18.

**Nothing in this module reads a model-authored field.** The `result` event carries the
session's own prose summary of what it did; `assistant` text blocks carry its narration. Both
are ignored here, by construction: `derive_metrics()` reads `tool_use` blocks (the CLI's record
of what was *invoked*) and `tool_result` blocks (the CLI's record of what came *back*), and
nothing else. `WALKED_EVENT_TYPES` and `WALKED_BLOCK_TYPES` are the
whole surface the derivation reads, and `tests/oracle/test_transcript.py` proves the claim
twice: statically, that `result` is not a walked event and `text`/`thinking` are not walked
blocks; and behaviourally, that scrubbing every model-authored field out of the captured fixture
leaves every derived number byte-identical. A metric quietly sourced from `result` would still
produce plausible numbers, which is why one proof is not enough.

**The three metrics, as § Deliverable 4 states them:**

* *steps to first success* — tool-use events **up to and including** the first invocation of the
  task's success command whose result satisfies the predicate. One-based, so a session that
  succeeded on its very first tool use scores 1 and a session that never succeeded scores
  `None` rather than 0.
* *failed commands* — `Bash` results that are not a genuine zero. Non-zero rather than
  "errored": the CLI marks a failing command `is_error`, and where it also prints its own
  `Exit code:` trailer that code is read. A result with **no completion** — a backgrounded
  launch's acknowledgment — is `None` rather than 0 and counts here (S-47).
* *files read* — distinct paths named by `Read`, `Grep` and `Glob` events.

**One JSON object per line, and a malformed line is skipped rather than fatal.** A session
killed at the wall cap leaves a truncated final line, and the events before it are still the
measurement.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

#: `stream-json` event types (`type` on the top-level object).
EVENT_SYSTEM: Final[str] = "system"
EVENT_ASSISTANT: Final[str] = "assistant"
EVENT_USER: Final[str] = "user"
EVENT_RESULT: Final[str] = "result"

#: Content-block types inside an `assistant` or `user` message.
BLOCK_TOOL_USE: Final[str] = "tool_use"
BLOCK_TOOL_RESULT: Final[str] = "tool_result"

#: The tools whose invocations count as reading a path (§ Deliverable 4).
READING_TOOLS: Final[tuple[str, ...]] = ("Read", "Grep", "Glob")

#: The tool whose non-zero results count as failed commands.
BASH_TOOL: Final[str] = "Bash"

#: The `input` key each reading tool names its path under.
PATH_KEYS: Final[dict[str, str]] = {"Read": "file_path", "Grep": "path", "Glob": "path"}

#: What a `Grep`/`Glob` with no explicit path is recorded as: the session's own cwd, which is
#: its clone. A distinct value rather than dropped, because "searched the whole tree" is a read.
IMPLICIT_PATH: Final[str] = "."

#: The **only** event types the derivation walks, and the only block types it looks inside. The
#: static half of "no metric is read from a model-authored field" is an assertion over these two
#: tuples: `result` is not a walked event and `text`/`thinking` are not walked blocks, so the
#: session's own prose is unreachable from here by construction rather than by discipline.
WALKED_EVENT_TYPES: Final[tuple[str, ...]] = (EVENT_ASSISTANT, EVENT_USER)
WALKED_BLOCK_TYPES: Final[tuple[str, ...]] = (BLOCK_TOOL_USE, BLOCK_TOOL_RESULT)

#: Where a model's own words live in a `stream-json` stream. `tests/oracle/test_transcript.py`
#: scrubs every one of these out of the captured fixture and asserts the derived metrics are
#: byte-identical — the behavioural half of the same claim.
#:
#: `MODEL_AUTHORED_BLOCK_TYPES` are content blocks the model composes. `MODEL_AUTHORED_EVENT_KEY`
#: is the `result` event's prose field, which is the session telling you what it thinks it did.
MODEL_AUTHORED_BLOCK_TYPES: Final[tuple[str, ...]] = ("text", "thinking", "redacted_thinking")
MODEL_AUTHORED_EVENT_KEY: Final[str] = "result"

#: How an exit code is recovered from a Bash tool result when the CLI printed one — the CLI's
#: own **trailer** form and nothing else (S-47). Anchored at both ends of a line and read only
#: out of the last few lines of the result, because unanchored this pattern matched a command
#: that merely *printed* the words: `echo "Exit code: 0"`, a `--help` page documenting exit
#: codes, a pasted log. An exit status the CLI did not state is not one that can be read.
_EXIT_CODE = re.compile(r"^exit\s*code[:\s]+(-?\d+)$", re.IGNORECASE)

#: How far back from the end of a tool result the trailer may sit. The CLI writes it last; the
#: slack is for a trailing blank line or a truncation notice beneath it.
EXIT_CODE_TRAILER_LINES: Final[int] = 5

#: How the CLI acknowledges a command it launched and did not wait for. The result carries a
#: task id and a path to poll — no output, no status, **no completion** (S-47). Measured in\n#: a recorded session fixture (not in this mirror).
BACKGROUND_ACKNOWLEDGMENT: Final[str] = "Command running in background"

#: The `Bash` input key that asks for a launch rather than a run. A `tool_use` carrying it is a
#: **measurement violation** and is named as one by `protean.oracle.audit` (S-47): the session
#: took a step whose outcome the transcript cannot witness.
BACKGROUND_KEY: Final[str] = "run_in_background"

#: pytest's terminal summary line: it carries at least one `N passed` or `N failed` and the
#: run's wall time. A collection abort prints `N errors in Ms` and matches neither
#: alternative — which is the whole point (dispatch-14 ledger D14-3).
_PYTEST_SUMMARY = re.compile(
    r"^[=\s]*(?P<body>(?=.*\b\d+\s+(?:passed|failed)\b).*?\bin\s+[\d.]+\s*m?s.*?)[=\s]*$"
)
_PYTEST_COUNT = re.compile(r"\b(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed)\b")


@dataclass(frozen=True, slots=True)
class TranscriptEvent:
    """One tool invocation and the result the CLI paired with it.

    `index` is the invocation's one-based position among **all** tool uses in the session,
    which is what "steps to first success" counts. `result_text` is the CLI's own record of
    what came back — a tool result, never the model's description of it.
    """

    index: int
    tool: str
    tool_use_id: str
    arguments: dict[str, Any]
    result_text: str = ""
    is_error: bool = False

    @property
    def command(self) -> str:
        """The shell command, for a `Bash` invocation; empty for every other tool."""
        return str(self.arguments.get("command", "")) if self.tool == BASH_TOOL else ""

    @property
    def path(self) -> str:
        """The path a reading tool named, or `IMPLICIT_PATH` when it named none."""
        key = PATH_KEYS.get(self.tool)
        if key is None:
            return ""
        return str(self.arguments.get(key) or IMPLICIT_PATH)

    @property
    def backgrounded(self) -> bool:
        """Was this a launch rather than a run? Either way the CLI records it (S-47).

        Two independent tells, because either alone would miss half the cases: the `tool_use`
        input asked for a background launch, or the `tool_result` came back as the CLI's launch
        acknowledgment. Both are the CLI's own bookkeeping; neither is a model's word.
        """
        if bool(self.arguments.get(BACKGROUND_KEY)):
            return True
        return BACKGROUND_ACKNOWLEDGMENT in self.result_text

    @property
    def exit_code(self) -> int | None:
        """The command's exit status, or `None` when the result carries no completion.

        `None` and 0 are different facts and S-47 is the ruling that they are. A result with no
        completion — a backgrounded launch's acknowledgment, or an error the CLI did not put a
        code on — is `None`, so a predicate that needs a genuine zero cannot be satisfied by a
        command whose outcome nobody ever saw. Before S-47 this returned 0 for both, and the
        real capture's tool use 10 (a backgrounded, un-stubbed `digest.cli`) read as a clean
        exit that never happened.
        """
        if self.backgrounded:
            return None
        found = trailer_exit_code(self.result_text)
        if found is not None:
            return found
        return None if self.is_error else 0


@dataclass(slots=True)
class TranscriptMetrics:
    """The three derived counts plus the run's own facts. Every one from the events above."""

    tool_uses: int = 0
    failed_commands: int = 0
    files_read: int = 0
    read_paths: tuple[str, ...] = ()
    tools_used: tuple[str, ...] = ()
    events: tuple[TranscriptEvent, ...] = field(default_factory=tuple)


def _blocks(message: Any) -> Iterator[dict[str, Any]]:
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                yield block


def _result_text(block: dict[str, Any]) -> str:
    """A `tool_result`'s payload, flattened to text.

    The `text` key read here is the one inside a **tool result** — the tool's own output, which
    the CLI writes. It is not an assistant `text` block, and the two are never confused because
    this function is only ever reached from a `BLOCK_TOOL_RESULT` branch.
    """
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return "" if content is None else str(content)


def trailer_exit_code(text: str) -> int | None:
    """The `Exit code: N` line the CLI ends a Bash result with, or `None` (S-47).

    Read from the end and anchored to a whole line, so the words have to be the CLI's trailer
    rather than anything the command printed. `echo "Exit code: 0"` produces the same eight
    characters in the middle of a result and is not an exit status.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in reversed(lines[-EXIT_CODE_TRAILER_LINES:]):
        found = _EXIT_CODE.match(line)
        if found is not None:
            return int(found.group(1))
    return None


def background_launches(metrics: "TranscriptMetrics") -> list[TranscriptEvent]:
    """Every tool use that launched rather than ran — S-47's measurement violations."""
    return [event for event in metrics.events if event.backgrounded]


def parse_transcript(stream: str) -> list[dict[str, Any]]:
    """One `stream-json` stream → its events, skipping any line that is not a JSON object.

    A truncated final line is the normal shape of a session killed at the wall cap, so it is
    dropped rather than raised on: the events before it happened and are still measurable.
    """
    events: list[dict[str, Any]] = []
    for line in stream.splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events


#: Where the CLI records what its permission layer **refused**. It sits on the `result` event
#: beside the session's prose, and it is the CLI's own bookkeeping rather than anything a model
#: wrote — which is why it is read here and the prose beside it is not.
DENIALS_EVENT_KEY: Final[str] = "permission_denials"


def permission_denials(stream: str) -> list[dict[str, Any]]:
    """Every call the permission layer refused, off the `result` event (S-44).

    **A denial is a receipt, not a violation.** Row K6 claims a session "names no tool outside
    that list", and a call the permission layer refused did not run: the list bound, which is
    the thing S-44 ruled into the containment after the first capture came back with an empty
    denial list and thirteen unlisted tools that *had* run (dispatch-14 ledger D14-8). So the
    audit counts denials beside `tool_violations()` rather than folding them into it — an empty
    violation list with a non-empty denial list is the containment working, in one reading.

    This is the one place the `result` event is read, and it is not a metric: nothing in
    `TranscriptMetrics` or `OracleReport` comes from here.
    """
    denials: list[dict[str, Any]] = []
    for event in parse_transcript(stream):
        if event.get("type") != EVENT_RESULT:
            continue
        found = event.get(DENIALS_EVENT_KEY)
        if isinstance(found, list):
            denials = [one for one in found if isinstance(one, dict)]
    return denials


def tool_events(events: Iterable[dict[str, Any]]) -> list[TranscriptEvent]:
    """Every tool invocation, in order, paired with the result the CLI returned for it."""
    invocations: list[TranscriptEvent] = []
    results: dict[str, tuple[str, bool]] = {}
    for event in events:
        kind = event.get("type")
        if kind not in WALKED_EVENT_TYPES:
            # A `system` init event and a `result` event are both skipped here, and the second
            # is the one that matters: it is where the session's own account of its work lives.
            continue
        if kind == EVENT_ASSISTANT:
            for block in _blocks(event.get("message")):
                if block.get("type") != BLOCK_TOOL_USE:
                    continue
                use_id = str(block.get("id", ""))
                arguments = block.get("input")
                invocations.append(
                    TranscriptEvent(
                        index=len(invocations) + 1,
                        tool=str(block.get("name", "")),
                        tool_use_id=use_id,
                        arguments=dict(arguments) if isinstance(arguments, dict) else {},
                    )
                )
        elif kind == EVENT_USER:
            for block in _blocks(event.get("message")):
                if block.get("type") != BLOCK_TOOL_RESULT:
                    continue
                results[str(block.get("tool_use_id", ""))] = (
                    _result_text(block),
                    bool(block.get("is_error", False)),
                )
    paired: list[TranscriptEvent] = []
    for invocation in invocations:
        text, errored = results.get(invocation.tool_use_id, ("", False))
        paired.append(
            TranscriptEvent(
                index=invocation.index,
                tool=invocation.tool,
                tool_use_id=invocation.tool_use_id,
                arguments=invocation.arguments,
                result_text=text,
                is_error=errored,
            )
        )
    return paired


def derive_metrics(stream: str) -> TranscriptMetrics:
    """The whole derivation, from the raw stream. The only entry point a caller needs."""
    events = tool_events(parse_transcript(stream))
    paths: list[str] = []
    seen: set[str] = set()
    failed = 0
    for event in events:
        if event.tool == BASH_TOOL and event.exit_code != 0:
            failed += 1
        if event.tool in READING_TOOLS:
            path = event.path
            if path and path not in seen:
                seen.add(path)
                paths.append(path)
    return TranscriptMetrics(
        tool_uses=len(events),
        failed_commands=failed,
        files_read=len(paths),
        read_paths=tuple(paths),
        tools_used=tuple(sorted({event.tool for event in events if event.tool})),
        events=tuple(events),
    )


def pytest_summary_line(text: str) -> str:
    """The **completion** summary pytest ends a finished run with, or the empty string.

    A collection abort (`2 errors in 1.89s`) carries neither a `passed` nor a `failed` count and
    is deliberately not matched: the run did not complete (dispatch-14 ledger D14-3).
    """
    for line in reversed(text.splitlines()):
        found = _PYTEST_SUMMARY.match(line.strip())
        if found is not None:
            return found.group("body").strip()
    return ""


def pytest_counts(summary: str) -> dict[str, int]:
    """`{passed: 2406, failed: 27, errors: 524}` off a summary line — never off a model's word."""
    counts: dict[str, int] = {}
    for number, label in _PYTEST_COUNT.findall(summary):
        counts["errors" if label.startswith("error") else label] = int(number)
    return counts


#: A line that is nothing but an exit-code marker. Skipped when choosing the line a human
#: would read as the outcome: the code is already carried by `exit_code`, and a `summary_line`
#: of `Exit code: 2` says less than the message above it.
_BARE_EXIT_CODE = re.compile(r"^exit\s*code[:\s]+-?\d+$", re.IGNORECASE)


def last_meaningful_line(text: str) -> str:
    """The last line of a tool result that says something — what `summary_line` carries.

    "Meaningful" excludes blank lines and a bare exit-code marker. Both are noise in the field
    a person reads to see what happened, and the exit status has its own field.
    """
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if stripped and not _BARE_EXIT_CODE.match(stripped):
            return stripped
    return ""


__all__: Sequence[str] = (
    "BACKGROUND_ACKNOWLEDGMENT",
    "BACKGROUND_KEY",
    "BASH_TOOL",
    "BLOCK_TOOL_RESULT",
    "BLOCK_TOOL_USE",
    "DENIALS_EVENT_KEY",
    "EVENT_ASSISTANT",
    "EVENT_RESULT",
    "EVENT_SYSTEM",
    "EVENT_USER",
    "EXIT_CODE_TRAILER_LINES",
    "IMPLICIT_PATH",
    "MODEL_AUTHORED_BLOCK_TYPES",
    "MODEL_AUTHORED_EVENT_KEY",
    "PATH_KEYS",
    "WALKED_BLOCK_TYPES",
    "WALKED_EVENT_TYPES",
    "READING_TOOLS",
    "TranscriptEvent",
    "TranscriptMetrics",
    "background_launches",
    "derive_metrics",
    "last_meaningful_line",
    "parse_transcript",
    "permission_denials",
    "pytest_counts",
    "pytest_summary_line",
    "tool_events",
    "trailer_exit_code",
)
