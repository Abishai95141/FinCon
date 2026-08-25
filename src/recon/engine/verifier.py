"""Independent proof verification.

**This file must never trust the proof, and must never take its policy from
the caller.** The P5 audit found both. `tolerance_allowed` was read out of the
proof being verified (`F1`), and the sign convention came in as an argument the
only production call site filled from `profile.side_signs` — the config an agent
would author (`F2`). Both now come from a `Policy`: versioned, frozen, approved
by a named human, and not something a proposer supplies.

**This file must never trust the proof.** `Proof.residual` and every
`ProofLeg.subtotal` are claims made by whatever produced the match. The verifier
fetches the Records by id, recomputes the subtotals and the residual from those
Records, and compares. A verifier that reads the stored residual and checks it
against the stored tolerance would pass every test in this repository and prove
nothing at all — it is the single most tempting shallow proxy here, which is why
`Proof.closes()` deliberately does not verify and says so.

The sign convention comes from `side_signs`, supplied by the caller alongside the
records — never from the proof. A proof that could choose its own signs could
make any set of numbers close.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from ..contracts import Policy, PolicyViolation, Proof, ProofTier, Record
from ..contracts.rule import ActionKind, Rule
from .rules import fires_on

ZERO = Decimal("0.00")


class VerdictKind(StrEnum):
    PROVEN = "proven"
    REFUTED = "refuted"


@dataclass(frozen=True)
class Verdict:
    kind: VerdictKind
    recomputed_residual: Decimal | None
    reasons: list[str] = field(default_factory=list)
    policy_ref: str | None = None
    """Which policy judged this. A verdict that cannot name its policy cannot be
    reproduced once the policy changes."""

    @property
    def proven(self) -> bool:
        return self.kind is VerdictKind.PROVEN

    def __str__(self) -> str:
        head = f"{self.kind.value.upper()}"
        if self.recomputed_residual is not None:
            head += f" residual={self.recomputed_residual}"
        return head + ("" if not self.reasons else " :: " + "; ".join(self.reasons))


def _refuted(
    reasons: list[str], residual: Decimal | None = None, policy_ref: str | None = None
) -> Verdict:
    return Verdict(VerdictKind.REFUTED, residual, reasons, policy_ref)


def verify(
    proof: Proof,
    records: Mapping[str, Record],
    policy: Policy,
    *,
    bundle: Sequence[Rule] = (),
    declared_scope: Iterable[str] = (),
) -> Verdict:
    """Re-derive the match from the records and report whether it holds.

    `records` must be the same records a third party would fetch — the verifier
    is meant to be runnable by someone who does not trust us and holds only the
    source files, the policy, and this function.

    `bundle` is the promoted rule set, supplied separately for the same reason
    `policy` is: it is not something the proposer may hand in with its proof.
    `declared_scope` is the close's own out-of-scope dispositions, which are part
    of the *input* the close ran on — a checker is given `x`, and refusing to
    look at `x` is what made a laundered tier verifiable.
    """
    ref = policy.ref
    reasons: list[str] = []

    # Every referenced record must exist. A proof citing a record nobody can
    # fetch is unverifiable, which is refuted, not "probably fine".
    missing = [rid for rid in proof.record_ids() if rid not in records]
    if missing:
        return _refuted(
            [f"{len(missing)} referenced record(s) not found: {missing[:5]}"], None, ref
        )

    # A proof may claim any tolerance it likes; policy decides whether it had
    # that much to spend. Checked before the arithmetic so a forged ceiling
    # cannot launder a residual (audit F1).
    if not policy.permits_tolerance(proof.tolerance_allowed):
        reasons.append(
            f"proof claims tolerance {proof.tolerance_allowed}, above the "
            f"ceiling {policy.tolerance_ceiling} in {ref}"
        )
    effective = min(proof.tolerance_allowed, policy.tolerance_ceiling)

    # No record may appear in two legs — double-counting closes a residual that
    # should not close.
    seen: dict[str, str] = {}
    for leg in proof.legs:
        for rid in leg.record_ids:
            if rid in seen:
                reasons.append(f"record {rid} appears in both {seen[rid]!r} and {leg.side!r}")
            seen[rid] = leg.side

    recomputed_total = ZERO
    for leg in proof.legs:
        try:
            sign = policy.sign_for(leg.side)
        except PolicyViolation as exc:
            return _refuted([str(exc)], None, ref)

        actual = sum((records[rid].amount for rid in leg.record_ids), ZERO)
        if actual != leg.subtotal:
            reasons.append(
                f"leg {leg.side!r}: claimed subtotal {leg.subtotal} but its "
                f"{len(leg.record_ids)} record(s) sum to {actual} "
                f"(delta {actual - leg.subtotal})"
            )

        # Recompute from the records, not from the claimed subtotal — otherwise
        # a lying subtotal would be laundered into the residual.
        recomputed_total += sign * actual

        off_side = [rid for rid in leg.record_ids if records[rid].side != leg.side]
        if off_side:
            reasons.append(f"leg {leg.side!r} contains records from another side: {off_side[:3]}")

    declared = proof.declared_amount
    if declared is not None:
        # A residual the proof states instead of absorbing. It is checked, not
        # trusted: it must equal the residual these records actually give, to the
        # paisa. That is what stops "declared" from becoming a way to wave any
        # difference through — and the number has to become an open item and stay
        # in the unreconciled total, which the ledger's balance assertion is what
        # enforces, not this function.
        if proof.provenance is not ProofTier.P3_DECLARED:
            reasons.append(
                f"declares a residual of {declared} at {proof.provenance.value}; only "
                f"{ProofTier.P3_DECLARED.value} may carry one"
            )
        if abs(recomputed_total) != declared:
            reasons.append(
                f"declares a gap of {declared} but the records give "
                f"{abs(recomputed_total)} — a declared residual that does not match "
                f"the arithmetic is a number of the proof's own choosing"
            )
        if proof.tolerance_used != ZERO:
            reasons.append(
                f"declares a gap and also spent {proof.tolerance_used} of tolerance; "
                f"a gap is stated or absorbed, never both"
            )
    elif abs(recomputed_total) > effective:
        reasons.append(
            f"recomputed residual {recomputed_total} exceeds the effective "
            f"tolerance {effective} (proof claimed {proof.tolerance_allowed}, "
            f"ceiling {policy.tolerance_ceiling})"
        )

    reasons += _rule_dependency(proof, records, bundle, declared_scope)

    if recomputed_total != proof.residual:
        reasons.append(
            f"claimed residual {proof.residual} but the records give "
            f"{recomputed_total} (delta {recomputed_total - proof.residual})"
        )

    if declared is None and abs(recomputed_total) > proof.tolerance_used:
        # Skipped for a declared gap, where spending nothing is the point: the
        # residual was stated and is becoming an open item, not absorbed. The
        # equality check above is what holds a declared proof honest.
        reasons.append(
            f"tolerance_used {proof.tolerance_used} understates the actual "
            f"residual {abs(recomputed_total)}"
        )

    if reasons:
        return _refuted(reasons, recomputed_total, ref)
    return Verdict(VerdictKind.PROVEN, recomputed_total, policy_ref=ref)


def verify_all(
    proofs: list[Proof],
    records: Mapping[str, Record],
    policy: Policy,
) -> dict[str, Verdict]:
    return {p.proof_id: verify(p, records, policy) for p in proofs}


def _rule_dependency(
    proof: Proof,
    records: Mapping[str, Record],
    bundle: Sequence[Rule],
    declared_scope: Iterable[str],
) -> list[str]:
    """Whether the *provenance* this proof claims survives re-derivation.

    Everything above checks arithmetic, and arithmetic was never the hole. After
    a rule suppresses a row the legs hold only what was kept, so the sum is
    honestly zero and the claim is under-determined — the witness never carried
    what the rule removed. Measured on 2026-08-25: a `P1 RULE` proof relabelled
    `P0 ARITHMETIC` verified, and so did one citing a rule that did not exist.

    So the exclusion is **derived, not read**. The population comes from
    `records`, the effect comes from re-running the cited rule, and nothing here
    consults a field the producer could have written. An earlier draft rebuilt
    the population from the proof's own legs plus a claimed exclusion list, and
    a witness that under-reported its exclusions was then checked against an
    input that already had them removed — audit finding `F1` exactly, a check
    reading its input from the artifact it checks.
    """
    cited = {rid for leg in proof.legs for rid in leg.record_ids}
    groups = {records[r].group_ref for r in cited if r in records and records[r].group_ref}
    if not groups:
        # T2 reconstructs its group by subset-sum out of ungrouped rows, so there
        # is no declared population to be missing from. Nothing to say.
        return []

    population = [r for r in records.values() if r.group_ref in groups]
    missing = {r.record_id for r in population} - cited
    unexplained = missing - set(declared_scope)

    if proof.provenance is ProofTier.P0_ARITHMETIC:
        if unexplained:
            return [
                f"claims {ProofTier.P0_ARITHMETIC.value} but {len(unexplained)} record(s) of "
                f"group {sorted(groups)} are absent from the legs and from the close's declared "
                f"scope: {sorted(unexplained)[:3]}. A third party re-deriving from raw records "
                f"does not reach this residual"
            ]
        return []

    if proof.provenance is not ProofTier.P1_RULE:
        return []

    if not proof.rule_id:
        return [f"claims {ProofTier.P1_RULE.value} but names no rule"]
    cited_rule = next((r for r in bundle if r.rule_id == proof.rule_id), None)
    if cited_rule is None:
        return [
            f"cites rule {proof.rule_id!r}, which is not in the bundle supplied to this "
            f"verification ({len(bundle)} rule(s))"
        ]
    if not any(a.kind is ActionKind.SUPPRESS for a in cited_rule.then):
        # A rule that removes nothing cannot be what removed these rows.
        return (
            []
            if not unexplained
            else [
                f"cites {proof.rule_id!r}, which suppresses nothing, yet "
                f"{len(unexplained)} record(s) are missing from the legs"
            ]
        )

    fired = {r.record_id for r in population if fires_on(cited_rule, r)} - set(declared_scope)
    if fired != unexplained:
        return [
            f"re-running {proof.rule_id!r} over group {sorted(groups)} excludes "
            f"{len(fired)} record(s), but {len(unexplained)} are missing from the legs "
            f"— the rule does not account for the partition this proof claims"
        ]
    return []
