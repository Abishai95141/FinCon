"""A break has to be recognisable the second time it happens.

`exception_id` is `EXC-00001` — a position in a list, naming a different finding
in every batch. So nothing linked an unresolved break across two closes: no
first-seen, no occurrence count, and a worklist "age" that measured the age of
the transaction rather than of the problem.

That is the defect P12 fixed for records (`source:natural-key-hash:occurrence`)
left in place one layer up, and it was found by reading Formance's
reconciliation service, which dedups alerts on `(rule_id, fingerprint,
period_id)` and carries `first_seen_at` / `occurrence_count`.
"""

from __future__ import annotations

import pytest
from bench.run import close

from recon.engine import fingerprint


@pytest.fixture(scope="module")
def closes():
    return close("A"), close("B")


def test_every_exception_carries_one(closes):
    for result in closes:
        for exc in result.exceptions:
            assert exc.fingerprint, exc.exception_id
            assert len(exc.fingerprint) == 16


def test_the_same_break_fingerprints_the_same_way_twice(closes):
    """Stability first: an identity that moved between runs would be worse than
    a positional one, because it would look stable and not be."""
    a, _ = closes
    again = close("A")
    assert {e.fingerprint for e in a.exceptions} == {e.fingerprint for e in again.exceptions}


def test_different_breaks_do_not_collide(closes):
    for result in closes:
        prints = [e.fingerprint for e in result.exceptions]
        assert len(prints) == len(set(prints))


def test_a_break_present_in_two_closes_is_recognisable_as_the_same_one(closes):
    """The whole point. Positional ids made `EXC-00001` in A and `EXC-00001` in
    B look like the same thing while being different findings; these make the
    genuinely recurring ones visible."""
    a, b = closes
    fa = {e.fingerprint: e.code for e in a.exceptions}
    fb = {e.fingerprint: e.code for e in b.exceptions}
    shared = set(fa) & set(fb)

    assert shared, "no break recurs across the two batches, so this proves nothing"
    for f in shared:
        assert fa[f] == fb[f], "the same fingerprint carries two different codes"


def test_positional_ids_would_have_shown_a_false_match(closes):
    """The counterfactual, asserted so the improvement is not taken on trust."""
    a, b = closes
    ids_a = {e.exception_id for e in a.exceptions}
    ids_b = {e.exception_id for e in b.exceptions}

    assert ids_a == ids_b, "positional ids are supposed to collide — that is the defect"
    assert {e.fingerprint for e in a.exceptions} != {e.fingerprint for e in b.exceptions}


def test_the_amount_is_deliberately_not_part_of_the_identity(closes):
    """A partial payment that grows between two closes is the same unresolved
    break with a bigger number. A fingerprint that moved with the amount would
    report it as a new case every period, which is how a recurring problem hides
    as a stream of one-offs."""
    from decimal import Decimal

    a, _ = closes
    exc = next(e for e in a.exceptions if e.code == "E04")
    bigger = exc.model_copy(update={"amount": exc.amount + Decimal("100.00")})

    assert fingerprint.of(bigger, a.records) == fingerprint.of(exc, a.records)


def test_a_different_set_of_records_is_a_different_break(closes):
    """The other half: if the identity ignored the records too, every `E14`
    would be the same break."""
    a, _ = closes
    e14 = [e for e in a.exceptions if e.code == "E14"]
    assert len(e14) > 1
    assert len({fingerprint.of(e, a.records) for e in e14}) == len(e14)
