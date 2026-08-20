"""Entities for the synthetic settlement corpus, and the money type.

Everything here is Decimal at paise precision. No float — see CLAUDE.md rule 4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

PAISE = Decimal("0.01")


def money(value: str | int | Decimal) -> Decimal:
    """Quantize to paise. The only way money enters this package."""
    return Decimal(value).quantize(PAISE, rounding=ROUND_HALF_UP)


ZERO = money(0)


@dataclass(frozen=True)
class Gateway:
    name: str
    # Contract terms: what the merchant agreement says fees should be.
    contract_pct: Decimal
    contract_fixed: Decimal


@dataclass
class Order:
    order_id: str
    order_date: date
    gross: Decimal
    payment_id: str | None
    email: str


@dataclass
class Charge:
    charge_id: str
    payment_id: str
    charge_date: date
    gross: Decimal


@dataclass
class Refund:
    refund_id: str
    payment_id: str
    refund_date: date
    amount: Decimal  # negative


@dataclass
class Fee:
    fee_id: str
    charge_id: str
    amount: Decimal  # negative
    # Fee as the contract says it should have been. Differs from `amount`
    # only where an E02 fee variance was planted.
    contract_amount: Decimal


@dataclass
class Payout:
    payout_id: str
    gateway: str
    settled_on: date
    charges: list[Charge] = field(default_factory=list)
    refunds: list[Refund] = field(default_factory=list)
    fees: list[Fee] = field(default_factory=list)

    def actual_net(self) -> Decimal:
        """What the gateway actually paid out — drives the bank credit."""
        return money(
            sum((c.gross for c in self.charges), ZERO)
            + sum((r.amount for r in self.refunds), ZERO)
            + sum((f.amount for f in self.fees), ZERO)
        )

    def contract_net(self) -> Decimal:
        """What the merchant agreement says the payout should have been.

        The ledger books against this. Where it differs from actual_net, real
        money did not arrive and the difference is unreconciled.
        """
        return money(
            sum((c.gross for c in self.charges), ZERO)
            + sum((r.amount for r in self.refunds), ZERO)
            + sum((f.contract_amount for f in self.fees), ZERO)
        )


@dataclass
class BankLine:
    line_id: str
    posted_on: date
    amount: Decimal  # signed: credit positive, debit negative
    narration: str
    running_balance: Decimal = ZERO


@dataclass
class PlantedException:
    """A defect the generator deliberately introduced.

    `unreconciled` is the rupee amount a perfect reconciler cannot tie because
    of this defect. It is cross-checked against an independent recomputation in
    bench/generator/__init__.py — see check_batch().

    `leg` says which reconciliation the defect breaks, because they do not sum
    together. "bank" defects move the settlement-vs-bank residual and therefore
    the balance-assertion gap; "orders" defects are linkage failures between the
    order register and settlement, and leave the bank balance untouched.
    Conflating the two would make the invariant unfalsifiable.
    """

    code: str
    unreconciled: Decimal
    subject: str  # payout_id, bank line_id, or charge_id
    note: str
    leg: str = "bank"  # "bank" | "orders"
    # E09 only: the competing subsets. Present so a grader can confirm the
    # ambiguity is real rather than taking the generator's word for it.
    ambiguous_subsets: list[list[str]] | None = None


@dataclass
class Batch:
    name: str
    seed: int
    period_start: date
    period_end: date
    opening_balance: Decimal
    orders: list[Order] = field(default_factory=list)
    payouts: list[Payout] = field(default_factory=list)
    bank: list[BankLine] = field(default_factory=list)
    planted: list[PlantedException] = field(default_factory=list)
    # payout_id -> bank line_id. Absent where the payout has no bank line
    # in this period (E01 timing).
    payout_to_bank: dict[str, str] = field(default_factory=dict)
    # payout_id -> amount to subtract from actual_net() when writing the bank
    # credit. Used where the settlement export is wrong and the bank is right
    # (E06 duplicate) or where only part of a payout banked (E09).
    credit_adjust: dict[str, Decimal] = field(default_factory=dict)
    # Payouts whose settlement rows are emitted without a payout_id, forcing
    # the matcher to infer the grouping.
    ungrouped: list[str] = field(default_factory=list)
    # Payouts whose bank narration carries a truncated reference. Recoverable
    # at T1 on amount + date + counterparty, so not an exception — but the
    # tolerant tier has nothing to exercise it unless these exist.
    truncated_refs: list[str] = field(default_factory=list)
