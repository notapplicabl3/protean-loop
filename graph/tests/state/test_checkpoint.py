"""M2, second half: the checkpoint round-trips, and a version mismatch is a named refusal.

`the build specification (not in this mirror)` § Deliverable 2 — the envelope table, the canonicalization
recipe, and "Versioning is a refusal, not a migration."

The two refusal cases M2 closes on assert on the **error text**, not on the exception type:
the row's check reads "two refusal assertions whose captured error text quotes both version
numbers", and a refusal that printed only "version mismatch" would satisfy the raise while
failing the row. Both numbers, on both sides, in the message.

The ladder's order is asserted directly — envelope version → state version → extension
versions → integrity → `seed_hashes` — by handing `load_checkpoint` a payload that is broken
at two rungs at once and requiring the earlier rung to be the one that fires. An order that
drifted would leave a hand-edited state file reported as an integrity failure, which tells an
operator nothing about what to fix.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from protean import config
from protean.state import (
    BrainState,
    Checkpoint,
    ExtensionVersionMismatch,
    IntegrityMismatch,
    ProjectExtension,
    SchemaVersionMismatch,
    SeedHashMismatch,
    canonical_body,
    compute_integrity,
    load_checkpoint,
    sealed,
    verify_integrity,
)
from tests.state.conftest import populated_state

SEED_PATH = "nodes/anterior_cingulate/weights.yaml"
SEED_HASH = hashlib.sha256(b"seed-bytes").hexdigest()


def make_checkpoint(state: BrainState | None = None) -> Checkpoint:
    return sealed(
        Checkpoint(
            state=state if state is not None else populated_state(),
            extensions={"workload": 1},
            seed_hashes={SEED_PATH: SEED_HASH},
        )
    )


def test_the_envelope_carries_exactly_the_fields_the_spec_names() -> None:
    assert sorted(Checkpoint.model_fields) == sorted(
        ["schema_version", "revision", "state", "extensions", "seed_hashes", "integrity"]
    )


def test_the_envelope_version_is_distinct_from_the_state_version() -> None:
    """Two rungs of the ladder need two numbers; one field cannot refuse twice."""
    checkpoint = make_checkpoint()
    assert "schema_version" in Checkpoint.model_fields
    assert "schema_version" in BrainState.model_fields
    assert checkpoint.schema_version == config.CHECKPOINT_SCHEMA_VERSION
    assert checkpoint.state.schema_version == config.BRAIN_STATE_SCHEMA_VERSION


def test_a_checkpoint_round_trips_the_state_unchanged() -> None:
    checkpoint = make_checkpoint()
    payload = json.loads(json.dumps(checkpoint.model_dump(mode="json")))
    restored = load_checkpoint(payload, extension_versions={"workload": 1})
    assert restored.state == checkpoint.state
    assert restored == checkpoint


def test_the_integrity_hash_excludes_itself_and_is_reproducible() -> None:
    checkpoint = make_checkpoint()
    payload = checkpoint.model_dump(mode="json")
    assert "integrity" not in canonical_body(payload)
    assert compute_integrity(payload) == checkpoint.integrity
    assert compute_integrity(payload) == compute_integrity(payload)
    verify_integrity(payload)


def test_canonicalization_does_not_depend_on_key_order() -> None:
    """`sort_keys=True` is what makes the hash reproducible across two dict orderings."""
    checkpoint = make_checkpoint()
    payload = checkpoint.model_dump(mode="json")
    shuffled = dict(reversed(list(payload.items())))
    assert canonical_body(shuffled) == canonical_body(payload)
    assert compute_integrity(shuffled) == compute_integrity(payload)


def test_a_core_schema_version_mismatch_is_refused_quoting_both_versions() -> None:
    """M2's first refusal. The message carries the number on disk AND the one in the code."""
    checkpoint = make_checkpoint()
    payload = checkpoint.model_dump(mode="json")
    payload["state"]["schema_version"] = config.BRAIN_STATE_SCHEMA_VERSION + 1
    with pytest.raises(SchemaVersionMismatch) as raised:
        load_checkpoint(payload, extension_versions={"workload": 1})
    message = str(raised.value)
    assert str(config.BRAIN_STATE_SCHEMA_VERSION + 1) in message
    assert str(config.BRAIN_STATE_SCHEMA_VERSION) in message
    assert "BrainState" in message
    assert "refuses rather than migrating" in message


