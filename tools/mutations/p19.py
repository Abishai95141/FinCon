# ruff: noqa: E501 — a mutation anchor is a verbatim source line and must not
# be reflowed; wrapping one is how a set silently stops applying.
"""Mutations for the substrate and the surface — P13 and P14.

Every control here guards something a *surface* made visible for the first time.
Two of them guard defects the surface itself found: a rule that broke a match and
a rule refused as inadmissible each reached the decision log nowhere at all, and
neither fires on batches A or B, so both were invisible to every test that runs
the corpus.

The ones worth naming are the verification mutants. `verify_proof` is the whole
trust argument, and the two ways to hollow it out are not arithmetic — they are
(1) picking a policy for the caller when they name none, and (2) reporting a
verdict without saying whose constraints produced it. Either leaves the
arithmetic perfectly correct and the claim worthless.
"""

TARGETS = [
    "tests/gates/gate_p13.py",
    "tests/gates/gate_p14.py",
    "tests/property/test_one_surface.py",
    "tests/property/test_the_record_names_its_refusals.py",
    "tests/property/test_loop_definition.py",
    "tests/property/test_contract_defaults.py",
]

MUTATIONS = [
    # ---- the record ------------------------------------------------------
    (
        "the log goes back to naming a proof id and storing no proof",
        "src/recon/journal/derive.py",
        """                    proof=match.proof,""",
        """                    proof=None,""",
    ),
    (
        "the record forgets how an exception came by its label",
        "src/recon/journal/derive.py",
        """                    code_provenance=exc.code_provenance.value,""",
        """                    code_provenance="P3",""",
    ),
    (
        "replay drops the provenance, so every label looks freely reclassifiable",
        "src/recon/journal/replay.py",
        """                        code_provenance=ProofTier(payload.code_provenance),""",
        """                        code_provenance=ProofTier.P3_DECLARED,""",
    ),
    (
        "the record describes only what came out — a numerator with no denominator",
        "src/recon/journal/derive.py",
        """                anchors_in_scope=len(
                    [a for a in decisions.completeness.anchors if a not in decisions.scope]
                ),""",
        """                anchors_in_scope=0,""",
    ),
    (
        "a ledger error hides the fact that exceptions are also blocking",
        "src/recon/journal/derive.py",
        """                    reasons=list(decisions.blocked_reasons)
                    + ([f"{len(blocking)} exception(s) block sign-off"] if blocking else []),""",
        """                    reasons=list(decisions.blocked_reasons)
                    or [f"{len(blocking)} exception(s) block sign-off"],""",
    ),
    (
        "a rule that breaks a match sets ok=False and tells the record nothing",
        "src/recon/close.py",
        """        + [
            f"rule_broke_match: {anchor} matched without the rule bundle and "
            f"does not match with it (invariant 5)"
            for anchor in broken
        ],""",
        """        + [],""",
    ),
    (
        "a rule refused as inadmissible is declined silently",
        "src/recon/close.py",
        """    for rule_id, reasons in sorted(staged.inadmissible.items()):""",
        """    for rule_id, reasons in []:""",
    ),
    # ---- the verification ------------------------------------------------
    (
        "verification picks a policy for the caller instead of refusing",
        "src/recon/service.py",
        """    if (policy is None) == (loop_name is None):""",
        """    if policy is None and loop_name is None:
        loop_name = "settlement_3way"
    if False:""",
    ),
    (
        "a verdict no longer says whose constraints produced it",
        "src/recon/service.py",
        """    source = "caller-supplied"
    if loop_name is not None:
        policy = looplib.get(loop_name).policy()
        source = "in-force\"""",
        """    source = "in-force"
    if loop_name is not None:
        policy = looplib.get(loop_name).policy()""",
    ),
    (
        "a re-derivation with nothing to check reports a pass",
        "src/recon/service.py",
        """        holds=all(c.same_file for c in checks) and not refuted and not gaps and checked > 0,""",
        """        holds=not refuted,""",
    ),
    (
        "matches with no proof in the record stop being named",
        "src/recon/journal/replay.py",
        """    return sorted(m for m, pid in replayed.match_proofs.items() if pid not in replayed.proofs)""",
        """    return []""",
    ),
    # ---- the surface -----------------------------------------------------
    (
        "blocking recall is reported as zero rather than absent",
        "src/recon/service.py",
        """    recall: None = None""",
        """    recall: float = 0.0""",
    ),
    (
        "a rate is printed without its decomposition",
        "src/recon/service.py",
        """    return f"{numerator}/{denominator} ({pct}%)\"""",
        """    return f"({pct}%)\"""",
    ),
    (
        "the break's identity is dropped on the way out of the record",
        "src/recon/journal/replay.py",
        """                        fingerprint=payload.fingerprint,""",
        """                        fingerprint="",""",
    ),
    (
        "the record names a bundle by an absolute path from someone's laptop",
        "src/recon/close.py",
        """                bundle=verdict.name,""",
        """                bundle=str(verdict.bundle),""",
    ),
    (
        "the surface serves the run instead of the record",
        "src/recon/service.py",
        """    blocked=[r for r in replayed.blocked if r not in _signoff_lines(replayed)],""",
        """    blocked=list(replayed.blocked),""",
    ),
    (
        "an incomplete source set is closed anyway",
        "src/recon/loop.py",
        """    missing = loop.missing(root)
    if missing:""",
        """    missing = []
    if missing:""",
    ),
    (
        "the loader drops group rows the source gave no id, ahead of the audit",
        "src/recon/profiles/settlement.py",
        """        return [(rec.source_row_id or rec.record_id, rec) for rec in out]""",
        """        return [(rec.source_row_id, rec) for rec in out if rec.source_row_id]""",
    ),
    (
        "policy stops validating its own defaults",
        "src/recon/contracts/policy.py",
        """    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)""",
        """    model_config = ConfigDict(frozen=True, extra="forbid")""",
    ),
    (
        "the run id becomes positional, so two closes share one record",
        "src/recon/loop.py",
        """    return f"{label}-{hashlib.sha256(body.encode()).hexdigest()[:8]}\"""",
        """    return label""",
    ),
]
