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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from ..contracts import Policy, PolicyViolation, ProofTier, Record, TaxonomyRegistry
from ..contracts.event import EventKind, ProposalRefusedPayload, RulePromotedPayload
from ..contracts.rule import ActionKind, PromotionEvent, Rule, RuleStatus
from ..contracts.taxonomy import TaxonomyViolation
from .verifier import verify

ZERO = Decimal("0.00")

SAMPLE_SIZE = 5

#: Action kinds `regress` can actually simulate. Anything else comes back with
#: no delta — and `0 broken, 0 added` reads as "safe" when it means
#: "unmeasured". That is CLAUDE.md's "an unmeasured thing reported as zero",
#: inside the one gate that exists to stop unsafe rules, so `evaluate` refuses
#: rather than letting the silence pass for a clean bill.
#:
#: Two of these were absent until the regression grew a second dimension.
#:
#: `normalize_key` was always match-shaped — rewriting a key changes what is
#: comparable, which changes matches — and the regression simply never applied
#: it. Refusing was safe and left a fifth of the action vocabulary decorative.
#:
#: `book_to` genuinely is not match-shaped: it changes where money posts, not
#: which rows pair. A match-delta regression has nothing to say about it, so
#: `regress` now also diffs the *journal* — the same rule replayed through the
#: posting layer, before and after.
MODELLED_ACTIONS = frozenset(
    {"set_tolerance", "suppress", "raise_advisory", "normalize_key", "book_to"}
)

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

    exceptions: list[object] = field(default_factory=list)
    """What that close could not commit. Needed to replay the posting layer: a
    `book_to` rule acts on exceptions, so without them there is nothing to
    reroute and the delta is reported *absent* rather than zero."""

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
    """Exceptions raised before the rule and not after, both sides measured by
    the same run under the same profile. It was `len(added)` until 2026-08-24:
    a field named for exceptions that had never counted one, aliased to the
    added-match count and printed in the record a human reads before
    approving."""

    advisories_applied: int = 0
    """Exceptions a `raise_advisory` rule re-coded. Zero from a rule that raises
    one means it landed on nothing — the no-op that scored clean."""

    value_suppressed: Decimal = ZERO
    """Net amount on the rows a `SUPPRESS` rule removes from the close.

    The dimension that let a strictly harmful rule through. The gate measured
    matches broken, matches added and postings moved, and a suppression that
    deleted a real discrepancy scored as a clean win on all three: the anchor it
    unblocked became an added match, nothing broke, and the finding it destroyed
    was named by no dimension. Measured on the *records*, so it does not depend
    on anyone having raised an exception for them yet."""

    evidence_hash: str = ""
    postings: PostingDelta | None = None
    """`None` means the posting layer was not replayed — no taxonomy or no
    exceptions were supplied. Distinct from an empty delta, which means it *was*
    replayed and nothing moved. Absent is not zero."""

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
    """The rule's effect on the matching configuration.

    Delegates, so the widening the regression measures is by construction the
    widening the close performs. These were two implementations until the close
    grew the ability to apply a rule at all — at which point the second one
    would have been free to disagree with the first.
    """
    from .rulestore import tolerance_for

    return tolerance_for([rule], profile)


def _unmodelled(rule: Rule) -> list[str]:
    return sorted({a.kind.value for a in rule.then if a.kind.value not in MODELLED_ACTIONS})


def _normalized_by(rule: Rule, records: list[Record]) -> list[Record]:
    """Apply the rule's key rewrites before matching. See `rulestore.normalize`."""
    from .rulestore import normalize

    return normalize([rule], records)


def _booking_overrides(rule: Rule, history: MatchHistory) -> dict[str, object]:
    """Which exceptions a `book_to` rule reroutes. See `rulestore.booking_overrides`."""
    from .rulestore import booking_overrides

    return booking_overrides([rule], list(history.exceptions), history.records)


