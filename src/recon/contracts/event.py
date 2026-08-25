"""The decision log's public surface.

You cannot audit an agent you did not log, and P12 is where a model first
authors configuration — so the record lands before the model edge, not after.

Three properties are structural rather than advisory.

**Typed, not free-form.** Each kind has a payload model, and `PAYLOADS` is
asserted complete against `EventKind` at import. A kind added without a payload
breaks the build rather than surfacing as an untyped dict in someone's audit
export. Same shape as the parse-verb registry.

**Every kind declares its producer.** Three kinds have none yet — a model
authors them and there is no model. `PRODUCERS` names the phase instead of
leaving the kind quietly absent, for the same reason the LLM arm reports
*absent* rather than zero: a hole that nobody can see is the dangerous kind.

**Refusals are events.** `ProposalRefused` and `MatchRejected` are first-class
kinds, not an absence of a success. A log that contains only what worked is a
marketing document; in a governed system the refusal is the interesting part.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny, model_validator

from . import CONTRACT_VERSION, Money

GENESIS = "0" * 64


class EventKind(StrEnum):
    CLOSE_STARTED = "CloseStarted"
    SOURCE_INGESTED = "SourceIngested"
    INTAKE_UNVERIFIED = "IntakeUnverified"
    OUT_OF_SCOPE = "OutOfScope"
    MATCH_PROVEN = "MatchProven"
    MATCH_REJECTED = "MatchRejected"
    EXCEPTION_RAISED = "ExceptionRaised"
    POSTING_WRITTEN = "PostingWritten"
    CLOSE_BLOCKED = "CloseBlocked"
    CLOSE_COMPLETED = "CloseCompleted"
    RULE_PROMOTED = "RulePromoted"
    RULE_APPLIED = "RuleApplied"
    PROPOSAL_REFUSED = "ProposalRefused"
    CLASSIFICATION_PROPOSED = "ClassificationProposed"
    CODE_PROPOSED = "CodeProposed"
    CODE_ACCEPTED = "CodeAccepted"
    CODE_PROMOTED = "CodePromoted"
    RULE_INDUCED = "RuleInduced"
    ADAPTER_AUTHORED = "AdapterAuthored"


#: kind -> who writes it. A value starting with "P" is a phase that has not run:
#: the kind exists in the vocabulary and nothing can produce one yet.
PRODUCERS: dict[EventKind, str] = {
    EventKind.CLOSE_STARTED: "engine",
    EventKind.SOURCE_INGESTED: "engine",
    EventKind.INTAKE_UNVERIFIED: "engine",
    EventKind.OUT_OF_SCOPE: "engine",
    EventKind.MATCH_PROVEN: "engine",
    EventKind.MATCH_REJECTED: "engine",
    EventKind.EXCEPTION_RAISED: "engine",
    EventKind.POSTING_WRITTEN: "engine",
    EventKind.CLOSE_BLOCKED: "engine",
    EventKind.CLOSE_COMPLETED: "engine",
    EventKind.RULE_PROMOTED: "recon.engine.promotion.promote",
    EventKind.RULE_APPLIED: "recon.close.run_close",
    EventKind.PROPOSAL_REFUSED: "recon.engine.promotion.promote",
    EventKind.CLASSIFICATION_PROPOSED: "recon.triage.classify.classify",
    EventKind.CODE_PROPOSED: "recon.engine.taxonomy.propose",
    EventKind.CODE_ACCEPTED: "recon.engine.taxonomy.accept",
    EventKind.CODE_PROMOTED: "recon.engine.taxonomy.promote",
    EventKind.RULE_INDUCED: "recon.triage.induce.induce",
    EventKind.ADAPTER_AUTHORED: "recon.triage.normalize.author_spec",
}


class _Payload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    def record_ids(self) -> set[str]:
        """Which inputs this event speaks about.

        Load-bearing: the derivation checks that every input the completeness
        audit gave a disposition to is named by at least one event, and this is
        how an event says which. It is also what makes the replayed id map
        total — a record named by no event would be unmappable on replay.
        """
        return set()

    def externals(self) -> dict[str, str]:
        """record id -> the source's own id, for the ids this event names.

        Carried per event rather than in one header blob so the map a replay
        rebuilds is exactly the map the events justify.
        """
        return {}


class CloseStartedPayload(_Payload):
    batch: str
    profile: str
    taxonomy_ref: str = ""
    taxonomy_digest: str = ""
    """sha256 of the code registry *file*. Same reason the policy is pinned: a
    run judged under a vocabulary nobody approved should be visible in the
    record rather than invisible in memory."""

    policy_digest: str
    """sha256 of the policy *file*. P7 shipped with policy loaded from disk and
    trusted; a run judged under a version nobody approved is now visible in the
    record rather than invisible in memory."""
    source_digests: dict[str, str]
    label_digest: str | None = None
    period: list[str] = Field(default_factory=list)


class SourceIngestedPayload(_Payload):
    source: str
    doc_hash: str
    strength: str
    rows_in_file: int
    rows_parsed: int
    rows_rejected: int


class IntakeUnverifiedPayload(SourceIngestedPayload):
    gap: str
    """Why this source could not be verified — the words that go beside any
    number derived from it."""


class OutOfScopePayload(_Payload):
    record_id: str
    external_id: str | None = None
    reason: str

    def record_ids(self) -> set[str]:
        return {self.record_id}

    def externals(self) -> dict[str, str]:
        return {self.record_id: self.external_id} if self.external_id else {}


class MatchProvenPayload(_Payload):
    match_id: str
    tier: str
    proof_id: str
    anchor_id: str
    group_ref: str
    group_ids: list[str]
    residual: Money
    external_ids: dict[str, str]

    def record_ids(self) -> set[str]:
        return {self.anchor_id, *self.group_ids}

    def externals(self) -> dict[str, str]:
        return dict(self.external_ids)


class MatchRejectedPayload(_Payload):
    match_id: str
    proof_id: str
    anchor_id: str
    group_ids: list[str]
    reasons: list[str]
    external_ids: dict[str, str] = Field(default_factory=dict)

    def record_ids(self) -> set[str]:
        return {self.anchor_id, *self.group_ids}

    def externals(self) -> dict[str, str]:
        return dict(self.external_ids)


class ExceptionRaisedPayload(_Payload):
    exception_id: str
    code: str
    amount: Money
    leg: str
    as_of: str
    named_records: list[str]
    alternatives: list[list[str]] | None = None
    hypothesis: str | None = None
    evidence: list[str] = Field(default_factory=list)
    blocks_close: bool = False
    external_ids: dict[str, str] = Field(default_factory=dict)

    def record_ids(self) -> set[str]:
        ids = set(self.named_records)
        for subset in self.alternatives or []:
            ids |= set(subset)
        return ids

    def externals(self) -> dict[str, str]:
        return dict(self.external_ids)


class PostingWrittenPayload(_Payload):
    entry_id: str
    entry_date: str
    narration: str
    postings: list[dict[str, str]]
    proof_id: str | None = None
    exception_id: str | None = None


class CloseBlockedPayload(_Payload):
    reasons: list[str]
    blocking_exceptions: list[str] = Field(default_factory=list)


class CloseCompletedPayload(_Payload):
    events_before_this: int
    matches: int
    rejected: int
    exceptions: int
    postings: int
    out_of_scope: int
    outcome_digest: str
    """A fingerprint of what this close decided, from the close alone.

    The terminator committed only to `scorecard_digest` until 7.0.0 — a digest
    of the *benchmark scorecard*, which is computed against truth labels. So a
    close run anywhere but the benchmark could not write its own terminal event,
    and "replay a close from its log" quietly meant "replay a close that has
    labels". This commits to the decisions: which anchor matched which group, at
    which tier and provenance, which exceptions were raised, what was posted,
    what was excluded."""

    scorecard_digest: str = ""
    """Optional, and a *benchmark* fact rather than a product one. A caller that
    can score against ground truth attaches its digest here; production leaves
    it empty because in production nobody knows the right answer."""

    complete: bool


class RuleAppliedPayload(_Payload):
    """What one promoted rule did to one close.

    A rule acting is a decision, so it is an event. Four action kinds could be
    promoted and do nothing, and the close said nothing about it — the log
    recorded that a rule *existed*, never that it *moved* anything. `observable`
    false means the rule fired and changed nothing a human can point at, which
    is a finding rather than a quiet success.
    """

    rule_ref: str
    fired: int
    suppressed: int = 0
    advisories_applied: int = 0
    keys_normalized: int = 0
    postings_redirected: int = 0
    tolerance_widened: bool = False
    unapplied: list[str] = Field(default_factory=list)
    observable: bool = True


class RulePromotedPayload(_Payload):
    rule_ref: str
    evidence_hash: str
    matches_checked: int
    matches_broken: int
    matches_added: int
    sample_added: list[str] = Field(default_factory=list)


class ProposalRefusedPayload(_Payload):
    subject: str
    proposal_kind: str
    reasons: list[str]


class ClassificationProposedPayload(_Payload):
    exception_id: str
    from_code: str
    to_code: str
    hypothesis: str
    evidence: list[str] = Field(default_factory=list)
    model: str = ""
    accepted: bool = False
    """Always False at proposal time. An attestation is a separate decision by a
    named human, and conflating the two would lose the distinction the whole
    trust boundary rests on."""

    def record_ids(self) -> set[str]:
        return set(self.evidence)


class CodeProposedPayload(_Payload):
    code: str
    title: str
    definition: str
    claimed_owner: str | None = None
    claimed_booking: str | None = None
    """What the proposal *asked for*. Recorded rather than honoured, so a later
    reader can see the difference between what was requested and what was
    granted."""

    routed_to: str = ""
    granted: str = ""


class CodeAcceptedPayload(_Payload):
    code: str
    owner: str
    granted: str = ""


class CodePromotedPayload(_Payload):
    code: str
    definition: str
    owner: str | None = None
    books_to: str | None = None
    granted: str = ""


class RuleInducedPayload(_Payload):
    rule_id: str
    induced_from: str
    """The exception whose resolution produced this. A rule's justification
    travels with it, so a later reader can see why it exists."""

    rationale: str = ""
    when: list[dict] = Field(default_factory=list)
    then: list[dict] = Field(default_factory=list)
    model: str = ""


class AdapterAuthoredPayload(_Payload):
    spec_id: str
    source: str
    delimiter: str = ","
    header_row: int = 1
    mappings: list[str] = Field(default_factory=list)
    reasoning: str = ""
    model: str = ""
    needs_approval: bool = True
    """Always true for a model-authored spec. Set by the engine, never read from
    the proposal — a spec that could name its own author could declare itself
    human-written and walk past first-use approval."""


class UnproducedPayload(_Payload):
    """For kinds whose producer has not been built. Carries the phase, so an
    event of this shape appearing in a log is itself a bug worth seeing."""

    phase: str


PAYLOADS: dict[EventKind, type[_Payload]] = {
    EventKind.CLOSE_STARTED: CloseStartedPayload,
    EventKind.SOURCE_INGESTED: SourceIngestedPayload,
    EventKind.INTAKE_UNVERIFIED: IntakeUnverifiedPayload,
    EventKind.OUT_OF_SCOPE: OutOfScopePayload,
    EventKind.MATCH_PROVEN: MatchProvenPayload,
    EventKind.MATCH_REJECTED: MatchRejectedPayload,
    EventKind.EXCEPTION_RAISED: ExceptionRaisedPayload,
    EventKind.POSTING_WRITTEN: PostingWrittenPayload,
    EventKind.CLOSE_BLOCKED: CloseBlockedPayload,
    EventKind.CLOSE_COMPLETED: CloseCompletedPayload,
    EventKind.RULE_PROMOTED: RulePromotedPayload,
    EventKind.RULE_APPLIED: RuleAppliedPayload,
    EventKind.PROPOSAL_REFUSED: ProposalRefusedPayload,
    EventKind.CLASSIFICATION_PROPOSED: ClassificationProposedPayload,
    EventKind.CODE_PROPOSED: CodeProposedPayload,
    EventKind.CODE_ACCEPTED: CodeAcceptedPayload,
    EventKind.CODE_PROMOTED: CodePromotedPayload,
    EventKind.RULE_INDUCED: RuleInducedPayload,
    EventKind.ADAPTER_AUTHORED: AdapterAuthoredPayload,
}

# Asserted at import, like the parse-verb registry: a kind added without a
# payload model or without a declared producer fails the build here rather than
# on someone's audit export.
assert set(PAYLOADS) == set(EventKind), sorted(set(EventKind) - set(PAYLOADS))
assert set(PRODUCERS) == set(EventKind), sorted(set(EventKind) - set(PRODUCERS))


class Event(BaseModel):
    """One decision, hash-chained to the one before it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: str = CONTRACT_VERSION
    seq: int
    kind: EventKind
    at: datetime
    actor: str
    """Who decided. "engine" for a deterministic step, a person's name for an
    attestation, "agent:<role>" once a model can propose."""

    outcome: str
    """What happened, in one word: proven, refused, raised, posted, blocked."""

    input_hash: str
    """What the decision was about — a doc hash, a proof id, a record id. An
    event that cannot say what it acted on cannot be checked against anything."""

    policy_ref: str | None = None
    payload: SerializeAsAny[_Payload]
    prev_hash: str = GENESIS
    event_hash: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce_payload(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        kind = data.get("kind")
        if kind is None:
            return data
        model = PAYLOADS[EventKind(kind)]
        payload = data.get("payload")
        if isinstance(payload, dict):
            data = {**data, "payload": model.model_validate(payload)}
        return data

    @model_validator(mode="after")
    def _payload_matches_kind(self) -> Event:
        expected = PAYLOADS[self.kind]
        if not isinstance(self.payload, expected):
            raise ValueError(
                f"{self.kind.value} requires a {expected.__name__}, "
                f"got {type(self.payload).__name__}"
            )
        if not self.actor.strip():
            raise ValueError("an event must name who decided")
        return self
