"""Rows that disagree with their own population.

`E02` — a gateway billing above the contract tier — was the one planted defect
this engine could not see, and the reason looked obvious: you cannot check a fee
against a contract you were never given. The engine's inputs are
`row_id, row_type, payout_id, gateway, payment_id, value_date, amount`. There is
no rate anywhere, and no terms file. The audit concluded `E02` needed a fee
compared against a rate on a sibling record, and that was wrong — there is no
rate to compare to.

What there *is*, is the population. A gateway's fees follow one relation,
`fee = rate x charge + fixed`, and rows billed on different terms sit off it. So
the finding is not "this fee disagrees with the contract" — we have no contract —
but "**these rows disagree with the other rows of their own peer group, by this
much**". A controller can act on that, and it is re-derivable by a third party
holding only the export.

Measured on batch A: razorpay's 176 fee rows imply `0.024 x charge + 2.00`, and
twelve of them — all in one payout — sit off it by exactly **290.07**, which is
the planted `E02` amount to the paisa. Cashfree's rows scatter by 0.26 in total,
which is rounding, three orders of magnitude away.

**What this deliberately does not claim.** Not "above contract tier": without the
contract, which of the two rates is the agreed one is unknowable, and the
majority is not automatically right. The finding states the disagreement and its
size, and a human decides which side of it is wrong.

Domain-agnostic (invariant 7): the peer key, the two row classes and the link
between them are declared by a profile. Nothing here knows what a gateway is.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from ..contracts import Record

ZERO = Decimal("0.00")
#: Pairs sampled when inferring the relation. Every pair of rows gives one
#: estimate of the rate — the fixed component cancels in the difference — so the
#: mode over a sample is the rate the population agrees on. Bounded because this
#: is quadratic and a close should not pay for certainty it does not need.
SAMPLE = 40


@dataclass(frozen=True)
class Relation:
    """The rate a peer group's rows agree on, and how many agreed."""

    peer: str
    rate: Decimal
    fixed: Decimal
    agreeing: int
    total: int

    def expected(self, base: Decimal) -> Decimal:
        return self.rate * base + self.fixed

    def summary(self) -> str:
        return (
            f"{self.peer}: {self.agreeing}/{self.total} rows agree on "
            f"{self.rate} x base + {self.fixed}"
        )


@dataclass(frozen=True)
class Disagreement:
    """Rows that do not follow their population's relation, and by how much."""

    peer: str
    relation: Relation
    record_ids: list[str]
    variance: Decimal
    group_refs: list[str] = field(default_factory=list)

    def evidence(self) -> list[str]:
        return [
            self.relation.summary(),
            f"{len(self.record_ids)} row(s) disagree by {self.variance} in total",
            f"group(s) {', '.join(self.group_refs) or 'ungrouped'}",
        ]


@dataclass(frozen=True)
class RelationSpec:
    """Which rows relate to which, declared by a profile rather than assumed.

    `subject` rows are the ones under test (a fee); `base` rows are what they are
    levied on (a charge); `link_key` is what pairs one to the other; `peer_key`
    is the population a row is compared against.
    """

    peer_key: str
    link_key: str
    row_type_key: str
    subject: str
    base: str
    minimum_peers: int = 8
    """Below this a 'population' is a handful of rows, and the majority is not
    evidence of anything. Stated rather than tuned: a relation inferred from
    three rows is a coincidence with a decimal point."""


def _pairs(rows: list[tuple[Decimal, Decimal, Record]]) -> Decimal | None:
    """The rate the population agrees on.

    Every pair gives `(f1 - f2) / (g1 - g2)`, and the fixed component cancels —
    so this needs no fitting, no least squares and no floats. The mode wins:
    rows on the agreed terms all produce the same value exactly, and rows on
    other terms produce a scatter.
    """
    seen: Counter[Decimal] = Counter()
    # Sorted before sampling, and the metamorphic suite is why. Taking the first
    # `SAMPLE` rows *in input order* made the inferred rate depend on how the
    # source happened to order its file — so shuffling the same records could
    # change which rows were reported, and a close stopped being replayable.
    # An engine whose answer depends on row order is not a domain-agnostic
    # engine, it is a lucky one.
    window = sorted(rows, key=lambda t: (t[0], t[1], t[2].record_id))[:SAMPLE]
    for i, (g1, f1, _) in enumerate(window):
        for g2, f2, _ in window[i + 1 :]:
            if g1 != g2:
                seen[(f1 - f2) / (g1 - g2)] += 1
    return seen.most_common(1)[0][0] if seen else None


def find(
    records: Sequence[Record], spec: RelationSpec, *, tolerance: Decimal
) -> list[Disagreement]:
    """Rows whose value disagrees with the relation their peers follow.

    `tolerance` is the total variance a peer group may show before it is a
    finding, and it comes from policy — never from the data being examined.
    Rounding shows up here as a few paisa across a whole population; a different
    billing tier shows up as hundreds. The gap is wide enough that the threshold
    is not doing delicate work, which is the only kind of threshold worth having.
    """
    by_link = {
        r.keys.get(spec.link_key): r for r in records if r.keys.get(spec.row_type_key) == spec.base
    }
    populations: dict[str, list[tuple[Decimal, Decimal, Record]]] = defaultdict(list)
    for record in records:
        if record.keys.get(spec.row_type_key) != spec.subject:
            continue
        base = by_link.get(record.keys.get(spec.link_key))
        if base is None or base.amount == ZERO:
            continue
        populations[record.keys.get(spec.peer_key) or ""].append(
            (base.amount, abs(record.amount), record)
        )

    findings: list[Disagreement] = []
    for peer, rows in sorted(populations.items()):
        if len(rows) < spec.minimum_peers:
            continue
        rate = _pairs(rows)
        if rate is None:
            continue
        offsets = Counter((f - rate * g).quantize(Decimal("0.01")) for g, f, _ in rows)
        fixed, agreeing = offsets.most_common(1)[0]
        relation = Relation(peer, rate, fixed, agreeing, len(rows))

        off = [(g, f, r) for g, f, r in rows if (f - rate * g).quantize(Decimal("0.01")) != fixed]
        variance = sum((abs(f - relation.expected(g)) for g, f, _ in off), ZERO).quantize(
            Decimal("0.01")
        )
        if not off or variance <= tolerance:
            continue
        findings.append(
            Disagreement(
                peer=peer,
                relation=relation,
                record_ids=sorted(r.record_id for _, _, r in off),
                variance=variance,
                group_refs=sorted({r.group_ref for _, _, r in off if r.group_ref}),
            )
        )
    return findings
