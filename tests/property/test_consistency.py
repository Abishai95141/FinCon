"""`E02`, and why it was invisible for eleven phases.

The engine's inputs are `row_id, row_type, payout_id, gateway, payment_id,
value_date, amount`. No rate, no terms file, no contract — so "the gateway billed
above the contract tier" looked undetectable, and the audit concluded it needed a
fee compared against a rate on a sibling record. That was wrong: there is no rate
to compare to anywhere in the data.

What is there is the population. A gateway bills its whole book on one set of
terms, so rows on different terms disagree with their own peers, and the size of
the disagreement is the finding.

Matching is structurally blind to this. A payout whose fees were billed on the
wrong terms still sums to exactly what the bank paid, so it reconciles perfectly
and the variance walks out the door.
"""

from __future__ import annotations

import random
from decimal import Decimal

import pytest
from bench.planted import load_planted
from bench.run import BATCHES, SETTLEMENT_3WAY, SETTLEMENT_POLICY, close

from recon.engine.consistency import RelationSpec, find

SPEC = SETTLEMENT_3WAY.consistency
TOLERANCE = Decimal(SETTLEMENT_POLICY.consistency_tolerance)


@pytest.fixture(scope="module")
def rows_a():
    return close("A", rules=[]).settlement_records


@pytest.mark.parametrize(("batch", "expected"), [("A", "290.07"), ("B", "392.66")])
def test_the_variance_is_the_planted_amount_to_the_paisa(batch, expected):
    """Not "close to". The generator planted an exact figure and the detector
    re-derives it from the export alone, on both batches, with one threshold and
    no tuning."""
    rows = close(batch, rules=[]).settlement_records
    findings = find(rows, SPEC, tolerance=TOLERANCE)

    assert len(findings) == 1, [f.peer for f in findings]
    assert findings[0].variance == Decimal(expected)


@pytest.mark.parametrize("batch", ["A", "B"])
def test_every_row_it_names_is_one_the_generator_planted(batch):
    """Precision, against labels authored before the engine. A detector that
    found the right total by naming the wrong rows would score the same on
    coverage and be useless to whoever has to work the queue."""
    result = close(batch, rules=[])
    planted = next(
        p
        for p in load_planted(BATCHES / batch / "labels.json", result.external_of)
        if p.code == "E02"
    )
    found = find(result.settlement_records, SPEC, tolerance=TOLERANCE)[0]

    assert set(found.record_ids) <= set(planted.record_ids)
    assert found.record_ids


def test_rounding_scatter_is_not_a_finding(rows_a):
    """The other gateway's rows are off the relation too — by 0.26 across the
    whole population, which is rounding. Three orders of magnitude from 290.07,
    which is why the threshold is not doing delicate work."""
    findings = find(rows_a, SPEC, tolerance=TOLERANCE)
    assert {f.peer for f in findings} == {"razorpay"}

    # Drop the threshold to nothing and the rounding appears — so the check is
    # discriminating on size, not silently ignoring the other population.
    everything = find(rows_a, SPEC, tolerance=Decimal("0.00"))
    assert {f.peer for f in everything} == {"cashfree", "razorpay"}
    assert next(f for f in everything if f.peer == "cashfree").variance < Decimal("1.00")


def test_the_answer_does_not_depend_on_row_order(rows_a):
    """Caught by the metamorphic suite, not by review. The rate was inferred
    from the first N rows *in input order*, so shuffling the same records could
    change which rows were reported and a close stopped being replayable."""
    seen = set()
    for seed in range(6):
        shuffled = list(rows_a)
        random.Random(seed).shuffle(shuffled)
        seen.add(
            tuple(
                (f.peer, f.variance, tuple(f.record_ids))
                for f in find(shuffled, SPEC, tolerance=TOLERANCE)
            )
        )
    assert len(seen) == 1, f"{len(seen)} different answers over 6 shuffles"


