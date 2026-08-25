"""Gate P5 — T2 subset-sum + ambiguity detection.

Gate: the planted ambiguous payout raises `E09` rather than a confident wrong
answer, and solver timeouts surface as `E13` rather than silent non-matches.

The three traps this gate was written against, from the P4 hand-off note:
finding one solution is not proving it unique; assert against the labelled
subset ids rather than a count; and bound the search *before* it is needed, so
the capacity path is exercised rather than dead.
"""

from __future__ import annotations

import json
import pathlib
from datetime import date as _date
from decimal import Decimal as D

import pytest
from bench.run import BATCHES, SETTLEMENT_3WAY, SETTLEMENT_POLICY, load_sides

from recon.contracts import ExceptionCode, MatchTier, ProofTier, Record
from recon.engine.subsetsum import Outcome, SolverBounds, solve
from recon.engine.tiers import run as run_tiers
from recon.engine.verifier import verify

pytestmark = pytest.mark.gate


@pytest.fixture(scope="module", autouse=True)
def _batches_exist():
    if not (BATCHES / "A" / "labels.json").exists():
        pytest.skip("run `make gen` first — P5 reads the P0 batches")


@pytest.fixture(scope="module")
def env():
    out = {}
    for batch in ("A", "B"):
        bank, settlement, provenance = load_sides(batch).in_scope()
        labels = json.loads((BATCHES / batch / "labels.json").read_text())
        out[batch] = (bank, settlement, provenance, labels)
    return out


def _ambiguous_anchor(bank, labels):
    payout = labels["ungrouped_payouts"][0]
    line = labels["payout_membership"][payout]["bank_line"]
    return next(rec for _, rec in bank if rec.keys["entry_ref"] == line), payout


def _ext(settlement):
    return {rec.record_id: rec.source_row_id for _, rec in settlement}


def _record(rid: str, amount: str, payment: str = "p") -> Record:
    return Record(
        record_id=rid,
        side="settlement",
        source="s",
        row_ordinal=int(rid.rsplit(":", 1)[-1]) if ":" in rid else 0,
        posted_on=_date(2026, 8, 14),
        amount=amount,
        currency="INR",
        keys={"payment_id": payment},
        doc_hash="h" * 8,
    )


# --------------------------------------------------------------------------
# the gate proper
# --------------------------------------------------------------------------


@pytest.mark.parametrize("batch", ["A", "B"])
def test_ambiguous_payout_raises_e09_with_the_labelled_subsets(env, batch):
    """Asserted against the ids in `labels.json`, not against a count — a count
    would pass on two subsets that happen to be the wrong two."""
    bank, settlement, provenance, labels = env[batch]
    outcome = run_tiers(
        [r for _, r in bank], [r for _, r in settlement], SETTLEMENT_3WAY, provenance
    )

    e09 = [e for e in outcome.exceptions if e.code == ExceptionCode.E09_NETTING_AMBIGUITY]
    assert len(e09) == 1
    exc = e09[0]
    assert exc.blocks_close
    from recon.contracts import TaxonomyRegistry

    taxonomy = TaxonomyRegistry.model_validate_json(
        pathlib.Path("data/taxonomy/codes.json").read_text(encoding="utf-8")
    )
    assert taxonomy.escalates(exc.code)

    ext = _ext(settlement)
    got = sorted(
        sorted(x for x in (ext[r] for r in subset) if x.startswith("ch_"))
        for subset in exc.alternatives
    )
    expected = sorted(
        sorted(s)
        for s in next(e for e in labels["expected_exceptions"] if e["code"] == "E09")[
            "ambiguous_subsets"
        ]
    )
    assert got == expected, f"solver found {got}, labels say {expected}"


@pytest.mark.parametrize("batch", ["A", "B"])
def test_the_ambiguous_credit_is_never_committed_as_a_match(env, batch):
    """The whole point. A confident wrong answer here is worse than no answer."""
    bank, settlement, provenance, labels = env[batch]
    anchor, _payout = _ambiguous_anchor(bank, labels)
    outcome = run_tiers(
        [r for _, r in bank], [r for _, r in settlement], SETTLEMENT_3WAY, provenance
    )
    assert anchor.record_id not in {m.anchor_id for m in outcome.matches}
    assert any(anchor.record_id in e.record_ids for e in outcome.exceptions)


