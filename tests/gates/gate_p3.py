"""Gate P3 — engine T0/T1 + proof verifier + baseline arm.

Gate: auto-match rate **and** false-match rate, ours vs the securo baseline, on
batch A.

The load-bearing tests here are the tampering ones. A 0% false-match rate means
nothing if the verifier rubber-stamps whatever it is handed, so every way a
proof can lie is asserted to be refuted. Without those, this gate would pass
with `verify()` returning PROVEN unconditionally.
"""

from __future__ import annotations

import json
from decimal import Decimal as D

import pytest
from bench.arms import deterministic, securo_baseline
from bench.metrics import score, truth_pairs
from bench.run import BATCHES, SETTLEMENT_3WAY, load_sides

from recon.contracts import MatchTier, Proof, ProofTier
from recon.engine.tiers import MatchProfile
from recon.engine.tiers import run as run_tiers
from recon.engine.tolerance import ToleranceBudget, TolerancePolicy
from recon.engine.verifier import verify

pytestmark = pytest.mark.gate

SIGNS = SETTLEMENT_3WAY.side_signs


@pytest.fixture(scope="module", autouse=True)
def _batches_exist():
    if not (BATCHES / "A" / "labels.json").exists():
        pytest.skip("run `make gen` first — P3 reads the P0 batches")


@pytest.fixture(scope="module")
def sides():
    return {b: load_sides(b) for b in ("A", "B")}


def _run(sides, batch):
    bank, settlement, provenance = sides[batch]
    truth = truth_pairs(BATCHES / batch / "labels.json")
    return bank, settlement, provenance, truth


# --------------------------------------------------------------------------
# the gate proper — the first number
# --------------------------------------------------------------------------


@pytest.mark.parametrize("batch", ["A", "B"])
def test_deterministic_arm_scores_with_zero_false_matches(sides, batch):
    bank, settlement, provenance, truth = _run(sides, batch)
    card = score(deterministic.run(bank, settlement, SETTLEMENT_3WAY, provenance), truth)

    assert card.true_pairs == 22
    assert card.false_matches == 0, "a wrong match corrupts the books; this must stay at zero"
    assert card.false_match_rate == 0.0
    assert card.precision == 1.0
    assert card.auto_match_rate >= 0.90


@pytest.mark.parametrize("batch", ["A", "B"])
def test_baseline_arms_are_scored_on_the_same_ground_truth(sides, batch):
    bank, settlement, _provenance, truth = _run(sides, batch)

    raw = score(securo_baseline.run_raw(bank, settlement), truth)
    grouped = score(securo_baseline.run_grouped(bank, settlement), truth)

    # securo's rule applied to raw rows: a 1:1 exact matcher cannot address an
    # N:1 problem. Zero is the honest score, and the arm says so in its notes.
    assert raw.correct == 0
    assert raw.notes, "an arm that scores zero must carry its caveat beside the number"

    # Handed the grouping, the same rule works. This is the fair comparison.
    assert grouped.correct >= 20
    assert grouped.false_matches == 0


@pytest.mark.parametrize("batch", ["A", "B"])
def test_our_matching_rule_does_not_beat_the_fair_baseline(sides, batch):
    """Recorded because it is true, not because it flatters us.

    Once securo's rule is handed the payout grouping it produces *identical*
    pairs to T0/T1 on this data. The match rate is not our differentiator — the
    grouping is most of the work, and the tail is where the difference lives.
    If a later change makes these diverge, this test should be updated with the
    reason rather than deleted.
    """
    bank, settlement, provenance, _truth = _run(sides, batch)
    ours = deterministic.run(bank, settlement, SETTLEMENT_3WAY, provenance)
    theirs = securo_baseline.run_grouped(bank, settlement)
    assert ours.pairs == theirs.pairs


@pytest.mark.parametrize("batch", ["A", "B"])
def test_what_we_miss_is_what_should_be_missed(sides, batch):
    """The unmatched payouts are exactly the two planted defects that must block
    a match: a duplicated row in the export, and a genuinely ambiguous payout.
    Missing them is correct, so 90.9% is the ceiling at T0/T1, not a shortfall."""
    bank, settlement, provenance, truth = _run(sides, batch)
    result = deterministic.run(bank, settlement, SETTLEMENT_3WAY, provenance)
    labels = json.loads((BATCHES / batch / "labels.json").read_text())
    line_to_payout = {
        v["bank_line"]: k for k, v in labels["payout_membership"].items() if v["bank_line"]
    }

    missed = {line_to_payout[line] for line in set(truth) - set(result.pairs)}
    dup_charge = next(e["subject"] for e in labels["expected_exceptions"] if e["code"] == "E06")
    dup_payout = next(
        pid for pid, v in labels["payout_membership"].items() if dup_charge in v["charges"]
    )
    ambiguous = set(labels["ungrouped_payouts"])

    assert missed == {dup_payout} | ambiguous, (
        f"missed {missed}, expected exactly the E06 payout and the ambiguous one"
    )


