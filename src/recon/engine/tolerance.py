"""Per-match tolerance budget.

One budget per match, consumed across tiers and recorded in the proof. Without a
single budget, several small allowances compose into a large one: a fee
allowance plus an FX allowance plus a rounding allowance can silently admit a
residual none of them would have admitted alone (build plan, problem P14).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class TolerancePolicy:
    """Profile-level limits. Domain-specific values live in a profile; the
    engine only knows there is a ceiling and a date window."""

    absolute: Decimal = Decimal("0.50")
    """Total residual a single match may absorb, in the profile's currency."""

    date_window_days: int = 3
    """How far a settlement date and a bank posting date may sit apart. Real
    payouts bank a day or two after they settle."""

    def within_window(self, left: date, right: date) -> bool:
        return abs((left - right).days) <= self.date_window_days

    def window_bounds(self, anchor: date) -> tuple[date, date]:
        delta = timedelta(days=self.date_window_days)
        return anchor - delta, anchor + delta


@dataclass
class ToleranceBudget:
    """Mutable, one per candidate match. `used` ends up in the proof so a
    reviewer can see how much slack a match actually needed."""

    allowed: Decimal
    used: Decimal = field(default=ZERO)

    @property
    def remaining(self) -> Decimal:
        return self.allowed - self.used

    def can_absorb(self, residual: Decimal) -> bool:
        return abs(residual) <= self.remaining

    def consume(self, residual: Decimal) -> bool:
        """Spend against the budget. Returns False and spends nothing when the
        residual would exceed what is left — a partial consume would leave the
        budget in a state that no longer describes the match."""
        if not self.can_absorb(residual):
            return False
        self.used += abs(residual)
        return True
