"""The five ingestion proofs.

None of them needs to know the source's format or domain. They exist because an
adapter authored from a fifty-row sample can be wrong on the tail, and the only
defence that scales is checking what the adapter *produced* against what the
document *asserts about itself*.

A source with no control total, no balances and no internal redundancy gives
these checks almost nothing to bite on. That is not a pass — it is
`strength == "declared"`, and every record from it inherits a lower proof tier.
Reporting a weak intake as verified would be exactly the shallow proxy this
project exists to refuse.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise

from ..contracts import AdapterSpec, Policy, ProofTier, Record
from .readers import SourceDocument
from .spec import Interpreted, interpret

ZERO = Decimal("0.00")


class CheckStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    """The document does not carry what this check needs. Not a pass."""


@dataclass(frozen=True)
class Check:
    name: str
    status: CheckStatus
    detail: str = ""


#: Checks that can actually catch a mis-mapped column. If none of these ran,
#: the intake is unverified however many structural checks passed.
SUBSTANTIVE = frozenset({"control_total", "balance_roll_forward"})


@dataclass(frozen=True)
class IntakeProof:
    source: str
    spec_ref: str
    doc_hash: str
    rows_in_file: int
    rows_parsed: int
    rows_rejected: int
    checks: list[Check]

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if c.status is CheckStatus.FAIL]

    @property
    def verified(self) -> bool:
        """No check failed *and* at least one substantive check actually ran."""
        return not self.failed and any(
            c.name in SUBSTANTIVE and c.status is CheckStatus.PASS for c in self.checks
        )

    @property
    def strength(self) -> str:
        if self.failed:
            return "failed"
        return "verified" if self.verified else "declared"

    @property
    def provenance(self) -> ProofTier:
        """The tier a match built on these records may claim at best."""
        return ProofTier.P0_ARITHMETIC if self.verified else ProofTier.P3_DECLARED

    def summary(self) -> str:
        marks = " ".join(
            f"{c.name}={c.status.value}" for c in sorted(self.checks, key=lambda c: c.name)
        )
        return (
            f"{self.source} [{self.strength}] "
            f"{self.rows_parsed}/{self.rows_in_file} parsed, "
            f"{self.rows_rejected} rejected :: {marks}"
        )


def _row_conservation(doc: SourceDocument, out: Interpreted) -> Check:
    accounted = len(out.records) + len(out.rejections)
    if accounted != doc.rows_in_file:
        return Check(
            "row_conservation",
            CheckStatus.FAIL,
            f"{doc.rows_in_file} rows in file but {accounted} accounted for "
            f"({len(out.records)} parsed + {len(out.rejections)} rejected) — "
            f"{doc.rows_in_file - accounted} vanished",
        )
    unreasoned = [r for r in out.rejections if not r.reason]
    if unreasoned:
        return Check(
            "row_conservation",
            CheckStatus.FAIL,
            f"{len(unreasoned)} rejection(s) carry no reason — a dropped row "
            f"without one is a silent loss",
        )
    # Every row accounted for and none survived is a spec that does not match
    # this document, not a weakly-evidenced intake. Without this, a wrong date
    # format parses nothing and still reports "declared" — which reads as "we
    # got data we could not fully verify" rather than "we got nothing".
    if not out.records:
        if doc.rows_in_file == 0:
            # A header with no data rows. Could be a genuinely empty period or a
            # failed download, and nothing in the file distinguishes them — so
            # this escalates rather than passing as a clean month.
            return Check(
                "row_conservation",
                CheckStatus.FAIL,
                "the source produced zero records and contained no data rows — "
                "either a genuinely empty period or a failed fetch, and the file "
                "cannot tell us which. Declare an empty period explicitly.",
            )
        reasons = sorted({r.detail or r.reason for r in out.rejections})
        return Check(
            "row_conservation",
            CheckStatus.FAIL,
            f"all {doc.rows_in_file} row(s) rejected — the spec does not match "
            f"this document. Reasons: {reasons[:3]}",
        )
    rate = len(out.rejections) / doc.rows_in_file if doc.rows_in_file else 0.0
    return Check(
        "row_conservation",
        CheckStatus.PASS,
        f"{doc.rows_in_file} = {len(out.records)} parsed + {len(out.rejections)} "
        f"rejected ({rate:.0%} rejected)",
    )


def _rejection_budget(doc: SourceDocument, out: Interpreted, policy: Policy | None) -> Check:
    """A reason makes a rejection legible; a budget makes it bounded.

    Row conservation asks whether every departing row carried a reason, never
    whether the departures were justified — so a plausible reject rule discarded
    251 of 517 rows and the intake reported `ok=True` (audit finding `F4`).
    """
    if policy is None:
        # SKIP, not PASS. A check that silently passes without its policy is the
        # same shape as the bypasses this phase closes.
        return Check("rejection_budget", CheckStatus.SKIP, "no policy supplied")
    if doc.rows_in_file == 0:
        return Check("rejection_budget", CheckStatus.SKIP, "no rows to budget")
    rate = Decimal(len(out.rejections)) / Decimal(doc.rows_in_file)
    budget = policy.rejection_budget_pct
    if rate > budget:
        return Check(
            "rejection_budget",
            CheckStatus.FAIL,
            f"{len(out.rejections)}/{doc.rows_in_file} rows rejected = "
            f"{rate:.1%}, over the {budget:.1%} budget in {policy.ref}. A reason "
            f"makes a rejection legible; it does not make it justified.",
        )
    return Check(
        "rejection_budget",
        CheckStatus.PASS,
        f"{rate:.1%} rejected, within the {budget:.1%} budget in {policy.ref}",
    )


def _control_total(doc: SourceDocument, out: Interpreted) -> Check:
    if doc.control_total is None:
        return Check("control_total", CheckStatus.SKIP, "source states no total")
    got = sum((r.amount for r in out.records), ZERO)
    if got != doc.control_total:
        return Check(
            "control_total",
            CheckStatus.FAIL,
            f"parsed sum {got} != stated total {doc.control_total} "
            f"(delta {got - doc.control_total})",
        )
    return Check("control_total", CheckStatus.PASS, f"sum ties to stated {doc.control_total}")


def _roll_forward(doc: SourceDocument, out: Interpreted) -> Check:
    """Per-row where the source carries a running balance, aggregate where it
    states opening and closing. The per-row form is the stronger of the two: it
    localises the first divergent row instead of reporting one end-to-end delta.
    """
    amounts = {r.row_ordinal: r.amount for r in out.records}

    if len(out.running_balances) >= 2:
        chain = sorted(out.running_balances)
        for (_, prev_bal), (ordinal, stated) in pairwise(chain):
            movement = amounts.get(ordinal)
            if movement is None:
                continue
            expected = prev_bal + movement
            if expected != stated:
                return Check(
                    "balance_roll_forward",
                    CheckStatus.FAIL,
                    f"row {ordinal}: {prev_bal} + {movement} = {expected}, "
                    f"but the source states {stated} (delta {expected - stated})",
                )
        return Check(
            "balance_roll_forward",
            CheckStatus.PASS,
            f"running balance chains across {len(chain)} rows",
        )

    if doc.opening_balance is not None and doc.closing_balance is not None:
        rolled = doc.opening_balance + sum((r.amount for r in out.records), ZERO)
        if rolled != doc.closing_balance:
            return Check(
                "balance_roll_forward",
                CheckStatus.FAIL,
                f"opening {doc.opening_balance} + movements = {rolled}, "
                f"but closing is stated as {doc.closing_balance} "
                f"(delta {rolled - doc.closing_balance})",
            )
        return Check(
            "balance_roll_forward",
            CheckStatus.PASS,
            f"{doc.opening_balance} + movements = {doc.closing_balance}",
        )

    return Check("balance_roll_forward", CheckStatus.SKIP, "source carries no balances")


def _type_domain(spec: AdapterSpec, out: Interpreted, window: tuple[date, date] | None) -> Check:
    """Record's own validators already reject a bad currency or a non-Decimal
    amount at construction, so this checks what they cannot: that the values are
    *plausible*. A two-digit year pivoting to the wrong century parses cleanly
    and is wrong by a hundred years."""
    wrong_ccy = [r.record_id for r in out.records if r.currency != spec.currency]
    if wrong_ccy:
        return Check(
            "type_domain",
            CheckStatus.FAIL,
            f"{len(wrong_ccy)} record(s) not in {spec.currency}: {wrong_ccy[:3]}",
        )
    if window is not None:
        lo, hi = window
        stray = [(r.record_id, r.posted_on) for r in out.records if not lo <= r.posted_on <= hi]
        if stray:
            return Check(
                "type_domain",
                CheckStatus.FAIL,
                f"{len(stray)} date(s) outside {lo}..{hi} — check the century "
                f"pivot on two-digit years: {stray[:3]}",
            )
    return Check(
        "type_domain",
        CheckStatus.PASS,
        f"{len(out.records)} record(s) in {spec.currency}"
        + (f", dates within {window[0]}..{window[1]}" if window else ""),
    )


def _idempotence(spec: AdapterSpec, doc: SourceDocument, out: Interpreted) -> Check:
    """Re-interpret the same document and compare. Catches nondeterminism in the
    interpreter itself — a set iteration, a dict ordering assumption — which
    would make re-ingest produce different records from identical bytes."""
    again = interpret(spec, doc)
    first = [(r.record_id, r.posted_on, r.amount) for r in out.records]
    second = [(r.record_id, r.posted_on, r.amount) for r in again.records]
    if first != second:
        return Check(
            "idempotence",
            CheckStatus.FAIL,
            "re-interpreting the same bytes produced different records",
        )
    return Check("idempotence", CheckStatus.PASS, f"stable over {len(first)} record(s)")


def prove(
    spec: AdapterSpec,
    doc: SourceDocument,
    out: Interpreted,
    window: tuple[date, date] | None = None,
    policy: Policy | None = None,
) -> IntakeProof:
    return IntakeProof(
        source=spec.source,
        spec_ref=spec.ref,
        doc_hash=doc.doc_hash,
        rows_in_file=doc.rows_in_file,
        rows_parsed=len(out.records),
        rows_rejected=len(out.rejections),
        checks=[
            _row_conservation(doc, out),
            _rejection_budget(doc, out, policy),
            _control_total(doc, out),
            _roll_forward(doc, out),
            _type_domain(spec, out, window),
            _idempotence(spec, doc, out),
        ],
    )


__all__ = ["Check", "CheckStatus", "IntakeProof", "Record", "prove"]
