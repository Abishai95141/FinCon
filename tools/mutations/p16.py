"""Mutations for the consistency pass — `E02`, the last uncovered planted defect.

Every one restores a state the detector passed through while being built,
including the order-dependence the metamorphic suite caught after it already
produced the right answer on both batches.
"""

TARGETS = [
    "tests/property/test_consistency.py",
    "tests/property/test_metamorphic.py",
    "tests/gates/gate_p11.py",
]

MUTATIONS = [
    (
        "the consistency pass stops running",
        "src/recon/engine/tiers.py",
        """    _consistency_pass(group_records, profile, policy, exceptions)""",
        """    pass""",
    ),
    (
        "the inferred rate goes back to depending on row order",
        "src/recon/engine/consistency.py",
        """    window = sorted(rows, key=lambda t: (t[0], t[1], t[2].record_id))[:SAMPLE]""",
        """    window = rows[:SAMPLE]""",
    ),
    (
        "the threshold is ignored, so rounding becomes a finding",
        "src/recon/engine/consistency.py",
        """        if not off or variance <= tolerance:""",
        """        if not off:""",
    ),
    (
        "the threshold comes from the data instead of policy",
        "src/recon/engine/tiers.py",
        """    for finding in consistency.find(records, spec, tolerance=Decimal(policy.consistency_tolerance)):""",
        """    for finding in consistency.find(records, spec, tolerance=Decimal("0.00")):""",
    ),
    (
        "a handful of rows is treated as a population",
        "src/recon/engine/consistency.py",
        """        if len(rows) < spec.minimum_peers:""",
        """        if False:""",
    ),
    (
        "the majority offset is replaced by the first one seen",
        "src/recon/engine/consistency.py",
        """        fixed, agreeing = offsets.most_common(1)[0]""",
        """        fixed, agreeing = next(iter(offsets.items()))""",
    ),
    (
        "the finding stops carrying the relation it was measured against",
        "src/recon/engine/consistency.py",
        """            self.relation.summary(),""",
        """            "",""",
    ),
    (
        "the variance is reported as a row count rather than an amount",
        "src/recon/engine/consistency.py",
        """                variance=variance,""",
        """                variance=Decimal(len(off)),""",
    ),
]
