"""The published baseline: securo's transfer-detection algorithm.

Transcribed from `repos/securo/backend/app/services/transfer_detection_service.py`
(142 lines). Its algorithm, verbatim in behaviour:

    exact absolute amount equality
    different account
    date within +/- tolerance days (default 2)
    greedy, closest-date-first
    strictly 1:1 — each row pairs at most once

**Fairness note, which belongs beside the number.** securo built this to pair
internal transfers: two accounts, one amount, opposite signs. Our problem is
N:1 — one bank credit against many settlement rows. Running it on raw rows is
running it outside the domain it was written for, and it will score near zero.
That is a true finding (a 1:1 exact matcher cannot address an N:1 problem) but
on its own it is not a flattering comparison.

So we run two variants and report both:

  securo_raw       its algorithm on our data as it actually arrives
  securo_grouped   the same algorithm handed the payout grouping for free

`securo_grouped` is the fairer arm. It isolates what the *matching rule*
contributes once the grouping — which is most of the work — is already done.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from recon.contracts import Record

from . import ArmResult

DATE_TOLERANCE_DAYS = 2  # securo's default


def _greedy_pair(
    anchors: list[tuple[str, Record]],
    candidates: list[tuple[str, Record, Decimal]],
) -> dict[str, frozenset[str]]:
    """Exact absolute amount, within the date window, closest date wins, 1:1."""
    by_amount: dict[Decimal, list[tuple[str, Record, Decimal]]] = defaultdict(list)
    for ext_id, record, total in candidates:
        by_amount[abs(total)].append((ext_id, record, total))

    taken: set[str] = set()
    pairs: dict[str, frozenset[str]] = {}
    for anchor_ext, anchor in sorted(anchors, key=lambda a: (a[1].posted_on, a[0])):
        best: tuple[int, str, Record] | None = None
        for cand_ext, cand, _total in by_amount.get(abs(anchor.amount), []):
            if cand_ext in taken:
                continue
            delta = abs((cand.posted_on - anchor.posted_on).days)
            if delta > DATE_TOLERANCE_DAYS:
                continue
            if best is None or delta < best[0]:
                best = (delta, cand_ext, cand)
        if best is not None:
            taken.add(best[1])
            pairs[anchor_ext] = frozenset({best[1]})
    return pairs


def run_raw(
    bank: list[tuple[str, Record]],
    settlement: list[tuple[str, Record]],
) -> ArmResult:
    candidates = [(ext, rec, rec.amount) for ext, rec in settlement]
    pairs = _greedy_pair(bank, candidates)
    return ArmResult(
        name="securo_raw",
        pairs=pairs,
        notes=[
            "securo's 1:1 exact-amount matcher on raw rows",
            "applied outside its designed domain (it pairs internal transfers, "
            "not N:1 settlements) — a low score here is expected and is the point",
        ],
    )


def run_grouped(
    bank: list[tuple[str, Record]],
    settlement: list[tuple[str, Record]],
) -> ArmResult:
    """Same rule, but handed the payout grouping. Isolates the matching rule
    from the grouping work."""
    groups: dict[str, list[tuple[str, Record]]] = defaultdict(list)
    for ext, rec in settlement:
        if rec.group_ref:
            groups[rec.group_ref].append((ext, rec))

    candidates: list[tuple[str, Record, Decimal]] = []
    members: dict[str, frozenset[str]] = {}
    for group_ref, rows in sorted(groups.items()):
        total = sum((r.amount for _, r in rows), Decimal("0.00"))
        # Represent the group by its LATEST row. A payout settles after the
        # charges in it, so the latest row sits closest to the settlement date
        # and the bank credit that follows. Using the earliest row would push
        # the delta past securo's +/-2 day window and score the baseline at zero
        # for a reason of our choosing rather than its own — a handicapped
        # baseline is a strawman, and the comparison would be worthless.
        anchor_row = max(rows, key=lambda pair: (pair[1].posted_on, pair[0]))[1]
        candidates.append((group_ref, anchor_row, total))
        members[group_ref] = frozenset(ext for ext, _ in rows)

    grouped_pairs = _greedy_pair(bank, candidates)
    pairs = {
        anchor: frozenset().union(*(members[g] for g in group_refs))
        for anchor, group_refs in grouped_pairs.items()
    }
    return ArmResult(
        name="securo_grouped",
        pairs=pairs,
        notes=[
            "securo's rule, given the payout grouping for free",
            "the fairer comparison: it isolates the matching rule from the "
            "grouping, which is most of the work",
        ],
    )
