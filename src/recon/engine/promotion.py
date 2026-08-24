"""The promotion gate.

`RegressionReport.promotable` was `matches_broken == 0`. Widening a tolerance
never *breaks* a match — it only adds — so the gate measured the one direction
that cannot detect the danger. A model optimising for "exceptions cleared" finds
that move immediately, and it looks like excellent performance.

Two changes, and the second matters more:

* **Count what a rule adds, not only what it breaks.** Additions are the point of
  a rule, so they cannot simply be forbidden — they are bounded by policy and
  shown to the approver.
* **Re-run the regression instead of reading it.** A report attached to a rule is
  a claim by the proposer, which is audit finding `F1` wearing a different
  costume. `regress` replays the rule against real history; nothing here trusts
  what the rule says about itself.

Measurement and judgement are kept apart on purpose. `regress` reports what a
rule *would do*, including things policy forbids — a gate that cannot describe a
refused rule cannot explain the refusal. `evaluate` decides.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal

from ..contracts import Policy, PolicyViolation, ProofTier, Record, TaxonomyRegistry
from ..contracts.event import EventKind, ProposalRefusedPayload, RulePromotedPayload
from ..contracts.rule import ActionKind, PromotionEvent, Rule, RuleStatus
from ..contracts.taxonomy import TaxonomyViolation
from .verifier import verify

SAMPLE_SIZE = 5

#: Action kinds `regress` can actually simulate. Anything else comes back with
#: no delta — and `0 broken, 0 added` reads as "safe" when it means
#: "unmeasured". That is CLAUDE.md's "an unmeasured thing reported as zero",
#: inside the one gate that exists to stop unsafe rules, so `evaluate` refuses
#: rather than letting the silence pass for a clean bill.
#:
#: `book_to` is absent on purpose: it changes where money posts, not which rows
#: match, so a match-delta regression has nothing to say about it. Measuring it
#: needs a posting-delta regression, which is not built.
MODELLED_ACTIONS = frozenset({"set_tolerance", "suppress", "raise_advisory"})

#: A rule that fires only on the rows it was induced from is a correction with a
#: rule's grammar. The P8 regression cannot see it — an id-specific rule breaks
#: no history and adds exactly what it was written to add — so generality is
#: measured on data the rule has never seen. Residual risk `P19`, checked before
#: promotion rather than monitored after it.
MIN_HELD_OUT_FIRINGS = 1

#: Fields that name *one row*, not a property of rows. An `eq`/`in` predicate on
#: one of these pins specific records, which is a correction however it is
#: dressed up.
#:
#: The structural check is the primary one, because the statistical one is
#: foolable: record ids here are positional (`source:ordinal`), so
#: `gateway-settlement:266` exists in every batch and names a *different row* in
#: each. An id-keyed rule therefore fires happily on held-out data — on rows
#: that have nothing to do with the case it was induced from. That is worse than
#: not firing, and a firing count alone would have called it a pass.
IDENTITY_FIELDS = frozenset({"record_id", "source_row_id", "group_ref"})
PINNING_OPS = frozenset({"eq", "in"})


def _record(journal, kind, **fields) -> None:
    """Write to the journal when one was supplied.

    Optional on purpose: the gate exists whether or not anyone is recording, and
    a promotion path that could not run without a log would make the log a
    dependency of the control rather than a record of it.
    """
    if journal is not None:
        journal.append(kind, **fields)


@dataclass(frozen=True)
class MatchHistory:
    """What a rule is replayed against: the inputs of an earlier close and the
    matches it proved."""

    anchors: list[Record]
    group_records: list[Record]
    records: dict[str, Record]
    matches: list[object]
    """Previously proven matches. Typed loosely to avoid a cycle with `tiers`."""

    def matched_anchor_ids(self) -> set[str]:
        return {m.anchor_id for m in self.matches}

    def digest(self) -> str:
        """Stable over the inputs, so the evidence hash moves when they do."""
        parts = [
            f"{r.record_id}:{r.amount}:{r.posted_on}:{r.group_ref or ''}"
            for r in sorted([*self.anchors, *self.group_records], key=lambda r: r.record_id)
        ]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()


@dataclass(frozen=True)
class RegressionOutcome:
    """What re-running the rule actually produced. Not what the rule claimed."""

    ran_at: datetime
    policy_ref: str
    rule_ref: str
    matches_checked: int
    broken: list[str] = field(default_factory=list)
    """Anchors matched before the rule and not after."""
    added: list[str] = field(default_factory=list)
    """Anchors matched after and not before — the direction the old gate missed."""
    unverifiable: list[str] = field(default_factory=list)
    """Added matches whose proof does not hold under policy. A rule may not
    create a match that would fail the same gate as any other."""
    exceptions_cleared: int = 0
    evidence_hash: str = ""
    unmodelled: list[str] = field(default_factory=list)
    """Action kinds this regression could not simulate. Non-empty means the
    delta above is *absent*, not zero."""


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)


def _tolerance_asked_for(rule: Rule) -> Decimal | None:
    """`is not None`, not truthiness. Found at P9 by a coverage gap: a rule
    asking for a tolerance of exactly `0.00` was filtered out here, because
    `Decimal("0.00")` is falsy — so `_apply` left the profile alone and the
    regression reported that a rule tightening tolerance to zero changes
    nothing. Tightening is a legitimate proposal, and the gate could not see
    what it did: audit finding `F3` pointing the other way."""
    asked = [
        a.amount for a in rule.then if a.kind is ActionKind.SET_TOLERANCE and a.amount is not None
    ]
    return max(asked) if asked else None


def _apply(rule: Rule, profile):
    """The rule's effect on the matching configuration."""
    asked = _tolerance_asked_for(rule)
    if asked is None:
        return profile
    return replace(profile, tolerance=replace(profile.tolerance, absolute=asked))


