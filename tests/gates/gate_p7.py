"""Gate P7 — policy and the constraint layer.

Gate: every attack from the control-plane audit is reproduced here as a test and
refused.

**These were written before the fix and they failed.** That order matters: a test
authored after the code it checks tends to assert what the code already does.
Each one below reproduces a bypass that was live at P6 —

    verify(proof, records, {"bank": 0, "settlement": 0})        -> PROVEN   F2
    proof declaring tolerance_allowed 9999999, residual 7466.19 -> PROVEN   F1
    reject rule discarding 251 of 517 rows                      -> ok=True  F4
    journal entry off by 0.005                                  -> blocked=False

The root cause they share: the system checked artifacts against themselves and
took its policy from whoever called it. Policy is now a separate object the
proposer cannot supply.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal as D
from pathlib import Path

import pytest
from bench.arms import deterministic
from bench.run import BATCHES, SETTLEMENT_3WAY, load_sides
from pydantic import ValidationError

from recon.contracts import AdapterSpec, Proof
from recon.contracts.policy import Policy, PolicyViolation
from recon.engine.tiers import MatchProfile
from recon.engine.tiers import run as run_tiers
from recon.engine.tolerance import TolerancePolicy
from recon.engine.verifier import verify
from recon.intake import ADAPTER_DIR, ingest, load_spec
from recon.ledger.accounts import SETTLEMENT_CHART
from recon.ledger.accounts import AccountRole as R
from recon.ledger.beancount_io import JournalEntry, Posting, post_and_assert

pytestmark = pytest.mark.gate

WINDOW = (date(2026, 7, 1), date(2026, 10, 31))


def _policy(**over) -> Policy:
    base = dict(
        policy_id="settlement-in",
        profile="settlement_3way",
        side_signs={"bank": 1, "settlement": -1},
        tolerance_ceiling="0.50",
        rejection_budget_pct="0.10",
        rounding_threshold="0.01",
        approved_by="meera",
        approved_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    return Policy(**{**base, **over})


@pytest.fixture(scope="module", autouse=True)
def _batches():
    if not (BATCHES / "A" / "labels.json").exists():
        pytest.skip("run `make gen` first")


@pytest.fixture(scope="module")
def proven():
    bank, settlement, provenance = load_sides("A").in_scope()
    result = deterministic.run(bank, settlement, SETTLEMENT_3WAY, _policy(), provenance)
    records = {rec.record_id: rec for _, rec in bank + settlement}
    return result.proofs[0], records


def _tamper(proof: Proof, **changes) -> Proof:
    return Proof.model_validate({**proof.model_dump(), **changes})


# --------------------------------------------------------------------------
# F1 — a proof may no longer declare its own permission
# --------------------------------------------------------------------------


def test_f1_a_proof_cannot_grant_itself_a_tolerance_policy_forbids(proven):
    """Was PROVEN at P6. `verify()` read `tolerance_allowed` out of the proof it
    was verifying, so a forged proof declaring 9999999 passed with any residual."""
    proof, records = proven
    legs = [leg.model_dump() for leg in proof.legs]
    legs[1]["record_ids"] = legs[1]["record_ids"][:-2]
    subtotal = sum(records[r].amount for r in legs[1]["record_ids"])
    legs[1]["subtotal"] = str(subtotal)
    residual = proof.legs[0].subtotal - subtotal

    forged = _tamper(
        proof,
        legs=legs,
        residual=str(residual),
        tolerance_allowed="9999999.00",
        tolerance_used=str(abs(residual)),
    )
    assert abs(residual) > D("0.50"), "the residual must exceed the real ceiling"

    verdict = verify(forged, records, _policy())
    assert not verdict.proven
    assert any("ceiling" in r for r in verdict.reasons), verdict.reasons


def test_a_proof_within_the_ceiling_still_verifies(proven):
    """The fix must not refuse honest proofs."""
    proof, records = proven
    assert verify(proof, records, _policy()).proven


# --------------------------------------------------------------------------
# F2 — the sign convention comes from policy, not the caller
# --------------------------------------------------------------------------


def test_f2_zero_signs_are_unrepresentable_in_policy():
    """Was PROVEN at P6: `side_signs={0, 0}` made every residual zero, so every
    match verified forever. Nothing validated the signs because `MatchProfile`
    had no validators at all."""
    with pytest.raises(ValidationError):
        _policy(side_signs={"bank": 0, "settlement": 0})
    for bad in ({"bank": 2, "settlement": -1}, {"bank": 1, "settlement": 0}):
        with pytest.raises(ValidationError):
            _policy(side_signs=bad)


def test_f2_a_profile_whose_signs_disagree_with_policy_refuses_to_run():
    """The profile is a proposal; policy is authority. A disagreement is caught
    before a single match is attempted, not discovered afterwards."""
    rogue = MatchProfile(
        name="settlement_3way",
        anchor_side="bank",
        group_side="settlement",
        side_signs={"bank": 1, "settlement": 1},
        tolerance=TolerancePolicy(absolute=D("0.50"), date_window_days=3),
    )
    with pytest.raises(PolicyViolation, match="sign"):
        run_tiers([], [], rogue, policy=_policy())


def test_f2_a_profile_cannot_widen_its_own_tolerance_past_the_ceiling():
    greedy = MatchProfile(
        name="settlement_3way",
        anchor_side="bank",
        group_side="settlement",
        side_signs={"bank": 1, "settlement": -1},
        tolerance=TolerancePolicy(absolute=D("5000.00"), date_window_days=3),
    )
    with pytest.raises(PolicyViolation, match="ceiling"):
        run_tiers([], [], greedy, policy=_policy())


def test_f2_profile_signs_must_be_plus_or_minus_one():
    """The validator `MatchProfile` never had. It is a dataclass rather than a
    contract model, so it raises ValueError — policy remains the authority; this
    just stops an obviously broken proposal earlier and with a clearer message."""
    for bad in ({"bank": 0, "settlement": -1}, {"bank": 1, "settlement": 3}):
        with pytest.raises(ValueError, match="must be"):
            MatchProfile(name="p", anchor_side="bank", group_side="settlement", side_signs=bad)


def test_verify_refuses_a_policy_that_does_not_cover_a_side(proven):
    proof, records = proven
    verdict = verify(proof, records, _policy(side_signs={"bank": 1}))
    assert not verdict.proven
    assert any("no sign" in r for r in verdict.reasons)


# --------------------------------------------------------------------------
# F4 — a reasoned rejection is still bounded
# --------------------------------------------------------------------------


def test_f4_a_reject_rule_cannot_discard_half_the_file():
    """Was `declared / ok=True` at P6: row conservation asked whether each
    departing row carried a reason, never whether the departures were justified.
    251 of 517 rows discarded and the intake reported fine."""
    raw = json.loads((ADAPTER_DIR / "gateway-settlement.json").read_text())
    raw["reject"].append(
        {
            "when": "column_matches",
            "column": "row_type",
            "pattern": "FEE",
            "reason": "fees_are_not_settlement_rows",
        }
    )
    result = ingest(
        AdapterSpec.model_validate(raw),
        BATCHES / "A" / "settlement.csv",
        WINDOW,
        policy=_policy(),
    )
    assert not result.ok
    assert result.proof.strength == "failed"
    detail = next(c.detail for c in result.proof.failed if c.name == "rejection_budget")
    assert "budget" in detail and "%" in detail


def test_f4_the_normal_two_blank_footer_rows_stay_within_budget():
    """2 of 28 is 7%, under a 10% budget. The fix must not fail a good run."""
    result = ingest(
        load_spec("icici-current"),
        BATCHES / "A" / "bank_icici.csv",
        WINDOW,
        policy=_policy(),
    )
    assert result.ok
    assert result.proof.strength == "verified"


def test_f4_budget_is_skipped_not_assumed_when_no_policy_is_supplied():
    """A check that silently passes without its policy is the F1 shape again."""
    result = ingest(load_spec("icici-current"), BATCHES / "A" / "bank_icici.csv", WINDOW)
    budget = next(c for c in result.proof.checks if c.name == "rejection_budget")
    assert budget.status.value == "skip"
    assert "no policy" in budget.detail


# --------------------------------------------------------------------------
# sub-paisa residue
# --------------------------------------------------------------------------


def test_sub_paisa_residue_no_longer_posts_silently():
    """Was `blocked=False`, zero errors at P6 — beancount's own default tolerance
    absorbed it. Build-plan problem P16, never built until now."""
    drifting = JournalEntry(
        "M-1",
        date(2026, 8, 14),
        "residue",
        [Posting(R.BANK, D("100.005")), Posting(R.INCOME, D("-100.00"))],
    )
    result = post_and_assert(
        [drifting], SETTLEMENT_CHART, date(2026, 8, 1), date(2026, 8, 31), policy=_policy()
    )
    assert not result.blocked, "0.005 is inside the 0.01 threshold — it should absorb"
    # NOT `"Expenses:Rounding" in text` — every chart account appears in the
    # `open` directives, so that assertion passed even with rounding disabled.
    # The metadata key only exists on an entry the rounding path actually
    # touched.
    assert 'rounding: "' in result.text, "the residue must be posted, not swallowed"
    assert "Expenses:Rounding  " in result.text, "a rounding posting, not just the account"


def test_residue_above_the_threshold_blocks_rather_than_rounding():
    big = JournalEntry(
        "M-2",
        date(2026, 8, 14),
        "not rounding",
        [Posting(R.BANK, D("105.00")), Posting(R.INCOME, D("-100.00"))],
    )
    result = post_and_assert(
        [big], SETTLEMENT_CHART, date(2026, 8, 1), date(2026, 8, 31), policy=_policy()
    )
    assert result.blocked
    assert any("threshold" in e.message or "rounding" in e.message for e in result.errors), (
        result.errors
    )


# --------------------------------------------------------------------------
# the policy object itself
# --------------------------------------------------------------------------


def test_policy_must_carry_a_name_and_a_date():
    """Unapproved policy is not policy — it is configuration wearing the word."""
    with pytest.raises(ValidationError):
        Policy(
            policy_id="p",
            profile="settlement_3way",
            side_signs={"bank": 1, "settlement": -1},
            tolerance_ceiling="0.50",
            rejection_budget_pct="0.10",
            rounding_threshold="0.01",
        )


def test_policy_rejects_a_float_anywhere():
    with pytest.raises(ValidationError):
        _policy(tolerance_ceiling=0.5)
    with pytest.raises(ValidationError):
        _policy(rounding_threshold=0.01)


def test_policy_rejects_an_impossible_budget():
    for bad in ("-0.1", "1.5"):
        with pytest.raises(ValidationError):
            _policy(rejection_budget_pct=bad)


def test_policy_is_frozen_so_a_caller_cannot_edit_it_mid_run():
    policy = _policy()
    with pytest.raises(ValidationError):
        policy.tolerance_ceiling = D("9999.00")


def test_policy_is_versioned_and_travels_in_the_verdict(proven):
    """A verdict that does not say which policy it was judged under cannot be
    reproduced later."""
    proof, records = proven
    verdict = verify(proof, records, _policy())
    assert verdict.policy_ref == "settlement-in@v1"


# --------------------------------------------------------------------------
# the honest path is unchanged
# --------------------------------------------------------------------------


@pytest.mark.parametrize("batch", ["A", "B"])
def test_p3_numbers_survive_the_policy_layer(batch):
    bank, settlement, provenance = load_sides(batch).in_scope()
    outcome = run_tiers(
        [r for _, r in bank],
        [r for _, r in settlement],
        SETTLEMENT_3WAY,
        provenance,
        policy=_policy(),
    )
    tiers = outcome.by_tier()
    assert tiers.get("T0", 0) + tiers.get("T1", 0) == 20
    outcome.completeness.raise_if_incomplete()
    records = {r.record_id: r for _, r in bank + settlement}
    for match in outcome.matches:
        assert verify(match.proof, records, _policy()).proven


def test_a_full_close_runs_end_to_end_under_policy():
    """Intake, match, verify and post, all governed by one policy object."""
    policy = _policy()
    bank, settlement, provenance = load_sides("A").in_scope()
    outcome = run_tiers(
        [r for _, r in bank],
        [r for _, r in settlement],
        SETTLEMENT_3WAY,
        provenance,
        policy=policy,
    )
    assert outcome.matches
    assert outcome.completeness.complete
    ledger = post_and_assert(
        [
            JournalEntry(
                "M-1",
                date(2026, 8, 14),
                "clean",
                [Posting(R.BANK, D("100.00")), Posting(R.INCOME, D("-100.00"))],
            )
        ],
        SETTLEMENT_CHART,
        date(2026, 8, 1),
        date(2026, 8, 31),
        {R.BANK: D("100.00")},
        policy=policy,
    )
    assert not ledger.blocked, ledger.errors


def test_shipped_policy_asset_loads_and_governs():
    """Policy is an asset on disk, like an adapter spec — reviewable in a diff."""
    policy = Policy.model_validate_json(
        Path("data/policy/settlement_3way.json").read_text(encoding="utf-8")
    )
    assert policy.approved_by
    assert policy.sign_for("bank") == 1
    assert policy.sign_for("settlement") == -1
    with pytest.raises(PolicyViolation):
        policy.sign_for("nonexistent")
