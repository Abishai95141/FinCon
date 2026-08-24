"""Policy — the answer to "was this allowed?".

The control-plane audit found five bypasses with one root cause: the system
checked artifacts against themselves and took its policy from whoever called it.
A proof carried its own tolerance, the verifier took its signs from the caller,
an adapter declared its own rejections. Every check was rigorous about internal
consistency and silent about permission.

This object is the permission, and it is deliberately **not** something a
proposer can supply. An `AdapterSpec` or a `MatchProfile` is a proposal — an
agent may author either. A `Policy` is authority: versioned, frozen, and
carrying the name of whoever approved it. Nothing in the system reads a
threshold out of the artifact it is checking any more; it reads it here.

Kept on disk under `data/policy/` for the same reason adapter specs are: a
change should show up in a diff and go past a human.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer, field_validator, model_validator
from pydantic.functional_validators import BeforeValidator

from . import CONTRACT_VERSION, Money

_RATIO = Decimal("0.0001")


def _to_ratio(value: object) -> Decimal:
    if isinstance(value, float):
        raise ValueError("float is not a valid ratio — pass str or Decimal")
    return Decimal(str(value)).quantize(_RATIO, rounding=ROUND_HALF_UP)


Ratio = Annotated[
    Decimal,
    BeforeValidator(_to_ratio),
    PlainSerializer(lambda v: f"{v:.4f}", return_type=str, when_used="json"),
]


class PolicyViolation(RuntimeError):
    """A proposal asked for something policy does not permit. Raised rather than
    returned: a run that proceeds past a policy violation has no meaning, and a
    caller that could ignore a boolean would."""


class Policy(BaseModel):
    """Frozen on purpose — a caller that could edit policy mid-run would be
    supplying its own permission, which is the whole failure this closes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: str = CONTRACT_VERSION
    policy_id: str
    version: int = 1
    profile: str
    """Which reconciliation loop this governs. A settlement policy must not
    silently authorise a GST run."""

    side_signs: dict[str, int]
    """The arithmetic convention, owned here rather than by the profile. Must be
    ±1: a zero sign makes every residual zero and every match verify, which is
    audit finding `F2`."""

    tolerance_ceiling: Money
    """The most any single match may absorb, whatever the proof claims for
    itself. Audit finding `F1`."""

    rejection_budget_pct: Ratio
    """The largest share of a source's rows a spec may discard. A reason makes a
    rejection legible; this makes it bounded. Audit finding `F4`."""

    rounding_threshold: Money
    """Residue at or below this posts to the rounding account. Above it, the
    close is blocked rather than plugged."""

    max_added_matches: int = 25
    """How many matches one promoted rule may add. A rule exists to clear
    exceptions, so some additions are the point — but unbounded additions are
    how a rule quietly rewrites a close. Above this the rule escalates instead
    of promoting."""

    max_selectivity_pct: Ratio = "0.25"
    """The share of rows a rule may fire on before it is over-broad.

    `max_added_matches` caps what a rule *adds*. Nothing capped what it *touches*
    — so an advisory rule firing on two thirds of the batch broke no match, added
    no match, and promoted cleanly while flooding the worklist. Found at P12 when
    an induced rule selected 344 of 517 rows and the gate had nothing to say.
    A rule that fires on everything is not a rule; it is a denial of attention."""

    approved_by: str
    approved_at: datetime
    notes: str | None = None

    @field_validator("side_signs")
    @classmethod
    def _signs_are_unit(cls, value: dict[str, int]) -> dict[str, int]:
        if not value:
            raise ValueError("a policy with no sides governs nothing")
        bad = {side: sign for side, sign in value.items() if sign not in (1, -1)}
        if bad:
            raise ValueError(
                f"side signs must be +1 or -1; a zero makes every residual zero "
                f"and every match verify (audit F2). Got {bad}"
            )
        return value

    @field_validator("rejection_budget_pct")
    @classmethod
    def _budget_is_a_share(cls, value: Decimal) -> Decimal:
        if not Decimal("0") <= value <= Decimal("1"):
            raise ValueError(f"rejection budget must be a share between 0 and 1, got {value}")
        return value

    @model_validator(mode="after")
    def _limits_are_not_negative(self) -> Policy:
        if self.tolerance_ceiling < 0 or self.rounding_threshold < 0:
            raise ValueError("a negative limit is not a limit")
        if self.rounding_threshold > self.tolerance_ceiling:
            raise ValueError(
                "rounding_threshold above tolerance_ceiling would let the "
                "rounding account absorb more than a match may"
            )
        if not (Decimal("0") < Decimal(self.max_selectivity_pct) <= Decimal("1")):
            raise ValueError("max_selectivity_pct must be a share in (0, 1]")
        if self.max_added_matches < 0:
            raise ValueError("a negative match delta cap is not a cap")
        if not self.approved_by.strip():
            raise ValueError("unapproved policy is not policy — name the approver")
        return self

    @property
    def ref(self) -> str:
        return f"{self.policy_id}@v{self.version}"

    def sign_for(self, side: str) -> int:
        """Raises rather than defaulting. A missing side is an unpoliced side,
        and quietly assuming +1 there would be the F2 bypass by another route."""
        if side not in self.side_signs:
            raise PolicyViolation(f"no sign convention in {self.ref} for side {side!r}")
        return self.side_signs[side]

    def permits_selectivity(self, fires: int, sampled: int) -> bool:
        """Whether a rule touching `fires` of `sampled` rows is narrow enough."""
        if not sampled:
            return False
        return Decimal(fires) / Decimal(sampled) <= Decimal(self.max_selectivity_pct)

    def permits_tolerance(self, claimed: Decimal) -> bool:
        return claimed <= self.tolerance_ceiling

    def check_profile(self, profile: object) -> None:
        """Validate a proposal against this authority before it runs.

        Caught here rather than at verification: a profile whose signs disagree
        with policy would produce matches the verifier then refutes, which is the
        right outcome reached the expensive way.
        """
        name = getattr(profile, "name", "<profile>")
        if getattr(profile, "name", None) != self.profile:
            raise PolicyViolation(
                f"policy {self.ref} governs profile {self.profile!r}, not {name!r}"
            )
        signs = getattr(profile, "side_signs", {}) or {}
        mismatched = {
            side: sign
            for side, sign in signs.items()
            if side in self.side_signs and sign != self.side_signs[side]
        }
        if mismatched:
            raise PolicyViolation(
                f"profile {name!r} proposes side sign(s) {mismatched} that "
                f"disagree with policy {self.ref} ({self.side_signs})"
            )
        unpoliced = sorted(set(signs) - set(self.side_signs))
        if unpoliced:
            raise PolicyViolation(
                f"profile {name!r} names side(s) {unpoliced} that policy {self.ref} does not cover"
            )
        tolerance = getattr(getattr(profile, "tolerance", None), "absolute", None)
        if tolerance is not None and not self.permits_tolerance(tolerance):
            raise PolicyViolation(
                f"profile {name!r} asks for tolerance {tolerance}, above the "
                f"ceiling {self.tolerance_ceiling} in {self.ref}"
            )
