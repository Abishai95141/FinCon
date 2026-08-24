"""The ranked, routed exception worklist.

This is where a controller meets the tail, and until P11 nothing produced it:
`ReconException.rank` was a field with a docstring and no writer.

Two things it is not.

**Not a classifier.** Ranking and routing are arithmetic and a registry lookup —
both deterministic, both available with no model in the room. What an exception
*is* stays P12's problem; where it goes and who looks first does not need one.

**Not a place codes are minted.** An exception carrying a code that resolves in
no registry entry stops the run. Open vocabulary means a code can be *proposed*;
it does not mean a typo becomes a category on first use.

Scoring is integer paise-days. CLAUDE.md rule 4 bans float in the engine for
money, and the same argument applies to a rank: a score that drifts on float
rounding reorders someone's queue between runs for no reason anyone can explain.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..contracts import CodeDefinition, CodeStatus, ReconException, TaxonomyRegistry


@dataclass(frozen=True)
class WorkItem:
    rank: int
    exception: ReconException
    code: CodeDefinition
    owner: str
    cash_impact_paise: int
    age_days: int
    score: int
    authority_note: str | None = None
    """Set when the code is not ratified. A worklist that renders a proposed
    category identically to a promoted one hides the one thing the reader needs
    in order to treat it with the right amount of trust."""

    def render(self) -> str:
        note = f"  [{self.authority_note}]" if self.authority_note else ""
        return (
            f"{self.rank:>3}. {self.code.code:<14} ₹{self.exception.amount:>12}  "
            f"{self.age_days:>3}d  → {self.owner}{note}"
        )


def summarise(items: list[WorkItem]) -> str:
    """How far the routing actually spread.

    Worth printing because on this corpus the answer is uncomfortable: every
    exception the engine raises is an honesty code, honesty codes all belong to
    the controller, and so a working router delivers every item to one desk.
    The machinery is not the bottleneck — classification is, and a dispersion of
    1 says so in a way a green test cannot.
    """
    if not items:
        return "worklist empty"
    owners = sorted({item.owner for item in items})
    unratified = [i for i in items if i.authority_note]
    parts = [f"{len(items)} items → {len(owners)} owner(s): {', '.join(owners)}"]
    if len(owners) == 1:
        parts.append(
            "routing has nothing to discriminate on — every code here resolves to "
            "the same desk, which is what an unclassified tail looks like"
        )
    if unratified:
        parts.append(f"{len(unratified)} carry an unratified code")
    return " · ".join(parts)


def _note(code: CodeDefinition) -> str | None:
    if code.status is CodeStatus.PROMOTED:
        return None
    granted = code.authority.summary()
    return f"{code.status.value} code — {granted}, cannot direct a posting"


def build(
    exceptions: list[ReconException],
    taxonomy: TaxonomyRegistry,
    as_of: date,
) -> list[WorkItem]:
    """Rank by cash impact x age, route by the registry.

    Age is floored at one day so a same-day exception is ranked by its money
    rather than multiplied to nothing — a large exception raised this morning is
    not less urgent than a small one from last week.
    """
    scored: list[tuple[int, str, ReconException, CodeDefinition]] = []
    for exc in exceptions:
        entry = taxonomy.resolve(exc.code)
        paise = int(abs(exc.amount) * 100)
        age = max((as_of - exc.as_of).days, 1)
        scored.append((paise * age, exc.exception_id, exc, entry))

    # Ties break on the exception id, so two identical items keep a stable order
    # across runs. A worklist that shuffles is a worklist nobody trusts.
    scored.sort(key=lambda row: (-row[0], row[1]))

    return [
        WorkItem(
            rank=position,
            exception=exc,
            code=entry,
            owner=taxonomy.route(exc.code),
            cash_impact_paise=int(abs(exc.amount) * 100),
            age_days=max((as_of - exc.as_of).days, 1),
            score=score,
            authority_note=_note(entry),
        )
        for position, (score, _, exc, entry) in enumerate(scored, start=1)
    ]
