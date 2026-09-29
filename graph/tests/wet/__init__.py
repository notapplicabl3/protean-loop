"""The wet battery: the only place outside the two licensed packages that spawns the binary.

`the build specification (not in this mirror)` § Deliverable 6, the first wet row.

Everything here is `live`-marked and deselected by `pyproject.toml`'s default `addopts`, so
`uv run pytest` with no marker named stays a no-model-call command exactly as build 1 left it.
The spend itself lives in `probe_first_row.py`, which is a driver rather than a test: a test
module that spent money every time it was collected would make the battery unrunnable.
"""
