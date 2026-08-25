"""Mutations for the P10 controls. See tools/mutate.py."""

TARGETS = ["tests/gates/gate_p10.py"]

MUTATIONS = [
    (
        "absent arm renders a row of zeros",
        "bench/metrics.py",
        '''        if self.absent:
            return f"{self.arm:<16} {'absent — ' + self.absent}"
        return (
            f"{self.arm:<16} {self.auto_match_rate.value:>10.1%} "''',
        '''        if self.absent:
            return f"{self.arm:<16} {0.0:>10.1%} {0.0:>11.2%} {0.0:>9.1%} {0.0:>7.1%}"
        return (
            f"{self.arm:<16} {self.auto_match_rate.value:>10.1%} "''',
    ),
    (
        "absent arm answers with a number instead of raising",
        "bench/metrics.py",
        """    def _guard(self) -> None:
        if self.absent:
            raise ArmAbsent(f"{self.arm}: {self.absent}")""",
        """    def _guard(self) -> None:
        return None""",
    ),
    (
        "absence stops being exclusive of results",
        "bench/metrics.py",
        """            if self.produced or self.correct or self.false_matches or self.true_pairs:
                raise ValueError(""",
        """            if False:
                raise ValueError(""",
    ),
    (
        "rate prints the headline without its decomposition",
        "bench/rate.py",
        '''        return f"{self.value:.1%} ({self.numerator}/{self.denominator})"''',
        '''        return f"{self.value:.1%}"''',
    ),
    (
        "tier split no longer has to account for every match",
        "bench/metrics.py",
        """        if self.tiers is not None and sum(self.tiers.values()) != self.produced:""",
        """        if False:""",
    ),
    (
        "an arm may report matches with no tier split",
        "bench/metrics.py",
        """        if self.produced and self.tiers is None:""",
        """        if False:""",
    ),
    (
        "any surfaced exception counts as classified",
        "bench/planted.py",
        """        named = item.code in codes""",
        """        named = True""",
    ),
    (
        "ambiguity detection stops counting the subsets",
        "bench/planted.py",
        """    if not planted or not ours or len(planted) != len(ours):
        return False""",
        """    if not planted or not ours:
        return False""",
    ),
    (
        "ambiguity detection accepts any E09",
        "bench/planted.py",
        """                exc.code == ExceptionCode.E09_NETTING_AMBIGUITY
                and subsets_agree(item.alternatives, exc.alternatives)""",
        """                exc.code == ExceptionCode.E09_NETTING_AMBIGUITY""",
    ),
    (
        "a missed in-scope defect is quietly reclassified out of scope",
        "bench/planted.py",
        """    in_scope = [p for p in planted if p.leg in in_scope_legs]
    out_of_scope = [p for p in planted if p.leg not in in_scope_legs]""",
        """    hit_ids = {rid for exc in raised for rid in exc.record_ids}
    in_scope = [p for p in planted if p.leg in in_scope_legs and (p.record_ids & hit_ids)]
    out_of_scope = [p for p in planted if p not in in_scope]""",
    ),
    (
        # Re-anchored at P13: the loading moved from `bench/run.py` into the
        # profile it configures, so the product could read its own files. The
        # bug this reverts is the same one — filter the anchor side before the
        # completeness audit can see it, and the planted `E08` leaves the
        # pipeline with no disposition while invariant 8 still reads `complete`.
        "the anchor side is filtered before the audit can see it (the P10 bug)",
        "src/recon/profiles/settlement.py",
        """    anchor_rows = named(SOURCES[0])""",
        """    anchor_rows = [
        (ext, rec)
        for ext, rec in named(SOURCES[0])
        if rec.keys.get("gateway") and rec.amount > 0
    ]""",
    ),
    (
        "out-of-scope records stop reaching the completeness audit",
        "src/recon/engine/tiers.py",
        """            out_of_scope=scope,""",
        """            out_of_scope=None,""",
    ),
    (
        "input verification always passes",
        "bench/generator/__init__.py",
        """    mpath = out / "MANIFEST.json"
    if not mpath.exists():""",
        """    return []
    mpath = out / "MANIFEST.json"
    if not mpath.exists():""",
    ),
    (
        "the runner exits zero on an incomplete close",
        "bench/run.py",
        """    return 1 if failed else 0""",
        """    return 0""",
    ),
    (
        "only the first batch is measured",
        "bench/run.py",
        """    names = ["A", "B"] if args.batch == "all" else [args.batch]""",
        """    names = ["A"] if args.batch == "all" else [args.batch]""",
    ),
]
