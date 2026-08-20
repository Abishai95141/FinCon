"""The deterministic arm: T0 exact + T1 tolerant, every match proof-carrying.

A match here counts only if the independent verifier re-derives it from the
Records. `run` refuses to report a match whose proof is refuted — a match rate
that includes unverified matches is the number this project exists not to
publish.
"""

from __future__ import annotations

from recon.contracts import ProofTier, Record
from recon.engine.blocking import CandidateSet
from recon.engine.tiers import MatchProfile
from recon.engine.tiers import run as run_tiers
from recon.engine.verifier import verify

from . import ArmResult


def run(
    bank: list[tuple[str, Record]],
    settlement: list[tuple[str, Record]],
    profile: MatchProfile,
    provenance: ProofTier = ProofTier.P0_ARITHMETIC,
    candidates: CandidateSet | None = None,
) -> ArmResult:
    anchors = [rec for _, rec in bank]
    group_records = [rec for _, rec in settlement]
    outcome = run_tiers(anchors, group_records, profile, provenance, candidates)

    records = {rec.record_id: rec for _, rec in bank + settlement}
    external = {rec.record_id: ext for ext, rec in bank + settlement}

    pairs: dict[str, frozenset[str]] = {}
    proofs = []
    refuted: list[str] = []

    for match in outcome.matches:
        verdict = verify(match.proof, records, profile.side_signs)
        if not verdict.proven:
            # An unverified match is not a match. Recorded so the count of
            # rejections is visible rather than silently absorbed.
            refuted.append(f"{match.match_id}: {verdict}")
            continue
        pairs[external[match.anchor_id]] = frozenset(external[r] for r in match.group_ids)
        proofs.append(match.proof)

    notes = [
        f"tiers: {outcome.by_tier() or 'none'}",
        *([outcome.candidates.summary()] if outcome.candidates else ["no blocking — exhaustive"]),
        f"{len(outcome.ungrouped_records)} record(s) the source left ungrouped "
        f"— unreachable by T0/T1, deferred to subset-sum at P5",
    ]
    if refuted:
        notes.append(f"{len(refuted)} match(es) refused by the verifier: {refuted[:3]}")

    return ArmResult(name="deterministic", pairs=pairs, proofs=proofs, notes=notes)
