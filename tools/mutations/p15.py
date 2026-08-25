"""Mutations for promotion running in band.

Both restore states measured on 2026-08-25: a rule approved under
`some-other-policy@v99` acting under `settlement-in@v1`, and a promoted suppress
rule taking a close from 20 matches to 19 with `ok=True` and nothing flagged.
"""

TARGETS = [
    "tests/property/test_promotion_in_band.py",
    "tests/property/test_rule_effects.py",
]

MUTATIONS = [
    (
        "a stale approval acts again",
        "src/recon/engine/promotion.py",
        """    if event.policy_ref != policy.ref:""",
        """    if False:""",
    ),
    (
        "a promoted rule named by nobody acts again",
        "src/recon/engine/promotion.py",
        """    if event is None:
        reasons.append("promoted with no promotion event — nobody is named")
        return reasons""",
        """    if event is None:
        return reasons""",
    ),
    (
        "a revoked rule acts again",
        "src/recon/engine/promotion.py",
        """    if rule.revoked_at is not None:""",
        """    if False:""",
    ),
    (
        "admissibility stops being checked at all",
        "src/recon/close.py",
        """        reasons = admissible(rule, request.policy)""",
        """        reasons = []""",
    ),
    (
        "an inadmissible rule is dropped without a word",
        "src/recon/close.py",
        """        if reasons:
            inadmissible[rule.rule_id] = reasons""",
        """        if reasons:
            pass""",
    ),
    (
        "a match destroyed by a rule stops being detected",
        "src/recon/engine/promotion.py",
        """    return sorted(before - after)""",
        """    return []""",
    ),
    (
        "the in-band regression stops running",
        "src/recon/close.py",
        """        unruled = match_and_verify(_dc.replace(request, rules=()))
        broken = broken_by_rules(unruled.matches, staged.matches)""",
        """        broken = []""",
    ),
    (
        "invariant 5 becomes advisory at close time",
        "src/recon/close.py",
        """        ok=complete and not ledger.blocked and not broken,""",
        """        ok=complete and not ledger.blocked,""",
    ),
]
