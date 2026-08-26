"""Events derived from a close, by set arithmetic over what it decided.

**Not by instrumenting the happy path.** A log written where someone remembered
to call `emit()` records what the author was thinking about, and the refusals
are exactly what nobody is thinking about. Three failure classes shipped green
before P6 for the same reason: every check answered its own question and nobody
asked whether everything got an answer.

So this walks the same structures the completeness audit walks, and then checks
itself against that audit: **every input the audit gave a disposition to must be
named by at least one event.** An input that was matched, excepted or excluded
and appears nowhere in the log is a derivation bug, and `derive` refuses to
finish. That check is also what makes replay total — a record named by no event
would have no external id on the way back, so the log would reconstruct a
scorecard over an incomplete universe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..contracts import Policy, ReconException, Record, TaxonomyRegistry
from ..contracts.event import (
    CloseBlockedPayload,
    CloseStartedPayload,
    Event,
    EventKind,
    ExceptionRaisedPayload,
    IntakeUnverifiedPayload,
    MatchProvenPayload,
    MatchRejectedPayload,
    OutOfScopePayload,
    PostingWrittenPayload,
    SourceIngestedPayload,
)
from ..engine.completeness import CompletenessReport, Disposition
from ..intake.proofs import IntakeProof
from ..ledger.beancount_io import JournalEntry

ENGINE = "engine"


class DerivationError(AssertionError):
    """The log does not account for something the close disposed of.

    An assertion rather than a domain error, for the same reason
    `CompletenessError` is: this is a bug in the system, not a finding about
    the data.
    """


@dataclass(frozen=True)
class RejectedMatch:
    """A match the verifier refused. Kept as a first-class decision — an arm
    that silently drops what it cannot prove would log the same as one that
    proves everything."""

    match_id: str
    proof_id: str
    anchor_id: str
    group_ids: list[str]
    reasons: list[str]


@dataclass(frozen=True)
class Decisions:
    """Everything one close decided, in the shapes the audit walks."""

    batch: str
    profile: str
    policy: Policy
    policy_digest: str
    taxonomy: TaxonomyRegistry
    taxonomy_digest: str
    source_digests: dict[str, str]
    sources: list[IntakeProof]
    scope: dict[str, str]
    matches: list[object]
    """`engine.tiers.Match`. Typed loosely to keep this module off the engine's
    import path — replay must not be able to reach the matcher."""

    rejected: list[RejectedMatch]
    exceptions: list[ReconException]
    entries: list[JournalEntry]
    completeness: CompletenessReport
    records: dict[str, Record]
    external_of: dict[str, str]
    blocked_reasons: list[str] = field(default_factory=list)
    label_digest: str | None = None
    period: list[str] = field(default_factory=list)


def _externals(decisions: Decisions, ids: set[str]) -> dict[str, str]:
    return {rid: decisions.external_of[rid] for rid in sorted(ids) if rid in decisions.external_of}


def unlogged(report: CompletenessReport, events: list[Event]) -> list[str]:
    """Inputs the audit disposed of that no event names."""
    named: set[str] = set()
    for event in events:
        named |= event.payload.record_ids()
    disposed = {
        rid
        for pool in (report.anchors, report.records)
        for rid, disposition in pool.items()
        if disposition is not Disposition.UNDISPOSED
    }
    return sorted(disposed - named)


def derive(decisions: Decisions) -> list[Event]:
    """Build the event stream for a close, then check it accounts for the run."""
    policy_ref = decisions.policy.ref

    def event(kind, payload, *, outcome, input_hash, actor=ENGINE, policy=policy_ref):
        return Event(
            seq=0,
            kind=kind,
            at=datetime.now(UTC),
            actor=actor,
            outcome=outcome,
            input_hash=input_hash,
            policy_ref=policy,
            payload=payload,
        )

    events: list[Event] = [
        event(
            EventKind.CLOSE_STARTED,
            CloseStartedPayload(
                batch=decisions.batch,
                profile=decisions.profile,
                anchors_in_scope=len(
                    [a for a in decisions.completeness.anchors if a not in decisions.scope]
                ),
                group_records=len(
                    [
                        r
                        for r in decisions.completeness.records
                        if r not in decisions.completeness.anchors
                    ]
                ),
                policy_digest=decisions.policy_digest,
                taxonomy_ref=decisions.taxonomy.ref,
                taxonomy_digest=decisions.taxonomy_digest,
                source_digests=dict(decisions.source_digests),
                label_digest=decisions.label_digest,
                period=list(decisions.period),
            ),
            outcome="started",
            input_hash=decisions.policy_digest,
        )
    ]

    for proof in decisions.sources:
        common = dict(
            source=proof.source,
            doc_hash=proof.doc_hash,
            strength=proof.strength,
            rows_in_file=proof.rows_in_file,
            rows_parsed=proof.rows_parsed,
            rows_rejected=proof.rows_rejected,
        )
        if proof.strength == "verified":
            events.append(
                event(
                    EventKind.SOURCE_INGESTED,
                    SourceIngestedPayload(**common),
                    outcome="verified",
                    input_hash=proof.doc_hash,
                )
            )
        else:
            # The gap travels with the source, so a number derived from it can
            # never be quoted without the words that qualify it.
            gap = (
                "; ".join(f"{c.name}: {c.detail}" for c in proof.failed)
                or "no substantive check could run — the source carries no "
                "control total and no balances"
            )
            events.append(
                event(
                    EventKind.INTAKE_UNVERIFIED,
                    IntakeUnverifiedPayload(**common, gap=gap),
                    outcome=proof.strength,
                    input_hash=proof.doc_hash,
                )
            )

    for record_id, reason in sorted(decisions.scope.items()):
        events.append(
            event(
                EventKind.OUT_OF_SCOPE,
                OutOfScopePayload(
                    record_id=record_id,
                    external_id=decisions.external_of.get(record_id),
                    reason=reason,
                ),
                outcome="excluded",
                input_hash=record_id,
            )
        )

    for match in decisions.matches:
        ids = {match.anchor_id, *match.group_ids}
        events.append(
            event(
                EventKind.MATCH_PROVEN,
                MatchProvenPayload(
                    match_id=match.match_id,
                    tier=match.tier.value,
                    proof_id=match.proof.proof_id,
                    anchor_id=match.anchor_id,
                    group_ref=match.group_ref,
                    group_ids=list(match.group_ids),
                    residual=match.proof.residual,
                    external_ids=_externals(decisions, ids),
                    # The proof travels with the event. A record that names a
                    # proof id and not the proof cites a document the reader
                    # cannot fetch — and re-deriving our arithmetic from the log
                    # plus the source files is the whole trust argument (P13).
                    proof=match.proof,
                ),
                outcome="proven",
                input_hash=match.proof.proof_id,
            )
        )

    for refusal in decisions.rejected:
        ids = {refusal.anchor_id, *refusal.group_ids}
        events.append(
            event(
                EventKind.MATCH_REJECTED,
                MatchRejectedPayload(
                    match_id=refusal.match_id,
                    proof_id=refusal.proof_id,
                    anchor_id=refusal.anchor_id,
                    group_ids=list(refusal.group_ids),
                    reasons=list(refusal.reasons),
                    external_ids=_externals(decisions, ids),
                ),
                outcome="refused",
                input_hash=refusal.proof_id,
            )
        )

    for exc in decisions.exceptions:
        ids = set(exc.record_ids) | {r for s in (exc.alternatives or []) for r in s}
        events.append(
            event(
                EventKind.EXCEPTION_RAISED,
                ExceptionRaisedPayload(
                    exception_id=exc.exception_id,
                    fingerprint=exc.fingerprint,
                    code=exc.code,
                    code_provenance=exc.code_provenance.value,
                    amount=exc.amount,
                    leg=exc.leg,
                    as_of=exc.as_of.isoformat(),
                    named_records=list(exc.record_ids),
                    alternatives=[list(s) for s in exc.alternatives] if exc.alternatives else None,
                    hypothesis=exc.hypothesis,
                    evidence=list(exc.evidence),
                    ambiguous_codes=list(exc.ambiguous_codes),
                    blocks_close=exc.blocks_close,
                    external_ids=_externals(decisions, ids),
                ),
                outcome="raised",
                input_hash=exc.exception_id,
            )
        )

    for entry in decisions.entries:
        events.append(
            event(
                EventKind.POSTING_WRITTEN,
                PostingWrittenPayload(
                    entry_id=entry.entry_id,
                    entry_date=entry.entry_date.isoformat(),
                    narration=entry.narration,
                    postings=[
                        {"role": p.role.value, "amount": f"{p.amount:.2f}"} for p in entry.postings
                    ],
                    proof_id=entry.proof_id,
                    exception_id=entry.meta.get("exception_id"),
                ),
                outcome="posted",
                input_hash=entry.entry_id,
            )
        )

    blocking = [e.exception_id for e in decisions.exceptions if e.blocks_close]
    if decisions.blocked_reasons or blocking:
        events.append(
            event(
                EventKind.CLOSE_BLOCKED,
                CloseBlockedPayload(
                    # Both, always. The `or` that used to be here let a ledger
                    # error hide the fact that exceptions were blocking too —
                    # two different states collapsed into one list, so a reader
                    # of the record could not tell "the books do not balance"
                    # from "five items need a human before sign-off". A surface
                    # rendering that list had no way to separate them either.
                    reasons=list(decisions.blocked_reasons)
                    + ([f"{len(blocking)} exception(s) block sign-off"] if blocking else []),
                    blocking_exceptions=blocking,
                ),
                outcome="blocked",
                input_hash=decisions.batch,
            )
        )

    missing = unlogged(decisions.completeness, events)
    if missing:
        raise DerivationError(
            f"{len(missing)} input(s) the audit disposed of are named by no event: "
            f"{missing[:5]} — the log does not account for the run"
        )
    return events
