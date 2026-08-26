"""What almost matched, and on which component it failed.

An unmatched row currently arrives at triage saying "1 row, total 821.25". From
that, six of this project's exception codes are indistinguishable: a deduction
filed in the wrong quarter, one filed under the wrong section, one deducted at
the wrong rate and one never deposited at all look identical when all you are
shown is the row that did not match.

Handing that to a model does not produce a classification. It produces a
confident guess between options the input cannot separate — which is worse than
`E14`, because `E14` at least says nobody knows.

So this derives the missing half **arithmetically**. A composite key has parts;
a row that matched nothing may still agree with a row on the other side on all
but one of them, and *which* one is the whole diagnosis. Same party, same
section, same amount, different quarter is a timing error. Same party, same
quarter, same amount, different section is a filing error. Nothing on the other
side at all is a third thing entirely.

**This is arithmetic over records, not a heuristic.** It re-derives from raw
inputs and a third party holding the same two files reaches the same near
misses — which is what makes the evidence usable in a `P0` argument rather than
being another opinion for a human to weigh.

**Domain-agnostic.** The parts come from the profile; this module knows only
that a key has components and that comparing them is informative. `settlement_3way`
declares none and gets the amount-and-date comparison, which is all a payout
reference supports.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..contracts import Record

#: How many candidates to report for one unmatched row. A row that "almost
#: matches" fifty others has not almost matched anything, and a list that long
#: is a prompt nobody can read and a page nobody can scan. Reported as truncated
#: when it bites, because a silent cap reads as "these are all of them".
MAX_CANDIDATES = 4

#: Components always compared, whatever the profile declares. Both are on every
#: record by construction.
ALWAYS = ("amount", "date")


@dataclass(frozen=True)
class Candidate:
    """One row on the other side, and exactly how it differs."""

    record_id: str
    side: str
    agrees_on: tuple[str, ...]
    differs_on: tuple[str, ...]
    detail: dict[str, str]
    """Part -> "ours vs theirs", for the parts that differ. The strings are what
    a person and a model both read, so they carry both values rather than a
    verdict about them."""

    amount_delta: Decimal

    @property
    def strength(self) -> int:
        """How close. Ranking on this rather than on a score, because a score
        invites a threshold and a threshold invites tuning it until the answer
        comes out right."""
        return len(self.agrees_on)


@dataclass(frozen=True)
class NearMiss:
    """The unmatched row, and what nearly matched it."""

    record_id: str
    side: str
    candidates: tuple[Candidate, ...]
    considered: int
    truncated: bool

    def as_evidence(self) -> list[str]:
        """Lines a person reads and a model is given verbatim.

        Deliberately flat strings rather than a structure: this goes into
        `ReconException.evidence`, which is `list[str]` in the semver'd
        contract, and widening a public field to carry a richer shape is a
        breaking change that this does not need.
        """
        if not self.candidates:
            return [
                f"no near miss: nothing on the other side agrees with "
                f"{self.record_id} on any key component ({self.considered} row(s) compared)"
            ]
        lines = []
        for candidate in self.candidates:
            differs = ", ".join(f"{part} {candidate.detail[part]}" for part in candidate.differs_on)
            lines.append(
                f"near miss {candidate.record_id}: agrees on "
                f"{'+'.join(candidate.agrees_on) or 'nothing'}; differs on {differs}"
            )
        if self.truncated:
            lines.append(
                f"{self.considered} row(s) compared; showing the {len(self.candidates)} "
                f"closest — there are more"
            )
        return lines


def _parts_of(record: Record, key_parts: tuple[str, ...]) -> dict[str, str]:
    values = {part: (record.keys.get(part) or "") for part in key_parts}
    values["amount"] = f"{record.amount}"
    values["date"] = record.posted_on.isoformat() if record.posted_on else ""
    return values


def compare(
    row: Record,
    others: list[Record],
    key_parts: tuple[str, ...],
    *,
    limit: int = MAX_CANDIDATES,
) -> NearMiss:
    """Find what `row` almost matched among `others`.

    A candidate must agree on **at least one** declared part. Rows agreeing on
    nothing are not near misses — they are unrelated rows that happen to be in
    the same file, and listing them would bury the one line that matters.
    """
    parts = tuple(key_parts) + ALWAYS
    mine = _parts_of(row, key_parts)

    found: list[Candidate] = []
    for other in others:
        theirs = _parts_of(other, key_parts)
        agrees = tuple(p for p in parts if mine[p] == theirs[p])
        differs = tuple(p for p in parts if mine[p] != theirs[p])
        if not agrees or not differs:
            # Agreeing on nothing is not a near miss. Agreeing on everything is
            # a match the matcher should have made, and reporting it here would
            # hide a matcher bug behind an evidence line.
            continue
        found.append(
            Candidate(
                record_id=other.record_id,
                side=other.side,
                agrees_on=agrees,
                differs_on=differs,
                detail={p: f"{mine[p]!r} vs {theirs[p]!r}" for p in differs},
                amount_delta=(row.amount - other.amount),
            )
        )

    # Closest first, then by smallest amount difference, then by id so two runs
    # over the same inputs produce the same evidence — a decision log that
    # reordered between runs would not replay.
    found.sort(key=lambda c: (-c.strength, abs(c.amount_delta), c.record_id))
    return NearMiss(
        record_id=row.record_id,
        side=row.side,
        candidates=tuple(found[:limit]),
        considered=len(others),
        truncated=len(found) > limit,
    )
