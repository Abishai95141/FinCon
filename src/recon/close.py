"""One close, in the library rather than in the benchmark.

Until 2026-08-25 `bench/run.py:close()` was the only thing that assembled
intake -> tiers -> ledger -> journal -> worklist, and `src/recon/api/` and
`src/recon/mcp/` were empty files. `src/recon` was a library with no
application, so the benchmark harness was the product's only executable form.

That is why so many controls could be green while guarding nothing. A control
that only a test drives can be checked on its *inputs*; nothing observes its
*outputs*, because outside a test it has none. Moving the pipeline here gives
"in band" somewhere to be: the benchmark, the API and the MCP server become
driving adapters that call `run_close`, and a checker placed here runs on every
real close rather than on whatever a test happened to construct.

**What is deliberately not here.** Scoring. Truth labels. Ablation arms. Those
are the benchmark's business and the product cannot do them — in production
nobody knows the right answer, which is the whole problem. Extracting this
surfaced one thing that had been hidden by the entanglement: the log's terminal
event committed to a digest of the *benchmark scorecard*, so a close outside the
benchmark could not write its own terminator. It now commits to `outcome_digest`,
computed from the close's own decisions, which needs no labels. A caller that
*can* score may attach its digest through `annotations` — recorded, never read.
"""

from __future__ import annotations

import contextlib  # noqa: F401 — a mutation anchor in tools/mutations/p20.py
import dataclasses
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import trust
from .contracts import (
    AuthorityVerifiedPayload,
    CloseCompletedPayload,
    EventKind,
    Policy,
    ProofTier,
    ProposalRefusedPayload,
    ReconException,
    Record,
    RuleAppliedPayload,
    TaxonomyRegistry,
)
from .contracts.rule import Rule
from .engine import fingerprint
from .engine.blocking import BlockingPolicy, CandidateSet
from .engine.blocking import build as build_candidates
from .engine.completeness import CompletenessReport
from .engine.tiers import MatchProfile
from .engine.tiers import run as run_tiers
from .engine.verifier import verify
from .intake.proofs import IntakeProof
from .journal import Journal
from .journal import exclusive as journal_lock
from .journal.derive import Decisions, RejectedMatch, derive
from .ledger.accounts import ChartOfAccounts
from .ledger.beancount_io import CloseResult as LedgerResult
from .ledger.beancount_io import JournalEntry, post_and_assert
from .ledger.posting_rules import entries_for
from .triage.worklist import WorkItem
from .triage.worklist import build as build_worklist


@dataclass(frozen=True)
class CloseRequest:
    """Everything one close needs, and nothing about how it will be judged.

    Records arrive already ingested: *which* files a loop reads is the adapter's
    business, and `recon.intake.ingest` is the product function it uses to read
    them. Keeping that choice outside means a batch on disk, an upload through
    the API and a fixture in a test all reach this function the same way.
    """

    run_id: str
    anchors: Sequence[tuple[str, Record]]
    """(external id, record) — the external id is what a human calls the row."""
    groups: Sequence[tuple[str, Record]]
    profile: MatchProfile
    policy: Policy
    taxonomy: TaxonomyRegistry
    chart: ChartOfAccounts
    period: tuple[date, date]
    opened_on: date
    journal_path: Path
    source_proofs: Sequence[IntakeProof] = ()
    provenance: ProofTier = ProofTier.P0_ARITHMETIC
    out_of_scope: Mapping[str, str] = field(default_factory=dict)
    """Records this loop does not reconcile, each with a reason. A *disposition*,
    not a filter: the completeness audit still walks them (invariant 8), and
    `audit` refuses a blank reason so nothing can be dropped quietly."""

    rules: Sequence[Rule] = ()
    policy_digest: str = ""
    taxonomy_digest: str = ""
    bundles: Sequence[Path] = ()
    """Directories whose signatures this close checks before trusting what it
    loaded from them — policy, the taxonomy, the promoted rule store. The close
    verifies them itself rather than being handed a verdict, for the same reason
    it takes its policy separately: a caller that supplies the trust is
    supplying its own permission."""

    require_signed: bool = False
    """Whether an untrusted bundle stops the close. Default false and reported
    either way — refusing to close the books because a verification key is
    missing is its own kind of failure, and which risk is worse is policy's
    call, not this function's."""

    annotations: Mapping[str, str] = field(default_factory=dict)
    """Facts a caller knows and the product does not — the benchmark's label
    digest and scorecard digest. Written into the record and never read by
    anything here. A caller cannot grant itself a permission through them."""


