"""Mutations for the rule-application controls. See tools/mutate.py.

Every one of these was live in the codebase at some point on 2026-08-24. They
are here because the promotion gate spent four phases deciding whether to grant
a permission nothing exercised, and the first time a rule actually acted it was
strictly harmful.
"""

TARGETS = [
    "tests/property/test_rule_application.py",
    "tests/property/test_identity.py",
    "tests/gates/gate_p8.py",
]

MUTATIONS = [
    (
        "removing value from a close stops being refused",
        "src/recon/engine/promotion.py",
        """    if outcome.value_suppressed != ZERO:""",
        """    if False:""",
    ),
    (
        "value suppressed is never measured — the state before the fix",
        "src/recon/engine/promotion.py",
        """        value_suppressed=sum(
            (r.amount for r in history.group_records if r.record_id in suppressed), ZERO
        ),""",
        """        value_suppressed=ZERO,""",
    ),
    (
        "exceptions_cleared goes back to aliasing the added-match count",
        "src/recon/engine/promotion.py",
        """        exceptions_cleared=len(baseline.exceptions) - len(after.exceptions),""",
        """        exceptions_cleared=len(added),""",
    ),
    (
        "a rule-assisted match claims P0 ARITHMETIC",
        "src/recon/engine/tiers.py",
        """    tier = ProofTier.P1_RULE if base.outranks(ProofTier.P1_RULE) else base
    return tier, (rule if tier is ProofTier.P1_RULE else None)""",
        """    return base, None""",
    ),
    (
        "an unpromoted rule is allowed to act",
        "src/recon/engine/rulestore.py",
        """        if rule.status is not RuleStatus.PROMOTED or rule.revoked_at is not None:""",
        """        if False:""",
    ),
    (
        "a rule's suppressions never reach the close's scope",
        "src/recon/engine/tiers.py",
        """    scope.update(applied.scope)""",
        """    pass""",
    ),
    (
        "the decision log goes back to the caller's copy of scope",
        "bench/run.py",
        """        scope=ours.scope,""",
        """        scope=sides.scope,""",
    ),
]