def _unmodelled(rule: Rule) -> list[str]:
    return sorted({a.kind.value for a in rule.then if a.kind.value not in MODELLED_ACTIONS})


def _suppressed_by(rule: Rule, records: list[Record]) -> set[str]:
    """Rows a `SUPPRESS` rule removes before matching. Simulated rather than
    assumed: suppressing a duplicated export row is exactly the case where the
    match delta is the whole point, and reporting `0 added` for it would be
    measuring nothing."""
    from .rules import select

    if not any(a.kind is ActionKind.SUPPRESS for a in rule.then):
        return set()
    return set(select(rule, records).matched)


@dataclass(frozen=True)
class GeneralisationOutcome:
    fires: int
    sampled: int
    examples: list[str] = field(default_factory=list)

    @property
    def generalises(self) -> bool:
        return self.fires >= MIN_HELD_OUT_FIRINGS

    def summary(self) -> str:
        if self.fires < MIN_HELD_OUT_FIRINGS:
            return f"CORRECTION — fires on 0/{self.sampled} held-out rows"
        return f"generalises — fires on {self.fires}/{self.sampled} held-out rows"


def generalises(rule: Rule, held_out: list[Record]) -> GeneralisationOutcome:
    """Does this rule have anything to say about data it did not come from?

    Purely behavioural since identity became content-derived. A structural ban
    on `eq`/`in` predicates over `record_id` sat in front of this, because
    positional ids meant `gateway-settlement:266` existed in every batch and an
    id-keyed rule fired on strangers — a firing count called it general. With
    stable ids the count is sound on its own, and the shape judgment is gone: a
    rule keyed on ids that genuinely recur *is* saying something about data it
    did not come from, and refusing it for how it looked was the wrong axis.

    Two constraints were being enforced as one. ADR-001 stratifies the
    vocabulary by arity; this stratifies by generality. "Suppress the row the
    export asserted twice" is maximally general and was not unary — which is why
    it had no path through the system until `key_occurrence` existed.
    """
    from .rules import select

    selection = select(rule, held_out)
    return GeneralisationOutcome(
        fires=selection.count,
        sampled=len(held_out),
        examples=selection.matched[:SAMPLE_SIZE],
    )


