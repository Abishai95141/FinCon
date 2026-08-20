"""Candidate generation.

Blocking is the throughput lever: comparing every anchor against every group is
quadratic and will not survive a real corpus. It is also the layer that can
silently cap the whole system — a true pair dropped here can never be matched
downstream, and nothing later will notice. So `recall` is computed against the
labels and printed on every scorecard (CLAUDE.md invariant 6).

**Blocks are unioned, never intersected.** A pair survives if *any* block
proposes it. Intersecting would mean every block must agree, so a single
imperfect block would drop true pairs — precisely the invisible cap this design
exists to avoid. Blocks are cheap and over-inclusive on purpose; the expensive
exactness lives in the tiers.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from ..contracts import Record

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class BlockingPolicy:
    amount_bucket: Decimal = Decimal("10000.00")
    """Width of an amount bucket. Adjacent buckets are always included, so a
    total sitting near a boundary is not lost to rounding."""

    date_window_days: int = 3
    counterparty_key: str = "gateway"


@dataclass(frozen=True)
class CandidateSet:
    pairs: frozenset[tuple[str, str]]
    """(anchor record_id, group_ref) worth comparing."""

    anchors: int
    groups: int
    by_block: dict[str, int] = field(default_factory=dict)
    """How many pairs each block proposed, before the union. Sums to more than
    `considered` — blocks overlap, which is the point."""

    @property
    def exhaustive(self) -> int:
        return self.anchors * self.groups

    @property
    def considered(self) -> int:
        return len(self.pairs)

    @property
    def reduction(self) -> float:
        return 1 - (self.considered / self.exhaustive) if self.exhaustive else 0.0

    def groups_for(self, anchor_id: str) -> set[str]:
        return {group for anchor, group in self.pairs if anchor == anchor_id}

    def summary(self) -> str:
        blocks = " ".join(f"{name}={n}" for name, n in sorted(self.by_block.items()))
        return (
            f"{self.considered}/{self.exhaustive} pairs "
            f"({self.reduction:.1%} reduction) :: {blocks}"
        )


@dataclass(frozen=True)
class GroupSummary:
    group_ref: str
    total: Decimal
    earliest: object
    latest: object
    counterparties: frozenset[str]


def summarise_groups(records: list[Record], policy: BlockingPolicy) -> dict[str, GroupSummary]:
    buckets: dict[str, list[Record]] = defaultdict(list)
    for record in records:
        if record.group_ref:
            buckets[record.group_ref].append(record)
    return {
        ref: GroupSummary(
            group_ref=ref,
            total=sum((r.amount for r in rows), ZERO),
            earliest=min(r.posted_on for r in rows),
            latest=max(r.posted_on for r in rows),
            counterparties=frozenset(
                v for v in (r.keys.get(policy.counterparty_key) for r in rows) if v
            ),
        )
        for ref, rows in sorted(buckets.items())
    }


def _bucket(amount: Decimal, width: Decimal) -> int:
    return int(abs(amount) // width)


def build(
    anchors: list[Record],
    group_records: list[Record],
    policy: BlockingPolicy | None = None,
) -> CandidateSet:
    """Union of three blocks, each a hash lookup rather than a scan.

    reference     the anchor names a group outright — one candidate, O(1)
    amount        same counterparty, amount in the same or an adjacent bucket
    date          same counterparty, group active inside the date window
    """
    policy = policy or BlockingPolicy()
    groups = summarise_groups(group_records, policy)

    by_amount: dict[tuple[str, int], set[str]] = defaultdict(set)
    by_date: dict[tuple[str, object], set[str]] = defaultdict(set)
    for summary in groups.values():
        bucket = _bucket(summary.total, policy.amount_bucket)
        for party in summary.counterparties or {""}:
            by_amount[(party, bucket)].add(summary.group_ref)
            day = summary.earliest
            while day <= summary.latest:
                by_date[(party, day)].add(summary.group_ref)
                day = day + timedelta(days=1)

    pairs: set[tuple[str, str]] = set()
    counts: dict[str, int] = {"reference": 0, "amount": 0, "date": 0}

    for anchor in anchors:
        party = anchor.keys.get(policy.counterparty_key) or ""

        if anchor.source_row_id and anchor.source_row_id in groups:
            pairs.add((anchor.record_id, anchor.source_row_id))
            counts["reference"] += 1

        bucket = _bucket(anchor.amount, policy.amount_bucket)
        for adjacent in (bucket - 1, bucket, bucket + 1):
            for ref in by_amount.get((party, adjacent), ()):
                pairs.add((anchor.record_id, ref))
                counts["amount"] += 1

        for offset in range(-policy.date_window_days, policy.date_window_days + 1):
            day = anchor.posted_on + timedelta(days=offset)
            for ref in by_date.get((party, day), ()):
                pairs.add((anchor.record_id, ref))
                counts["date"] += 1

    return CandidateSet(
        pairs=frozenset(pairs),
        anchors=len(anchors),
        groups=len(groups),
        by_block=counts,
    )


@dataclass(frozen=True)
class RecallReport:
    """Measured on **candidate pairs**, not on final matches.

    A blocker that keeps a true pair which the tiers then fail to match still
    has perfect recall. Conflating the two would hide which layer lost the pair,
    and blocking is the layer whose losses are unrecoverable.

    For the same reason `dropped` and `unreachable` are separate. A pair whose
    group the source never declared — the ungrouped E09 rows — was never
    presented to the blocker, so calling it a blocking drop blames the wrong
    layer. Both counts are printed: nothing is hidden, and each loss is
    attributed where it belongs.
    """

    reachable: int
    kept: int
    dropped: list[tuple[str, str]]
    unreachable: list[tuple[str, str]]
    """True pairs whose group_ref is not declared anywhere in the data. Not a
    blocking failure — they need subset-sum to become reachable at all."""

    @property
    def true_pairs(self) -> int:
        return self.reachable + len(self.unreachable)

    @property
    def recall(self) -> float:
        return self.kept / self.reachable if self.reachable else 0.0

    def render(self) -> str:
        text = (
            f"blocking recall {self.recall:.1%} "
            f"({self.kept}/{self.reachable} reachable true pairs kept)"
        )
        if self.dropped:
            text += f" — DROPPED {len(self.dropped)}: {self.dropped[:3]}"
        if self.unreachable:
            text += (
                f"; {len(self.unreachable)} true pair(s) not reachable at all — "
                f"the source declared no group: {[p for _, p in self.unreachable][:3]}"
            )
        return text


def recall(
    candidates: CandidateSet,
    truth: dict[str, str],
    anchor_ids: dict[str, str],
    declared_groups: set[str],
) -> RecallReport:
    """`truth` maps anchor external id -> the group_ref that truly backs it.
    `anchor_ids` maps that external id -> the anchor's record_id.
    `declared_groups` is every group_ref that actually appears in the data.
    """
    kept = 0
    dropped: list[tuple[str, str]] = []
    unreachable: list[tuple[str, str]] = []
    for external, group_ref in sorted(truth.items()):
        if group_ref not in declared_groups:
            unreachable.append((external, group_ref))
            continue
        record_id = anchor_ids.get(external)
        if record_id is not None and (record_id, group_ref) in candidates.pairs:
            kept += 1
        else:
            dropped.append((external, group_ref))
    return RecallReport(
        reachable=len(truth) - len(unreachable),
        kept=kept,
        dropped=dropped,
        unreachable=unreachable,
    )
