"""What happens to an exception once a person has decided.

For thirteen phases this product could name a break, price it, rank it, route it
and record who agreed with the naming — and the money stayed exactly where it
was. `docs/10-THE-USER-FLOW.md` §5.1 measured it: accepting a classification left
the journal at 23 entries and 4,994 bytes and changed nothing about what blocked
the close. An attestation with no entry behind it tells an auditor that somebody
looked. It does not tell them what was done.

There are four things a controller does with a reconciling item, and every one of
them produces a journal entry:

| | | |
|---|---|---|
| **book** | the difference is real and explained | it becomes an expense |
| **carry forward** | timing — the money is real and late | it becomes cash in transit |
| **chase** | somebody owes us | it becomes a receivable |
| **write off** | small, or aged out | it leaves the books |

**Every one is `P2 ATTESTED`.** None is `P1 RULE`, and the reason is not
squeamishness: raw records cannot prove a row is spurious — they *contain* it.
A rule may propose a disposition; only a person may make one.

**The two ceilings are policy, not preference.** A write-off has a per-item
ceiling and the close has a total budget, and both arrive from the signed bundle
alongside the exception rather than from whoever is clicking. The per-item
ceiling alone is trivially defeated — ninety items at ₹499 pass it one at a time
— which is audit finding `F4` in its general form: a reason makes a write-off
legible and only a budget makes it bounded.

**Refusals raise.** A disposition this module will not make is an exception this
module leaves open, loudly. Returning a "disposition" with an `applied=False`
flag would be the same shape as `raise_advisory`, which sat in the enum, the tool
schema and `MODELLED_ACTIONS` while being implemented nowhere.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from .contracts import Money, Policy, ReconException
from .ledger.accounts import AccountRole, ChartOfAccounts
from .ledger.beancount_io import JournalEntry, Posting

ZERO = Decimal("0.00")


class DispositionError(RuntimeError):
    """A disposition this module refuses to make, with the reason intact.

    Raised rather than returned. The caller may be a screen, and a screen that
    receives a refusal as a value renders it as a state; a screen that receives
    it as an exception has to show it to somebody.
    """


class Disposition(StrEnum):
    """The four endings. Adding a fifth means adding its account and its rule —
    never `frozenset(Disposition)`, which certifies the next member by
    construction and is how `raise_advisory` scored better than any real rule by
    doing nothing on every dimension."""

    BOOK = "book"
    CARRY_FORWARD = "carry_forward"
    CHASE = "chase"
    WRITE_OFF = "write_off"


#: Where each disposition debits. Declared here and resolved through the loop's
#: chart, so no caller ever names an account: a free-text account field is the
#: caller supplying its own chart, which is finding `F2` wearing an apron.
DESTINATION: dict[Disposition, AccountRole] = {
    Disposition.CARRY_FORWARD: AccountRole.IN_TRANSIT,
    Disposition.CHASE: AccountRole.RECEIVABLE,
    Disposition.WRITE_OFF: AccountRole.WRITE_OFF,
    # BOOK has no fixed destination — it books where the *code* says, which is
    # why it is absent here and handled explicitly below. A default would let an
    # unratified code reach an expense account by omission.
}

#: What a disposition draws down. The exception's value is sitting in the loop's
#: clearing account — the gateway said it had the money — and every disposition
#: moves it somewhere that is true. Passed by the caller from the loop's own
#: profile rather than hardcoded, because invariant 7 says the engine is
#: domain-agnostic and a second loop will not have a gateway.
DEFAULT_SOURCE = AccountRole.CLEARING


class Decision:
    """One disposition, checked. Construct it and it is admissible, or it raised.

    Not a dataclass with an `ok` field. A half-valid decision that a caller may
    ignore the invalid half of is the shape this codebase keeps finding at the
    bottom of its audits.
    """

    __slots__ = ("budget_left", "ceiling", "disposition", "due_on", "entry", "exception", "owner")

    def __init__(
        self,
        *,
        entry: JournalEntry,
        exception: ReconException,
        disposition: Disposition,
        ceiling: Money | None,
        budget_left: Money | None,
        due_on: date | None,
        owner: str,
    ) -> None:
        self.entry = entry
        self.exception = exception
        self.disposition = disposition
        self.ceiling = ceiling
        self.budget_left = budget_left
        self.due_on = due_on
        self.owner = owner


def budget_for(tail: list[ReconException], policy: Policy) -> Money:
    """The total value this close may write off, all items together.

    Measured against the tail as the close left it — a fixed denominator, so a
    write-off cannot enlarge the budget for the next one. The same mistake in
    `max_reference_selectivity` let a rule go from refused to allowed by padding
    the batch, and a metamorphic relation caught it; this one is fixed by
    construction instead.
    """
    total = sum((abs(exc.amount) for exc in tail), start=ZERO)
    return (total * policy.write_off_budget_ratio).quantize(Decimal("0.01"))


def decide(
    *,
    exception: ReconException,
    disposition: Disposition,
    chart: ChartOfAccounts,
    policy: Policy,
    decided_by: str,
    rationale: str,
    tail: list[ReconException],
    already_written_off: Money = ZERO,
    books_to: AccountRole | None = None,
    due_on: date | None = None,
    owner: str = "",
    source: AccountRole = DEFAULT_SOURCE,
) -> Decision:
    """Check a proposed disposition and build its entry, or refuse and say why.

    `tail` and `already_written_off` are how the budget is evaluated. Both are
    facts about the close rather than about this item, and neither is supplied by
    the person deciding — the caller reads them off the record.
    """
    value = abs(exception.amount)

    if not decided_by.strip():
        raise DispositionError(
            "a disposition needs a named human — P2 ATTESTED means somebody is accountable"
        )
    if not rationale.strip():
        raise DispositionError(
            f"{exception.exception_id}: a disposition with no rationale is a number in the "
            f"books that nobody can defend to an auditor"
        )
    if value <= ZERO:
        raise DispositionError(
            f"{exception.exception_id} carries no value to dispose of; a zero-value entry "
            f"would balance and mean nothing"
        )

    ceiling: Money | None = None
    budget_left: Money | None = None

    if disposition is Disposition.WRITE_OFF:
        ceiling = policy.write_off_ceiling
        if value > ceiling:
            raise DispositionError(
                f"{exception.exception_id} is ₹{value} and the write-off ceiling under "
                f"{policy.ref} is ₹{ceiling}. This item escalates; there is no override, "
                f"because a ceiling with an override beside it is advice."
            )
        budget = budget_for(tail, policy)
        remaining = budget - already_written_off
        if value > remaining:
            raise DispositionError(
                f"{exception.exception_id} is ₹{value} and this close has ₹{remaining} of its "
                f"₹{budget} write-off budget left ({policy.write_off_budget_ratio:%} of a tail "
                f"worth ₹{sum((abs(e.amount) for e in tail), start=ZERO)}). Writing off is "
                f"bounded in total as well as per item — ninety items under the ceiling are "
                f"still ₹44,910 leaving the close."
            )
        budget_left = remaining - value

    if disposition is Disposition.CHASE:
        if not owner.strip():
            raise DispositionError(
                f"{exception.exception_id}: a receivable with no owner is a note. Name who "
                f"is chasing it."
            )
        if due_on is None:
            raise DispositionError(
                f"{exception.exception_id}: a receivable with no date is never late, and an "
                f"item that is never late is never chased."
            )

    if disposition is Disposition.BOOK:
        if books_to is None:
            raise DispositionError(
                f"{exception.exception_id} carries {exception.code}, which names no account to "
                f"book to. A code books only once it is promoted with a written definition — "
                f"naming grants nothing."
            )
        debit = books_to
    else:
        debit = DESTINATION[disposition]

    if debit == source:
        raise DispositionError(
            f"{exception.exception_id}: {disposition.value} would debit and credit "
            f"{chart[source]}, which moves nothing and balances anyway"
        )

    verb = disposition.value.replace("_", " ")
    on = exception.as_of.date() if hasattr(exception.as_of, "date") else exception.as_of
    entry = JournalEntry(
        entry_id=f"JE-D-{exception.exception_id}",
        entry_date=on,
        narration=f"{verb} {exception.exception_id} ({exception.code})",
        postings=[Posting(role=debit, amount=value), Posting(role=source, amount=-value)],
        meta={
            "disposition": disposition.value,
            "exception_id": exception.exception_id,
            "code": exception.code,
            "decided_by": decided_by,
            "tier": "P2",
            "amount": f"{value:.2f}",
        },
    )

    return Decision(
        entry=entry,
        exception=exception,
        disposition=disposition,
        ceiling=ceiling,
        budget_left=budget_left,
        due_on=due_on,
        owner=owner,
    )