def regress(rule: Rule, history: MatchHistory, profile, policy: Policy) -> RegressionOutcome:
    """Replay the rule against real history and report the delta.

    Deliberately runs **without** policy enforcement on the profile: a rule
    asking for more than policy allows must still be measurable, or the refusal
    could not say what the rule would have done.
    """
    from .tiers import run as run_tiers

    suppressed = _suppressed_by(rule, history.group_records)
    after = run_tiers(
        history.anchors,
        [r for r in history.group_records if r.record_id not in suppressed],
        _apply(rule, profile),
        ProofTier.P0_ARITHMETIC,
    )

    before_ids = history.matched_anchor_ids()
    after_by_anchor = {m.anchor_id: m for m in after.matches}
    after_ids = set(after_by_anchor)

    added = sorted(after_ids - before_ids)
    unverifiable = [
        anchor_id
        for anchor_id in added
        if not verify(after_by_anchor[anchor_id].proof, history.records, policy).proven
    ]

    payload = "|".join(
        [history.digest(), rule.ref, policy.ref, str(_tolerance_asked_for(rule) or "")]
    )
    return RegressionOutcome(
        ran_at=datetime.now(UTC),
        policy_ref=policy.ref,
        rule_ref=rule.ref,
        matches_checked=len(history.matches),
        broken=sorted(before_ids - after_ids),
        added=added,
        unverifiable=unverifiable,
        exceptions_cleared=len(added),
        evidence_hash=hashlib.sha256(payload.encode()).hexdigest(),
        unmodelled=_unmodelled(rule),
    )


def evaluate(
    rule: Rule,
    outcome: RegressionOutcome,
    policy: Policy,
    taxonomy: TaxonomyRegistry | None = None,
    held_out: list[Record] | None = None,
    induced_on: list[Record] | None = None,
) -> Decision:
    """Judge a measured outcome against policy. Returns every reason it found
    rather than the first — an approver deciding whether to override needs the
    whole picture, not the earliest objection.

    The taxonomy joins the judgement at P11. A rule keyed on an exception code
    is a rule that acts on a *category*, so the category has to be one somebody
    ratified — otherwise a code minted this morning acquires power through the
    side door of a rule that mentions it.
    """
    reasons: list[str] = []

    if taxonomy is not None:
        for predicate in rule.when:
            if predicate.field != "code":
                continue
            for value in (
                predicate.value if isinstance(predicate.value, list) else [predicate.value]
            ):
                try:
                    taxonomy.check_may_fire_rule(value)
                except TaxonomyViolation as exc:
                    reasons.append(str(exc))

    if rule.profile != policy.profile:
        reasons.append(
            f"rule targets profile {rule.profile!r}; policy {policy.ref} governs {policy.profile!r}"
        )

    asked = _tolerance_asked_for(rule)
    if asked is not None and not policy.permits_tolerance(asked):
        reasons.append(
            f"rule asks for tolerance {asked}, above the ceiling "
            f"{policy.tolerance_ceiling} in {policy.ref}"
        )

    if outcome.broken:
        reasons.append(
            f"{len(outcome.broken)} historical match(es) would break: {outcome.broken[:3]}"
        )

    if len(outcome.added) > policy.max_added_matches:
        reasons.append(
            f"{len(outcome.added)} matches added, over the cap of "
            f"{policy.max_added_matches} in {policy.ref}"
        )

    if outcome.unmodelled:
        reasons.append(
            f"the regression could not model {outcome.unmodelled} — its delta is "
            f"absent, not zero, and a rule whose effect nobody measured cannot be "
            f"shown to be safe"
        )

    if induced_on is not None:
        source = generalises(rule, induced_on)
        if source.fires < MIN_HELD_OUT_FIRINGS:
            reasons.append(
                f"the rule fires on 0/{source.sampled} rows of the batch it was "
                f"induced from — it does not implement the resolution it came from, "
                f"whatever it reads like"
            )

    if held_out is not None:
        general = generalises(rule, held_out)
        if not general.generalises:
            reasons.append(
                f"refused as a correction, not a rule: {general.summary()}. A rule "
                f"that fires only on the rows it was induced from breaks no history "
                f"and adds exactly what it was written to add, so the regression "
                f"cannot see it"
            )

    if outcome.unverifiable:
        reasons.append(
            f"{len(outcome.unverifiable)} added match(es) do not verify under "
            f"{policy.ref}: {outcome.unverifiable[:3]}"
        )

    return Decision(allowed=not reasons, reasons=reasons)