def test_t2_commits_only_on_a_proven_unique_subset(env):
    """A unique subset does become a T2 match, and its proof verifies — so the
    refusals above are refusals, not an inability to match at all."""
    bank, settlement, provenance, labels = env["A"]
    anchor, _ = _ambiguous_anchor(bank, labels)
    pool = [r for _, r in settlement if r.group_ref is None]

    # Half the pool: exactly one subset now sums to that half's total.
    half = sorted(pool, key=lambda r: r.record_id)[:4]
    target = sum(r.amount for r in half)
    stand_in = anchor.model_copy(update={"amount": target, "record_id": "bank:solo"})

    outcome = run_tiers([stand_in], half, SETTLEMENT_3WAY, provenance)
    assert [m.tier for m in outcome.matches] == [MatchTier.T2_SUBSET_SUM]
    assert outcome.exceptions == []

    match = outcome.matches[0]
    records = {r.record_id: r for r in [stand_in, *half]}
    assert verify(match.proof, records, SETTLEMENT_POLICY).proven


# --------------------------------------------------------------------------
# capacity limits must never read as data findings
# --------------------------------------------------------------------------


def test_stopping_early_reports_unproven_not_unique(env):
    """Trap 1. With the enumeration capped at one, the solver finds a subset —
    and must not call it unique."""
    bank, settlement, _p, labels = env["A"]
    anchor, _ = _ambiguous_anchor(bank, labels)
    pool = [r for _, r in settlement if r.group_ref is None]

    capped = solve(
        anchor.amount, pool, D("0.50"), SolverBounds(max_solutions=1), cohesion_key="payment_id"
    )
    assert capped.outcome is Outcome.UNPROVEN
    assert not capped.proven_unique
    assert capped.is_capacity_limit
    assert "max_solutions" in capped.bound_hit

    uncapped = solve(anchor.amount, pool, D("0.50"), cohesion_key="payment_id")
    assert uncapped.outcome is Outcome.AMBIGUOUS
    assert len(uncapped.solutions) == 2


def test_unproven_uniqueness_becomes_e13_not_a_match(env):
    """A bound stopped the search, so uniqueness was not established. Committing
    would be a confident answer we cannot back; calling it E09 would blame the
    data for our compute limit."""
    bank, settlement, provenance, labels = env["A"]
    anchor, _ = _ambiguous_anchor(bank, labels)
    pool = [r for _, r in settlement if r.group_ref is None]
    tight = SETTLEMENT_3WAY.__class__(
        **{**SETTLEMENT_3WAY.__dict__, "solver_bounds": SolverBounds(max_solutions=1)}
    )

    outcome = run_tiers([anchor], pool, tight, provenance)
    assert outcome.matches == []
    assert [e.code for e in outcome.exceptions] == [ExceptionCode.E13_SOLVER_TIMEOUT]
    assert "compute bound" in outcome.exceptions[0].hypothesis


def test_too_many_candidates_is_refused_up_front_as_e13(env):
    """Trap 3. Refusing names its bound; hanging does not."""
    _bank, _s, provenance, _labels = env["A"]
    pool = [_record(f"s:{i}", "100.00", f"p{i}") for i in range(60)]
    anchor = Record(
        record_id="bank:big",
        side="bank",
        source="b",
        row_ordinal=0,
        posted_on=_date(2026, 8, 14),
        amount="500.00",
        currency="INR",
        keys={"gateway": "razorpay"},
        doc_hash="h" * 8,
    )
    bounded = SETTLEMENT_3WAY.__class__(
        **{**SETTLEMENT_3WAY.__dict__, "solver_bounds": SolverBounds(max_candidates=10)}
    )

    outcome = run_tiers([anchor], pool, bounded, provenance)
    assert outcome.matches == []
    assert [e.code for e in outcome.exceptions] == [ExceptionCode.E13_SOLVER_TIMEOUT]
    assert "max_candidates" in outcome.exceptions[0].evidence[-1]


def test_t2_never_produces_a_silent_non_match(env):
    """Every anchor T2 fails to commit leaves an exception behind. A quiet drop
    would look identical to a clean run on the scorecard."""
    bank, settlement, provenance, labels = env["A"]
    outcome = run_tiers(
        [r for _, r in bank], [r for _, r in settlement], SETTLEMENT_3WAY, provenance
    )
    anchor, _ = _ambiguous_anchor(bank, labels)
    explained = {rid for e in outcome.exceptions for rid in e.record_ids}
    assert anchor.record_id in explained


