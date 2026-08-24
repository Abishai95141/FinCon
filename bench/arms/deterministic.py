"""The deterministic arm: T0 exact + T1 tolerant, every match proof-carrying.

A match here counts only if the independent verifier re-derives it from the
Records. `run` refuses to report a match whose proof is refuted — a match rate
that includes unverified matches is the number this project exists not to
publish.
"""

from __future__ import annotations

from collections.abc import Mapping

from recon.contracts import Policy, ProofTier, Record
from recon.engine.blocking import CandidateSet
from recon.engine.tiers import MatchProfile
from recon.engine.tiers import run as run_tiers
from recon.engine.verifier import verify

from . import ArmResult


def run(
    bank: list[tuple[str, Record]],
    settlement: list[tuple[str, Record]],
    profile: MatchProfile,
    policy: Policy,
    provenance: ProofTier = ProofTier.P0_ARITHMETIC,
    candidates: CandidateSet | None = None,
    out_of_scope: Mapping[str, str] | None = None,
) -> ArmResult:
    anchors = [rec for _, rec in bank]
    group_records = [rec for _, rec in settlement]
    outcome = run_tiers(
        anchors, group_records, profile, provenance, candidates, policy, out_of_scope
    )

    records = {rec.record_id: rec for _, rec in bank + settlement}
    external = {rec.record_id: ext for ext, rec in bank + settlement}

    pairs: dict[str, frozenset[str]] = {}
    proofs = []
    refuted: list[str] = []
    # The split of what we *report*, not of what the tiers produced. A match the
    # verifier refused must leave both numbers together, or the scorecard would
    # decompose a count it does not have.
    tiers: dict[str, int] = {}

    for match in outcome.matches:
        verdict = verify(match.proof, records, policy)
        if not verdict.proven:
            # An unverified match is not a match. Recorded so the count of
            # rejections is visible rather than silently absorbed.
            refuted.append(f"{match.match_id}: {verdict}")
            continue
        pairs[external[match.anchor_id]] = frozenset(external[r] for r in match.group_ids)
        proofs.append(match.proof)
        tiers[match.tier.value] = tiers.get(match.tier.value, 0) + 1

    exceptions = outcome.exceptions
    notes = [
        f"tiers: {tiers or 'none'}",
        *(
            ["exceptions raised: " + ", ".join(f"{e.code.value} ₹{e.amount}" for e in exceptions)]
            if exceptions
            else []
        ),
        *([outcome.candidates.summary()] if outcome.candidates else ["no blocking — exhaustive"]),
        f"{len(outcome.ungrouped_records)} record(s) the source left ungrouped "
        f"— unreachable by T0/T1, reconstructed by T2 subset-sum",
    ]
    if refuted:
        notes.append(f"{len(refuted)} match(es) refused by the verifier: {refuted[:3]}")

    return ArmResult(
        name="deterministic",
        pairs=pairs,
        proofs=proofs,
        tiers=tiers,
        notes=notes,
        exceptions=exceptions,
        completeness=outcome.completeness,
    )