def test_an_extension_version_mismatch_is_refused_quoting_both_versions() -> None:
    """M2's second refusal. Adaptation is data, and data carries its own version."""
    checkpoint = sealed(
        Checkpoint(
            state=populated_state().model_copy(
                update={"extensions": {"workload": ProjectExtension(name="workload", version=2)}}
            ),
            extensions={"workload": 2},
            seed_hashes={},
        )
    )
    payload = checkpoint.model_dump(mode="json")
    with pytest.raises(ExtensionVersionMismatch) as raised:
        load_checkpoint(payload, extension_versions={"workload": 5})
    message = str(raised.value)
    assert "2" in message and "5" in message
    assert "workload" in message
    assert "refuses rather than migrating" in message


def test_an_envelope_version_mismatch_is_refused_before_the_state_version() -> None:
    checkpoint = make_checkpoint()
    payload = checkpoint.model_dump(mode="json")
    payload["schema_version"] = config.CHECKPOINT_SCHEMA_VERSION + 9
    payload["state"]["schema_version"] = config.BRAIN_STATE_SCHEMA_VERSION + 9
    with pytest.raises(SchemaVersionMismatch) as raised:
        load_checkpoint(payload, extension_versions={"workload": 1})
    assert raised.value.artifact == "checkpoint"
    assert str(config.CHECKPOINT_SCHEMA_VERSION + 9) in str(raised.value)


def test_a_one_byte_edit_to_the_state_is_refused_by_the_integrity_arm() -> None:
    """decision 19's state half: an outside write is a named refusal, not a silent divergence."""
    checkpoint = make_checkpoint()
    payload = checkpoint.model_dump(mode="json")
    payload["state"]["task_id"] = payload["state"]["task_id"] + "!"
    with pytest.raises(IntegrityMismatch) as raised:
        load_checkpoint(payload, extension_versions={"workload": 1})
    assert checkpoint.integrity in str(raised.value)


def test_a_changed_seed_file_is_refused_and_reseed_disarms_only_that_arm() -> None:
    """§ Deliverable 3: `resume --reseed` runs the ladder with the seed arm disarmed, and the
    version arms and the integrity arm over the stored body stay armed."""
    checkpoint = make_checkpoint()
    payload = checkpoint.model_dump(mode="json")

    def retuned(_path: str) -> str:
        return hashlib.sha256(b"someone-retuned-a-threshold").hexdigest()

    with pytest.raises(SeedHashMismatch) as raised:
        load_checkpoint(payload, extension_versions={"workload": 1}, seed_reader=retuned)
    assert SEED_PATH in str(raised.value)
    assert "resume --reseed" in str(raised.value)

    # disarmed: the same payload loads
    load_checkpoint(payload, extension_versions={"workload": 1}, seed_reader=None)

    # ...but the integrity arm is still armed with the seed arm disarmed
    edited = checkpoint.model_dump(mode="json")
    edited["state"]["tick"] = 999
    with pytest.raises(IntegrityMismatch):
        load_checkpoint(edited, extension_versions={"workload": 1}, seed_reader=None)


def test_an_unchanged_seed_file_passes_the_arm() -> None:
    checkpoint = make_checkpoint()
    payload = checkpoint.model_dump(mode="json")
    load_checkpoint(
        payload, extension_versions={"workload": 1}, seed_reader=lambda _p: SEED_HASH
    )


def test_the_revision_exists_from_v1_and_an_administrative_commit_reseals() -> None:
    """§ Deliverable 3: an administrative commit increments `revision` and recomputes
    `integrity` while no node runs."""
    checkpoint = make_checkpoint()
    assert checkpoint.revision == 0
    administrative = sealed(checkpoint.model_copy(update={"revision": 1}))
    assert administrative.revision == 1
    assert administrative.integrity != checkpoint.integrity
    load_checkpoint(administrative.model_dump(mode="json"), extension_versions={"workload": 1})


def test_the_lock_file_is_parsed_by_no_loader() -> None:
    """decision 12: `protean.lock` is persisted and deliberately outside the versioned set."""
    # The table's own contents are asserted once, at
    # `test_config_literals.py::test_every_persisted_artifact_carries_a_version`.
    assert config.LOCK_FILENAME not in config.ARTIFACT_SCHEMA_VERSIONS
