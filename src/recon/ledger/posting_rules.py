"""Proof and exception to journal entry.

Until this phase nothing in the close path posted. The ledger existed and only
tests used it, so "writes double-entry journal entries for everything it can
prove" was a claim with no code behind it, and CLAUDE.md invariant 1 —
unreconciled value equals the balance-assertion gap — could not even be
evaluated.

Three rules, and the third is the one that matters.

**A proven payout clears.** The gateway held the money; now the bank has it.
`Dr Bank / Cr Clearing` at the anchor's amount. The fee and revenue split
belongs to the capture side, which this loop does not reconcile — inventing it
here would put numbers in the books that no source in this close supports.

**A bank credit nobody can attribute parks in suspense.** The money *is* in the
account and the balance has to say so; what it is for is unknown. `Dr Bank / Cr
Liabilities:UnappliedCash`. Guessing it into revenue is precisely the error the
suspense account exists to prevent, and the E08 case is planted to prove it.

**Settlement the bank never received is not posted at all.** A group the gateway
says it sent and no anchor claims is a receivable, not cash. Posting it would
put money in the books that is not in the account — a plug wearing a
reconciliation's clothes. It stays an exception with a stated reason, and this
module records why it declined rather than passing over it silently.
"""

from __future__ import annotations

from decimal import Decimal

from ..contracts import ReconException, Record
from .accounts import AccountRole
from .beancount_io import JournalEntry, Posting

ZERO = Decimal("0.00")


def _entry(entry_id, on, narration, debit_role, credit_role, value, **meta) -> JournalEntry:
    """Debits positive, credits negative — the beancount convention, so nothing
    flips signs at render time."""
    return JournalEntry(
        entry_id=entry_id,
        entry_date=on,
        narration=narration,
        postings=[
            Posting(role=debit_role, amount=value),
            Posting(role=credit_role, amount=-value),
        ],
        proof_id=meta.pop("proof_id", None),
        meta={k: v for k, v in meta.items() if v is not None},
    )


def entries_for(
    *,
    matches: list[object],
    exceptions: list[ReconException],
    records: dict[str, Record],
    anchor_side: str,
) -> tuple[list[JournalEntry], list[str]]:
    """Returns the entries and the reasons anything was *not* posted.

    The second half is not decoration. A posting rule that quietly skips what it
    cannot handle is indistinguishable from one that has no case for it, and the
    difference is the whole product.
    """
    entries: list[JournalEntry] = []
    declined: list[str] = []

    for match in matches:
        anchor = records[match.anchor_id]
        entries.append(
            _entry(
                f"JE-{match.match_id}",
                anchor.posted_on,
                f"settlement {match.group_ref} cleared to bank",
                AccountRole.BANK,
                AccountRole.CLEARING,
                anchor.amount,
                proof_id=match.proof.proof_id,
                match_id=match.match_id,
                tier=match.tier.value,
                amount=f"{anchor.amount:.2f}",
            )
        )

    for index, exc in enumerate(exceptions, start=1):
        on_anchor = [r for r in exc.record_ids if records.get(r) and records[r].side == anchor_side]
        if not on_anchor:
            declined.append(
                f"{exc.exception_id} ({exc.code.value}, ₹{exc.amount}): no bank line — the money "
                f"never reached the account, so this is a receivable and posting it would put "
                f"cash in the books that is not in the bank"
            )
            continue
        anchor = records[on_anchor[0]]
        entries.append(
            _entry(
                f"JE-EXC-{index:03d}",
                anchor.posted_on,
                f"{exc.code.value} unattributed receipt held in suspense",
                AccountRole.BANK,
                AccountRole.SUSPENSE,
                abs(anchor.amount),
                exception_id=exc.exception_id,
                code=exc.code.value,
                amount=f"{abs(anchor.amount):.2f}",
            )
        )

    return entries, declined