def test_a_population_too_small_to_have_a_majority_is_not_judged(rows_a):
    """A relation inferred from three rows is a coincidence with a decimal point.

    The first version of this took six ordinary rows and asserted no finding —
    which held whether or not the guard existed, because six rows on the same
    terms disagree with nothing. It passed under its own mutant. This builds a
    population that *would* fire: a handful of rows where a bare majority sets
    the relation and the rest are declared wrong on that authority.
    """
    from decimal import Decimal as D

    charges = {r.keys.get("payment_id"): r for r in rows_a if r.keys.get("row_type") == "charge"}
    fees = [
        r for r in rows_a if r.keys.get("row_type") == "fee" and r.keys.get("payment_id") in charges
    ][:4]
    assert len(fees) == 4 and len(fees) < SPEC.minimum_peers

    # One row billed on different terms, in a population of four. Without the
    # guard, three rows out-vote it and it is reported as a finding.
    odd = fees[-1].model_copy(update={"amount": fees[-1].amount * D("1.30")})
    population = [*charges.values(), *fees[:-1], odd]

    assert find(population, SPEC, tolerance=TOLERANCE) == [], (
        "a majority of three declared a fourth row wrong"
    )

    relaxed = RelationSpec(**{**SPEC.__dict__, "minimum_peers": 2})
    assert find(population, relaxed, tolerance=TOLERANCE), (
        "the population cannot fire at all, so the guard is untested"
    )


def test_the_close_uses_the_threshold_policy_states(rows_a):
    """The wiring, not the function. `find()` takes a tolerance and the tests
    above pass it by hand; a close that read a different one — or none — would
    raise the rounding scatter as a finding and nothing here would notice."""
    result = close("A", rules=[])
    raised = [e for e in result.exceptions if e.code == "E02"]

    assert len(raised) == 1, [str(e.amount) for e in raised]
    assert raised[0].amount == Decimal("290.07")
    assert Decimal(SETTLEMENT_POLICY.consistency_tolerance) > Decimal("0.26"), (
        "the policy threshold must sit above the rounding scatter it exists to ignore"
    )


def test_the_finding_carries_the_relation_it_was_measured_against(rows_a):
    """A variance with no relation behind it is a number a controller cannot
    check. The evidence names the rate, how many rows agreed, and the group."""
    found = find(rows_a, SPEC, tolerance=TOLERANCE)[0]
    evidence = " ".join(found.evidence())

    assert str(found.relation.rate) in evidence
    assert f"{found.relation.agreeing}/{found.relation.total}" in evidence
    assert found.relation.agreeing > found.relation.total // 2


def test_matching_alone_never_sees_it(rows_a):
    """The reason this needed a pass of its own. The payout the variance sits in
    matches perfectly — the legs tie, the residual is zero, and nothing about the
    match is wrong."""
    result = close("A", rules=[])
    found = find(rows_a, SPEC, tolerance=TOLERANCE)[0]
    affected = set(found.group_refs)

    matched_groups = {m.group_ref for m in result.matches}
    assert affected <= matched_groups, "the variance is inside a group that matched"
    for match in result.matches:
        if match.group_ref in affected:
            assert match.proof.residual == Decimal("0.00")


@pytest.mark.parametrize("batch", ["A", "B"])
def test_coverage_reaches_every_planted_defect_in_scope(batch):
    """The headline this moved: 4/5 -> 5/5, on both batches."""
    card = next(c for c in close(batch).cards if "determin" in c.arm)
    assert card.exceptions.coverage.numerator == card.exceptions.coverage.denominator == 5
    assert card.false_matches == 0, "coverage bought with a false match is not coverage"


def test_the_majority_defines_the_relation_even_when_the_minority_comes_first():
    """Which offset wins must be decided by how many rows hold it, not by which
    row the file happened to list first.

    Caught by mutation, twice over: replacing `most_common` with "the first one
    seen" produces an identical answer on both batches, because the majority
    offset also happens to be the first inserted. A control that only bites on
    inputs we do not have is a control nobody has tested — so this orders the
    input against it.
    """
    result = close("A", rules=[])
    rows = result.settlement_records
    charges = {r.keys.get("payment_id"): r for r in rows if r.keys.get("row_type") == "charge"}

    found = find(rows, SPEC, tolerance=TOLERANCE)[0]
    odd_ones = set(found.record_ids)
    minority = [r for r in rows if r.record_id in odd_ones]
    majority = [
        r
        for r in rows
        if r.keys.get("row_type") == "fee"
        and r.record_id not in odd_ones
        and r.keys.get("gateway") == found.peer
    ]
    assert len(minority) < len(majority)

    # Minority first. If the first offset seen won, these twelve rows would
    # define the relation and the other 164 would be reported as the finding.
    reordered = [*charges.values(), *minority, *majority]
    again = find(reordered, SPEC, tolerance=TOLERANCE)

    assert len(again) == 1
    assert set(again[0].record_ids) == odd_ones, (
        "the minority defined the relation and the majority was declared wrong"
    )
    assert again[0].variance == found.variance
