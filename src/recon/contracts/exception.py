"""ReconException — one unresolved item, classified into a closed taxonomy.

Named ReconException rather than Exception to avoid shadowing the builtin: a
model named `Exception` in a package that also raises would be a trap for every
future reader.

The code set is closed on purpose. A model that can invent a category can drift;
an enum forces a genuinely new class of failure through a contract version bump
where someone has to look at it.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import CONTRACT_VERSION, Money


class ExceptionCode(StrEnum):
    E01_TIMING = "E01"
    E02_FEE_VARIANCE = "E02"
    E03_FX_ROUNDING = "E03"
    E04_PARTIAL_PAYMENT = "E04"
    E05_OVERPAYMENT = "E05"
    E06_DUPLICATE = "E06"
    E07_CHARGEBACK_POST_PERIOD = "E07"
    E08_MISSING_REMITTANCE = "E08"
    E09_NETTING_AMBIGUITY = "E09"
    E10_REFERENCE_CORRUPTION = "E10"
    E11_COUNTERPARTY_ALIAS = "E11"
    E12_WRONG_ENTITY = "E12"
    E13_SOLVER_TIMEOUT = "E13"


#: Codes where escalating is the correct outcome, not a failure to match.
#: E09 has no unique answer; E13 is a compute bound, and a capacity limit must
#: never be reported as a data finding.
HONESTY_CODES = frozenset({ExceptionCode.E09_NETTING_AMBIGUITY, ExceptionCode.E13_SOLVER_TIMEOUT})


class Resolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolved_by: str
    resolved_at: datetime
    action: str
    """What was done, in the resolver's words. Feeds rule induction (P7)."""
    posting_hint: str | None = None
    """Account the difference was booked to, where one was chosen."""


class ReconException(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str = CONTRACT_VERSION
    exception_id: str
    code: ExceptionCode
    as_of: date

    amount: Money
    """Cash impact. Drives ranking and must tie to the balance-assertion gap
    for bank-leg exceptions (CLAUDE.md invariant 1)."""

    leg: str = "bank"
    """"bank" moves the balance-assertion gap; "orders" is a linkage failure
    that leaves the bank balance untouched. Summing the two would make the
    invariant unfalsifiable."""

    record_ids: list[str] = Field(default_factory=list)
    """The records this is about."""

    hypothesis: str | None = None
    """Model-authored, one sentence. Never authoritative — a human reads it."""

    evidence: list[str] = Field(default_factory=list)
    """Citations a human can follow: record lineage, contract clause, prior rule."""

    rank: int | None = None
    """1 = work this first. Assigned by triage on cash impact x age."""

    alternatives: list[list[str]] | None = None
    """E09 only: the competing record subsets. Present so a reviewer can confirm
    the ambiguity rather than take the classifier's word for it."""

    blocks_close: bool = False
    resolution: Resolution | None = None

    @model_validator(mode="after")
    def _ambiguity_shows_its_alternatives(self) -> ReconException:
        if self.code is ExceptionCode.E09_NETTING_AMBIGUITY:
            if not self.alternatives or len(self.alternatives) < 2:
                raise ValueError("E09 must carry at least two competing subsets")
            flat = [r for subset in self.alternatives for r in subset]
            if len(flat) != len(set(flat)):
                raise ValueError("E09 alternatives must be disjoint")
        if self.leg not in {"bank", "orders"}:
            raise ValueError(f"leg must be 'bank' or 'orders', got {self.leg!r}")
        return self

    @property
    def is_honesty_code(self) -> bool:
        """True where escalating is correct behaviour rather than a shortfall."""
        return self.code in HONESTY_CODES
