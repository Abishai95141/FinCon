"""The deterministic arm: T0 exact + T1 tolerant, every match proof-carrying.

A match here counts only if the independent verifier re-derives it from the
Records. `run` refuses to report a match whose proof is refuted — a match rate
that includes unverified matches is the number this project exists not to
publish.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from pathlib import Path

from recon.contracts import Policy, ProofTier, Record
from recon.contracts.rule import Rule
from recon.engine.tiers import MatchProfile

from . import ArmResult


def run(
    bank: list[tuple[str, Record]],
    settlement: list[tuple[str, Record]],
    profile: MatchProfile,
    policy: Policy,
    provenance: ProofTier = ProofTier.P0_ARITHMETIC,
    out_of_scope: Mapping[str, str] | None = None,
    rules: list[Rule] | None = None,
) -> ArmResult:
    """The deterministic arm, as an adapter over the product's matching stage.

    This used to call `run_tiers` and then verify every match itself, which was a
    second implementation of matching-and-verification sitting beside the one a
    real close used. They agreed by inspection. `recon.close.match_and_verify` is
    now the only one, and this function is what the benchmark wraps around it —
    a driving adapter, in the shape the scorecard wants.

    The stage builds its own candidate set from the loop's `BlockingPolicy`, and
    that set travels back on `ArmResult.candidates` so the runner can report the
    narrowing that actually happened.

    This used to take a `candidates` argument and ignore it, on the stated
    grounds that "the stage builds its own from the same `BlockingPolicy`, so an
    arm cannot hand in a wider or narrower one". The premise was false — the
    runner built its with a bare `BlockingPolicy()` and no counterparty key, so
    it was wider — and a parameter nothing reads cannot be what keeps the two
    honest. Removed, so there is one candidate set and nowhere to disagree.
    """
    from recon.close import CloseRequest, match_and_verify

    staged = match_and_verify(
        CloseRequest(
            run_id="arm",
            anchors=bank,
            groups=settlement,
            profile=profile,
            policy=policy,
            taxonomy=None,  # matching raises exceptions; only posting reads the registry
            chart=None,
            period=(date.min, date.max),
            opened_on=date.min,
            journal_path=Path("/dev/null"),
            provenance=provenance,
            out_of_scope=out_of_scope or {},
            rules=list(rules or []),
        )
    )
    outcome = staged.run
    external = staged.external_of
    kept = staged.matches
    refusals = staged.rejected
    refuted = staged.refuted
    tiers = staged.tiers
    proofs = [m.proof for m in kept]
    pairs = {external[m.anchor_id]: frozenset(external[r] for r in m.group_ids) for m in kept}

    exceptions = outcome.exceptions
    notes = [
        f"tiers: {tiers or 'none'}",
        *(
            ["exceptions raised: " + ", ".join(f"{e.code} ₹{e.amount}" for e in exceptions)]
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
        candidates=outcome.candidates,
        completeness=outcome.completeness,
        scope=outcome.scope,
        matches=kept,
        rejected=refusals,
        run=outcome,
    )
