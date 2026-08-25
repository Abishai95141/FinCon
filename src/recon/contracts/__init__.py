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

CONTRACT_VERSION = "7.0.0"
# 6.1.0 — RuleAction.value (normalize_key could say which key to rewrite and
#         never what to, which is why it was unusable), PromotionEvent
#         .postings_moved, AdapterAuthoredPayload, AdapterSpec.natural_key.
#         New optional fields and a new payload, so minor. ChartOfAccounts and
#         AdapterSpec currency became REQUIRED — that is major in isolation, and
#         it ships inside 6.0.0's break rather than after it.
# 6.0.0 — Identity stops being positional. `Record.record_id` was
#         `source:ordinal`, so the same id named a different row in every batch
#         and an id-keyed rule fired on strangers in held-out data. It is now
#         `source:natural-key-hash:occurrence` — stable and unique.
#         `Record.natural_key` and `Record.key_occurrence` added, and
#         `AdapterSpec.natural_key` declares which fields build it.
#         `key_occurrence` is `row_number() over (partition by natural_key)`
#         evaluated once at intake, which is the one production that makes
#         "suppress the row the export asserted twice" sayable with a UNARY
#         predicate. That rule was maximally general and previously unsayable:
#         two constraints on different axes — arity and generality — were being
#         enforced as one.
#         Identity is deliberately NOT the natural key: on batch A exactly two
#         natural keys collide and they are the planted duplicate, so a
#         content-keyed id would delete the rows it exists to find.
#         Retyping a required field is MAJOR.
# 5.0.0 — P11's claim enforced. `HONESTY_CODES` and `ReconException.is_honesty_code`
#         are REMOVED: whether escalating is correct is a fact about the
#         category, so it is `CodeDefinition.escalation_is_correct` and answered
#         by `TaxonomyRegistry.escalates()`. While it lived as a frozenset of ids
#         in this package, a code minted through the P11 lifecycle could never be
#         an honesty code however honest it was.
#         `ReconException.code_provenance: ProofTier` added (default P3) and
#         `ProofTier.outranks()` with it. It replaces `DERIVED_CODES = {"E09",
#         "E13"}` in the triage module — which was the proof-tier ordering
#         written down in the wrong place and in terms of the wrong thing: a
#         model can propose `E09` too, and what matters is how the label was
#         arrived at, not which label it is.
#         Removing a public property is MAJOR.
# 4.0.0 — P12 removed Policy.max_selectivity_pct, added one commit earlier. A
#         metamorphic relation refuted it: the SAME rule, still firing on the
#         same 502 rows, went from refused to allowed when 1,500 unrelated rows
#         were added to the corpus. It measured corpus composition, not the
#         rule. Its mutation test passed the whole time, which is what makes it
#         worth recording: a mutant proves code is reachable, not that it means
#         anything. Removing a field is MAJOR.
#         The concern it addressed — a rule that floods the worklist — is real
#         and is now UNGUARDED. See STATUS. Any replacement must be invariant to
#         corpus padding; tests/property/ holds the relation that will refute it
#         if it is not.
# 3.2.0 — P12 part 2 gave EventKind.RULE_INDUCED a real payload and a real
#         producer. New model only, so minor.
# 3.1.0 — P12 added EventKind.CLASSIFICATION_PROPOSED and its payload: the model
#         edge proposing a code for an exception. New enum member plus a new
#         model, so minor. `accepted` is always False at proposal time — an
#         attestation is a separate decision by a named human.
# 3.0.0 — P11 opened the exception taxonomy. `ReconException.code` was an
#         `ExceptionCode` enum member and is now a pattern-validated string, so
#         this is a retype on a required field: MAJOR. The enum survives as
#         named constants for the seeded ids and carries no authority.
#         New: TaxonomyRegistry / CodeDefinition / CodeStatus / Authority — the
#         registry says what a code means and what it may do, and it is a
#         separate versioned input the proposer cannot supply (finding F2's
#         shape). New event kinds CodeProposed / CodeAccepted / CodePromoted,
#         and CloseStarted now pins the taxonomy digest beside the policy one.
#         Done now, deliberately, while there are no external consumers.
# 2.1.0 — P9 added the decision-log surface: Event, EventKind, the per-kind
#         payload models, and PRODUCERS (which kind is written by what, and for
#         the three with no producer yet, the phase that will build them). All
#         new models, so minor — nothing existing changed shape. The log is a
#         public artifact: an external auditor reads it without our code, so it
#         is versioned like everything else here.
# 6.2.0 — `RuleAction.target` is required for RAISE_ADVISORY, alongside BOOK_TO
#         and NORMALIZE_KEY. The advisory action reached no close before this,
#         so no valid consumer could depend on a target-less one; a model wrote
#         exactly that and produced a rule with nothing to advise.
# 7.0.0 — BREAKING, and the reason A1 was worth doing. `CloseCompletedPayload`
#         gains a required `outcome_digest` and `scorecard_digest` becomes
#         optional. The terminator used to commit to a digest of the benchmark
#         scorecard, which needs truth labels — so a close outside the benchmark
#         could not write its own terminal event at all. `Proof` gains
#         `rule_bundle_digest`, and `verify()` gains the clauses that make a
#         `P1 RULE` claim checkable: a relabelled tier and a forged rule_id both
#         verified before this.
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
    AdapterAuthoredPayload,
    ClassificationProposedPayload,
    CloseBlockedPayload,
    CloseCompletedPayload,
    CloseStartedPayload,
    CodeAcceptedPayload,
    CodePromotedPayload,
    CodeProposedPayload,
    Event,
    EventKind,
    ExceptionRaisedPayload,
    IntakeUnverifiedPayload,
    MatchProvenPayload,
    MatchRejectedPayload,
    OutOfScopePayload,
    PostingWrittenPayload,
    ProposalRefusedPayload,
    RuleInducedPayload,
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
from .taxonomy import (  # noqa: E402
    AUTHORITY,
    CODE_PATTERN,
    Authority,
    CodeDefinition,
    CodeId,
    CodeStatus,
    TaxonomyRegistry,
    TaxonomyViolation,
)

__all__ = [
    "AUTHORITY",
    "CODE_PATTERN",
    "CONTRACT_VERSION",
    "GENESIS",
    "PAYLOADS",
    "PRODUCERS",
    "AdapterAuthoredPayload",
    "AdapterSpec",
    "Authority",
    "CanonicalField",
    "ClassificationProposedPayload",
    "CloseBlockedPayload",
    "CloseCompletedPayload",
    "CloseStartedPayload",
    "CodeAcceptedPayload",
    "CodeDefinition",
    "CodeId",
    "CodePromotedPayload",
    "CodeProposedPayload",
    "CodeStatus",
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
    "RuleInducedPayload",
    "RulePromotedPayload",
    "RuleStatus",
    "SourceIngestedPayload",
    "TaxonomyRegistry",
    "TaxonomyViolation",
]