def _posting_delta(rule: Rule, history: MatchHistory, taxonomy) -> PostingDelta | None:
    """Replay the posting layer with and without the rule, and diff."""
    if taxonomy is None or not history.exceptions:
        return None
    from ..ledger.posting_rules import entries_for

    def run(overrides):
        entries, _ = entries_for(
            matches=[],
            exceptions=list(history.exceptions),
            records=history.records,
            anchor_side="bank",
            taxonomy=taxonomy,
            overrides=overrides,
        )
        return {e.entry_id: e for e in entries}

    overrides = _booking_overrides(rule, history)
    before, after = run(None), run(overrides)

    def credit_role(entry):
        return next((p.role for p in entry.postings if p.amount < 0), None)

    rerouted, moved = [], Decimal("0.00")
    for entry_id, entry in before.items():
        other = after.get(entry_id)
        if other is None or credit_role(entry) == credit_role(other):
            continue
        rerouted.append(entry_id)
        moved += abs(sum((p.amount for p in entry.postings if p.amount > 0), Decimal("0.00")))

    def tally(entries):
        counts: dict[str, int] = {}
        for entry in entries.values():
            role = credit_role(entry)
            if role is not None:
                counts[role.value] = counts.get(role.value, 0) + 1
        return dict(sorted(counts.items()))

    return PostingDelta(
        rerouted=sorted(rerouted), value_moved=moved, before=tally(before), after=tally(after)
    )


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
class PostingDelta:
    """What a rule does to the books, measured by replaying the posting layer.

    A match-delta regression reports `0 broken, 0 added` for a rule that reroutes
    every rupee in the close, because no row pairs differently. This is the
    dimension that sees it.
    """

    rerouted: list[str] = field(default_factory=list)
    """Entry ids whose credit account changed."""

    value_moved: Decimal = Decimal("0.00")
    """Total value that changed account. The number an approver needs: `3
    entries rerouted` says nothing about whether it was ₹30 or ₹3,000,000."""

    before: dict[str, int] = field(default_factory=dict)
    after: dict[str, int] = field(default_factory=dict)

    @property
    def moved(self) -> bool:
        return bool(self.rerouted)

    def summary(self) -> str:
        if not self.moved:
            return "no entry changed account"
        return (
            f"{len(self.rerouted)} entr(ies) rerouted, ₹{self.value_moved} moved: "
            f"{self.before} -> {self.after}"
        )


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


