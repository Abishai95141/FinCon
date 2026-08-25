"""Match tiers T0 (exact) and T1 (tolerant).

T2 subset-sum is P5; groups the source did not declare are left untouched here
and fall to the exception queue, which is the honest outcome for a tier that
cannot address them.

The rule that keeps the false-match rate down is in `_tolerant`: when more than
one group could absorb a bank credit, the matcher **refuses** rather than
picking. An arbitrary pick would raise the headline match rate and corrupt the
books, which is the trade this project exists to refuse.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal

from ..contracts import (
    ExceptionCode,
    MatchTier,
    Policy,
    Proof,
    ProofLeg,
    ProofTier,
    ReconException,
    Record,
)
from ..contracts.rule import Rule
from . import consistency, rulestore, strategies
from .blocking import CandidateSet
from .completeness import CompletenessReport, audit
from .consistency import RelationSpec
from .subsetsum import Outcome, SolverBounds, solve
from .tolerance import ToleranceBudget, TolerancePolicy

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class MatchProfile:
    """Everything domain-specific about one reconciliation loop.

    The engine reads this; it never hardcodes a side name, a key name or a sign
    (CLAUDE.md invariant 7).
    """

    name: str
    anchor_side: str
    """The side iterated one record at a time — typically the bank."""
    group_side: str
    """The side whose records form the other leg, grouped by `group_ref`."""
    side_signs: dict[str, int]
    tolerance: TolerancePolicy = field(default_factory=TolerancePolicy)
    counterparty_key: str = "gateway"
    """Key that must agree before two records are considered comparable."""
    cohesion_key: str | None = None
    """Key whose equal values must move together in a subset — a fee and the
    charge it was levied on. Passed through to the solver; naming it here keeps
    the engine domain-agnostic."""
    strategies: tuple[str, ...] = ("exact", "tolerant", "subset_sum")
    """The ways this loop may match, in the order it tries them.

    Was a literal tuple inside `run`, so adding a fourth needed an engine edit —
    which made invariant 7 true of field names and false of behaviour. Resolved
    against a closed registry before a close begins; an unknown name is a
    profile error, never an execution (ADR-001)."""

    consistency: RelationSpec | None = None
    """A relation this loop's rows are expected to follow, if it has one — a fee
    against the charge it was levied on, per counterparty. Declared here because
    the engine must not know what a fee is (invariant 7); `engine.consistency`
    reads it and knows only "subject", "base" and "peer"."""

    solver_bounds: SolverBounds = field(default_factory=SolverBounds)

    def __post_init__(self) -> None:
        # The validator MatchProfile never had. A zero sign makes every residual
        # zero and every match verify — audit finding F2 — and nothing here
        # checked. Policy is still the authority; this stops an obviously broken
        # proposal earlier and with a clearer message.
        bad = {side: sign for side, sign in self.side_signs.items() if sign not in (1, -1)}
        if bad:
            raise ValueError(f"profile {self.name!r}: side signs must be +1 or -1, got {bad}")
        if self.anchor_side not in self.side_signs:
            raise ValueError(f"profile {self.name!r}: anchor side {self.anchor_side!r} has no sign")
        if self.group_side not in self.side_signs:
            raise ValueError(f"profile {self.name!r}: group side {self.group_side!r} has no sign")


@dataclass(frozen=True)
class Match:
    match_id: str
    tier: MatchTier
    anchor_id: str
    group_ref: str
    group_ids: list[str]
    proof: Proof


@dataclass(frozen=True)
class MatchRun:
    profile: str
    matches: list[Match]
    unmatched_anchors: list[str]
    unmatched_groups: list[str]
    ungrouped_records: list[str]
    """Records the source gave no grouping for. T0/T1 cannot reach them, so T2
    reconstructs the grouping by subset-sum."""

    exceptions: list[ReconException] = field(default_factory=list)
    """Everything the run could not commit, and why. E09 for ambiguity, E13 for
    a compute bound, E14 where the engine has no explanation to offer. Never a
    silent non-match — see invariant 8."""

    completeness: CompletenessReport | None = None
    """Invariant 8, computed by set arithmetic over inputs and outputs rather
    than by asking this function whether it handled everything."""

    scope: dict[str, str] = field(default_factory=dict)
    """Every exclusion this run actually made — the caller's, plus whatever a
    promoted rule suppressed. Downstream reads *this*, never the mapping it
    passed in: those two diverged the moment rules could exclude a row, and the
    decision log went on describing the caller's copy. Two answers to one
    question, and the control over the stale one goes quietly dead."""

    rules_unapplied: dict[str, list[str]] = field(default_factory=dict)
    """Actions a promoted rule carries that a close does not perform. Absent,
    not zero: a rule half-applied must not read as a rule applied."""

    rule_effects: dict[str, object] = field(default_factory=dict)
    """`rulestore.RuleEffect` per rule — what each one actually moved in this
    run. A rule with no observable effect is a finding, not a silent pass."""

    candidates: CandidateSet | None = None
    """The candidate set the tiers were restricted to, when one was supplied.
    Carried so a scorecard can print its recall beside the match rate."""

    def by_tier(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for m in self.matches:
            counts[m.tier.value] += 1
        return dict(counts)


def _groups_of(records: list[Record]) -> tuple[dict[str, list[Record]], list[str]]:
    grouped: dict[str, list[Record]] = defaultdict(list)
    ungrouped: list[str] = []
    for record in records:
        if record.group_ref:
            grouped[record.group_ref].append(record)
        else:
            ungrouped.append(record.record_id)
    return dict(grouped), ungrouped


def _residual(anchor: Record, group: list[Record], profile: MatchProfile) -> Decimal:
    anchor_sign = profile.side_signs[anchor.side]
    group_sign = profile.side_signs[profile.group_side]
    total = sum((r.amount for r in group), ZERO)
    return anchor_sign * anchor.amount + group_sign * total


def _build_proof(
    match_id: str,
    tier: MatchTier,
    anchor: Record,
    group: list[Record],
    profile: MatchProfile,
    budget: ToleranceBudget,
    provenance: ProofTier,
    rule: Rule | None = None,
    bundle_digest: str | None = None,
    declared: Decimal | None = None,
) -> Proof:
    group_total = sum((r.amount for r in group), ZERO)
    return Proof(
        proof_id=f"PRF-{match_id}",
        match_id=match_id,
        tier=tier,
        provenance=ProofTier.P3_DECLARED if declared is not None else provenance,
        rule_bundle_digest=bundle_digest,
        rule_id=rule.rule_id if rule is not None else None,
        rule_version=rule.version if rule is not None else None,
        legs=[
            ProofLeg(side=anchor.side, record_ids=[anchor.record_id], subtotal=anchor.amount),
            ProofLeg(
                side=profile.group_side,
                record_ids=sorted(r.record_id for r in group),
                subtotal=group_total,
            ),
        ],
        residual=_residual(anchor, group, profile),
        tolerance_allowed=budget.allowed,
        tolerance_used=budget.used,
        declared_amount=declared,
        declared_gap=(
            f"{declared} of this payout never arrived; the remainder stays "
            f"receivable and in the unreconciled total"
            if declared is not None
            else "intake for one or more sources was not independently verified"
            if provenance is ProofTier.P3_DECLARED
            else None
        ),
    )


def _advise(
    exceptions: list[ReconException], advisories: list[rulestore.Advisory]
) -> tuple[list[ReconException], dict[str, int]]:
    """Let a promoted rule say what an exception *is*.

    `E14` is the absence of an explanation — `P3 DECLARED`, nobody vouched for
    it. A promoted rule that recognises the shape supplies one, and the label
    becomes `P1 RULE`: weaker than a derivation, stronger than a default.

    The ladder does the guarding, so there is no list of which codes may be
    overwritten. `E09` came out of an enumeration that found two valid subsets —
    `P0 ARITHMETIC` — and a rule does not get to talk over an answer the engine
    proved. That is `outranks`, and it is the same check triage runs on a model
    proposal, for the same reason.
    """
    applied: dict[str, int] = {}
    if not advisories:
        return exceptions, applied
    out: list[ReconException] = []
    for exception in exceptions:
        touching = [
            a for a in advisories if a.code and not set(exception.record_ids).isdisjoint(a.records)
        ]
        if not touching or exception.code_provenance.outranks(ProofTier.P1_RULE):
            out.append(exception)
            continue
        # Deterministic, and not by the order the caller happened to pass the
        # rules in. Two advisories can touch one exception — found the first time
        # a close ran two of them — and `touching[0]` meant the answer depended
        # on list order, which is a worse property than arbitrary. The loser is
        # visible either way: its `RuleEffect` records no observable effect,
        # which is exactly the signal A3 exists to produce.
        advisory = min(touching, key=lambda a: a.rule_id)
        applied[advisory.rule_id] = applied.get(advisory.rule_id, 0) + 1
        out.append(
            exception.model_copy(
                update={
                    "code": advisory.code,
                    "code_provenance": ProofTier.P1_RULE,
                    "evidence": [
                        *exception.evidence,
                        f"{advisory.rule_id}@v{advisory.rule_version}: {advisory.reason}",
                    ],
                }
            )
        )
    return out, applied


def _provenance_for(
    group_ref: str, applied: rulestore.Applied, base: ProofTier
) -> tuple[ProofTier, Rule | None]:
    """A group a rule reshaped cannot claim the tier of one it did not.

    The residual closes to zero either way; what differs is whose word the zero
    rests on. `P0 ARITHMETIC` says a third party re-deriving from raw records
    reaches this. After a suppression they do not — they reach it from the raw
    records *and* the rule. That is exactly `P1 RULE`, and the ladder is only
    worth having if the difference is recorded rather than rounded away.
    """
    rule = applied.ruled_groups.get(group_ref)
    if rule is None:
        return base, None
    # The weaker of the two. An unverified-intake close is already P3; a rule
    # firing inside it does not promote it to P1.
    tier = ProofTier.P1_RULE if base.outranks(ProofTier.P1_RULE) else base
    return tier, (rule if tier is ProofTier.P1_RULE else None)


def run(
    anchors: list[Record],
    group_records: list[Record],
    profile: MatchProfile,
    provenance: ProofTier = ProofTier.P0_ARITHMETIC,
    candidates: CandidateSet | None = None,
    policy: Policy | None = None,
    out_of_scope: Mapping[str, str] | None = None,
    rules: list[Rule] | None = None,
    simulate: bool = False,
) -> MatchRun:
    """T0 then T1. A group already claimed by an earlier tier is not offered to
    a later one — a group can back exactly one anchor.

    When `candidates` is supplied it bounds **both** tiers, not just the
    expensive one. Letting T0 reach outside the candidate set would make the
    reported blocking recall a number about T1 rather than about the system,
    and the invariant it serves is that a pair dropped at blocking is
    unrecoverable downstream.

    `out_of_scope` maps record id -> reason. Those records are not matched and
    raise no exception, but they are still audited, so an exclusion is a
    *disposition* rather than a disappearance. It exists because the alternative
    — callers filtering their inputs before handing them over — puts the filter
    upstream of the accountability boundary, where invariant 8 cannot see it.
    `audit` refuses a blank reason, so this cannot be used to drop something
    quietly.
    """
    if policy is not None:
        # Before a single match is attempted. A profile whose signs disagree with
        # policy would otherwise produce matches the verifier then refutes — the
        # right outcome reached the expensive way, and only if someone looks.
        policy.check_profile(profile)

    scope = dict(out_of_scope or {})
    # A promoted rule acts here or nowhere. Merging its suppressions into the
    # same `scope` the caller uses means a rule cannot remove a row by a route
    # the completeness audit does not walk — invariant 8 sees a rule's effect on
    # exactly the terms it sees an operator's.
    active = list(rules or [])
    applied = rulestore.apply(active, group_records, profile=profile.name, simulate=simulate)
    digest = rulestore.bundle_digest(active)
    scope.update(applied.scope)
    # The remaining two match-affecting actions, in the order the regression
    # measures them: suppression removes rows, then key rewrites change what is
    # comparable among the rows that are left.
    profile = rulestore.tolerance_for(active, profile)
    # Normalise every row, including the suppressed ones. Pre-filtering here
    # removed them from `group_records` outright, so the completeness audit at
    # the end of this function never saw them and invariant 8 had nothing to
    # dispose of — a silent drop with extra steps, which is the exact thing
    # `out_of_scope` exists to prevent. Exclusion from *matching* already
    # happens below, where `scope` is applied and the audit can still see it.
    group_records = rulestore.normalize(active, group_records)
    in_scope_anchors = [a for a in anchors if a.record_id not in scope]
    grouped, ungrouped = _groups_of([r for r in group_records if r.record_id not in scope])
    claimed: set[str] = set()
    declared_gaps: dict[str, tuple[str, Decimal, str]] = {}
    matches: list[Match] = []
    unmatched: list[Record] = []

    def attempt(anchor: Record, strategy_name: str) -> bool:
        allowed = candidates.groups_for(anchor.record_id) if candidates else None
        # A claimed group is not offered again: a group backs exactly one anchor,
        # and re-offering a claimed one is how a match count starts exceeding the
        # number of payouts.
        offer = strategies.Offer(
            anchor=anchor,
            available={ref: g for ref, g in grouped.items() if ref not in claimed},
            allowed=allowed,
            profile=profile,
            residual=lambda a, g: _residual(a, list(g), profile),
        )
        proposal = strategies.STRATEGIES[strategy_name](offer)
        if proposal is None:
            return False

        group_ref, tier = proposal.group_ref, proposal.tier
        group = grouped[group_ref]
        budget = ToleranceBudget(allowed=profile.tolerance.absolute)
        residual = _residual(anchor, group, profile)
        # The budget is spent here rather than inside the strategy: a strategy
        # that could both propose a match and decide what it cost would be
        # marking its own homework, and the tier split is a headline number.
        if proposal.declared is not None:
            # A residual stated instead of spent. It does not touch the budget —
            # a tolerance wide enough to swallow a partial payment is wide enough
            # to swallow a theft — and it must equal the residual the records
            # give, or the proof would be declaring a number of its own choosing.
            if abs(residual) != proposal.declared:
                return False
            declared_gaps[anchor.record_id] = (group_ref, proposal.declared, proposal.code or "")
        elif tier is MatchTier.T0_EXACT:
            if residual != ZERO:
                return False
        elif not budget.consume(residual):
            return False

        match_id = f"M-{len(matches) + 1:05d}"
        tier_for_group = _provenance_for(group_ref, applied, provenance)
        matches.append(
            Match(
                match_id=match_id,
                tier=tier,
                anchor_id=anchor.record_id,
                group_ref=group_ref,
                group_ids=sorted(r.record_id for r in group),
                proof=_build_proof(
                    match_id,
                    tier,
                    anchor,
                    group,
                    profile,
                    budget,
                    *tier_for_group,
                    bundle_digest=digest,
                    declared=proposal.declared,
                ),
            )
        )
        claimed.add(group_ref)
        return True

    # The sequence the profile declared, in the order it declared it. This was a
    # literal tuple inside this function: correct, and invisible to anything that
    # might want a fourth way of matching.
    sequence = strategies.resolve(profile.strategies)
    exceptions: list[ReconException] = []
    ungrouped_pool = [r for r in group_records if not r.group_ref and r.record_id not in scope]
    for name in sequence:
        if name in strategies.POOL_STRATEGIES:
            unmatched, raised = _subset_pass(
                unmatched or list(in_scope_anchors),
                ungrouped_pool,
                profile,
                provenance,
                digest,
                matches,
            )
            exceptions.extend(raised)
            continue
        pending = unmatched if unmatched else list(in_scope_anchors)
        unmatched = [a for a in pending if not attempt(a, name)]

    unclaimed = sorted(set(grouped) - claimed)
    _disposition_pass(unmatched, unclaimed, grouped, exceptions)
    _declared_gap_pass(declared_gaps, grouped, {a.record_id: a for a in anchors}, exceptions)
    _consistency_pass(group_records, profile, policy, exceptions)
    exceptions, advised = _advise(exceptions, applied.advisories)
    # The effect a rule had on *this* close, recorded where it happened. A
    # rule that fires and changes nothing is the failure this project keeps
    # rediscovering, and it is invisible unless someone counts.
    effects = {
        rid: replace(eff, advisories_applied=advised.get(rid, 0))
        for rid, eff in applied.effects.items()
    }

    return MatchRun(
        profile=profile.name,
        matches=matches,
        unmatched_anchors=[a.record_id for a in unmatched],
        unmatched_groups=unclaimed,
        ungrouped_records=ungrouped,
        candidates=candidates,
        exceptions=exceptions,
        scope=scope,
        rules_unapplied=applied.unapplied,
        rule_effects=effects,
        completeness=audit(
            anchors=anchors,
            group_records=group_records,
            matched_anchor_ids=[m.anchor_id for m in matches],
            matched_record_ids=[rid for m in matches for rid in m.group_ids],
            exceptions=exceptions,
            out_of_scope=scope,
        ),
    )


def _declared_gap_pass(
    gaps: dict[str, tuple[str, Decimal, str]],
    grouped: dict[str, list[Record]],
    records: dict[str, Record],
    exceptions: list[ReconException],
) -> None:
    """Every residual a strategy stated instead of spending becomes an open item.

    The match records that the payout is identified and the money that arrived
    is reconciled; this records that the rest is still owed. Both are true, and
    a system that kept only the first would have laundered a loss into a clean
    close.
    """
    for anchor_id, (group_ref, amount, code) in sorted(gaps.items()):
        anchor = records[anchor_id]
        exceptions.append(
            ReconException(
                exception_id=f"EXC-{len(exceptions) + 1:05d}",
                code=code,
                code_provenance=ProofTier.P0_ARITHMETIC,
                as_of=anchor.posted_on,
                amount=amount,
                record_ids=sorted([anchor_id, *(r.record_id for r in grouped.get(group_ref, []))]),
                hypothesis=(
                    f"the credit is {amount} short of {group_ref}; the reference is "
                    f"unambiguous, so the payout is identified and the remainder unpaid"
                ),
                evidence=[
                    anchor.lineage,
                    f"credit {anchor.amount}",
                    f"group {group_ref} of {len(grouped.get(group_ref, []))} row(s)",
                ],
            )
        )


def _consistency_pass(
    records: list[Record],
    profile: MatchProfile,
    policy: Policy | None,
    exceptions: list[ReconException],
) -> None:
    """Rows that disagree with their own population, raised as `E02`.

    Matching cannot see this. A payout whose fees were billed on different terms
    still sums to what the bank paid, so it reconciles perfectly and the variance
    goes out the door — which is exactly the case a controller most wants raised
    and the one the tiers are structurally blind to.

    `E02` is *fee variance*, not "above contract tier". Without the contract,
    which of the two rates was agreed is unknowable and the majority is not
    automatically right; the finding states the disagreement and its size.
    """
    spec = profile.consistency
    if spec is None or policy is None:
        return
    for finding in consistency.find(records, spec, tolerance=Decimal(policy.consistency_tolerance)):
        rows = [r for r in records if r.record_id in set(finding.record_ids)]
        exceptions.append(
            ReconException(
                exception_id=f"EXC-{len(exceptions) + 1:05d}",
                code=ExceptionCode.E02_FEE_VARIANCE,
                code_provenance=ProofTier.P0_ARITHMETIC,
                as_of=max(r.posted_on for r in rows),
                amount=finding.variance,
                record_ids=sorted(finding.record_ids),
                hypothesis=(
                    f"{len(finding.record_ids)} row(s) do not follow the relation the "
                    f"other {finding.relation.agreeing} rows of {finding.peer!r} follow"
                ),
                evidence=finding.evidence(),
            )
        )


def _disposition_pass(
    unmatched: list[Record],
    unclaimed_groups: list[str],
    grouped: dict[str, list[Record]],
    exceptions: list[ReconException],
) -> None:
    """Invariant 8's teeth. Anything the tiers left over gets an `E14` naming
    the facts the engine actually has.

    `E14` rather than a guess: the engine knows an anchor did not match and what
    it is worth, but not *why*. Force-fitting it into `E06` or `E01` would put a
    guess where there are only facts, and rules key on codes — a wrong code
    routes the item to the wrong owner and may fire the wrong rule. Triage
    classifies it later; the engine states what it saw.
    """
    seen = {rid for exc in exceptions for rid in exc.record_ids}
    seen |= {rid for exc in exceptions for s in (exc.alternatives or []) for rid in s}

    for anchor in unmatched:
        if anchor.record_id in seen:
            continue
        exceptions.append(
            ReconException(
                exception_id=f"EXC-{len(exceptions) + 1:05d}",
                code=ExceptionCode.E14_UNEXPLAINED,
                as_of=anchor.posted_on,
                amount=abs(anchor.amount),
                record_ids=[anchor.record_id],
                hypothesis="no strategy produced a match and the engine cannot say why",
                evidence=[anchor.lineage, f"amount {anchor.amount}"],
                blocks_close=True,
            )
        )

    for group_ref in unclaimed_groups:
        rows = grouped[group_ref]
        row_ids = sorted(r.record_id for r in rows)
        if all(rid in seen for rid in row_ids):
            continue
        total = sum((r.amount for r in rows), ZERO)
        exceptions.append(
            ReconException(
                exception_id=f"EXC-{len(exceptions) + 1:05d}",
                code=ExceptionCode.E14_UNEXPLAINED,
                as_of=max(r.posted_on for r in rows),
                amount=abs(total),
                record_ids=row_ids,
                hypothesis=f"group {group_ref!r} was not claimed by any anchor in this period",
                evidence=[f"{len(rows)} row(s)", f"total {total}"],
                blocks_close=True,
            )
        )


def _subset_pass(
    anchors: list[Record],
    pool: list[Record],
    profile: MatchProfile,
    provenance: ProofTier,
    _bundle: str | None,
    matches: list[Match],
) -> tuple[list[Record], list[ReconException]]:
    """T2: reconstruct which rows back a credit when the source declared no
    grouping.

    Commits only on a proven-unique subset. Everything else becomes an
    exception that names why — an ambiguity (E09, a finding about the data) or
    a compute bound (E13, a finding about us). A capacity limit reported as a
    data finding would be the worst failure this module can produce.
    """
    exceptions: list[ReconException] = []
    still: list[Record] = []
    consumed: set[str] = set()
    anchor_sign = profile.side_signs[profile.anchor_side]
    group_sign = profile.side_signs[profile.group_side]

    for anchor in anchors:
        available = [r for r in pool if r.record_id not in consumed]
        if not available:
            still.append(anchor)
            continue

        target = Decimal(-anchor_sign) * anchor.amount / Decimal(group_sign)
        result = solve(
            target,
            available,
            profile.tolerance.absolute,
            profile.solver_bounds,
            profile.cohesion_key,
        )

        def raise_exception(
            code: ExceptionCode,
            note: str,
            alternatives: list[list[str]] | None = None,
            *,
            # Bound explicitly rather than closed over: a closure capturing the
            # loop variable reads whatever the loop has moved on to, which is
            # correct only by accident of being called immediately.
            subject: Record = anchor,
            evidence: str = result.summary(),
        ) -> None:
            exceptions.append(
                ReconException(
                    exception_id=f"EXC-{len(exceptions) + 1:05d}",
                    code=code,
                    # The solver *derived* this label — it enumerated the
                    # subsets, or it measured the bound it hit. That is
                    # arithmetic a third party can re-run, so it outranks any
                    # proposal and `reclassifiable` refuses to offer it.
                    code_provenance=ProofTier.P0_ARITHMETIC,
                    as_of=subject.posted_on,
                    amount=abs(subject.amount),
                    record_ids=[subject.record_id],
                    hypothesis=note,
                    evidence=[subject.lineage, evidence],
                    alternatives=alternatives,
                    blocks_close=True,
                )
            )

        if result.outcome is Outcome.UNIQUE:
            group = [r for r in available if r.record_id in set(result.solutions[0])]
            budget = ToleranceBudget(allowed=profile.tolerance.absolute)
            budget.consume(_residual(anchor, group, profile))
            match_id = f"M-{len(matches) + 1:05d}"
            matches.append(
                Match(
                    match_id=match_id,
                    tier=MatchTier.T2_SUBSET_SUM,
                    anchor_id=anchor.record_id,
                    group_ref=f"inferred:{match_id}",
                    group_ids=sorted(r.record_id for r in group),
                    proof=_build_proof(
                        match_id,
                        MatchTier.T2_SUBSET_SUM,
                        anchor,
                        group,
                        profile,
                        budget,
                        provenance,
                        bundle_digest=_bundle,
                    ),
                )
            )
            consumed.update(r.record_id for r in group)
            continue

        if result.outcome is Outcome.AMBIGUOUS:
            raise_exception(
                ExceptionCode.E09_NETTING_AMBIGUITY,
                f"{len(result.solutions)} distinct subsets sum to this credit "
                f"within tolerance; no unique answer exists",
                alternatives=result.solutions,
            )
        elif result.is_capacity_limit:
            raise_exception(
                ExceptionCode.E13_SOLVER_TIMEOUT,
                f"search stopped at a compute bound ({result.bound_hit}) — "
                f"uniqueness was not established, so this is a limit of ours "
                f"and not a finding about the data",
            )
        still.append(anchor)

    return still, exceptions


def _exact_ref(anchor: Record, grouped: dict[str, list[Record]]) -> str | None:
    """T0: the anchor names the group outright. `reference` is whatever the
    adapter extracted; an exact hit is the only thing that counts here — a
    truncated reference is T1's problem."""
    ref = anchor.source_row_id
    return ref if ref in grouped else None


def _tolerant(
    anchor: Record,
    grouped: dict[str, list[Record]],
    claimed: set[str],
    profile: MatchProfile,
    allowed: set[str] | None = None,
) -> list[str]:
    """T1: no usable reference. Comparable counterparty, a date inside the
    window, and a residual the budget could absorb.

    Returns every candidate, including when there is more than one. `run`
    refuses on anything but a single candidate — reporting the ambiguity rather
    than resolving it arbitrarily.
    """
    want = anchor.keys.get(profile.counterparty_key)
    candidates: list[str] = []
    for group_ref, group in sorted(grouped.items()):
        if group_ref in claimed:
            continue
        if allowed is not None and group_ref not in allowed:
            continue
        if want is not None:
            same = {r.keys.get(profile.counterparty_key) for r in group}
            if same != {want}:
                continue
        if not any(profile.tolerance.within_window(anchor.posted_on, r.posted_on) for r in group):
            continue
        if abs(_residual(anchor, group, profile)) <= profile.tolerance.absolute:
            candidates.append(group_ref)
    return candidates