@dataclass(frozen=True)
class CloseOutcome:
    run_id: str
    matches: list = field(default_factory=list)
    rejected: list[RejectedMatch] = field(default_factory=list)
    exceptions: list[ReconException] = field(default_factory=list)
    entries: list[JournalEntry] = field(default_factory=list)
    not_posted: list[str] = field(default_factory=list)
    ledger: LedgerResult | None = None
    completeness: CompletenessReport | None = None
    worklist: list[WorkItem] = field(default_factory=list)
    scope: dict[str, str] = field(default_factory=dict)
    records: dict[str, Record] = field(default_factory=dict)
    external_of: dict[str, str] = field(default_factory=dict)
    candidates: CandidateSet | None = None
    decisions: Decisions | None = None
    journal_path: Path | None = None
    outcome_digest: str = ""
    rules_unapplied: dict[str, list[str]] = field(default_factory=dict)
    rule_effects: list = field(default_factory=list)
    """`rulestore.RuleEffect` per promoted rule. A rule whose `observable` is
    false fired and moved nothing — recorded, because that is the shape four
    action kinds shipped in and nobody could see it."""

    inert_rules: list[str] = field(default_factory=list)
    matches_broken_by_rules: list[str] = field(default_factory=list)
    """Anchors this batch would have matched without the rule bundle. Not
    advisory: invariant 5 says a rule may not break a match, and a close that
    lost one to its own rules has not finished successfully."""

    inadmissible: dict[str, list[str]] = field(default_factory=dict)
    authority: list = field(default_factory=list)
    """`trust.Verdict` per bundle — which authority this close ran under, and
    who put their name to it. A digest proves what ran; a signature proves who
    approved it."""

    ok: bool = True


