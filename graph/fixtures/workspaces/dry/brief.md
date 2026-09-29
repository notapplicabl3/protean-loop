# brief

The seeded material the `dry` scenario's task acts on. Hand-authored: nothing here is copied
from another repository, and no path outside this fixture tree is named.

`the build specification (not in this mirror)` § Directional decisions 17 — the dry task acts on a
**throwaway temp workspace**, created and destroyed by the run, "so the executor contract
carries file-shaped observations from day one". This file is what makes that workspace a real
directory with real bytes in it rather than an empty path string: `protean dry` copies this
directory to a temp location, hands the copy's path to the executor request, and removes it.

## What the note should say

One line, recording that the run reached the act: the loop planned a unit, acted inside it,
and graded the act against a predicate the planner declared before the seat was called.

## What this fixture does NOT prove

The scripted executor **reports** an observation of `notes.md`; nothing in build 1 writes that
file, because build 1 calls no model and the seats are hand-authored responders. The claim
under test here is that the contract can carry a file-shaped observation from a seat to the
monitor and be graded deterministically — not that the observation is true. Whether these are
contracts a live cortex will honour is the build's load-bearing risk and it is the operator's row (B9),
not a row any test in this repository can close.
