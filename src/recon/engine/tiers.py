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
from dataclasses import dataclass, field
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
from .blocking import CandidateSet
from .completeness import CompletenessReport, audit
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
) -> Proof:
    group_total = sum((r.amount for r in group), ZERO)
    return Proof(
        proof_id=f"PRF-{match_id}",
        match_id=match_id,
        tier=tier,
        provenance=provenance,
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
        declared_gap=(
            "intake for one or more sources was not independently verified"
            if provenance is ProofTier.P3_DECLARED
            else None
        ),
    )


def run(
    anchors: list[Record],
    group_records: list[Record],
    profile: MatchProfile,
    provenance: ProofTier = ProofTier.P0_ARITHMETIC,
    candidates: CandidateSet | None = None,
    policy: Policy | None = None,
) -> MatchRun:
    """T0 then T1. A group already claimed by an earlier tier is not offered to
    a later one — a group can back exactly one anchor.

    When `candidates` is supplied it bounds **both** tiers, not just the
    expensive one. Letting T0 reach outside the candidate set would make the
    reported blocking recall a number about T1 rather than about the system,
    and the invariant it serves is that a pair dropped at blocking is
    unrecoverable downstream.
    """
    if policy is not None:
        # Before a single match is attempted. A profile whose signs disagree with
        # policy would otherwise produce matches the verifier then refutes — the
        # right outcome reached the expensive way, and only if someone looks.
        policy.check_profile(profile)

    grouped, ungrouped = _groups_of(group_records)
    claimed: set[str] = set()
    matches: list[Match] = []
    unmatched: list[Record] = []

    def attempt(anchor: Record, tier: MatchTier) -> bool:
        allowed = candidates.groups_for(anchor.record_id) if candidates else None
        if tier is MatchTier.T0_EXACT:
            ref = _exact_ref(anchor, grouped)
            viable = [ref] if ref and ref not in claimed else []
        else:
            viable = _tolerant(anchor, grouped, claimed, profile, allowed)
        if allowed is not None:
            viable = [ref for ref in viable if ref in allowed]

        if len(viable) != 1:
            return False

        group_ref = viable[0]
        group = grouped[group_ref]
        budget = ToleranceBudget(allowed=profile.tolerance.absolute)
        residual = _residual(anchor, group, profile)
        if tier is MatchTier.T0_EXACT:
            if residual != ZERO:
                return False
        elif not budget.consume(residual):
            return False

        match_id = f"M-{len(matches) + 1:05d}"
        matches.append(
            Match(
                match_id=match_id,
                tier=tier,
                anchor_id=anchor.record_id,
                group_ref=group_ref,
                group_ids=sorted(r.record_id for r in group),
                proof=_build_proof(match_id, tier, anchor, group, profile, budget, provenance),
            )
        )
        claimed.add(group_ref)
        return True

    for tier in (MatchTier.T0_EXACT, MatchTier.T1_TOLERANT):
        pending = unmatched if unmatched else list(anchors)
        unmatched = [a for a in pending if not attempt(a, tier)]

    ungrouped_pool = [r for r in group_records if not r.group_ref]
    unmatched, exceptions = _subset_pass(unmatched, ungrouped_pool, profile, provenance, matches)

    unclaimed = sorted(set(grouped) - claimed)
    _disposition_pass(unmatched, unclaimed, grouped, exceptions)

    return MatchRun(
        profile=profile.name,
        matches=matches,
        unmatched_anchors=[a.record_id for a in unmatched],
        unmatched_groups=unclaimed,
        ungrouped_records=ungrouped,
        candidates=candidates,
        exceptions=exceptions,
        completeness=audit(
            anchors=anchors,
            group_records=group_records,
            matched_anchor_ids=[m.anchor_id for m in matches],
            matched_record_ids=[rid for m in matches for rid in m.group_ids],
            exceptions=exceptions,
        ),
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
