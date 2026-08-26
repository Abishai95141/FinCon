"""Mutations for A3 (in-band rule effects) and A4 (signed authority bundles).

The A3 mutations restore the exact state four action kinds shipped in: promoted,
running, and moving nothing that anyone could see. The A4 mutations restore a
digest pin, which proves what ran and never who approved it.
"""

TARGETS = [
    "tests/property/test_rule_effects.py",
    "tests/property/test_signed_bundles.py",
    "tests/known_broken.py",
]

MUTATIONS = [
    (
        "a rule that moved nothing reads as observable",
        "src/recon/engine/rulestore.py",
        """        return bool(
            self.suppressed
            or self.advisories_applied
            or self.keys_normalized
            or self.postings_redirected
            or self.tolerance_widened
        )""",
        """        return True""",
    ),
    (
        "suppressions stop being counted as an effect",
        "src/recon/engine/rulestore.py",
        """            suppressed=sum(1 for r in records if r.record_id in fired),""",
        """            suppressed=0,""",
    ),
    (
        "advisories applied stop being counted",
        "src/recon/engine/tiers.py",
        """        applied[advisory.rule_id] = applied.get(advisory.rule_id, 0) + 1""",
        """        pass""",
    ),
    (
        "the close stops naming its inert rules",
        "src/recon/close.py",
        """    inert = [e.rule_id for e in effects if not e.observable]""",
        """    inert = []""",
    ),
    (
        "a rule acting stops reaching the decision log",
        "src/recon/close.py",
        """        for eff in effects:
            journal.append(
                EventKind.RULE_APPLIED,""",
        """        for eff in []:
            journal.append(
                EventKind.RULE_APPLIED,""",
    ),
    (
        "which advisory wins goes back to depending on list order",
        "src/recon/engine/tiers.py",
        """        advisory = min(touching, key=lambda a: a.rule_id)""",
        """        advisory = touching[0]""",
    ),
    (
        "an unpromoted rule leaves no trace of having been refused",
        "src/recon/engine/rulestore.py",
        """            effects[rule.rule_id] = RuleEffect(
                rule_id=rule.rule_id,
                rule_version=rule.version,
                fired=0,
                unapplied=tuple(unapplied[rule.rule_id]),
            )""",
        """            pass""",
    ),
    (
        "a rule inert in every close stops being findable",
        "src/recon/engine/rulestore.py",
        """    return {rid: n for rid, n in sorted(seen.items()) if rid not in moved}""",
        """    return {}""",
    ),
    (
        "a tampered bundle verifies again",
        "src/recon/trust.py",
        """        elif claimed[name] != actual[name]:""",
        """        elif False:""",
    ),
    (
        "a file added to a signed bundle is not noticed",
        "src/recon/trust.py",
        """        elif name not in claimed:""",
        """        elif False:""",
    ),
    (
        "the signature itself stops being checked",
        "src/recon/trust.py",
        """        key.verify(bytes.fromhex(manifest.get("signature", "")), _canonical(claimed))""",
        """        pass""",
    ),
    (
        "a bundle may supply the key it is verified against",
        "src/recon/trust.py",
        """    key = public_key or load_public_key()""",
        """    key = public_key or load_public_key(
        (bundle / "trusted-key.hex").read_text() if (bundle / "trusted-key.hex").exists() else None
    )""",
    ),
    (
        "an anonymous signature is accepted",
        "src/recon/trust.py",
        """    if not signed_by.strip():""",
        """    if False:""",
    ),
    (
        "the close stops recording which authority it ran under",
        "src/recon/close.py",
        """    authority = [trust.verify(b) for b in request.bundles]""",
        """    authority = []""",
    ),
]