def outcome_digest(
    matches: Sequence, exceptions: Sequence[ReconException], entries: Sequence, scope: Mapping
) -> str:
    """A fingerprint of what this close decided, from the close alone.

    The terminator used to commit to a digest of the benchmark *scorecard*,
    which is computed against truth labels — so a close run anywhere but the
    benchmark could not write its own terminal event, and "replay a close from
    its log" quietly meant "replay a close that has labels". This commits to the
    decisions instead: which anchor matched which group, at which tier and
    provenance, which exceptions were raised, what was posted, what was excluded.

    Timing is excluded on purpose — a wall clock is a fact about our machine and
    a digest that moved every run would say nothing about whether the answers
    matched.
    """
    body = {
        "matches": sorted(
            {
                "anchor": m.anchor_id,
                "groups": sorted(m.group_ids),
                "tier": m.tier.value,
                "provenance": m.proof.provenance.value,
                "rule": m.proof.rule_id,
            }.__repr__()
            for m in matches
        ),
        "exceptions": sorted(f"{e.code}:{e.amount}:{sorted(e.record_ids)}" for e in exceptions),
        "postings": sorted(f"{e.proof_id}:{len(e.postings)}" for e in entries),
        "out_of_scope": sorted(scope),
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class MatchOutcome:
    """The matching stage: what was matched, what was refused, what was raised.

    Split out so the benchmark's deterministic arm and a real close share one
    implementation of matching-and-verification rather than two that agree by
    inspection. An arm using a *stage* of the pipeline is a driving adapter; an
    arm with its own copy of the stage is the second code path this whole
    refactor exists to remove.
    """

    matches: list = field(default_factory=list)
    rejected: list[RejectedMatch] = field(default_factory=list)
    refuted: list[str] = field(default_factory=list)
    exceptions: list[ReconException] = field(default_factory=list)
    scope: dict[str, str] = field(default_factory=dict)
    records: dict[str, Record] = field(default_factory=dict)
    external_of: dict[str, str] = field(default_factory=dict)
    candidates: CandidateSet | None = None
    completeness: CompletenessReport | None = None
    rules_unapplied: dict[str, list[str]] = field(default_factory=dict)
    rule_effects: dict = field(default_factory=dict)
    inadmissible: dict[str, list[str]] = field(default_factory=dict)
    """Rules whose approval does not hold in this close, and why. They are
    not applied — and a refusal nobody records reads like a rule working."""

    tiers: dict[str, int] = field(default_factory=dict)
    run: object | None = None
    """The raw `engine.tiers.MatchRun`, for callers that need what the
    stage saw rather than what it decided."""


def match_and_verify(request: CloseRequest) -> MatchOutcome:
    """Match, then check every match on real output before anyone sees it.

    An unverified match is not a match (invariant 2) and its refusal is recorded
    rather than absorbed. The checker re-derives from the records, takes its
    policy separately, and now takes the rule bundle separately too — a proposer
    may not hand in the rules that excuse its own proof.
    """
    from .engine.promotion import admissible

    anchors = [rec for _, rec in request.anchors]
    groups = [rec for _, rec in request.groups]
    records = {rec.record_id: rec for _, rec in [*request.anchors, *request.groups]}
    external_of = {rec.record_id: ext for ext, rec in [*request.anchors, *request.groups]}

    # A rule's approval is checked before it acts, not merely at the moment it
    # was granted. `rulestore.load` looked at `status` and stopped, so a rule
    # approved under a policy that is not the one in force acted unchanged.
    rules, inadmissible = [], {}
    for rule in request.rules:
        reasons = admissible(rule, request.policy)
        if reasons:
            inadmissible[rule.rule_id] = reasons
        else:
            rules.append(rule)

    candidates = build_candidates(anchors, groups, BlockingPolicy())
    outcome = run_tiers(
        anchors,
        groups,
        request.profile,
        request.provenance,
        candidates,
        request.policy,
        request.out_of_scope,
        rules,
    )

    kept, rejected, refuted, tiers = [], [], [], {}
    for match in outcome.matches:
        verdict = verify(
            match.proof,
            records,
            request.policy,
            bundle=rules,
            declared_scope=request.out_of_scope,
        )
        if not verdict.proven:
            refuted.append(f"{match.match_id}: {verdict}")
            rejected.append(
                RejectedMatch(
                    match_id=match.match_id,
                    proof_id=match.proof.proof_id,
                    anchor_id=match.anchor_id,
                    group_ids=list(match.group_ids),
                    reasons=list(verdict.reasons) or [str(verdict)],
                )
            )
            continue
        kept.append(match)
        tiers[match.tier.value] = tiers.get(match.tier.value, 0) + 1

    return MatchOutcome(
        matches=kept,
        rejected=rejected,
        refuted=refuted,
        exceptions=fingerprint.stamp(outcome.exceptions, records),
        scope=outcome.scope,
        records=records,
        external_of=external_of,
        candidates=candidates,
        completeness=outcome.completeness,
        rules_unapplied=outcome.rules_unapplied,
        rule_effects=outcome.rule_effects,
        inadmissible=inadmissible,
        tiers=tiers,
        run=outcome,
    )


def run_close(request: CloseRequest) -> CloseOutcome:
    """Match, verify, post, record. The product's one path.

    The order is load-bearing and unchanged from the benchmark's: posting
    happens before the log is derived, because a decision log for a
    reconciliation that never reached the books is a log of half the system; and
    deriving happens before the terminator, because `derive` refuses to finish
    while any input the audit disposed of is named by no event.
    """
    import dataclasses as _dc

    from .engine import rulestore
    from .engine.promotion import broken_by_rules

    staged = match_and_verify(request)

    # Invariant 5 with a batch in front of it. Promotion measured breakage
    # against the history a rule was promoted on; nothing measured it against
    # the close being run, so a suppress rule aimed at a matched group took a
    # close from 20 matches to 19 with `ok=True` and nothing flagged.
    #
    # One extra tier pass, and only when there is a bundle to blame: with no
    # rules there is nothing that could have broken anything.
    broken: list[str] = []
    if request.rules:
        unruled = match_and_verify(_dc.replace(request, rules=()))
        broken = broken_by_rules(unruled.matches, staged.matches)
    records, external_of = staged.records, staged.external_of
    rules = list(request.rules)
    kept, rejected = staged.matches, staged.rejected

    exceptions = staged.exceptions
    entries, not_posted = entries_for(
        matches=kept,
        exceptions=exceptions,
        records=records,
        anchor_side=request.profile.anchor_side,
        taxonomy=request.taxonomy,
        overrides=rulestore.booking_overrides(rules, exceptions, records),
    )
    # The last effect a rule can have, and the only one the matching stage
    # cannot see: a `book_to` that reached an actual posting.
    # Which authority this close ran under. Verified here rather than trusted
    # from the caller: policy, the taxonomy and the rule store were pinned by
    # digest, and a digest proves what ran, not who approved it.
    authority = [trust.verify(b) for b in request.bundles]
    untrusted = [v for v in authority if not v.trusted]
    if untrusted and request.require_signed:
        raise trust.BundleError(
            "close requires signed authority: " + "; ".join(str(v) for v in untrusted)
        )

    redirected: dict[str, int] = {}
    for _ in rulestore.booking_overrides(rules, exceptions, records):
        for rule in rules:
            if any(a.kind.value == "book_to" for a in rule.then):
                redirected[rule.rule_id] = redirected.get(rule.rule_id, 0) + 1
                break
    effects = [
        dataclasses.replace(eff, postings_redirected=redirected.get(rid, 0))
        for rid, eff in sorted(staged.rule_effects.items())
    ]
    inert = [e.rule_id for e in effects if not e.observable]

    ledger = post_and_assert(
        entries,
        request.chart,
        opened_on=request.opened_on,
        period_end=request.period[1],
        policy=request.policy,
    )

    # Extended, not recomputed. The engine's audit already did the set arithmetic
    # over records; the postings and the intake strengths are what it could not
    # know. Auditing twice leaves two answers to one question, and the one
    # nobody reads is the one that rots.
    completeness = staged.completeness.extend(
        sources={p.source: p.strength for p in request.source_proofs},
        proof_ids=[m.proof.proof_id for m in kept],
        posted_proof_ids=[e.proof_id for e in entries if e.proof_id],
    )

    # Built before the record, so an unresolvable code stops the run here rather
    # than being written into a log as if it were a finding.
    worklist = build_worklist(exceptions, request.taxonomy, as_of=request.period[1])

    digest = outcome_digest(kept, exceptions, entries, staged.scope)
    decisions = Decisions(
        batch=request.run_id,
        profile=request.profile.name,
        policy=request.policy,
        policy_digest=request.policy_digest,
        taxonomy=request.taxonomy,
        taxonomy_digest=request.taxonomy_digest,
        source_digests={p.source: p.doc_hash for p in request.source_proofs},
        sources=list(request.source_proofs),
        scope=staged.scope,
        matches=kept,
        rejected=rejected,
        exceptions=exceptions,
        entries=entries,
        completeness=completeness,
        records=records,
        external_of=external_of,
        blocked_reasons=[f"{e.kind}: {e.message}" for e in ledger.errors]
        # Invariant 5 is not advisory, so a close that lost a match to its own
        # rule bundle is a blocked close and says so in the record. Until P13
        # `broken` set `ok=False` and reached the log nowhere: the one artifact
        # an auditor is handed said nothing about the one thing that had gone
        # wrong. A surface serving from the record could not have shown it,
        # which is how building the surface found it.
        + [
            f"rule_broke_match: {anchor} matched without the rule bundle and "
            f"does not match with it (invariant 5)"
            for anchor in broken
        ],
        label_digest=request.annotations.get("label_digest", digest),
        period=[request.period[0].isoformat(), request.period[1].isoformat()],
    )

    # One writer per decision log, and readers wait rather than seeing half of
    # one. Two closes of the same period used to interleave — one deleting the
    # file while the other read it back — and the caller was told the log had
    # been TAMPERED WITH, which is the most alarming message this system can
    # produce, emitted for two people pressing the same button. Measured, not
    # hypothesised: four concurrent closes, one JournalTampered.
    with journal_lock(request.journal_path):
        journal = Journal(request.journal_path, fresh=True)
        journal.extend(derive(decisions))
        for verdict in authority:
            journal.append(
                EventKind.AUTHORITY_VERIFIED,
                actor="engine",
                outcome="trusted" if verdict.trusted else "untrusted",
                input_hash=verdict.digest,
                policy_ref=request.policy.ref,
                payload=AuthorityVerifiedPayload(
                    bundle=verdict.name,
                    digest=verdict.digest,
                    trusted=verdict.trusted,
                    signed_by=verdict.signed_by,
                    key_id=verdict.key_id,
                    reasons=list(verdict.reasons) or ([] if verdict.signed else ["unsigned"]),
                ),
            )
        # A rule whose approval does not hold in this close did not act. A refusal
        # nobody records reads exactly like a rule that worked.
        for rule_id, reasons in sorted(staged.inadmissible.items()):
            journal.append(
                EventKind.PROPOSAL_REFUSED,
                actor="engine",
                outcome="inadmissible",
                input_hash=rule_id,
                policy_ref=request.policy.ref,
                payload=ProposalRefusedPayload(
                    subject=rule_id,
                    proposal_kind="promoted_rule",
                    reasons=list(reasons),
                ),
            )
        for eff in effects:
            journal.append(
                EventKind.RULE_APPLIED,
                actor="engine",
                outcome="observable" if eff.observable else "inert",
                input_hash=eff.rule_id,
                policy_ref=request.policy.ref,
                payload=RuleAppliedPayload(
                    rule_ref=f"{eff.rule_id}@v{eff.rule_version}",
                    fired=eff.fired,
                    suppressed=eff.suppressed,
                    advisories_applied=eff.advisories_applied,
                    keys_normalized=eff.keys_normalized,
                    postings_redirected=eff.postings_redirected,
                    tolerance_widened=eff.tolerance_widened,
                    unapplied=list(eff.unapplied),
                    observable=eff.observable,
                ),
            )
        complete = completeness.complete
        journal.append(
            EventKind.CLOSE_COMPLETED,
            actor="engine",
            outcome="complete" if complete else "incomplete",
            input_hash=decisions.label_digest,
            policy_ref=request.policy.ref,
            payload=CloseCompletedPayload(
                events_before_this=journal.count,
                matches=len(kept),
                rejected=len(rejected),
                exceptions=len(exceptions),
                postings=len(entries),
                out_of_scope=len(staged.scope),
                outcome_digest=digest,
                scorecard_digest=request.annotations.get("scorecard_digest", ""),
                complete=complete,
            ),
        )

    return CloseOutcome(
        run_id=request.run_id,
        matches=kept,
        rejected=rejected,
        exceptions=exceptions,
        entries=entries,
        not_posted=not_posted,
        ledger=ledger,
        completeness=completeness,
        worklist=worklist,
        scope=staged.scope,
        records=records,
        external_of=external_of,
        candidates=staged.candidates,
        decisions=decisions,
        journal_path=journal.path,
        outcome_digest=digest,
        rules_unapplied=staged.rules_unapplied,
        rule_effects=effects,
        inert_rules=inert,
        matches_broken_by_rules=broken,
        inadmissible=staged.inadmissible,
        authority=authority,
        ok=complete and not ledger.blocked and not broken,
    )
