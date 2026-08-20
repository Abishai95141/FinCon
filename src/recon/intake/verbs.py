"""Closed vocabulary of parse verbs. An unknown verb is a spec error, not an exec.

Unimplemented. Filled in by phase P2 — see STATUS.md.
Per CLAUDE.md rule 1: this raises rather than returning a plausible value.
"""


def _unbuilt(*_args, **_kwargs):
    raise NotImplementedError(
        "P2 — Closed vocabulary of parse verbs. An unknown verb is a spec error, not an exec."
    )