@pytest.mark.parametrize("batch", ["A", "B"])
def test_every_reported_match_verifies_independently(sides, batch):
    """A match counts only if the verifier re-derives it from the Records."""
    bank, settlement, provenance, _truth = _run(sides, batch)
    result = deterministic.run(bank, settlement, SETTLEMENT_3WAY, provenance)
    records = {rec.record_id: rec for _, rec in bank + settlement}

    assert result.proofs
    for proof in result.proofs:
        verdict = verify(proof, records, SIGNS)
        assert verdict.proven, f"{proof.proof_id}: {verdict}"
        assert verdict.recomputed_residual == D("0.00")


def test_tolerant_tier_actually_fires(sides):
    """T1 exists to recover truncated references. Until P3 the generator's
    truncation was a no-op on a 10-char id, so T1 had nothing to exercise it and
    would have passed as dead code."""
    bank, settlement, provenance, _truth = _run(sides, "A")
    anchors = [rec for _, rec in bank]
    groups = [rec for _, rec in settlement]
    outcome = run_tiers(anchors, groups, SETTLEMENT_3WAY, provenance)

    tiers = outcome.by_tier()
    assert tiers.get("T1", 0) >= 1, f"T1 never fired: {tiers}"

    labels = json.loads((BATCHES / "A" / "labels.json").read_text())
    truncated = set(labels["truncated_ref_payouts"])
    assert truncated
    t1_refs = {m.group_ref for m in outcome.matches if m.tier is MatchTier.T1_TOLERANT}
    assert t1_refs == truncated, f"T1 matched {t1_refs}, expected the truncated-ref payouts"


def test_ungrouped_records_are_reported_not_silently_dropped(sides):
    bank, settlement, provenance, _truth = _run(sides, "A")
    outcome = run_tiers(
        [r for _, r in bank], [r for _, r in settlement], SETTLEMENT_3WAY, provenance
    )
    assert outcome.ungrouped_records, "the E09 payout's rows should surface as ungrouped"
    assert all(m.group_ref for m in outcome.matches)


# --------------------------------------------------------------------------
# the verifier must refute — otherwise the false-match rate proves nothing
# --------------------------------------------------------------------------


@pytest.fixture
def proven(sides):
    bank, settlement, provenance, _truth = _run(sides, "A")
    result = deterministic.run(bank, settlement, SETTLEMENT_3WAY, provenance)
    records = {rec.record_id: rec for _, rec in bank + settlement}
    return result.proofs[0], records


def _tamper(proof: Proof, **changes) -> Proof:
    return Proof.model_validate({**proof.model_dump(), **changes})


def test_verifier_refutes_an_inflated_leg_subtotal(proven):
    proof, records = proven
    legs = [leg.model_dump() for leg in proof.legs]
    legs[0]["subtotal"] = D(legs[0]["subtotal"]) + D("1000.00")
    verdict = verify(_tamper(proof, legs=legs), records, SIGNS)
    assert not verdict.proven
    assert any("claimed subtotal" in r for r in verdict.reasons)


def test_verifier_refutes_a_residual_that_does_not_follow_from_the_records(proven):
    """The most tempting shallow proxy: trusting the stored residual. A proof
    claiming it closes must be refuted when the records say otherwise."""
    proof, records = proven
    legs = [leg.model_dump() for leg in proof.legs]
    legs[1]["record_ids"] = legs[1]["record_ids"][:-1]  # drop a row, keep the claim
    verdict = verify(_tamper(proof, legs=legs), records, SIGNS)
    assert not verdict.proven
    assert verdict.recomputed_residual != D("0.00")


def test_verifier_refutes_a_record_counted_in_two_legs(proven):
    proof, records = proven
    legs = [leg.model_dump() for leg in proof.legs]
    legs[0]["record_ids"] = [*legs[0]["record_ids"], legs[1]["record_ids"][0]]
    verdict = verify(_tamper(proof, legs=legs), records, SIGNS)
    assert not verdict.proven
    assert any("appears in both" in r for r in verdict.reasons)


def test_verifier_refutes_a_reference_to_a_record_that_does_not_exist(proven):
    proof, records = proven
    legs = [leg.model_dump() for leg in proof.legs]
    legs[1]["record_ids"] = [*legs[1]["record_ids"], "settlement:999999"]
    verdict = verify(_tamper(proof, legs=legs), records, SIGNS)
    assert not verdict.proven
    assert any("not found" in r for r in verdict.reasons)


def test_verifier_refutes_a_leg_holding_records_from_another_side(proven):
    proof, records = proven
    legs = [leg.model_dump() for leg in proof.legs]
    legs[0]["record_ids"] = [legs[1]["record_ids"][0]]
    legs[0]["subtotal"] = str(records[legs[1]["record_ids"][0]].amount)
    verdict = verify(_tamper(proof, legs=legs), records, SIGNS)
    assert not verdict.proven
    assert any("another side" in r for r in verdict.reasons)


