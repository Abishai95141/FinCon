"""Mutations for the declarative strategy pipeline.

The sequence was a literal tuple inside `tiers.run`. These restore that, and the
ways a pipeline can look declarative while deciding nothing.
"""

TARGETS = [
    "tests/property/test_strategy_pipeline.py",
    "tests/property/test_partial_payment.py",
    "tests/property/test_identity.py",
    "tests/gates/gate_p3.py",
    "tests/gates/gate_p9.py",
    "tests/known_broken.py",
]

MUTATIONS = [
    (
        "the profile's sequence is ignored for a hardcoded one",
        "src/recon/engine/tiers.py",
        """    sequence = strategies.resolve(profile.strategies)""",
        """    sequence = ["exact", "tolerant", "subset_sum"]""",
    ),
    (
        "an unknown strategy name is silently skipped instead of refused",
        "src/recon/engine/strategies.py",
        """    if unknown:""",
        """    if False:""",
    ),
    (
        "a profile declaring nothing is accepted",
        "src/recon/engine/strategies.py",
        """    if not names:""",
        """    if False:""",
    ),
    (
        "a claimed group is offered to a later strategy again",
        "src/recon/engine/tiers.py",
        """            available={ref: g for ref, g in grouped.items() if ref not in claimed},""",
        """            available=dict(grouped),""",
    ),
    (
        "T0 accepts a residual it should have left to T1",
        "src/recon/engine/tiers.py",
        """        elif tier is MatchTier.T0_EXACT:
            if residual != ZERO:
                return False""",
        """        elif tier is MatchTier.T0_EXACT:
            if False:
                return False""",
    ),
    (
        "the tolerant strategy picks the first of several viable groups",
        "src/recon/engine/strategies.py",
        """    return Proposal(found[0], MatchTier.T1_TOLERANT) if len(found) == 1 else None""",
        """    return Proposal(found[0], MatchTier.T1_TOLERANT) if found else None""",
    ),
    (
        "blocking is ignored, so a strategy reaches outside its candidate set",
        "src/recon/engine/strategies.py",
        """        if offer.allowed is not None and group_ref not in offer.allowed:""",
        """        if False:""",
    ),
]

MUTATIONS += [
    (
        "a partial payment absorbs its shortfall into tolerance",
        "src/recon/engine/tiers.py",
        """            if abs(residual) != proposal.declared:
                return False""",
        """            if False:
                return False""",
    ),
    (
        "a declared gap is not checked against the arithmetic",
        "src/recon/engine/verifier.py",
        """        if abs(recomputed_total) != declared:""",
        """        if False:""",
    ),
    (
        "any tier may declare a residual, not only P3",
        "src/recon/engine/verifier.py",
        """        if proof.provenance is not ProofTier.P3_DECLARED:""",
        """        if False:""",
    ),
    (
        "a gap is declared and absorbed at the same time",
        "src/recon/engine/verifier.py",
        """        if proof.tolerance_used != ZERO:""",
        """        if False:""",
    ),
    (
        "a duplicated row is claimed as a partial payment",
        "src/recon/engine/strategies.py",
        """    if repeated and abs(sum((r.amount for r in repeated), Decimal("0.00"))) == shortfall:
        return None""",
        """    if False:
        return None""",
    ),
    (
        "an overpayment is claimed as a partial payment",
        "src/recon/engine/strategies.py",
        """    if residual >= 0:
        return None  # not short — an overpayment is E05""",
        """    if False:
        return None""",
    ),
    (
        "the shortfall is posted against a bank that never received it",
        "src/recon/ledger/posting_rules.py",
        """        if anchor.record_id in matched_anchors:""",
        """        if False:""",
    ),
    (
        "a declared match is labelled tolerant, inflating T1",
        "src/recon/engine/strategies.py",
        """    return Proposal(ref, MatchTier.T4_DECLARED, declared=shortfall, code="E04")""",
        """    return Proposal(ref, MatchTier.T1_TOLERANT, declared=shortfall, code="E04")""",
    ),
]