def regress(
    rule: Rule, history: MatchHistory, profile, policy: Policy, taxonomy=None
) -> RegressionOutcome:
    """Replay the rule against real history and report the delta.

    Deliberately runs **without** policy enforcement on the profile: a rule
    asking for more than policy allows must still be measurable, or the refusal
    could not say what the rule would have done.
    """
    from . import rulestore
    from .tiers import _advise
    from .tiers import run as run_tiers

    suppressed = _suppressed_by(rule, history.group_records)
    # Was: filter the suppressed rows out by hand, then run the tiers over what
    # was left. That produced proofs claiming `P0 ARITHMETIC` over a group with
    # rows missing — the exact laundered shape the verifier learned to refuse in
    # 7.0.0, and the regression was manufacturing it. Handing the rule to the
    # engine instead means the simulation runs the same code a close runs, and
    # the proofs it judges carry the provenance a close would have given them.
    after = run_tiers(
        history.anchors,
        history.group_records,
        profile,
        ProofTier.P0_ARITHMETIC,
        rules=[rule],
        simulate=True,
    )
    # Like for like. `history.exceptions` came out of a full close — policy,
    # candidate bounding, declared scope — and `after` is a bare tier run, so
    # differencing the two counted the configuration as well as the rule and
    # reported -1 exceptions cleared for a rule that cleared one.
    baseline = run_tiers(history.anchors, history.group_records, profile, ProofTier.P0_ARITHMETIC)

    # `raise_advisory` was declared modelled and simulated nowhere, so a rule
    # using it came back 0 broken / 0 added / nothing suppressed and promoted
    # without an objection while doing nothing whatsoever.
    advised = _advise(
        after.exceptions,
        rulestore.apply(
            [rule], history.group_records, profile=profile.name, simulate=True
        ).advisories,
    )
    advisories_applied = sum(
        1 for was, now in zip(after.exceptions, advised, strict=True) if was.code != now.code
    )

    before_ids = history.matched_anchor_ids()
    after_by_anchor = {m.anchor_id: m for m in after.matches}
    after_ids = set(after_by_anchor)

    added = sorted(after_ids - before_ids)
    unverifiable = [
        anchor_id
        for anchor_id in added
        if not verify(
            after_by_anchor[anchor_id].proof,
            history.records,
            policy,
            bundle=[rule],
        ).proven
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
        exceptions_cleared=len(baseline.exceptions) - len(after.exceptions),
        advisories_applied=advisories_applied,
        value_suppressed=sum(
            (r.amount for r in history.group_records if r.record_id in suppressed), ZERO
        ),
        evidence_hash=hashlib.sha256(payload.encode()).hexdigest(),
        unmodelled=_unmodelled(rule),
        postings=_posting_delta(rule, history, taxonomy),
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

    for action in rule.then:
        if action.kind is ActionKind.BOOK_TO:
            from ..ledger.accounts import AccountRole

            try:
                AccountRole(action.target)
            except ValueError:
                # A closed vocabulary, like every other thing a proposal may
                # name. `book_to: "Assets:Offshore:Slush"` is a spec error, not
                # a posting — and refusing it here means the posting layer never
                # has to know a rule exists.
                reasons.append(
                    f"book_to names {action.target!r}, which is not an account role. "
                    f"Known: {sorted(r.value for r in AccountRole)}"
                )

    from .rulestore import APPLIED_ACTIONS

    inert = sorted({a.kind.value for a in rule.then} - {k.value for k in APPLIED_ACTIONS})
    if inert:
        # Two lists have to be satisfied, not one. `MODELLED_ACTIONS` says the
        # regression can *measure* an action; `APPLIED_ACTIONS` says a close can
        # *perform* it. Only the first was checked, so `set_tolerance`, `book_to`
        # and `normalize_key` promoted on a clean regression and then did
        # nothing — the close reported them `unapplied` and no one was reading.
        reasons.append(
            f"acts by {', '.join(inert)}, which a close does not perform. The "
            f"regression can measure it and nothing carries it out, so promoting "
            f"it would grant a permission with no effect"
        )

    advisory_targets = [a.target for a in rule.then if a.kind is ActionKind.RAISE_ADVISORY]
    if advisory_targets:
        if outcome.advisories_applied == 0:
            # The no-op that scored better than any real rule: clean on broken,
            # added, value and postings, because it did nothing on all four.
            reasons.append(
                "raises an advisory that re-codes no exception. A rule whose only "
                "effect lands on nothing is not a safe rule, it is an unmeasured one"
            )
        for target in advisory_targets:
            if not target:
                reasons.append("raise_advisory names no code — there is nothing to say")
            elif taxonomy is not None and target not in taxonomy:
                reasons.append(f"raise_advisory names {target!r}, which is not in the registry")
            elif taxonomy is not None and not taxonomy[target].authority.may_fire_rule:
                # P11: naming grants nothing. A code may label from birth and
                # fire a rule only once a human has promoted it with a written
                # definition.
                reasons.append(
                    f"raise_advisory names {target!r}, which is {taxonomy[target].status.value} "
                    f"— a code fires a rule only once promoted"
                )

    if outcome.value_suppressed != ZERO:
        # The gap a strictly harmful rule walked through on 2026-08-24. A model
        # rule suppressed a duplicated export row, unblocked its payout, and
        # scored 0 broken / 1 added / no postings moved — clean on every
        # dimension the gate had. Measured against the labels it added a false
        # match and destroyed a planted E06 worth the exact amount it removed.
        #
        # Refused on tier, not on outcome. "This row is spurious" is a claim
        # about the counterparty's data that the raw records cannot settle —
        # they contain the row. A rule asserting it is `P1 RULE` provenance on
        # something only a named human can attest, so the honest answer is that
        # value leaves a close over someone's signature or not at all. Dropping
        # rows that carry no value needs no signature and is unaffected.
        reasons.append(
            f"suppresses {outcome.value_suppressed} of value. Removing money from a "
            f"close is an attested act, not a rule's own authority: raw records "
            f"cannot prove a row is spurious — they contain it. Raise the finding "
            f"and let a named human accept it (P2), or suppress only zero-value rows"
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
        # Breadth is measured HERE, on the reference population, and never on
        # `induced_on`. That is the whole correction: a denominator the rule
        # author can pad is a denominator that measures the padding.
        if general.generalises and not policy.permits_reference_selectivity(
            general.fires, general.sampled
        ):
            share = Decimal(general.fires) / Decimal(general.sampled)
            reasons.append(
                f"over-broad: fires on {general.fires}/{general.sampled} reference "
                f"rows ({share:.1%}), above the "
                f"{Decimal(policy.max_reference_selectivity):.0%} cap in {policy.ref}. "
                f"A rule that fires on everything is not a rule"
            )
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
                postings_moved=(
                    outcome.postings.summary() if outcome.postings is not None else None
                ),
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
