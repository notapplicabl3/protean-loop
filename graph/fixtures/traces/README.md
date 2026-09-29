# `fixtures/traces/` — one hand-scripted arm of the update rule per directory

`the build specification (not in this mirror)` § Deliverable 6, the dry-oracle paragraph: "Hand-scripted trace
fixtures under `fixtures/traces/` — prediction/outcome pairs authored to exercise each arm … each
mapping to **byte-expected** `weights.yaml`, `procedures/*.yaml`, `ProjectMemoryRecord` lines and
`SleepReport`." `the work orders (not in this mirror)` order W8; § DoD rows N3 and L9.

**Each directory is one arm and holds two things.**

* `trace.yaml` — the arm, authored by hand. What the run recorded, what earlier runs left in
  project memory, and a `claims:` block naming the answer in the SPEC's own vocabulary.
* `expected/` — what sleep must produce from it, byte for byte. `expected/report.json` is the
  normalised `SleepReport`; `expected/brain/**` mirrors the throwaway brain root, so a
  `weights.yaml` or a project-memory `learning.jsonl` is compared as a whole file rather than
  key by key.

The compiled-habit files live one tree over, in `fixtures/procedures/<arm>/`, because a procedure
is the only artifact sleep writes that is also an artifact the runtime *reads*.

**`claims:` is the oracle; `expected/` is the lock.** The claims block states the arm's answer in
the terms § Deliverable 3 and § Deliverable 4 use — which key moved, from what to what, which way,
which reason withheld it — and `tests/sleep/test_battery.py` asserts it against the report before
it compares a single byte. The byte-expected files then hold the whole artifact still, so a rule
change surfaces as a diff a reader can read rather than as a green suite.

**Two strings in an artifact are environment rather than rule** and are substituted for a
placeholder at compare time (`tests/sleep/conftest.py::normalise`): the absolute path of the
throwaway brain root (`$brain`) and of the throwaway run directory (`$source`), and each verified
seed hash (`$seed:<file>`, naming the file it covers). Nothing else is normalised — every count,
every ratio and the `sleep_id` itself are compared as written, the `sleep_id` being fixed by the
`now=` the battery passes.

**Numbers here are deliberate.** The rule in `fixtures/scenarios/` and `fixtures/seat_scripts/`
that no authored fixture may restate a count or a threshold is a rule about *scenarios*, whose
thresholds live in the weights files the runtime reads. An arm of the update rule is the opposite
kind of fixture: the value a key moves from and the value it moves to are the answer being named.
