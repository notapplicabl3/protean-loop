# PROTEAN graph — task catalog

The earlier generation of PROTEAN: a fixed graph around Claude Code, with separate package and brain trees. It was retired on 2026-09-27 in favour of the loop at this repository's root and is kept here as a design reference; see `README.md` for what is and is not in this mirror.

| Task | Read next |
|---|---|
| Understand intended behavior and inherited rulings | [docs/doctrine.md](docs/doctrine.md) |
| Inspect, run, resume, test, intake or sleep | [docs/operations.md](docs/operations.md) |
| Locate ownership, files or generated artifacts | [architecture.md](architecture.md) |
| Understand design choices and rejected alternatives | [architecture-logic.md](architecture-logic.md) |
| Work with brain seeds, traces, mailbox or learned state | [brain/CONTEXT.md](brain/CONTEXT.md) |
| Change tick, journal, boundary commit or resume behavior | [src/protean/runtime/CONTEXT.md](src/protean/runtime/CONTEXT.md) |
| Change offline learning or its report | [src/protean/sleep/CONTEXT.md](src/protean/sleep/CONTEXT.md) |
| Change live invocation, kinds, wave bounds or containment | [src/protean/cortex/live/CONTEXT.md](src/protean/cortex/live/CONTEXT.md) |
| Add or change a subagent kind in the library | `brain/seats.yaml`'s `kinds:` container and `brain/seats/kinds/` |
| Change when an outer node calls — its trigger, the delegate bound or the edge rule | `src/protean/nodes/<node>.py` and `brain/nodes/<node>/NODE.md` `## Calls`, and the policy `src/protean/runtime/triggers.py` |
| Change what a seat is sent each tick, or where a seat's session lives | `src/protean/runtime/projections.py` `workspace()`, `src/protean/cortex/live/invoke.py` `cwd_for()`, and the summary bound `max_summary_chars` in `brain/nodes/thalamus/` |
| Change a deterministic node | `src/protean/nodes/<node>.py` and `brain/nodes/<node>/NODE.md`; ownership in `architecture.md` |
| Change a persisted schema | `src/protean/state/` |

Bracketed tags in comments and docstrings (`A.2.i`, `B42`, `W9`, `S-10`, `D14-1`, `§ Deliverable 3`, `decision 5`) cite the build specifications and work orders this tree was built from. Those documents are not in this mirror; the tags are left in place because each sits beside the reasoning it cites.

`brain/nodes/*/NODE.md` remains the node contract; Python source folders retain their existing roles.
