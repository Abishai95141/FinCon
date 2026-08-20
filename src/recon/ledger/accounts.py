"""Chart of accounts, addressed by role rather than by name.

The kernel posts to *roles* — "the bank account", "the gateway clearing
account" — and a chart maps roles to real account names. That keeps
invariant 7 intact: naming `Assets:Bank:HDFC` inside the engine would bake one
company's chart into domain-agnostic code.

SETTLEMENT_CHART below is default profile data, not kernel data. It moves into
`src/recon/profiles/` when profiles become first-class at P10.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator

# Beancount account names: a capitalised root from a fixed set, then
# colon-separated capitalised components.
_ACCOUNT_RE = re.compile(r"^(Assets|Liabilities|Equity|Income|Expenses)(:[A-Z][A-Za-z0-9-]*)+$")


class AccountRole(StrEnum):
    BANK = "bank"
    CLEARING = "clearing"
    """Money the gateway holds between capture and payout."""
    INCOME = "income"
    FEES = "fees"
    FEE_VARIANCE = "fee_variance"
    """Where an E02 delta lands — kept separate from ordinary fees so a
    variance never disappears into the fee line."""
    REFUNDS = "refunds"
    DISPUTES = "disputes"
    """Chargeback reserve. E07 books here rather than reopening a period."""
    ROUNDING = "rounding"
    """Sub-paisa residue, bounded by policy. Above the bound it is E03, not a
    silent plug — see build plan problem P16."""
    SUSPENSE = "suspense"
    """Unapplied cash: a credit with nothing behind it (E08) parks here rather
    than being guessed into revenue."""


class ChartOfAccounts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    currency: str = "INR"
    accounts: dict[AccountRole, str]

    @field_validator("accounts")
    @classmethod
    def _names_are_valid_and_complete(cls, v: dict[AccountRole, str]) -> dict[AccountRole, str]:
        missing = set(AccountRole) - set(v)
        if missing:
            raise ValueError(f"chart is missing roles: {sorted(r.value for r in missing)}")
        for role, name in v.items():
            if not _ACCOUNT_RE.match(name):
                raise ValueError(f"role {role.value!r}: {name!r} is not a valid account name")
        return v

    def __getitem__(self, role: AccountRole) -> str:
        return self.accounts[role]

    def all_accounts(self) -> list[str]:
        return sorted(set(self.accounts.values()))


SETTLEMENT_CHART = ChartOfAccounts(
    currency="INR",
    accounts={
        AccountRole.BANK: "Assets:Bank:HDFC",
        AccountRole.CLEARING: "Assets:Clearing:Gateway",
        AccountRole.INCOME: "Income:Sales",
        AccountRole.FEES: "Expenses:GatewayFees",
        AccountRole.FEE_VARIANCE: "Expenses:GatewayFees:Variance",
        AccountRole.REFUNDS: "Income:Sales:Refunds",
        AccountRole.DISPUTES: "Expenses:Disputes:Reserve",
        AccountRole.ROUNDING: "Expenses:Rounding",
        AccountRole.SUSPENSE: "Liabilities:UnappliedCash",
    },
)
