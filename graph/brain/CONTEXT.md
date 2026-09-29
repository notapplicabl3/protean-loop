# Brain — seeds and runtime artifacts

This is the runtime tree, separate from the installed Python package. This guide scopes maintenance; it adds no stage or runtime instruction. Current gates live in the status record (not in this mirror), command effects in [../docs/operations.md](../docs/operations.md).

## Inputs

- Reference: `nodes/<node>/NODE.md` and `weights.yaml`; `seats.yaml`; `seats/director.md`, `seats/manager.md`, `seats/calls/`, `seats/kinds/`; `intake/manifest.yaml`; `seeds.yaml`.
- Working: the selected task's `state/<task-id>/checkpoint.json` and journals, `mailbox/open/`, node traces, `semantic/` and `projects/<slug>/memory/`.
- Contract: the governing specification (not in this mirror) selects the applicable SPEC; [../src/protean/runtime/paths.py](../src/protean/runtime/paths.py) owns path derivation.

## Process and ownership

1. Identify whether the file is an authored seed, runtime record or learned material before changing it. The paths above are relative to the selected brain root, not necessarily this checkout.
2. Preserve each node's existing four-part contract: `NODE.md`, `weights.yaml`, `trace.jsonl`, `procedures/`. `NODE.md` supplies identity and the checked `## Reads` declaration; this guide does not replace it or widen its inputs.
3. Let the runtime own checkpoints, journals, committed traces and mailbox lifecycle. The human edit surface in a live mailbox item is its `## Answer` body. Seed hashes and schema checks govern resumption.
4. Let intake own semantic-store replacement and eligible first-write seeding; let offline sleep own learned weight/procedure rewrites and project-memory learning. Follow the operations guide before either writer runs.

## Outputs

- Runtime: `state/<task-id>/`, `episodes/<task-id>/`, `nodes/<node>/trace.jsonl`, mailbox records and terminal `archive/` copies.
- Intake: `semantic/*.jsonl` and eligible seed values.
- Sleep: eligible `nodes/<node>/weights.yaml`, `nodes/<node>/procedures/`, `projects/<slug>/memory/<node>/` and the external `../reports/sleep/` review report.

Generated state is not an interchangeable template. Use the CLI's fixture-copy path for dry scenarios. Seeds, learned files and evidence remain in their established homes; this documentation authorizes no reset, schema migration or kind admission.

## Human check

Read the writer's report alongside its diff and confirm every change belongs to that writer's scope; resolve reset/spend and live acceptance through the named gates in status before proceeding.
