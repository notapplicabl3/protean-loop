"""What a `claude -p` process needs in order to start at all under an INVERTED write profile.

`the build specification (not in this mirror)` § Deliverable 2's kernel half, § Build process leg 2,
§ Directional decisions 4, § Resolutions V2-4. **The allowances are measured, never authored:**
a spawn's profile is `file-write*`-denied by default and re-allowed under a per-class set, and
which **device literals** a real CLI process needs on top of that set is not a thing a SPEC can
assert. This script measures it, and its committed capture is what fixes the literal
`SPAWN_PROCESS_ALLOWANCES` in `src/protean/cortex/live/kinds.py`.

**It spends no model call and it resets nothing.** `claude --version` asks the binary its version
and returns; the stand-in binary under `tests/cortex/fake_cli.py` is a `/bin/sh` script. Both are
run under `sandbox-exec` with a composed profile, which is the whole measurement.

**It is a script, not a test** — `tests/cortex/probe_containment.py`'s shape, and for its reason:
a `live`-marked pytest module re-takes its receipt on every collection. Nothing here is collected,
the `--force` gate is what re-takes the capture, and `tests/cortex/test_kinds.py` asserts over what
it stored.

**It reads its own facts off disk** (S-63): the `sandbox-exec` binary comes off the tracked seed's
`sandbox:` block, the five-name environment off `ENV_ALLOWED`, and every exit status and stderr
line in the capture is what the kernel actually answered.

**The ladder is the method.** The narrowest profile is tried first — the allowed set and no device
literal at all — and one rung is added at a time until every criterion below holds. The **first**
rung that passes is what the literal carries: a measured allowance that was never needed is a
widening nobody asked for. If no rung passes, that is the leg's blocker and the capture says so
rather than the allowed set growing until something runs. The criteria are five, and the fifth is
itself a measurement of the first run's:

1. `claude --version` exits 0;
2. the stand-in exits 0 **and** its evidence files are on disk;
3. a write inside the allowed set exits 0;
4. a write to a third path is refused **by the kernel** and leaves nothing behind;
5. a shell under the profile can redirect to `/dev/null`. The first run of this probe measured
   why: rung 0 passed criteria 1–4 while the stand-in's own `2>/dev/null` came back `Operation
   not permitted` on the same line, which is a T3 surface that only *looks* contained — the
   `dispatch` class licenses `Bash(uv:*)` and `Bash(python:*)`, and a shell that cannot open
   `/dev/null` fails in ways nothing on the receipt explains. So the redirect is a criterion and
   the device literal it needs is measured rather than assumed.

**The controlling tty is NOT measurable here and the capture says so.** This script runs from a
dispatched build session with no terminal attached (`controlling_tty` reads `""`), so whether a
real `-p` session needs `(literal "/dev/tty")` is unmeasured by this receipt and the literal stays
without it. What that costs is named in the builder's ledger and is row B49's to settle.

**The profile string is composed here, locally and on purpose.** This script runs *before* the
composition lands in `SandboxPolicy`, so it cannot import it; what closes the gap is that the
capture stores the exact string that ran, and `tests/cortex/test_kinds.py` asserts the landed
composition reproduces it byte for byte. Measured, then asserted — never two spellings.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

from protean import config
from protean.cortex.live.config import ENV_ALLOWED, SANDBOX_BLOCK, SANDBOX_PROFILE_FLAG
from tests.cortex import fake_cli

REPO_ROOT = Path(__file__).resolve().parents[2]
CAPTURE = Path(__file__).resolve().parent / "captures" / "spawn-profile.json"

#: The seats' landed profile head, retained **verbatim** (§ Directional decisions 4): the
#: inversion is two clauses appended to a landed literal, never a second profile language.
PROFILE_HEAD = "(version 1)(allow default)"

#: The one tree `runtime.spawn_writable` seeds (§ Deliverable 5). Named here because the seed key
#: lands in this same order and a probe that read it off disk would be reading its own output.
#:
#: **It is allowed by its REALPATH**, and that is itself a measured fact: on this machine `/tmp`
#: is a symlink to `/private/tmp` and `/var` one to `/private/var`, and `sandbox-exec` matches a
#: `(subpath …)` clause against the resolved path — so an allow clause spelled with the symlink
#: matches nothing at all and the kernel refuses a write the seed meant to grant (measured on the
#: first run of this probe, whose stand-in could not write its own evidence directory). The loader
#: resolves every `spawn_writable` entry for the same reason.
WRITABLE_SEED = "/tmp"
WRITABLE_SEED_RESOLVED = str(Path(WRITABLE_SEED).resolve())

#: What the stand-in is asked to do: one invocation, which writes its argv, stdin, cwd and env
#: files beside `$0` — the evidence directory, and the reason a fixture root's `spawn_writable`
#: names one (folded: S-i37).
STAND_IN_ARGV = ("--print", "probe")

#: The rungs, narrowest first. Each is a tuple of `(path, is_device)` allowances ADDED to the
#: per-class allowed set. `/dev/tty` is the controlling terminal by name; `_TTY` below is the
#: same device as the parent's own, which is what a process that opens its tty by path finds.
_RUNGS: tuple[tuple[str, tuple[tuple[str, bool], ...]], ...] = (
    ("no device literal at all", ()),
    ("/dev/null", (("/dev/null", True),)),
    ("/dev/null + /dev/tty", (("/dev/null", True), ("/dev/tty", True))),
    (
        "/dev/null + /dev/tty + the parent's own tty",
        (("/dev/null", True), ("/dev/tty", True), ("__tty__", True)),
    ),
    ("the whole of /dev, as a subpath", (("/dev", False),)),
)


def compose(subpaths: tuple[str, ...], literals: tuple[str, ...]) -> str:
    """The inverted profile: the landed head, `file-write*` re-denied, then re-allowed.

    `(version 1)(allow default)(deny file-write*)(allow file-write* <subpaths…> <literals…>)` —
    § Deliverable 2's composed literal, stated whole there and composed here for the measurement.
    """
    allowed = " ".join(
        [f'(subpath "{path}")' for path in subpaths] + [f'(literal "{path}")' for path in literals]
    )
    return f"{PROFILE_HEAD}(deny file-write*)(allow file-write* {allowed})"


def controlling_tty() -> str:
    """The parent's own terminal device, or `""` when this runs with no tty at all."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            return os.ttyname(stream.fileno())
        except (OSError, ValueError):
            continue
    return ""


