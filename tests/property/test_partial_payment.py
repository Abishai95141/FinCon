"""`E04` — the money that arrived is reconciled, the rest stays owed.

Authored red first: `ADV-11` and `ADV-12` went into the adversarial set and
`E04` into the generator before any implementation existed, and the engine
reported `E14 unexplained` — it had the facts (the reference identifies the
payout, the shortfall is known to the paisa) and threw them away.

The design question — should a partial payment *match*? — was settled by the
benchmark rather than by me: `payout_membership` counts the short-paid pair as
findable, so refusing it scores a miss. `ADV-11` says the same from the domain
side. So it matches, at a tier of its own, with the difference declared as a
number a verifier checks.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from bench.run import BATCHES, SETTLEMENT_POLICY, close

from recon.contracts import MatchTier, ProofTier
from recon.engine.verifier import verify


def _planted(batch: str) -> dict:
    labels = json.loads((BATCHES / batch / "labels.json").read_text())
    return next(e for e in labels["expected_exceptions"] if e["code"] == "E04")


@pytest.mark.parametrize("batch", ["A", "B"])
def test_the_shortfall_is_the_planted_amount_to_the_paisa(batch):
    raised = [e for e in close(batch).exceptions if e.code == "E04"]
    assert len(raised) == 1
    assert str(raised[0].amount) == _planted(batch)["unreconciled"]


@pytest.mark.parametrize("batch", ["A", "B"])
def test_the_payout_matches_and_the_match_says_what_is_missing(batch):
    """Both halves. A refusal would discard a payout the reference identified;
    a silent match would launder the shortfall into a clean close."""
    result = close(batch)
    declared = [m for m in result.matches if m.proof.declared_amount is not None]

    assert len(declared) == 1
    match = declared[0]
    assert match.tier is MatchTier.T4_DECLARED
    assert match.proof.provenance is ProofTier.P3_DECLARED
    assert str(match.proof.declared_amount) == _planted(batch)["unreconciled"]
    assert match.proof.declared_gap, "a number with no reason a human can read"


@pytest.mark.parametrize("batch", ["A", "B"])
def test_the_declared_gap_is_checked_against_the_arithmetic(batch):
    """Prose cannot be verified. The number can: the verifier refuses unless the
    declaration equals the residual the records give, which is what stops
    'declared' from becoming a way to wave any difference through."""
    result = close(batch)
    match = next(m for m in result.matches if m.proof.declared_amount is not None)

    assert verify(match.proof, result.records, SETTLEMENT_POLICY).proven

    lying = match.proof.model_copy(update={"declared_amount": Decimal("1.00")})
    verdict = verify(lying, result.records, SETTLEMENT_POLICY)
    assert not verdict.proven
    assert any("of the proof's own choosing" in r for r in verdict.reasons), verdict.reasons


def test_a_declared_gap_cannot_also_be_absorbed():
    """Stated or absorbed, never both — otherwise a proof could spend tolerance
    and then declare the same difference again."""
    result = close("A")
    match = next(m for m in result.matches if m.proof.declared_amount is not None)

    both = match.proof.model_copy(update={"tolerance_used": Decimal("0.50")})
    verdict = verify(both, result.records, SETTLEMENT_POLICY)
    assert not verdict.proven
    assert any("stated or absorbed" in r for r in verdict.reasons), verdict.reasons


def test_only_a_declared_tier_may_carry_a_declared_residual():
    result = close("A")
    match = next(m for m in result.matches if m.proof.declared_amount is not None)

    laundered = match.proof.model_copy(update={"provenance": ProofTier.P0_ARITHMETIC})
    verdict = verify(laundered, result.records, SETTLEMENT_POLICY)
    assert not verdict.proven
    assert any("may carry one" in r for r in verdict.reasons), verdict.reasons


def test_a_duplicated_row_is_not_claimed_as_a_partial_payment():
    """Found by running it, not by reading it.

    A group carrying a row twice sums to more than its credit and looks exactly
    like short payment — so the first version of this strategy booked the
    duplicated-export payout as `E04`, putting a receivable on a counterparty
    who owed nothing. The money was never short; the export was wrong.
    """
    result = close("A")
    labels = json.loads((BATCHES / "A" / "labels.json").read_text())
    dup_charge = next(e["subject"] for e in labels["expected_exceptions"] if e["code"] == "E06")
    dup_payout = next(
        pid for pid, v in labels["payout_membership"].items() if dup_charge in v["charges"]
    )

    raised = [e for e in result.exceptions if e.code == "E04"]
    assert len(raised) == 1
    named = {result.records[r].group_ref for r in raised[0].record_ids if r in result.records}
    assert dup_payout not in named, "the duplicated payout was booked as a partial payment"


def test_the_shortfall_is_not_posted_against_a_bank_that_never_received_it():
    """The anchor matched, so its cash is already on the books. Posting the
    shortfall against BANK would credit the bank twice for money it received
    once — and invariant 1 is what notices."""
    result = close("A")
    raised = next(e for e in result.exceptions if e.code == "E04")

    assert any(raised.exception_id in note for note in result.not_posted)
    assert result.ok, "the books did not balance"


def test_an_overpayment_is_not_a_partial_payment():
    """`E05` is a credit balance, not a receivable, and the strategy declines it
    rather than guessing. Asserted structurally because the corpus has no
    overpayment to run against — a gap worth naming rather than leaving as a
    passing test that never executed the branch."""
    import inspect

    from recon.engine import strategies

    source = inspect.getsource(strategies._partial_payment)
    assert "residual >= 0" in source and "E05" in source


def test_the_driver_refuses_a_strategy_that_declares_a_number_of_its_own(monkeypatch):
    """The guard that cannot fire while every shipped strategy is honest.

    `_partial_payment` derives its declared amount from the same residual the
    driver recomputes, so the two always agree and deleting the check changes
    nothing — it survived its own mutant. The check exists for a strategy that
    is *wrong*, and a strategy that is wrong is what has to be constructed.
    """
    from dataclasses import replace as _replace
    from decimal import Decimal as D

    from bench.run import SETTLEMENT_3WAY, load_sides

    from recon.contracts import MatchTier
    from recon.engine import strategies, tiers

    def _liar(offer):
        ref = offer.anchor.source_row_id or ""
        if ref not in offer.available:
            return None
        return strategies.Proposal(ref, MatchTier.T4_DECLARED, declared=D("1.00"), code="E04")

    monkeypatch.setitem(strategies.STRATEGIES, "liar", _liar)
    sides = load_sides("A")
    run = tiers.run(
        [r for _, r in sides.anchors],
        [r for _, r in sides.settlement],
        _replace(SETTLEMENT_3WAY, strategies=("liar",)),
        out_of_scope=sides.scope,
    )

    assert not run.matches, (
        "a strategy declared ₹1.00 against residuals that are nothing of the sort "
        "and the driver took its word for it"
    )