def test_verifier_will_not_take_the_sign_convention_from_the_proof(proven):
    """Signs come from the caller. A proof that could pick its own could make
    any set of numbers close."""
    proof, records = proven
    assert not verify(proof, records, {"bank": 1, "settlement": 1}).proven
    assert not verify(proof, records, {"bank": 1}).proven  # side missing entirely


# --------------------------------------------------------------------------
# refusing to guess
# --------------------------------------------------------------------------


def test_tolerant_tier_refuses_when_two_groups_could_absorb_the_credit(sides):
    """Constructed, because batch A has no such case — and untested refusal
    logic is the same hazard as an untested tier. Two groups with identical
    totals and dates must produce no match, not an arbitrary pick."""
    bank, settlement, provenance, _truth = _run(sides, "A")
    labels = json.loads((BATCHES / "A" / "labels.json").read_text())

    truncated = labels["truncated_ref_payouts"][0]
    anchor = next(
        rec
        for _, rec in bank
        if rec.keys["entry_ref"] == labels["payout_membership"][truncated]["bank_line"]
    )
    group = [rec for _, rec in settlement if rec.group_ref == truncated]

    # A twin group: same rows, same dates, same total, different group_ref.
    twin = [
        rec.model_copy(update={"record_id": f"twin:{rec.record_id}", "group_ref": "pout_twin"})
        for rec in group
    ]

    outcome = run_tiers([anchor], [*group, *twin], SETTLEMENT_3WAY, provenance)
    assert outcome.matches == [], (
        "two groups can absorb this credit and the matcher picked one — an "
        "arbitrary pick raises the match rate and corrupts the books"
    )
    assert outcome.unmatched_anchors == [anchor.record_id]


def test_tolerance_budget_is_all_or_nothing():
    budget = ToleranceBudget(allowed=D("0.50"))
    assert budget.consume(D("0.30")) and budget.used == D("0.30")
    assert not budget.consume(D("0.40")), "a residual beyond the remaining budget must be refused"
    assert budget.used == D("0.30"), "a refused consume must spend nothing"
    assert budget.remaining == D("0.20")


def test_exact_tier_will_not_absorb_any_residual():
    """T0 means exact. If it could spend tolerance it would be T1 under another
    name, and the tier recorded in the proof would be misleading."""
    policy = TolerancePolicy(absolute=D("100.00"), date_window_days=3)
    profile = MatchProfile(
        name="t",
        anchor_side="bank",
        group_side="settlement",
        side_signs={"bank": 1, "settlement": -1},
        tolerance=policy,
    )
    from datetime import date as _date

    from recon.contracts import Record

    common = dict(currency="INR", doc_hash="h" * 8, posted_on=_date(2026, 8, 14))
    anchor = Record(
        record_id="b:0",
        side="bank",
        source="b",
        row_ordinal=0,
        amount="100.00",
        source_row_id="g1",
        **common,
    )
    row = Record(
        record_id="s:0",
        side="settlement",
        source="s",
        row_ordinal=0,
        amount="99.00",
        group_ref="g1",
        **common,
    )
    outcome = run_tiers([anchor], [row], profile)
    assert [m.tier for m in outcome.matches] == [MatchTier.T1_TOLERANT], (
        "a 1.00 residual must not be reported as T0 exact"
    )


def test_proof_provenance_follows_the_weakest_intake(sides):
    """Records from a 'declared' intake cannot back a P0 claim."""
    bank, settlement, _provenance, _truth = _run(sides, "A")
    weak = deterministic.run(bank, settlement, SETTLEMENT_3WAY, ProofTier.P3_DECLARED)
    assert weak.proofs
    for proof in weak.proofs:
        assert proof.provenance is ProofTier.P3_DECLARED
        assert proof.declared_gap, "a P3 proof must state its gap"


def test_proof_leg_shape_is_what_a_third_party_needs(sides):
    bank, settlement, provenance, _truth = _run(sides, "A")
    proof = deterministic.run(bank, settlement, SETTLEMENT_3WAY, provenance).proofs[0]
    assert {leg.side for leg in proof.legs} == {"bank", "settlement"}
    assert all(leg.record_ids for leg in proof.legs)
    assert Proof.model_validate_json(proof.model_dump_json()) == proof


def test_leg_subtotals_are_claims_not_authority(proven):
    """`Proof.closes()` reads stored values and is not verification. Pinned so
    nobody later mistakes it for the verifier."""
    proof, records = proven
    tampered = _tamper(proof, residual=D("0.00"), tolerance_allowed=D("999999.00"))
    legs = [leg.model_dump() for leg in tampered.legs]
    legs[0]["subtotal"] = "1.00"
    lying = _tamper(tampered, legs=legs)

    assert lying.closes(), "closes() reads the claim — that is why it is not verification"
    assert not verify(lying, records, SIGNS).proven
