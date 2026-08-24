"""Mutations for the P9 controls. See tools/mutate.py."""

TARGETS = ["tests/gates/gate_p9.py"]

MUTATIONS = [
    (
        "nothing checks the stream against its own terminator",
        "src/recon/journal/replay.py",
        """        if actual[key] != n""",
        """        if False""",
    ),
    (
        "replay re-runs the engine instead of reading the log",
        "bench/replay.py",
        """    replayed = replay_close(path, verify=verify)
    result = ArmResult(""",
        """    from recon.engine.tiers import run as _run  # noqa: F401
    replayed = replay_close(path, verify=verify)
    _run([], [], __import__("bench.run", fromlist=["x"]).SETTLEMENT_3WAY)
    result = ArmResult(""",
    ),
    (
        "the derivation stops checking that every disposed input is logged",
        "src/recon/journal/derive.py",
        """    missing = unlogged(decisions.completeness, events)
    if missing:""",
        """    missing = []
    if missing:""",
    ),
    (
        "unlogged() ignores excepted records",
        "src/recon/journal/derive.py",
        """        if disposition is not Disposition.UNDISPOSED""",
        """        if disposition is Disposition.MATCHED""",
    ),
    (
        "the chain stops covering event content",
        "src/recon/journal/__init__.py",
        """    body = event.model_dump(mode="json", exclude={"event_hash", "prev_hash"})
    return json.dumps(body, sort_keys=True, separators=(",", ":"))""",
        """    return str(event.seq)""",
    ),
    (
        "the chain stops linking to the previous event",
        "src/recon/journal/__init__.py",
        """        if event.prev_hash != prev:
            problems.append(f"seq {event.seq}: prev_hash does not follow seq {index - 1}")""",
        """        if False:
            problems.append("")""",
    ),
    (
        "seq numbering is no longer checked",
        "src/recon/journal/__init__.py",
        """        if event.seq != index:""",
        """        if False:""",
    ),
    (
        "reading a log stops verifying it",
        "src/recon/journal/__init__.py",
        """    if verify:
        problems = verify_chain(events, require_terminator=False)""",
        """    if False:
        problems = verify_chain(events, require_terminator=False)""",
    ),
    (
        "opening a tampered log is allowed",
        "src/recon/journal/__init__.py",
        """        existing = read(self.path) if self.path.exists() else []""",
        """        existing = read(self.path, verify=False) if self.path.exists() else []""",
    ),
    (
        "a finished log can be extended",
        "src/recon/journal/__init__.py",
        """        if self._sealed:
            raise JournalSealed(f"{self.path} already ended in CloseCompleted")""",
        """        if False:
            raise JournalSealed("")""",
    ),
    (
        "the terminator requirement is dropped",
        "src/recon/journal/__init__.py",
        """    if require_terminator and (not events or events[-1].kind is not EventKind.CLOSE_COMPLETED):""",
        """    if False:""",
    ),
    (
        "a refused promotion is not recorded",
        "src/recon/engine/promotion.py",
        """        _record(
            journal,
            EventKind.PROPOSAL_REFUSED,""",
        """        _record(
            None,
            EventKind.PROPOSAL_REFUSED,""",
    ),
    (
        "verifier refusals are dropped instead of logged",
        "bench/arms/deterministic.py",
        """            refusals.append(
                RejectedMatch(""",
        """            _ = (
                RejectedMatch(""",
    ),
    (
        "the log stops pinning the policy bytes",
        "bench/run.py",
        """        policy_digest=_digest(POLICY_FILE),""",
        """        policy_digest="0" * 64,""",
    ),
    (
        "scope declarations are not recorded",
        "src/recon/journal/derive.py",
        """    for record_id, reason in sorted(decisions.scope.items()):""",
        """    for record_id, reason in sorted({}.items()):""",
    ),
    (
        "proven matches are not posted",
        "src/recon/ledger/posting_rules.py",
        """    for match in matches:
        anchor = records[match.anchor_id]""",
        """    for match in []:
        anchor = records[match.anchor_id]""",
    ),
    (
        "settlement the bank never received is posted anyway",
        "src/recon/ledger/posting_rules.py",
        """        if not on_anchor:""",
        """        if False:""",
    ),
    (
        "the completeness audit stops covering postings",
        "src/recon/engine/completeness.py",
        """            or self.undisposed_postings
        )""",
        """        )""",
    ),
    (
        "the posting audit is fed the ids it is checking",
        "bench/run.py",
        """        posted_proof_ids=[e.proof_id for e in entries if e.proof_id],""",
        """        posted_proof_ids=[m.proof.proof_id for m in ours.matches],""",
    ),
    (
        "the engine's own audit is discarded and recomputed loosely",
        "bench/run.py",
        """    completeness = ours.completeness.extend(""",
        """    from recon.engine.completeness import CompletenessReport as _CR
    completeness = _CR(anchors={}, records={}, sources={}).extend(""",
    ),
]
