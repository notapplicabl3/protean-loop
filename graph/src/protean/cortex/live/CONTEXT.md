# Live cortex — invocation and contained spawns

Own live seat/call configuration, process invocation and the tier-three spawn desk. This is one of the two model-invocation packages; `../../oracle/` owns the other. This guide adds no kind or permission.

## Inputs

- Reference: `config.py`, `kinds.py`, `schema.py`; `../../state/calls.py`, `../../state/seat_calls.py` and `../../runtime/seat.py`; A.1/A.1.i contracts through [../../../../a planning record (not in this mirror)](../../../../a planning record (not in this mirror)).
- Working: the selected root's `seats.yaml`, `nodes/cortex/NODE.md`, seat/call/kind prefixes under `seats/`, requests from the common port, checkpointed sessions and the explicitly supplied task workspace.

## Process

1. Use `config.py` for typed configuration and `kinds.py` for class-scoped kind blocks, positive capability grants and confined prompt paths. A kind may narrow its class grant; it does not supply a second workspace or containment channel.
2. Use `invoke.py` for argv, composed profile, caps, retry and process termination; `session.py` owns session handles and `schema.py` the result schema. Tier-three processes use print mode; seat body selection is routed through `../bodies.py`.
3. Use `wave.py` for the task/tick desk: resolve kinds and workspace, check all wave bounds before its first member, spawn per-member instances, then join. Both the manager's wave and a node's delegate arm use this seam.
4. Use `audit.py` for derived witnesses. Return call facts to the runtime, which owns committed receipts; do not turn model assertions into filesystem evidence. Consult [../../../../docs/doctrine.md](../../../../docs/doctrine.md) for known containment limits.

## Outputs

Validated envelopes, call facts and spawn witnesses for the runtime's journal/receipt path; invocation scaffolding under the selected root's `state/<task-id>/spawns/<tick>/`; workspace effects permitted to dispatch members. No independent checkpoint or seed writer belongs here.

## Human check

Inspect the effective capability/profile and receipt against the governing SPEC, using the appropriate `../../../../tests/cortex/` evidence. The captured profile probe is not the live spawn receipt; [../../../the status record (not in this mirror)](../../../the status record (not in this mirror)) owns B42, B49 and B56, and the library is landed with its own operator rows. Dry proof does not authorize a live call.
