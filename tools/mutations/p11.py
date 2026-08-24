"""Mutations for the P11 controls. See tools/mutate.py."""

TARGETS = ["tests/gates/gate_p11.py"]

MUTATIONS = [
    (
        "a proposed code's booking is honoured",
        "src/recon/contracts/taxonomy.py",
        """        if not entry.authority.may_direct_posting or not entry.books_to:""",
        """        if not entry.books_to:""",
    ),
    (
        "the posting rule ignores the taxonomy entirely",
        "src/recon/ledger/posting_rules.py",
        """        directed = taxonomy.booking_for(exc.code) if taxonomy is not None else None""",
        """        directed = None""",
    ),
    (
        "the posting refusal is not reported",
        "src/recon/ledger/posting_rules.py",
        '''                declined.append(
                    f"{exc.exception_id} ({exc.code}): asked to book to "''',
        '''                _ = (
                    f"{exc.exception_id} ({exc.code}): asked to book to "''',
    ),
    (
        "a proposal keeps the status it asked for",
        "src/recon/engine/taxonomy.py",
        """        status=CodeStatus.PROPOSED,
        owner=owner,""",
        """        status=ignored.get("status", CodeStatus.PROPOSED),
        owner=owner,""",
    ),
    (
        "an agent may mint a canonical code",
        "src/recon/engine/taxonomy.py",
        """    if not code.startswith(AGENT_NAMESPACE) and actor != registry.approved_by:""",
        """    if False:""",
    ),
    (
        "a proposal may overwrite an existing code",
        "src/recon/engine/taxonomy.py",
        """    if code in registry:
        reasons.append(f"{code} already exists as {registry[code].status.value}")""",
        """    if False:
        reasons.append("")""",
    ),
    (
        "promotion no longer needs a written definition",
        "src/recon/engine/taxonomy.py",
        """    if len((definition or "").strip()) < MIN_DEFINITION:""",
        """    if False:""",
    ),
    (
        "promotion no longer needs a named human",
        "src/recon/engine/taxonomy.py",
        """    if not (actor or "").strip():
        reasons.append("a promotion must name who granted it")""",
        """    if False:
        reasons.append("")""",
    ),
    (
        "the lifecycle can be short-circuited",
        "src/recon/engine/taxonomy.py",
        """    if entry.status is not CodeStatus.PROVISIONAL:""",
        """    if False:""",
    ),
    (
        "a proposed code routes to the owner it claimed",
        "src/recon/contracts/taxonomy.py",
        """        if entry.authority.may_route_to_named_owner and entry.owner:""",
        """        if entry.owner:""",
    ),
    (
        "a code that resolves nowhere is tolerated",
        "src/recon/contracts/taxonomy.py",
        """        try:
            return self.codes[code]
        except KeyError:""",
        """        try:
            return self.codes[code]
        except KeyError:
            if True:
                from datetime import UTC, datetime
                return CodeDefinition(code=code, title="unknown", definition="",
                                      proposed_by="?", proposed_at=datetime.now(UTC))""",
    ),
    (
        "a retired code stays assignable",
        "src/recon/contracts/taxonomy.py",
        """    CodeStatus.RETIRED: Authority(True, False, False, False, False),""",
        """    CodeStatus.RETIRED: Authority(True, False, False, False, True),""",
    ),
    (
        "a retired code stops resolving",
        "src/recon/contracts/taxonomy.py",
        """    CodeStatus.RETIRED: Authority(True, False, False, False, False),""",
        """    CodeStatus.RETIRED: Authority(False, False, False, False, False),""",
    ),
    (
        "a rule may key on an unratified code",
        "src/recon/engine/promotion.py",
        """                    taxonomy.check_may_fire_rule(value)""",
        """                    pass""",
    ),
    (
        "the worklist stops ranking by age",
        "src/recon/triage/worklist.py",
        """        scored.append((paise * age, exc.exception_id, exc, entry))""",
        """        scored.append((paise, exc.exception_id, exc, entry))""",
    ),
    (
        "the worklist hides which codes are unratified",
        "src/recon/triage/worklist.py",
        """    if code.status is CodeStatus.PROMOTED:
        return None""",
        """    if True:
        return None""",
    ),
    (
        "ranking drifts to float",
        "src/recon/triage/worklist.py",
        """        paise = int(abs(exc.amount) * 100)""",
        """        paise = float(abs(exc.amount) * 100)""",
    ),
    (
        "the taxonomy bytes are not pinned",
        "bench/run.py",
        """        taxonomy_digest=_digest(TAXONOMY_FILE),""",
        """        taxonomy_digest="0" * 64,""",
    ),
    (
        "the close skips the worklist",
        "bench/run.py",
        """    worklist = build_worklist(list(ours.exceptions), TAXONOMY, as_of=WINDOW[1])""",
        """    worklist = []""",
    ),
    (
        "proposing a code is not recorded",
        "src/recon/engine/taxonomy.py",
        """    _record(
        journal,
        EventKind.CODE_PROPOSED,""",
        """    _record(
        None,
        EventKind.CODE_PROPOSED,""",
    ),
    (
        "a refused code promotion is not recorded",
        "src/recon/engine/taxonomy.py",
        """    _record(
        journal,
        EventKind.PROPOSAL_REFUSED,""",
        """    _record(
        None,
        EventKind.PROPOSAL_REFUSED,""",
    ),
    (
        "the contract accepts any string as a code",
        "src/recon/contracts/taxonomy.py",
        '''CODE_PATTERN = r"^(E[0-9]{2}|X-[A-Z][A-Z0-9-]{2,31})$"''',
        '''CODE_PATTERN = r"^.*$"''',
    ),
    (
        "an unattributable credit is booked to income",
        "src/recon/ledger/posting_rules.py",
        """        role = directed or AccountRole.SUSPENSE""",
        """        role = directed or AccountRole.INCOME""",
    ),
    (
        "a promoted code needs no definition at the contract level",
        "src/recon/contracts/taxonomy.py",
        """            if len(self.definition.strip()) < MIN_DEFINITION:""",
        """            if False:""",
    ),
]
