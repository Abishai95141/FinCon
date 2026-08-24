"""The LLM-only arm: an agent doing the matching, with no verification.

The research dossier calls this the most persuasive result available — publish
arm 3's silent-error rate against arm 4 and the verification thesis is argued
with our own numbers rather than someone else's.

It is not built. The model edge lands at P12, and CLAUDE.md rule 1 bans
"mocking the model and reporting agent metrics" for exactly the reason this arm
exists: the number *is* the claim.

So the arm reports **absent**, not zero. A zero in this row would say we ran a
model and it matched nothing, which is a statement about a model we never
called — and it happens to be a statement that flatters us. An empty row that
flatters us is the most dangerous kind of missing number, so it is named on the
scorecard on every run instead of quietly omitted.
"""

from __future__ import annotations

from . import ArmResult

REASON = "no model configured — the LLM arm and its lift number land at P12"


def absent() -> ArmResult:
    return ArmResult(
        name="llm_only",
        pairs={},
        absent=REASON,
        notes=[
            "reported absent, never zero: a zero here would read as 'it ran and "
            "matched nothing' — see CLAUDE.md rule 1 on mocking the model",
        ],
    )
