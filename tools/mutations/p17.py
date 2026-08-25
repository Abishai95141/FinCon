"""Mutations for the declarative strategy pipeline.

The sequence was a literal tuple inside `tiers.run`. These restore that, and the
ways a pipeline can look declarative while deciding nothing.
"""

TARGETS = [
    "tests/property/test_strategy_pipeline.py",
    "tests/property/test_metamorphic.py",
    "tests/gates/gate_p3.py",
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
        """        if tier is MatchTier.T0_EXACT:
            if residual != ZERO:
                return False""",
        """        if tier is MatchTier.T0_EXACT:
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
