"""Rule — a promoted, regression-tested matching policy.

Declarative for the same reason adapters are (ADR-001): a rule is authored by a
model and then executed against financial data, so it must be data a fixed
interpreter reads, never code. Predicate and action vocabularies are closed
enums — an unknown operator is a validation error, not an eval.

A rule cannot be promoted while it breaks a historical match (CLAUDE.md
invariant 5). That gate lives in the induction path (P7); this contract makes it
unrepresentable to promote without a regression report attached.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import CONTRACT_VERSION, Money


class RuleStatus(StrEnum):
    DRAFT = "draft"
    PROMOTED = "promoted"
    REVOKED = "revoked"


class Operator(StrEnum):
    EQ = "eq"
    NEQ = "neq"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    MATCHES = "matches"
    """Regex against a normalized key. Anchored and length-capped by the
    interpreter — an unbounded pattern from a model is a denial-of-service."""


class ActionKind(StrEnum):
    SET_TOLERANCE = "set_tolerance"
    """Widen the tolerance budget for matches this rule covers."""
    BOOK_TO = "book_to"
    """Post the residual to a named account."""
    NORMALIZE_KEY = "normalize_key"
    """Rewrite a match key (alias resolution, reference repair)."""
    SUPPRESS = "suppress"
    """Drop a record with a stated reason. Never silent."""
    RAISE_ADVISORY = "raise_advisory"
    """Surface a non-blocking note, e.g. a commercial-tier review."""


class Predicate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str
    """A record field or key name — resolved by the interpreter, not by eval."""
    op: Operator
    value: str | list[str]

    @model_validator(mode="after")
    def _value_shape_matches_operator(self) -> Predicate:
        if self.op is Operator.IN and not isinstance(self.value, list):
            raise ValueError("op 'in' requires a list value")
        if self.op is not Operator.IN and isinstance(self.value, list):
            raise ValueError(f"op {self.op!r} requires a scalar value")
        if self.op is Operator.MATCHES and isinstance(self.value, str) and len(self.value) > 200:
            raise ValueError("regex longer than 200 chars — refused as a DoS risk")
        return self


class RuleAction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ActionKind
    target: str | None = None
    """Account, key name, or advisory channel, depending on `kind`."""
    amount: Money | None = None
    pct: str | None = None
    """Decimal-as-string, e.g. "0.005". Not a float — see CLAUDE.md rule 4."""
    reason: str | None = None

    @model_validator(mode="after")
    def _suppression_states_a_reason(self) -> RuleAction:
        if self.kind is ActionKind.SUPPRESS and not self.reason:
            raise ValueError("a suppress action must state a reason — never silent")
        if self.kind in {ActionKind.BOOK_TO, ActionKind.NORMALIZE_KEY} and not self.target:
            raise ValueError(f"action {self.kind!r} requires a target")
        return self


class RegressionReport(BaseModel):
    """The evidence a rule is safe to promote."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ran_at: datetime
    matches_checked: int
    matches_broken: int
    exceptions_would_clear: int
    batches: list[str] = Field(default_factory=list)

    @property
    def promotable(self) -> bool:
        return self.matches_broken == 0 and self.matches_checked > 0


class PromotionEvent(BaseModel):
    """What a promotion *is*, from P8 onward.

    Before P8 a rule reached `PROMOTED` by carrying a `RegressionReport` — a
    model anyone could construct, asserting whatever it liked. That is audit
    finding `F1` in another costume: an artifact carrying its own evidence. This
    event is produced only by `recon.engine.promotion.promote`, which re-runs the
    regression against real history under a named policy, and it carries a hash a
    third party can recompute.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    promoted_by: str
    promoted_at: datetime
    policy_ref: str
    evidence_hash: str
    """sha256 over the history and the rule. Recomputing it is how a promotion is
    re-verified — see `verify_promotion`."""

    matches_checked: int
    matches_broken: int
    matches_added: int
    exceptions_cleared: int
    sample_added: list[str] = Field(default_factory=list)
    """Ids of matches the rule would create, shown to the approver. An approval
    granted without seeing what it adds is a signature on an empty page."""

    @model_validator(mode="after")
    def _named_and_evidenced(self) -> PromotionEvent:
        if not self.promoted_by.strip():
            raise ValueError("a promotion must name who granted it")
        if not self.evidence_hash.strip():
            raise ValueError("a promotion without evidence is an assertion")
        if self.matches_added and not self.sample_added:
            raise ValueError("a rule that adds matches must show a sample of them")
        return self


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str = CONTRACT_VERSION
    rule_id: str
    version: int = 1
    status: RuleStatus = RuleStatus.DRAFT

    profile: str
    """Rules are profile-scoped — a settlement rule must not fire on GST."""

    when: list[Predicate]
    then: list[RuleAction]

    induced_from: str | None = None
    """The exception_id whose resolution produced this. The rule's justification
    travels with it, so a later reader can see why it exists."""

    regression: RegressionReport | None = None
    """A *claim* the proposer may attach. Carries no authority — P8 re-runs the
    regression rather than reading this."""

    promotion: PromotionEvent | None = None
    """The only thing that authorises `PROMOTED`."""

    revoked_at: datetime | None = None

    @model_validator(mode="after")
    def _promotion_requires_a_clean_regression(self) -> Rule:
        if not self.when:
            raise ValueError("a rule with no conditions matches everything")
        if not self.then:
            raise ValueError("a rule with no actions does nothing")
        if self.status is RuleStatus.PROMOTED and self.promotion is None:
            # Tightened at contract 2.0.0. A hand-built RegressionReport used to
            # be enough, and a report is something anyone can construct.
            raise ValueError(
                "cannot promote without a PromotionEvent — a regression report "
                "attached by the proposer is a claim, not authority. Use "
                "recon.engine.promotion.promote()."
            )
        return self

    @property
    def ref(self) -> str:
        return f"{self.rule_id}@v{self.version}"

    @property
    def promoted_by(self) -> str | None:
        return self.promotion.promoted_by if self.promotion else None
