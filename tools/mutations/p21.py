"""Mutations for the four dispositions.

The feature this set guards is the one the product spent thirteen phases
without, so the first question is not "is it correct" but "does it do anything
at all". Three of these mutants make a disposition *succeed and move nothing* —
the exact defect being replaced — and a suite that stayed green under them would
mean the tests were watching the attestation rather than the entry.

The rest attack the bounds. A write-off control has two ways to be defeated and
they are not the same shape: one item over the ceiling, or ninety under it. A
mutant exists for each, and for the subtler one where the budget's denominator
starts moving with the write-offs it is supposed to bound.

The last two are about who is allowed to decide: the signer coming from the
request rather than the session, and an unpromoted code reaching an expense
account by omission.
"""

TARGETS = [
    "tests/property/test_disposition.py",
    "tests/property/test_close_pack.py",
    "tests/property/test_unenforced.py",
]

MUTATIONS = [
    # ---- does it move money at all -----------------------------------------
    (
        "the journal forgets the dispositions, so an ending writes no entry",
        "src/recon/service.py",
        """    for event in reviewlib.dispositions(run_id, runs_dir or runs_root()):""",
        """    for event in []:""",
    ),
    (
        "a disposition posts one side, which is a memo rather than an entry",
        "src/recon/service.py",
        """        for account, amount in ((debit, payload.amount), (credit, -payload.amount)):""",
        """        for account, amount in ((debit, payload.amount),):""",
    ),
    (
        "a disposed item goes on blocking, so the ending ends nothing",
        "src/recon/review.py",
        """        and exc.exception_id not in review.disposed""",
        """        and exc.exception_id not in review.acknowledged""",
    ),
    (
        "every ending books to the same account, so four endings become one",
        "src/recon/disposition.py",
        """        debit = DESTINATION[disposition]""",
        """        debit = AccountRole.SUSPENSE""",
    ),
    # ---- the bounds --------------------------------------------------------
    (
        "the per-item write-off ceiling stops refusing",
        "src/recon/disposition.py",
        """        if value > ceiling:""",
        """        if False:""",
    ),
    (
        "the whole-close write-off budget stops refusing",
        "src/recon/disposition.py",
        """        if value > remaining:""",
        """        if False:""",
    ),
    (
        "the budget's denominator follows the write-offs it is meant to bound",
        "src/recon/disposition.py",
        """    total = sum((abs(exc.amount) for exc in tail), start=ZERO)""",
        """    total = sum((abs(exc.amount) for exc in tail), start=ZERO) * 2""",
    ),
    (
        "the running write-off total resets, so each item sees a full budget",
        "src/recon/review.py",
        """                written_off += abs(payload.amount)""",
        """                written_off = ZERO""",
    ),
    # ---- who may decide ----------------------------------------------------
    (
        "the signer comes from the request instead of the session",
        "src/recon/api/ui.py",
        """            decided_by=user.email,""",
        """            decided_by=owner or user.email,""",
    ),
    (
        "an unpromoted code reaches an expense account by default",
        "src/recon/disposition.py",
        """    Disposition.WRITE_OFF: AccountRole.WRITE_OFF,""",
        """    Disposition.WRITE_OFF: AccountRole.WRITE_OFF,
    Disposition.BOOK: AccountRole.FEES,""",
    ),
    (
        "a disposition needs no rationale, so a number lands with no defence",
        "src/recon/disposition.py",
        """    if not rationale.strip():""",
        """    if False:""",
    ),
    (
        "an item can end twice, taking its value out of the close twice",
        "src/recon/review.py",
        """    if state and exception.exception_id in state.disposed:""",
        """    if False:""",
    ),
    # ---- the record --------------------------------------------------------
    (
        "the bounds a disposition was checked against stop being recorded",
        "src/recon/review.py",
        """            ceiling_applied=decision.ceiling,""",
        """            ceiling_applied=None,""",
    ),
    (
        "beancount metadata goes back to unquoted, silently dropping entries",
        "src/recon/service.py",
        """        lines.append(f'  decided_by: "{payload.decided_by}"')""",
        """        lines.append(f"  decided_by: {payload.decided_by}")""",
    ),
]
