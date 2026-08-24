"""Mutations for the P12B controls. See tools/mutate.py."""

TARGETS = ["tests/gates/gate_p12b.py"]

MUTATIONS = [
    (
        "suppression stops being simulated",
        "src/recon/engine/promotion.py",
        """    if not any(a.kind is ActionKind.SUPPRESS for a in rule.then):
        return set()""",
        """    return set()
    if False:""",
    ),
    (
        "unmodelled actions are not reported",
        "src/recon/engine/promotion.py",
        """    return sorted({a.kind.value for a in rule.then if a.kind.value not in MODELLED_ACTIONS})""",
        """    return list()""",
    ),
    (
        "book_to counts as modelled",
        "src/recon/engine/promotion.py",
        """MODELLED_ACTIONS = frozenset({"set_tolerance", "suppress", "raise_advisory"})""",
        """MODELLED_ACTIONS = frozenset({"set_tolerance", "suppress", "raise_advisory", "book_to"})""",
    ),
    (
        "an unmodelled action no longer blocks promotion",
        "src/recon/engine/promotion.py",
        """    if outcome.unmodelled:""",
        """    if False:""",
    ),
    (
        "identity predicates stop being detected",
        "src/recon/engine/promotion.py",
        """IDENTITY_FIELDS = frozenset({"record_id", "source_row_id", "group_ref"})""",
        """IDENTITY_FIELDS = frozenset()""",
    ),
    (
        "generalisation ignores pinned fields",
        "src/recon/engine/promotion.py",
        """        return not self.pinned_fields and self.fires >= MIN_HELD_OUT_FIRINGS""",
        """        return self.fires >= MIN_HELD_OUT_FIRINGS""",
    ),
    (
        "held-out check is dropped",
        "src/recon/engine/promotion.py",
        """    if held_out is not None:
        general = generalises(rule, held_out)""",
        """    if False:
        general = generalises(rule, held_out)""",
    ),
    (
        "the fires-on-source check is dropped",
        "src/recon/engine/promotion.py",
        """        if source.fires < MIN_HELD_OUT_FIRINGS:""",
        """        if False:""",
    ),
    (
        "the selectivity cap is dropped",
        "src/recon/engine/promotion.py",
        """        elif source.sampled and not policy.permits_selectivity(source.fires, source.sampled):""",
        """        elif False:""",
    ),
    (
        "selectivity permits everything",
        "src/recon/contracts/policy.py",
        """        return Decimal(fires) / Decimal(sampled) <= Decimal(self.max_selectivity_pct)""",
        """        return True""",
    ),
    (
        "matches becomes a substring search",
        "src/recon/engine/rules.py",
        """        return re.fullmatch(str(expected).strip(), str(actual)[:MAX_SUBJECT]) is not None""",
        """        return re.search(str(expected).strip(), str(actual)[:MAX_SUBJECT]) is not None""",
    ),
    (
        "an invalid rule proposal is built anyway",
        "src/recon/triage/induce.py",
        """        return None, [f"proposal is not a valid Rule: {exc}"]""",
        """        return None, ["silent"]""",
    ),
    (
        "the field table is replaced by attribute lookup",
        "src/recon/engine/rules.py",
        """        return FIELDS[field](record)""",
        """        return getattr(record, field)""",
    ),
    (
        "induction is not recorded",
        "src/recon/triage/induce.py",
        """            journal.append(
                EventKind.RULE_INDUCED,""",
        """            _ = (
                EventKind.RULE_INDUCED,""",
    ),
]