def child_environment() -> dict[str, str]:
    """The five names a spawned process inherits, and **no `TMPDIR`** (folded: S-i48).

    That absence is the measurement's subject as much as the profile is: with no `TMPDIR` among
    the five, the CLI and Python fall back to `/tmp`, which `runtime.spawn_writable` seeds.
    """
    environment = {name: os.environ[name] for name in ENV_ALLOWED if name in os.environ}
    environment.pop("TMPDIR", None)
    return environment


def run(binary: str, profile: str, argv: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
    """One wrapped process, as the runtime really spawns one: `[sandbox-exec, -p, <profile>, …]`."""
    wrapped = [binary, SANDBOX_PROFILE_FLAG, profile, *argv]
    completed = subprocess.run(
        wrapped,
        capture_output=True,
        text=True,
        input="",
        env=child_environment(),
        cwd=str(cwd) if cwd else None,
        timeout=120,
    )
    return {
        "argv": wrapped,
        "exit_status": completed.returncode,
        "stdout": completed.stdout.strip()[:400],
        "stderr": completed.stderr.strip()[:600],
    }


def _trial(
    sandbox_binary: str,
    claude: str,
    rung: tuple[str, tuple[tuple[str, bool], ...]],
    tty: str,
    directories: dict[str, Path],
) -> dict[str, Any]:
    """One rung of the ladder: the version probe, the stand-in, and the write that must refuse."""
    label, allowances = rung
    resolved = tuple(
        (tty if path == "__tty__" else path, device)
        for path, device in allowances
        if not (path == "__tty__" and not tty)
    )
    subpaths = (str(directories["evidence"]), WRITABLE_SEED_RESOLVED) + tuple(
        path for path, device in resolved if not device
    )
    literals = tuple(path for path, device in resolved if device)
    profile = compose(subpaths, literals)

    third = directories["third"] / "refused.txt"
    stand_in = directories["evidence"] / fake_cli.FAKE_BINARY
    for stale in sorted(directories["evidence"].glob("argv-*.txt")):
        stale.unlink()

    inside = directories["evidence"] / "allowed.txt"
    inside.unlink(missing_ok=True)
    marker = directories["evidence"] / "redirect.txt"
    marker.unlink(missing_ok=True)

    version = run(sandbox_binary, profile, [claude, "--version"])
    stand_in_call = run(sandbox_binary, profile, [str(stand_in), *STAND_IN_ARGV])
    shell_inside = run(sandbox_binary, profile, ["/bin/sh", "-c", f"echo ok > {inside}"])
    outside = run(sandbox_binary, profile, ["/bin/sh", "-c", f"echo no > {third}"])
    # Criterion 5, and the interpreter route beside it: what a licensed `Bash(...)`/`Bash(python:*)`
    # command does all day. `cat </dev/null` is a read; the redirect is the write.
    dev_null = run(
        sandbox_binary,
        profile,
        ["/bin/sh", "-c", f"echo hi 2>/dev/null && echo ok >/dev/null && echo done > {marker}"],
    )
    dev_null_python = run(
        sandbox_binary, profile, ["/usr/bin/python3", "-c", "open('/dev/null','w').write('x')"]
    )

    wrote_evidence = bool(sorted(directories["evidence"].glob("argv-*.txt")))
    return {
        "rung": label,
        "allowances": [{"path": path, "device": device} for path, device in resolved],
        "profile": profile,
        "claude_version": version,
        "stand_in": {**stand_in_call, "wrote_its_evidence_files": wrote_evidence},
        "write_inside_the_allowed_set": {
            **shell_inside,
            "path": str(inside),
            "exists_afterwards": inside.exists(),
        },
        "shell_redirect_to_dev_null": {**dev_null, "marker_written": marker.exists()},
        "interpreter_write_to_dev_null": dev_null_python,
        "write_outside_the_allowed_set": {
            **outside,
            "path": str(third),
            "exists_afterwards": third.exists(),
            "refused": not third.exists(),
        },
        "passes": (
            version["exit_status"] == 0
            and stand_in_call["exit_status"] == 0
            and wrote_evidence
            and shell_inside["exit_status"] == 0
            and inside.exists()
            and not third.exists()
            and dev_null["exit_status"] == 0
            and marker.exists()
            and "Operation not permitted" not in dev_null["stderr"]
            and dev_null_python["exit_status"] == 0
        ),
    }


def measure() -> dict[str, Any]:
    """Walk the ladder and answer the whole capture."""
    seed = yaml.safe_load(
        (config.repo_root() / "brain" / "seats.yaml").read_text(encoding="utf-8")
    )
    sandbox_binary = str(seed[SANDBOX_BLOCK]["binary"])
    claude = shutil.which("claude")
    if claude is None:  # pragma: no cover — the binary is `runtime.binary` on this machine
        raise SystemExit("`claude` is not on this machine's PATH; there is nothing to measure")
    claude = str(Path(claude).resolve())
    tty = controlling_tty()

    # Resolved, for `WRITABLE_SEED_RESOLVED`'s reason: a temp root under `/var` is a symlink and
    # an allow clause spelled with it matches nothing the kernel is asked about.
    root = Path(tempfile.mkdtemp(prefix="protean-spawn-profile-probe-")).resolve()
    directories = {
        "evidence": fake_cli.install(root / "evidence"),
        "third": root / "third",
        "cwd": root / "cwd",
    }
    directories["third"].mkdir(parents=True, exist_ok=True)
    directories["cwd"].mkdir(parents=True, exist_ok=True)

    unsandboxed = subprocess.run(
        [claude, "--version"], capture_output=True, text=True, input="", timeout=120
    )
    trials = []
    for rung in _RUNGS:
        trial = _trial(sandbox_binary, claude, rung, tty, directories)
        trials.append(trial)
        if trial["passes"]:
            break
    winner = next((trial for trial in trials if trial["passes"]), None)

    uv = shutil.which("uv")
    interpreter: dict[str, Any] = {"uv": uv}
    if winner is not None and uv is not None:
        # § Deliverable 5: uv's cache stays out of the shipping seed UNLESS a `uv run --offline`
        # needs a write there. Measured under the winning profile, which allows `/tmp` and the
        # evidence directory and nothing else — so a cache write shows up as a refusal.
        interpreter["uv_version"] = run(sandbox_binary, winner["profile"], [uv, "--version"])
        interpreter["uv_run_offline"] = run(
            sandbox_binary,
            winner["profile"],
            [uv, "run", "--offline", "python", "-c", "print('ok')"],
            cwd=directories["cwd"],
        )
        cache = subprocess.run(
            [uv, "cache", "dir"], capture_output=True, text=True, timeout=60
        ).stdout.strip()
        interpreter["uv_cache_dir"] = cache
        interpreter["uv_cache_dir_resolved"] = str(Path(cache).expanduser().resolve()) if cache else ""
        if cache:
            # The confirming half: the same command with the cache allowed and nothing else added,
            # which is what pins the failure above to the cache rather than to the profile's shape.
            with_cache = compose(
                tuple(
                    [str(directories["evidence"]), WRITABLE_SEED_RESOLVED]
                    + [str(Path(cache).expanduser().resolve())]
                    + [entry["path"] for entry in winner["allowances"] if not entry["device"]]
                ),
                tuple(entry["path"] for entry in winner["allowances"] if entry["device"]),
            )
            interpreter["uv_run_offline_with_cache_allowed"] = run(
                sandbox_binary,
                with_cache,
                [uv, "run", "--offline", "python", "-c", "print('ok')"],
                cwd=directories["cwd"],
            )
            interpreter["profile_with_cache_allowed"] = with_cache

    return {
        "measured_by": "tests/cortex/probe_profile.py",
        "spends": "nothing — `claude --version` and a /bin/sh stand-in, both under sandbox-exec",
        "sandbox_binary": sandbox_binary,
        "claude_binary": claude,
        "claude_version_unsandboxed": {
            "exit_status": unsandboxed.returncode,
            "stdout": unsandboxed.stdout.strip(),
            "stderr": unsandboxed.stderr.strip()[:400],
        },
        "profile_head_retained": PROFILE_HEAD,
        "spawn_writable_seed": [WRITABLE_SEED],
        "spawn_writable_seed_resolved": [WRITABLE_SEED_RESOLVED],
        "environment_names": sorted(child_environment()),
        "tmpdir_of_the_parent": os.environ.get("TMPDIR", ""),
        "controlling_tty": tty,
        "directories": {name: str(path) for name, path in directories.items()},
        "trials": trials,
        "measured_allowances": winner["allowances"] if winner else None,
        "measured_profile": winner["profile"] if winner else None,
        "measured_rung": winner["rung"] if winner else None,
        "interpreter": interpreter,
    }


def _summarise(capture: dict[str, Any]) -> str:
    lines = [
        f"  sandbox: {capture['sandbox_binary']} · claude: {capture['claude_binary']}",
        f"  unsandboxed --version: rc={capture['claude_version_unsandboxed']['exit_status']} "
        f"{capture['claude_version_unsandboxed']['stdout']!r}",
        f"  parent TMPDIR (never in a profile): {capture['tmpdir_of_the_parent']!r} · "
        f"tty: {capture['controlling_tty']!r}",
    ]
    for trial in capture["trials"]:
        outside = trial["write_outside_the_allowed_set"]
        lines.append(
            f"  [{'PASS' if trial['passes'] else 'fail'}] {trial['rung']}: "
            f"claude rc={trial['claude_version']['exit_status']} · "
            f"stand-in rc={trial['stand_in']['exit_status']} "
            f"(wrote={trial['stand_in']['wrote_its_evidence_files']}) · "
            f"inside rc={trial['write_inside_the_allowed_set']['exit_status']} · "
            f"/dev/null rc={trial['shell_redirect_to_dev_null']['exit_status']}"
            f"/py rc={trial['interpreter_write_to_dev_null']['exit_status']} · "
            f"outside rc={outside['exit_status']} refused={outside['refused']}"
        )
        if trial["stand_in"]["stderr"]:
            lines.append(f"        stand-in stderr: {trial['stand_in']['stderr'][:200]}")
        if trial["claude_version"]["stderr"]:
            lines.append(f"        claude stderr: {trial['claude_version']['stderr'][:200]}")
        if outside["stderr"]:
            lines.append(f"        outside stderr: {outside['stderr'][:120]}")
    lines.append(f"  MEASURED: {capture['measured_rung']!r} → {capture['measured_allowances']}")
    interpreter = capture.get("interpreter") or {}
    for name in ("uv_version", "uv_run_offline", "uv_run_offline_with_cache_allowed"):
        if name in interpreter:
            lines.append(
                f"  {name}: rc={interpreter[name]['exit_status']} "
                f"{interpreter[name]['stderr'][:160]!r}"
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-take the capture even though one already exists (it is a receipt, not a cache)",
    )
    args = parser.parse_args(argv)

    if CAPTURE.exists() and not args.force:
        print(f"{CAPTURE.relative_to(REPO_ROOT)} exists; it is the receipt that fixed the literal.")
        print("Pass --force to re-take it.")
        return 0

    capture = measure()
    CAPTURE.parent.mkdir(parents=True, exist_ok=True)
    CAPTURE.write_text(json.dumps(capture, indent=1, ensure_ascii=False), encoding="utf-8")
    print(_summarise(capture))
    print(f"written: {CAPTURE.relative_to(REPO_ROOT)}")
    return 0 if capture["measured_allowances"] is not None else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
