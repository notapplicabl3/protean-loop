"""One measured session: a contained `claude -p` with tools, streaming JSON, on a fresh clone.

`the build specification (not in this mirror)` § Deliverable 4's vehicle paragraph (folded: A1-8) and
§ Deliverable 1's containment paragraph, **taken whole** (folded: S-30, folded: S-31,
folded: S-32, folded: S-37).

**The containment is not re-derived here.** The environment, the `PATH` and the binary all come
out of `protean.cortex.live.config.SeatsConfig`, and the link farm out of
`protean.cortex.live.invoke.link_farm` — the shared seat environment and link-farm helpers. What this
module adds is the *shape of one measured call*: `--output-format stream-json` instead of
`json`, no `--json-schema` (a synthetic dev answers in prose, not in a result model), no
`--resume` (fresh context per task per repeat is the measurement's premise), and `--add-dir`
naming the session's own clone and nothing else.

**The oracle retains the shared seat containment** (S-44, S-45): the mode is
`dontAsk` and not `auto`, `--tools` carries the seed's tool set, and the whole spawn is wrapped
in `sandbox-exec` with the profile the `sandbox:` block resolves to. All three come out of
`protean.cortex.live.config` — `OracleSeat.tools_argument()` and `SeatsConfig.sandbox` — so the
narrowing is not re-implemented here either.

**Two flags specific to the measured-session argv:**

* `--no-session-persistence`, so a measured session writes no transcript into the CLI's own
  state directory. Row K6 claims the oracle "writes nothing outside the fresh clone and its
  report directory", and session persistence would be a write outside both. Recorded as
  dispatch-14 ledger D14-6.
* `--verbose`, which the CLI requires beside `--output-format stream-json` in print mode. It
  changes what is emitted, never what may run.

**Bounded twice** (folded: S-32): `timeout_seconds` from the `oracle:` block kills the process,
and `--max-budget-usd` carries `max_call_usd`. A killed session is a *recorded outcome* — its
transcript up to the kill is kept and its metrics derived from it — not a retry: every call
spends real money and a re-run would spend it twice for one measurement.

**The process boundary is the live seat's, not a second one** (S-48). `open()` spawns through
`Popen(..., start_new_session=True)` and `communicate(timeout=)`, and a timeout `SIGKILL`s the
whole **process group** through `protean.cortex.live.invoke.kill_process_group` — the same
function `LiveSeat._spawn` calls. `subprocess.run(timeout=)`, which this used to be, kills
the direct child and leaves everything it started: a measured session's `uv`, `pytest` and
backgrounded commands outlived the wall cap and went on writing to a clone the run had already
declared finished, which the deep round found in a real capture. A spawn the kernel refuses
(`OSError` — missing binary, no execute bit, `E2BIG`, `EAGAIN`) becomes a **failed
`SessionResult`** carrying `spawn_error`, never an exception the run loop never expected.
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from protean.cortex.live.config import SeatsConfig
from protean.cortex.live.invoke import (
    ADD_DIR_FLAG,
    KILL_DRAIN_SECONDS,
    MESSAGE_LIMIT,
    ALLOWED_TOOLS_FLAG,
    BUDGET_FLAG,
    DISALLOWED_TOOLS_FLAG,
    EFFORT_FLAG,
    MODEL_FLAG,
    NO_SETTING_SOURCES,
    OUTPUT_FORMAT_FLAG,
    PERMISSION_MODE_FLAG,
    PRINT_FLAG,
    SETTING_SOURCES_FLAG,
    TOOLS_FLAG,
    VERSION_FLAG,
    VERSION_UNSPAWNABLE,
    kill_process_group,
    link_farm,
)
from protean.oracle.config import OracleSeat

#: What `--output-format` is given here, and the one difference from the seat argv that is not
#: a narrowing: the seats want one JSON envelope, the oracle wants every event.
OUTPUT_FORMAT_STREAM_JSON: Final[str] = "stream-json"

#: Required by the CLI beside `stream-json` in print mode. Emission only.
VERBOSE_FLAG: Final[str] = "--verbose"

#: A measured session is never resumed and never replayed, so it has no reason to leave a
#: session file behind — and row K6 claims it leaves nothing outside its clone.
NO_SESSION_PERSISTENCE_FLAG: Final[str] = "--no-session-persistence"


@dataclass(frozen=True, slots=True)
class SessionResult:
    """One spawned session, as it came back. Nothing here is interpreted yet.

    `stdout` is the raw `stream-json` stream — one JSON object per line — and it is what the
    transcript parser and the fixture both hold. `timed_out` records the wall cap firing, which
    is an outcome rather than an error: the events up to the kill are still a measurement.

    `spawn_error` is set when **no process ever existed** — the kernel refused the spawn — which
    is a different fact from a process that ran and exited non-zero, and the reason `OSError` is
    classified here rather than raised (S-48). It mirrors `_Spawn.spawn_error` in
    `protean.cortex.live.invoke`; the shape is mirrored rather than imported because that type
    is private and byte-shaped while this one is text-shaped (ledger S1-5).
    """

    argv: tuple[str, ...]
    cwd: str
    environment: dict[str, str]
    stdout: str
    stderr: str
    exit_code: int | None
    wall_seconds: float
    timed_out: bool
    cli_version: str
    spawn_error: str = ""

    @property
    def spawned(self) -> bool:
        """Did a process ever exist? `False` is the classified `OSError` path."""
        return not self.spawn_error


@dataclass(slots=True)
class OracleSession:
    """The spawner. One instance per run; `open()` is one measured session."""

    seat: OracleSeat
    containment: SeatsConfig
    _farm: Path | None = None
    _farm_built: bool = False
    _version: str = ""
    _spawned: list[tuple[str, ...]] = field(default_factory=list)

    # ----------------------------------------------------------------------------------
    # The environment the child gets, and the binary it is — the shared seat helpers
    # ----------------------------------------------------------------------------------

    def binary(self) -> Path:
        """The absolute path of the CLI, resolved from the parent's PATH before the scrub."""
        return self.containment.resolved_binary()

    def farm(self) -> Path | None:
        if not self._farm_built:
            self._farm = link_farm(
                self.containment.bin_links,
                os.environ.get("PATH", ""),
                self.containment.binary_paths(),
            )
            self._farm_built = True
        return self._farm

    def environment(self) -> dict[str, str]:
        """The scrubbed environment one measured session inherits — five names, PATH rebuilt."""
        farm = self.farm()
        return self.containment.child_environment(
            os.environ, extra_path=() if farm is None else (farm,)
        )

    def cli_version(self, refresh: bool = False) -> str:
        """The resolved `claude --version`, recorded on the report (decision 13).

        `refresh` re-probes rather than reading the cache, and `open()` passes it on every
        session (S-49; ledger S1-9). The CLI is a moving dependency — it auto-updates — and a
        24-session run recording one cached version could not tell you that the binary changed
        underneath it. The probe is a local spawn with no model call and no spend.
        """
        if refresh or not self._version:
            try:
                completed = subprocess.run(
                    [str(self.binary()), VERSION_FLAG],
                    capture_output=True,
                    text=True,
                    check=False,
                    env=self.environment(),
                )
            except OSError:
                # The probe is a spawn like any other, and it runs *inside* the record of a
                # session that is already being refused — so it classifies rather than raising,
                # or the refusal would never reach the run (the live seat's own reading).
                self._version = VERSION_UNSPAWNABLE
            else:
                self._version = (completed.stdout or completed.stderr or "").strip()
        return self._version

    # ----------------------------------------------------------------------------------
    # The invocation
    # ----------------------------------------------------------------------------------

    def argv(self, prompt: str, clone: Path) -> list[str]:
        """The measured session's argv, as it is run — **wrapped**. Recorded on `SessionResult`.

        The list starts at the sandbox binary, not at the CLI: `sandbox-exec -p <profile>` then
        the resolved binary and its flags (S-45), exactly as `LiveSeat.argv()` builds it.
        """
        argv = [
            str(self.binary()),
            PRINT_FLAG,
            SETTING_SOURCES_FLAG,
            NO_SETTING_SOURCES,
            NO_SESSION_PERSISTENCE_FLAG,
            MODEL_FLAG,
            self.seat.model,
            EFFORT_FLAG,
            self.seat.effort,
            OUTPUT_FORMAT_FLAG,
            OUTPUT_FORMAT_STREAM_JSON,
            VERBOSE_FLAG,
            PERMISSION_MODE_FLAG,
            self.seat.permission_mode,
        ]
        if self.seat.allowed_tools:
            argv += [ALLOWED_TOOLS_FLAG, *self.seat.allowed_tools]
        if self.seat.disallowed_tools:
            argv += [DISALLOWED_TOOLS_FLAG, *self.seat.disallowed_tools]
        tools = self.seat.tools_argument()
        if tools is not None:
            # The tool SET, comma-joined in the seed's order — what makes the allow-list above
            # bind at all under `dontAsk` (S-44).
            argv += [TOOLS_FLAG, tools]
        argv += [ADD_DIR_FLAG, str(clone)]
        argv += [BUDGET_FLAG, f"{self.seat.max_call_usd}"]
        argv += [prompt]
        return self.containment.sandbox.wrap(argv)

    def spawned(self) -> tuple[tuple[str, ...], ...]:
        """Every argv this instance has spawned — the audit surface row K6 reads."""
        return tuple(self._spawned)

    def open(self, prompt: str, clone: Path) -> SessionResult:
        """One session. Spends real money exactly once; a timeout is recorded, never retried.

        The spawn is the live seat's (S-48): its own process group, a group `SIGKILL` at the
        wall cap, and a kernel refusal classified rather than raised. Everything else about a
        measured session — the argv, the environment, the one-shot rule — is unchanged.
        """
        argv = self.argv(prompt, clone)
        environment = self.environment()
        started = time.monotonic()
        timed_out = False
        stdout = ""
        stderr = ""
        code: int | None = None
        spawn_error = ""
        try:
            process = subprocess.Popen(
                list(argv),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(clone),
                env=environment,
                text=True,
                # The session leads its own group, so the `uv`, `pytest` and backgrounded
                # commands it starts are in that group with it and die with it.
                start_new_session=True,
            )
        except OSError as error:
            # A missing binary, one without the execute bit, an argv the kernel refuses
            # (`E2BIG`), no process slots (`EAGAIN`). No process exists, so there is nothing to
            # measure — the OS text *is* the record, and the run records a failed session
            # rather than taking an exception it never expected (S-48).
            self._spawned.append(tuple(argv))
            return SessionResult(
                argv=tuple(argv),
                cwd=str(clone),
                environment=dict(environment),
                stdout="",
                stderr=str(error)[:MESSAGE_LIMIT],
                exit_code=None,
                wall_seconds=round(time.monotonic() - started, 3),
                timed_out=False,
                cli_version=self.cli_version(refresh=True),
                spawn_error=str(error)[:MESSAGE_LIMIT],
            )
        with process:
            try:
                stdout, stderr = process.communicate(timeout=self.seat.timeout_seconds)
                code = process.returncode
            except subprocess.TimeoutExpired as expired:
                # The partial stream is kept: a session that ran out of wall clock still took
                # the steps it took, and those steps are the measurement. What must not survive
                # the cap is anything the session started, so the kill is on the group.
                timed_out = True
                kill_process_group(process)
                try:
                    stdout, stderr = process.communicate(timeout=KILL_DRAIN_SECONDS)
                except subprocess.TimeoutExpired:  # pragma: no cover — everything had SIGKILL
                    process.kill()
                    stdout, stderr = _text(expired.stdout), _text(expired.stderr)
        wall = time.monotonic() - started
        self._spawned.append(tuple(argv))
        return SessionResult(
            argv=tuple(argv),
            cwd=str(clone),
            environment=dict(environment),
            stdout=_text(stdout),
            stderr=_text(stderr),
            exit_code=code,
            wall_seconds=round(wall, 3),
            timed_out=timed_out,
            cli_version=self.cli_version(refresh=True),
            spawn_error=spawn_error,
        )


def _text(raw: bytes | str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return raw


__all__: Sequence[str] = (
    "NO_SESSION_PERSISTENCE_FLAG",
    "OUTPUT_FORMAT_STREAM_JSON",
    "VERBOSE_FLAG",
    "OracleSession",
    "SessionResult",
)
