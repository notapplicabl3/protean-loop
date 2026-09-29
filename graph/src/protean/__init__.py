"""PROTEAN — the six-node runtime, two cortex seats, and tier-three call seams.

The default ring keeps one commit boundary per tick. Scripted layers make zero model calls;
live seats and bounded dispatch waves use the cortex port. Offline intake and sleep maintain
the licensed stores between tasks. Builds 1–3 and A.1/A.1.i retain their SPECs as the contract
homes; A.2's first production kinds are landed, and live outer-node triggers are landed and
ship off.

The package deliberately imports no submodule here: `protean.config` is the literal table that
`protean.state` reads its schema versions and closed sets from, so a package-level import of
`state` would make that a cycle.
"""

__version__ = "0.1.0"
