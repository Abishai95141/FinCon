"""Independent proof verification.

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

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from ..contracts import Proof, Record

ZERO = Decimal("0.00")


class VerdictKind(StrEnum):
    PROVEN = "proven"
    REFUTED = "refuted"


@dataclass(frozen=True)
class Verdict:
    kind: VerdictKind
    recomputed_residual: Decimal | None
    reasons: list[str] = field(default_factory=list)

    @property
    def proven(self) -> bool:
        return self.kind is VerdictKind.PROVEN

    def __str__(self) -> str:
        head = f"{self.kind.value.upper()}"
        if self.recomputed_residual is not None:
            head += f" residual={self.recomputed_residual}"
        return head + ("" if not self.reasons else " :: " + "; ".join(self.reasons))


def _refuted(reasons: list[str], residual: Decimal | None = None) -> Verdict:
    return Verdict(VerdictKind.REFUTED, residual, reasons)


def verify(
    proof: Proof,
    records: Mapping[str, Record],
    side_signs: Mapping[str, int],
) -> Verdict:
    """Re-derive the match from the records and report whether it holds.

    `records` must be the same records a third party would fetch — the verifier
    is meant to be runnable by someone who does not trust us and holds only the
    source files and this function.
    """
    reasons: list[str] = []

    # Every referenced record must exist. A proof citing a record nobody can
    # fetch is unverifiable, which is refuted, not "probably fine".
    missing = [rid for rid in proof.record_ids() if rid not in records]
    if missing:
        return _refuted([f"{len(missing)} referenced record(s) not found: {missing[:5]}"])

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
        sign = side_signs.get(leg.side)
        if sign is None:
            return _refuted([f"no sign convention supplied for side {leg.side!r}"])

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

    if abs(recomputed_total) > proof.tolerance_allowed:
        reasons.append(
            f"recomputed residual {recomputed_total} exceeds the tolerance "
            f"allowed {proof.tolerance_allowed}"
        )

    if recomputed_total != proof.residual:
        reasons.append(
            f"claimed residual {proof.residual} but the records give "
            f"{recomputed_total} (delta {recomputed_total - proof.residual})"
        )

    if abs(recomputed_total) > proof.tolerance_used:
        reasons.append(
            f"tolerance_used {proof.tolerance_used} understates the actual "
            f"residual {abs(recomputed_total)}"
        )

    if reasons:
        return _refuted(reasons, recomputed_total)
    return Verdict(VerdictKind.PROVEN, recomputed_total)


def verify_all(
    proofs: list[Proof],
    records: Mapping[str, Record],
    side_signs: Mapping[str, int],
) -> dict[str, Verdict]:
    return {p.proof_id: verify(p, records, side_signs) for p in proofs}
