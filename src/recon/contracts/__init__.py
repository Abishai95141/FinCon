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

CONTRACT_VERSION = "2.1.0"
# 2.1.0 — P9 added the decision-log surface: Event, EventKind, the per-kind
#         payload models, and PRODUCERS (which kind is written by what, and for
#         the three with no producer yet, the phase that will build them). All
#         new models, so minor — nothing existing changed shape. The log is a
#         public artifact: an external auditor reads it without our code, so it
#         is versioned like everything else here.
# 2.0.0 — P8 tightened the Rule promotion validator: PROMOTED now requires a
#         PromotionEvent produced by recon.engine.promotion.promote(), which
#         re-runs the regression against real history under a named policy. A
#         RegressionReport attached by the proposer is a claim and no longer
#         authorises anything. Tightening a validator is MAJOR by the rules
#         above, and `promoted_by`/`promoted_at` moved onto the event.
#         Also added Policy.max_added_matches (a rule's match-delta cap).
# 1.5.0 — P7 added the Policy contract: the answer to "was this allowed?".
#         Versioned, frozen, carrying an approver's name, and deliberately not
#         something a proposer can supply. verify() now takes it instead of a
#         side_signs mapping, closing audit findings F1 and F2 together. New
#         model plus a widened verify() signature; the old signature is gone,
#         but nothing outside this repo consumed it yet, so minor.
# 1.4.0 — P6 added two members, both so the system can say "I do not know" out
#         loud rather than guess:
#           ExceptionCode.E14_UNEXPLAINED — invariant 8 requires a disposition
#             for every input, and the engine often cannot say WHY an item did
#             not match. Force-fitting an existing code would put a guess where
#             there are only facts.
#           ParseVerb.UNMAPPABLE — a spec author (human or model) declares that
#             no verb expresses a column, instead of reaching for the nearest.
#         Both new enum members, so minor.
# 1.3.0 — P5 added ParseVerb.DECIMAL_MINOR: integer minor units. Found by
#         ingesting a source whose amounts were paise-as-integer; it parsed
#         cleanly and was 100x wrong, and no proof could contradict it because
#         that source carried no control total. New enum member, so minor.
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
from .event import (  # noqa: E402
    GENESIS,
    PAYLOADS,
    PRODUCERS,
    CloseBlockedPayload,
    CloseCompletedPayload,
    CloseStartedPayload,
    Event,
    EventKind,
    ExceptionRaisedPayload,
    IntakeUnverifiedPayload,
    MatchProvenPayload,
    MatchRejectedPayload,
    OutOfScopePayload,
    PostingWrittenPayload,
    ProposalRefusedPayload,
    RulePromotedPayload,
    SourceIngestedPayload,
)
from .exception import ExceptionCode, ReconException, Resolution  # noqa: E402
from .policy import Policy, PolicyViolation, Ratio  # noqa: E402
from .proof import MatchTier, Proof, ProofLeg, ProofTier  # noqa: E402
from .record import Record  # noqa: E402
from .rule import (  # noqa: E402
    Predicate,
    PromotionEvent,
    RegressionReport,
    Rule,
    RuleAction,
    RuleStatus,
)

__all__ = [
    "CONTRACT_VERSION",
    "GENESIS",
    "PAYLOADS",
    "PRODUCERS",
    "AdapterSpec",
    "CanonicalField",
    "CloseBlockedPayload",
    "CloseCompletedPayload",
    "CloseStartedPayload",
    "Event",
    "EventKind",
    "ExceptionCode",
    "ExceptionRaisedPayload",
    "FieldMap",
    "IntakeUnverifiedPayload",
    "MatchProvenPayload",
    "MatchRejectedPayload",
    "MatchTier",
    "Money",
    "OutOfScopePayload",
    "ParseVerb",
    "Policy",
    "PolicyViolation",
    "PostingWrittenPayload",
    "Predicate",
    "PromotionEvent",
    "Proof",
    "ProofLeg",
    "ProofTier",
    "ProposalRefusedPayload",
    "Ratio",
    "ReaderKind",
    "ReaderSpec",
    "ReconException",
    "Record",
    "RegressionReport",
    "RejectRule",
    "Resolution",
    "Rule",
    "RuleAction",
    "RulePromotedPayload",
    "RuleStatus",
    "SourceIngestedPayload",
]
