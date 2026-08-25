"""Mutations for the payload budget and the write lock.

Both controls exist because the surface was *tested and unusable*. `run_match`
returned 397 KB — most of a context window, for 543 rows of a toy corpus — and
two concurrent closes corrupted the record, telling the caller their decision log
had been **tampered with** because two people pressed the same button.

The interesting mutants are not the ones that make a response large again. They
are the four that make a bounded response *lie*: a page that drops its cursor, a
total that counts the slice, a withheld proof that renders like a missing one,
and a projection that changes the answer it projects.
"""

TARGETS = [
    "tests/property/test_result_budget.py",
    "tests/property/test_concurrent_closes.py",
    "tests/property/test_one_surface.py",
    "tests/gates/gate_p13.py",
    "tests/gates/gate_p14.py",
]

MUTATIONS = [
    (
        "the page drops its cursor, so a slice reads as the whole collection",
        "src/recon/service.py",
        """        "next_offset": consumed if consumed < total else None,""",
        """        "next_offset": None,""",
    ),
    (
        "total counts the slice rather than the collection",
        "src/recon/service.py",
        """    total = len(items)""",
        """    total = len(items[offset:])""",
    ),
    (
        "the byte budget is ignored and everything comes back",
        "src/recon/service.py",
        """        if taken and size + encoded > budget:""",
        """        if False:""",
    ),
    (
        "a page that stopped early no longer says it stopped early",
        "src/recon/service.py",
        """            stopped = True""",
        """            stopped = False""",
    ),
    (
        "an offset past the end returns an empty page instead of refusing",
        "src/recon/service.py",
        """    if offset < 0 or offset > total:
        raise ServiceError(f"offset {offset} is outside a collection of {total}")""",
        """    if False:
        raise ServiceError(f"offset {offset} is outside a collection of {total}")""",
    ),
    (
        "a withheld proof renders exactly like a proof the record does not have",
        "src/recon/service.py",
        """            proof_omitted=""
            if full or e.payload.proof is None
            else f"withheld at detail=summary; fetch it with get_proof({run_id!r}, "
            f"{e.payload.match_id!r}) or ask for detail=full",""",
        """            proof_omitted="",""",
    ),
    (
        "the projection changes the answer: proof tiers counted off withheld proofs",
        "src/recon/service.py",
        """    for event in by_kind.get("MatchProven", []):
        proof = event.payload.proof""",
        """    for event in [_m for _m in matches]:
        proof = event.proof""",
    ),
    (
        "withheld records report a count of zero",
        "src/recon/service.py",
        """        records_available=len(records),""",
        """        records_available=0,""",
    ),
    (
        "two closes of one period write the same log at once",
        "src/recon/close.py",
        """    with journal_lock(request.journal_path):""",
        """    with contextlib.nullcontext():""",
    ),
    (
        "a reader may catch a close mid-write",
        "src/recon/service.py",
        """    with journal_lock(path):
        return read_journal(path, verify=False)""",
        """    return read_journal(path, verify=False)""",
    ),
    (
        "the lock is taken on the log itself, which the writer then deletes",
        "src/recon/journal/__init__.py",
        """    lock = path.parent / f".{path.name}.lock\"""",
        """    lock = path""",
    ),
    (
        "a writer waits forever on a stuck lock instead of reporting it",
        "src/recon/journal/__init__.py",
        """                if time.monotonic() >= deadline:""",
        """                if False:""",
    ),
]
