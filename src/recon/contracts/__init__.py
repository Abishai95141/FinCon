"""Public contracts. Semver'd from P1 — see docs/decisions/ADR-002.

Changing a field here is a breaking change with a version bump, not an edit.
External callers re-derive proofs against these shapes; a shape that drifts
makes an independently-written verifier stop working, which is the whole
property we are selling.

Bump rules:
  patch — docs, validators that reject strictly less
  minor — a new optional field, a new enum member that old readers may ignore
  major — anything else: removing, renaming, retyping, tightening a validator,
          or adding a required field
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import BeforeValidator, PlainSerializer

CONTRACT_VERSION = "1.2.0"
# 1.2.0 — P5 loosened ReconException.alternatives from disjoint to distinct.
#         Disjointness was a modelling error: {A,B} and {B,C} both summing to
#         the target is genuine ambiguity, and rejecting it would have forced
#         the engine to hide real ambiguity to satisfy a validator. Loosening,
#         so minor: everything valid under 1.1.0 is still valid.
# 1.1.0 — P2 added FieldMap.sign (optional): a fixed dr/cr sign for DECIMAL,
#         needed by exports that split debits and credits into two columns.
#         New optional field, so minor per the bump rules above.
# 1.0.0 — P1 initial surface.

PAISE = Decimal("0.01")


def _to_minor_units(value: object) -> Decimal:
    """Quantize to two places. Accepts str/int/Decimal; rejects float outright.

    float is banned in the engine and ledger (CLAUDE.md rule 4). Accepting it
    here would launder it past that rule at the contract boundary.
    """
    if isinstance(value, float):
        # ValueError, not TypeError: pydantic wraps ValueError into
        # ValidationError, so every contract violation surfaces as one exception
        # type. A TypeError would escape raw and force callers to catch two.
        raise ValueError("float is not a valid money value — pass str or Decimal")
    return Decimal(str(value)).quantize(PAISE, rounding=ROUND_HALF_UP)


Money = Annotated[
    Decimal,
    BeforeValidator(_to_minor_units),
    PlainSerializer(lambda v: f"{v:.2f}", return_type=str, when_used="json"),
]

from .adapter import (  # noqa: E402
    AdapterSpec,
    CanonicalField,
    FieldMap,
    ParseVerb,
    ReaderKind,
    ReaderSpec,
    RejectRule,
)
from .exception import ExceptionCode, ReconException, Resolution  # noqa: E402
from .proof import MatchTier, Proof, ProofLeg, ProofTier  # noqa: E402
from .record import Record  # noqa: E402
from .rule import Predicate, RegressionReport, Rule, RuleAction, RuleStatus  # noqa: E402

__all__ = [
    "CONTRACT_VERSION",
    "AdapterSpec",
    "CanonicalField",
    "ExceptionCode",
    "FieldMap",
    "MatchTier",
    "Money",
    "ParseVerb",
    "Predicate",
    "Proof",
    "ProofLeg",
    "ProofTier",
    "ReaderKind",
    "ReaderSpec",
    "ReconException",
    "Record",
    "RegressionReport",
    "RejectRule",
    "Resolution",
    "Rule",
    "RuleAction",
    "RuleStatus",
]
