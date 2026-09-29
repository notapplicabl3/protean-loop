# fixture_one

**This is a fixture, not a kind of work.** It exists so that a `kinds:` container can be *loaded*
with a prefix file that really is on disk, inside `seats/kinds/`, hashed like every other seed —
which is the whole of what `the build specification (not in this mirror)` § Deliverable 1 requires of
a `prompt:`. It names no work, describes no approach and instructs nobody: **what a kind is for,
and what its prefix says, is build A.2's and the operator holds it** (§ Out of scope, rows B48, B52).

Nothing reads this text. The stand-in binary `tests/cortex/fake_cli.py` answers from files beside
itself, so the only facts this file carries are the ones the loader checks: that it exists, that
it resolves by realpath inside `seats/kinds/`, and that editing it moves `seed_hashes()`.