def promote(
    rule: Rule,
    outcome: RegressionOutcome,
    policy: Policy,
    actor: str,
    journal: object | None = None,
    taxonomy: TaxonomyRegistry | None = None,
    held_out: list[Record] | None = None,
    induced_on: list[Record] | None = None,
) -> Rule:
    """Promote, or refuse and say why.

    Raises rather than returning a flag: a caller able to ignore a boolean would
    be granting its own permission, which is the failure this whole layer exists
    to close.

    The refusal is written to the journal *before* the raise. `R-EVIL` being
    turned away is the most interesting thing that happens in a governed system,
    and a log that records only what succeeded is a marketing document.
    """
    if not actor or not actor.strip():
        raise PolicyViolation("a promotion must name who granted it")

    decision = evaluate(rule, outcome, policy, taxonomy, held_out, induced_on)
    if not decision.allowed:
        _record(
            journal,
            EventKind.PROPOSAL_REFUSED,
            actor=actor,
            outcome="refused",
            input_hash=outcome.evidence_hash,
            policy_ref=policy.ref,
            payload=ProposalRefusedPayload(
                subject=rule.ref, proposal_kind="rule", reasons=list(decision.reasons)
            ),
        )
        raise PolicyViolation(f"refused to promote {rule.ref}: " + "; ".join(decision.reasons))

    promoted = rule.model_copy(
        update={
            "status": RuleStatus.PROMOTED,
            "promotion": PromotionEvent(
                promoted_by=actor,
                promoted_at=datetime.now(UTC),
                policy_ref=policy.ref,
                evidence_hash=outcome.evidence_hash,
                matches_checked=outcome.matches_checked,
                matches_broken=len(outcome.broken),
                matches_added=len(outcome.added),
                exceptions_cleared=outcome.exceptions_cleared,
                sample_added=outcome.added[:SAMPLE_SIZE],
            ),
        }
    )
    _record(
        journal,
        EventKind.RULE_PROMOTED,
        actor=actor,
        outcome="promoted",
        input_hash=outcome.evidence_hash,
        policy_ref=policy.ref,
        payload=RulePromotedPayload(
            rule_ref=rule.ref,
            evidence_hash=outcome.evidence_hash,
            matches_checked=outcome.matches_checked,
            matches_broken=len(outcome.broken),
            matches_added=len(outcome.added),
            sample_added=outcome.added[:SAMPLE_SIZE],
        ),
    )
    return promoted


def verify_promotion(rule: Rule, history: MatchHistory, profile, policy: Policy) -> bool:
    """Re-derive a promotion from the history it claims to rest on.

    The same propose/verify shape as a match proof: the event is a claim, and
    replaying the regression is how it is checked. A promotion whose hash or
    counts do not reproduce is not a promotion.
    """
    event = rule.promotion
    if event is None:
        return False
    fresh = regress(rule, history, profile, policy)
    return (
        event.evidence_hash == fresh.evidence_hash
        and event.matches_added == len(fresh.added)
        and event.matches_broken == len(fresh.broken)
        and event.policy_ref == policy.ref
    )
