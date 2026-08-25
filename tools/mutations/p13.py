"""Mutations for A1 (one entry point) and A2 (the completed witness).

Every one of these was the live state of the code before 2026-08-25. The three
verifier mutations restore the exact holes measured in the audit: a `P1` proof
relabelled `P0` verified, and so did one citing a rule that did not exist.
"""

TARGETS = [
    "tests/property/test_witness.py",
    "tests/property/test_one_entry_point.py",
    "tests/property/test_identity.py",
]

MUTATIONS = [
    (
        "the verifier stops checking the rule dependency at all",
        "src/recon/engine/verifier.py",
        """    reasons += _rule_dependency(proof, records, bundle, declared_scope)""",
        """    reasons += []""",
    ),
    (
        "a tier laundered to P0 ARITHMETIC verifies again",
        "src/recon/engine/verifier.py",
        """    if proof.provenance is ProofTier.P0_ARITHMETIC:
        if unexplained:""",
        """    if proof.provenance is ProofTier.P0_ARITHMETIC:
        if False:""",
    ),
    (
        "a P1 proof citing a rule nobody promoted verifies again",
        "src/recon/engine/verifier.py",
        """    if cited_rule is None:""",
        """    if False:""",
    ),
    (
        "the checker trusts the rule id instead of re-running the rule",
        "src/recon/engine/verifier.py",
        """    if fired != unexplained:""",
        """    if False:""",
    ),
    (
        "the checker reads the population from the witness (audit F1, again)",
        "src/recon/engine/verifier.py",
        """    population = [r for r in records.values() if r.group_ref in groups]""",
        """    population = [records[r] for r in cited if r in records]""",
    ),
    (
        "a declared out-of-scope row is mistaken for a rule exclusion",
        "src/recon/engine/verifier.py",
        """    unexplained = missing - set(declared_scope)""",
        """    unexplained = missing""",
    ),
    (
        "proofs stop naming the bundle that produced them",
        "src/recon/engine/tiers.py",
        """        rule_bundle_digest=bundle_digest,""",
        """        rule_bundle_digest=None,""",
    ),
    (
        "the terminator goes back to committing to nothing of its own",
        "src/recon/close.py",
        """            outcome_digest=digest,""",
        """            outcome_digest="",""",
    ),
    (
        "the outcome digest stops depending on provenance",
        "src/recon/close.py",
        """                "provenance": m.proof.provenance.value,
                "rule": m.proof.rule_id,""",
        """                "provenance": "",
                "rule": None,""",
    ),
    (
        "the regression goes back to hand-filtering suppressed rows",
        "src/recon/engine/promotion.py",
        """    after = run_tiers(
        history.anchors,
        history.group_records,
        profile,
        ProofTier.P0_ARITHMETIC,
        rules=[rule],
        simulate=True,
    )""",
        """    kept = [r for r in history.group_records if r.record_id not in suppressed]
    after = run_tiers(
        history.anchors,
        _normalized_by(rule, kept),
        _apply(rule, profile),
        ProofTier.P0_ARITHMETIC,
    )""",
    ),
]