# --------------------------------------------------------------------------
# solver properties
# --------------------------------------------------------------------------


def test_cohesion_stops_the_solver_inventing_subsets(env):
    """Without it the solver mixes a charge from one group with a fee from
    another — more ambiguity than the data holds, and a space that grows
    combinatorially with the number of fee rows."""
    bank, settlement, _p, labels = env["A"]
    anchor, _ = _ambiguous_anchor(bank, labels)
    pool = [r for _, r in settlement if r.group_ref is None]

    loose = solve(anchor.amount, pool, D("0.50"))
    tight = solve(anchor.amount, pool, D("0.50"), cohesion_key="payment_id")
    assert len(loose.solutions) > len(tight.solutions) == 2


def test_solver_is_deterministic(env):
    bank, settlement, _p, labels = env["A"]
    anchor, _ = _ambiguous_anchor(bank, labels)
    pool = [r for _, r in settlement if r.group_ref is None]
    first = solve(anchor.amount, pool, D("0.50"), cohesion_key="payment_id")
    second = solve(anchor.amount, pool, D("0.50"), cohesion_key="payment_id")
    assert first.solutions == second.solutions


def test_amounts_cross_the_solver_as_integer_minor_units():
    """CP-SAT is integer-only. Rounding through float would reintroduce the
    drift the ledger exists to avoid — a sub-paisa error on 200 rows is real
    money."""
    pool = [_record("s:0", "0.07", "a"), _record("s:1", "0.14", "b"), _record("s:2", "0.21", "c")]
    exact = solve(D("0.21"), pool, D("0.00"), cohesion_key="payment_id")
    assert exact.outcome is not Outcome.NONE
    assert all(
        sum(r.amount for r in pool if r.record_id in set(sol)) == D("0.21")
        for sol in exact.solutions
    )


def test_no_solution_is_reported_as_none_not_as_a_capacity_limit():
    pool = [_record("s:0", "10.00", "a"), _record("s:1", "20.00", "b")]
    result = solve(D("999999.99"), pool, D("0.00"))
    assert result.outcome is Outcome.NONE
    assert not result.is_capacity_limit
    assert result.bound_hit is None


def test_empty_subset_is_not_an_answer():
    pool = [_record("s:0", "10.00", "a")]
    result = solve(D("0.00"), pool, D("0.00"))
    assert all(sol for sol in result.solutions)


@pytest.mark.parametrize("batch", ["A", "B"])
def test_t2_does_not_disturb_t0_or_t1(env, batch):
    """T2 runs only on anchors the earlier tiers left, and only over records the
    source never grouped."""
    bank, settlement, provenance, _labels = env[batch]
    anchors = [r for _, r in bank]
    groups = [r for _, r in settlement]
    outcome = run_tiers(anchors, groups, SETTLEMENT_3WAY, provenance)
    tiers = outcome.by_tier()
    # Total, not a per-batch split: A is 18/2 and B is 19/1 depending on how
    # many references the generator truncated. Pinning the split would make
    # this a test about the seed rather than about T2 leaving T0/T1 alone.
    # 20 -> 19 when `E04` was planted (2026-08-25): a bank credit short of its
    # payout does not match, correctly. Returns to 20 when the partial-payment
    # strategy lands — the labels count that pair as findable.
    assert tiers.get("T0", 0) + tiers.get("T1", 0) == 19
    assert tiers.get("T1", 0) >= 1, "the tolerant tier must still fire"
    ungrouped = {r.record_id for r in groups if not r.group_ref}
    for match in outcome.matches:
        if match.tier is not MatchTier.T2_SUBSET_SUM:
            assert not (set(match.group_ids) & ungrouped)


def test_t2_proofs_carry_the_subset_sum_tier(env):
    bank, settlement, _provenance, labels = env["A"]
    anchor, _ = _ambiguous_anchor(bank, labels)
    pool = sorted((r for _, r in settlement if r.group_ref is None), key=lambda r: r.record_id)[:4]
    stand_in = anchor.model_copy(
        update={"amount": sum(r.amount for r in pool), "record_id": "bank:solo"}
    )
    outcome = run_tiers([stand_in], pool, SETTLEMENT_3WAY, ProofTier.P0_ARITHMETIC)
    assert outcome.matches
    proof = outcome.matches[0].proof
    assert proof.tier is MatchTier.T2_SUBSET_SUM
    assert proof.provenance is ProofTier.P0_ARITHMETIC
