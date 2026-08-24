"""Gate P8 — the promotion gate.

Gate: `R-EVIL` is refused, **and** a legitimate narrow rule still promotes. The
second half matters as much as the first — a gate that refuses everything is as
useless as one that refuses nothing, and only the pair together shows the gate
discriminates rather than blocks.

Written before the fix. The attack is live at P7:

    rule R-EVIL  action: set_tolerance -> Rs 1,000,000
    regression:  0 broken, 93 cleared     promotable: True   -> PROMOTED accepted

Two things are wrong with it. The action asks for a hundred thousand times the
policy ceiling and nothing compares them. And the regression report is *shipped
with the rule* — self-reported, never re-run — which is audit finding `F1` in a
different costume: an artifact carrying its own evidence.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal as D

import pytest
from bench.run import SETTLEMENT_POLICY
from pydantic import ValidationError

from recon.contracts import Policy, PolicyViolation, ProofTier, Record, RegressionReport
from recon.contracts.rule import ActionKind, Operator, Predicate, Rule, RuleAction, RuleStatus
from recon.engine.promotion import (
    MatchHistory,
    evaluate,
    promote,
    regress,
    verify_promotion,
)
from recon.engine.tiers import MatchProfile
from recon.engine.tiers import run as run_tiers
from recon.engine.tolerance import TolerancePolicy

pytestmark = pytest.mark.gate


def _policy(**over) -> Policy:
    base = dict(
        policy_id="settlement-in",
        profile="promo_test",
        side_signs={"bank": 1, "settlement": -1},
        tolerance_ceiling="0.50",
        rejection_budget_pct="0.10",
        rounding_threshold="0.01",
        max_added_matches=3,
        approved_by="meera",
        approved_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    return Policy(**{**base, **over})


def _profile(tolerance: str = "0.10") -> MatchProfile:
    return MatchProfile(
        name="promo_test",
        anchor_side="bank",
        group_side="settlement",
        side_signs={"bank": 1, "settlement": -1},
        tolerance=TolerancePolicy(absolute=D(tolerance), date_window_days=3),
    )


def _rec(rid, side, amount, **kw):
    return Record(
        record_id=rid,
        side=side,
        source="s",
        row_ordinal=0,
        posted_on=date(2026, 8, 14),
        amount=amount,
        currency="INR",
        doc_hash="h" * 8,
        **kw,
    )


@pytest.fixture
def history():
    """Two anchors. One already matches exactly. The other sits ₹0.20 away from
    its group — outside the profile's ₹0.10 tolerance, inside the ₹0.50 ceiling,
    so a narrow widening legitimately picks it up and a reckless one does not
    need to."""
    anchors = [
        _rec("b:0", "bank", "100.00", keys={"gateway": "razorpay"}, source_row_id="g0"),
        _rec("b:1", "bank", "200.00", keys={"gateway": "razorpay"}, source_row_id="g1"),
    ]
    groups = [
        _rec("s:0", "settlement", "100.00", group_ref="g0", keys={"gateway": "razorpay"}),
        _rec("s:1", "settlement", "199.80", group_ref="g1", keys={"gateway": "razorpay"}),
        # A memo line: printed by the source, carrying no movement. The one
        # thing a rule may remove on its own authority, and the fixture had no
        # example of it — so "a legitimate suppression still promotes" was
        # demonstrated with a row worth ₹199.80.
        _rec("s:memo", "settlement", "0.00", group_ref="g9", keys={"gateway": "razorpay"}),
    ]
    profile, policy = _profile(), _policy()
    baseline = run_tiers(anchors, groups, profile, ProofTier.P0_ARITHMETIC, policy=policy)
    assert len(baseline.matches) == 1, "b:1 must start unmatched for this fixture to mean anything"
    return MatchHistory(
        anchors=anchors,
        group_records=groups,
        records={r.record_id: r for r in [*anchors, *groups]},
        matches=baseline.matches,
    )


@pytest.fixture
def wide_history(history):
    """The same records, matched under a tolerance wide enough that `b:1` is in
    the history. Narrowing then has something to take away."""
    profile, policy = _profile("0.30"), _policy()
    baseline = run_tiers(
        history.anchors, history.group_records, profile, ProofTier.P0_ARITHMETIC, policy=policy
    )
    assert len(baseline.matches) == 2, "both anchors must match for a narrowing rule to break one"
    return MatchHistory(
        anchors=history.anchors,
        group_records=history.group_records,
        records=history.records,
        matches=baseline.matches,
    )


def _rule(rule_id: str, action: RuleAction, **over) -> Rule:
    base = dict(
        rule_id=rule_id,
        profile="promo_test",
        when=[Predicate(field="keys.gateway", op=Operator.EQ, value="razorpay")],
        then=[action],
    )
    return Rule(**{**base, **over})


# --------------------------------------------------------------------------
# the attack
# --------------------------------------------------------------------------


def test_r_evil_is_refused(history):
    """The rule from the audit. Widening tolerance never *breaks* a match — it
    only adds — so the old gate's `matches_broken == 0` could never see it."""
    evil = _rule("R-EVIL", RuleAction(kind=ActionKind.SET_TOLERANCE, amount="1000000.00"))
    policy = _policy()

    outcome = regress(evil, history, _profile(), policy)
    decision = evaluate(evil, outcome, policy)

    assert not decision.allowed
    assert any("ceiling" in r for r in decision.reasons), decision.reasons
    with pytest.raises(PolicyViolation):
        promote(evil, outcome, policy, actor="agent")


def test_a_legitimate_narrow_rule_still_promotes(history):
    """The half that proves the gate discriminates. ₹0.30 is inside the ceiling
    and picks up exactly the one anchor sitting ₹0.20 away."""
    good = _rule("R-023", RuleAction(kind=ActionKind.SET_TOLERANCE, amount="0.30"))
    policy = _policy()

    outcome = regress(good, history, _profile(), policy)
    assert outcome.added == ["b:1"], outcome.added
    assert outcome.broken == []

    decision = evaluate(good, outcome, policy)
    assert decision.allowed, decision.reasons

    promoted = promote(good, outcome, policy, actor="meera")
    assert promoted.status is RuleStatus.PROMOTED
    assert promoted.promotion is not None


# --------------------------------------------------------------------------
# the report is re-run, not read
# --------------------------------------------------------------------------


def test_a_self_reported_regression_carries_no_authority(history):
    """Audit finding `F1` in a different costume: an artifact carrying its own
    evidence. A rule shipping a spotless report is still re-run."""
    liar = _rule(
        "R-LIAR",
        RuleAction(kind=ActionKind.SET_TOLERANCE, amount="1000000.00"),
        regression=RegressionReport(
            ran_at=datetime.now(UTC),
            matches_checked=1400,
            matches_broken=0,
            exceptions_would_clear=93,
        ),
    )
    policy = _policy()
    outcome = regress(liar, history, _profile(), policy)
    assert not evaluate(liar, outcome, policy).allowed
    assert outcome.matches_checked == len(history.matches), (
        "the outcome must reflect the real history, not the rule's claim of 1400"
    )


def test_added_matches_are_counted_not_just_broken(history):
    """The direction the old gate could not see."""
    widening = _rule("R-W", RuleAction(kind=ActionKind.SET_TOLERANCE, amount="0.30"))
    outcome = regress(widening, history, _profile(), _policy())
    assert outcome.added, "a widening rule adds matches; a gate blind to that is blind to the risk"
    assert hasattr(outcome, "broken")


def test_the_match_delta_is_capped_by_policy(history):
    """A rule may clear exceptions. It may not quietly rewrite the whole close."""
    widening = _rule("R-W", RuleAction(kind=ActionKind.SET_TOLERANCE, amount="0.30"))
    policy = _policy(max_added_matches=0)
    outcome = regress(widening, history, _profile(), policy)
    decision = evaluate(widening, outcome, policy)
    assert not decision.allowed
    assert any("added" in r for r in decision.reasons), decision.reasons


def test_every_added_match_must_verify_under_policy(history):
    """A rule can only add matches that pass the same proof gate as any other."""
    good = _rule("R-023", RuleAction(kind=ActionKind.SET_TOLERANCE, amount="0.30"))
    outcome = regress(good, history, _profile(), _policy())
    assert outcome.unverifiable == [], outcome.unverifiable
    assert outcome.added


def test_a_rule_that_breaks_history_is_refused(wide_history):
    """The one direction the old gate did check. It must keep working.

    Rewritten at P9: this was guarded by `if outcome.broken:` over a history
    where nothing could break — `b:0` matches at T0 with a zero residual, so
    narrowing the tolerance never touched it. The test passed by not running,
    and coverage showed the "would break" branch had never executed. The
    history here is built *wide*, so `b:1` exists only because of tolerance and
    narrowing genuinely takes it away.
    """
    narrowing = _rule("R-N", RuleAction(kind=ActionKind.SET_TOLERANCE, amount="0.00"))
    policy = _policy()
    outcome = regress(narrowing, wide_history, _profile("0.30"), policy)

    assert outcome.broken == ["b:1"], outcome.broken
    decision = evaluate(narrowing, outcome, policy)
    assert not decision.allowed
    assert any("would break" in r for r in decision.reasons), decision.reasons
    with pytest.raises(PolicyViolation):
        promote(narrowing, outcome, policy, actor="meera")


def test_a_promotion_event_is_required_before_one_can_be_re_verified(history):
    """`verify_promotion` on a rule that was never promoted. Untested until P9
    found the branch unexercised — and it is the branch that decides whether an
    unpromoted rule can pass for a promoted one."""
    draft = _rule("R-DRAFT", RuleAction(kind=ActionKind.SET_TOLERANCE, amount="0.30"))
    assert draft.promotion is None
    assert not verify_promotion(draft, history, _profile(), _policy())


# --------------------------------------------------------------------------
# promotion is an event, not a field
# --------------------------------------------------------------------------


def test_a_rule_cannot_reach_promoted_without_a_promotion_event():
    """Before P8, `status=PROMOTED` plus a hand-built `RegressionReport` was
    enough. The report was something anyone could construct."""
    with pytest.raises(ValidationError):
        _rule(
            "R-X",
            RuleAction(kind=ActionKind.SET_TOLERANCE, amount="0.30"),
            status=RuleStatus.PROMOTED,
            regression=RegressionReport(
                ran_at=datetime.now(UTC),
                matches_checked=10,
                matches_broken=0,
                exceptions_would_clear=1,
            ),
        )


def test_the_promotion_event_records_who_what_and_under_which_policy(history):
    good = _rule("R-023", RuleAction(kind=ActionKind.SET_TOLERANCE, amount="0.30"))
    policy = _policy()
    promoted = promote(good, regress(good, history, _profile(), policy), policy, actor="meera")

    event = promoted.promotion
    assert event.promoted_by == "meera"
    assert event.policy_ref == policy.ref
    assert event.evidence_hash
    assert event.matches_added == 1
    assert event.sample_added, "an approver must see what the rule would add"


def test_promotion_requires_an_actor(history):
    good = _rule("R-023", RuleAction(kind=ActionKind.SET_TOLERANCE, amount="0.30"))
    policy = _policy()
    outcome = regress(good, history, _profile(), policy)
    for blank in ("", "   "):
        with pytest.raises((PolicyViolation, ValidationError)):
            promote(good, outcome, policy, actor=blank)


def test_the_evidence_hash_covers_the_inputs(history):
    """A hash that does not change when the evidence changes proves nothing."""
    good = _rule("R-023", RuleAction(kind=ActionKind.SET_TOLERANCE, amount="0.30"))
    policy = _policy()
    first = regress(good, history, _profile(), policy)

    shifted = MatchHistory(
        anchors=history.anchors,
        group_records=[
            r.model_copy(update={"amount": D("199.75")}) if r.record_id == "s:1" else r
            for r in history.group_records
        ],
        records=history.records,
        matches=history.matches,
    )
    second = regress(good, shifted, _profile(), policy)
    assert first.evidence_hash != second.evidence_hash


def test_a_promotion_event_can_be_re_verified_against_history(history):
    """The same propose/verify shape as everything else: the event is a claim,
    and re-running the regression is how it is checked."""
    good = _rule("R-023", RuleAction(kind=ActionKind.SET_TOLERANCE, amount="0.30"))
    policy = _policy()
    promoted = promote(good, regress(good, history, _profile(), policy), policy, actor="meera")

    assert verify_promotion(promoted, history, _profile(), policy)

    # Each guard forged on its own. Changing two at once would pass even if only
    # one check were live — the mutation that stubbed the whole function to True
    # survived the combined version of this test.
    for forgery in (
        {"evidence_hash": "0" * 64},
        {"matches_added": 99},
        {"matches_broken": 7},
        {"policy_ref": "someone-elses-policy@v1"},
    ):
        forged = promoted.model_copy(
            update={"promotion": promoted.promotion.model_copy(update=forgery)}
        )
        assert not verify_promotion(forged, history, _profile(), policy), forgery


def test_a_rule_for_another_profile_cannot_be_promoted_under_this_policy(history):
    stranger = Rule(
        rule_id="R-OTHER",
        profile="gstr2b",
        when=[Predicate(field="keys.gateway", op=Operator.EQ, value="x")],
        then=[RuleAction(kind=ActionKind.SET_TOLERANCE, amount="0.30")],
    )
    policy = _policy()
    with pytest.raises(PolicyViolation, match="profile"):
        promote(stranger, regress(stranger, history, _profile(), policy), policy, actor="meera")


def test_a_suppress_rule_that_destroys_a_match_is_refused(history):
    """Rewritten at P12, and the rewrite is the point.

    This test used to assert that a broad `SUPPRESS` rule was *allowed*, on the
    reasoning that suppression adds no matches so a delta cap never sees it.
    That was true only because `regress` did not simulate suppression at all —
    the rule came back `0 broken, 0 added` because nothing measured it, and the
    test was passing on an unimplemented feature.

    Simulated, the same rule removes every razorpay row and destroys `b:0`'s
    match. Refusing it is correct; passing it never was.
    """
    suppressor = _rule(
        "R-S",
        RuleAction(kind=ActionKind.SUPPRESS, reason="balance summary row"),
    )
    policy = _policy()
    outcome = regress(suppressor, history, _profile(), policy)
    assert outcome.unmodelled == [], "suppress must be a modelled action"
    assert outcome.broken == ["b:0"], outcome.broken
    assert not evaluate(suppressor, outcome, policy).allowed


def test_a_narrow_suppress_rule_still_promotes(history):
    """The other half. A gate that refuses every suppression is as useless as
    one that refuses none.

    This asserted the wrong thing until 2026-08-24: it suppressed `s:1`, worth
    ₹199.80, on the reasoning that the row "backs no match in this history, so
    removing it costs nothing". Breaking no match is not the same as costing
    nothing — that conflation is precisely the blind spot that let a rule
    delete a real discrepancy and score clean. A memo line carrying no movement
    is the case that genuinely costs nothing.
    """
    narrow = Rule(
        rule_id="R-S2",
        profile="promo_test",
        when=[Predicate(field="amount", op=Operator.EQ, value="0.00")],
        then=[RuleAction(kind=ActionKind.SUPPRESS, reason="memo line, no movement")],
    )
    policy = _policy()
    outcome = regress(narrow, history, _profile(), policy)
    assert outcome.broken == []
    assert outcome.added == []
    assert outcome.value_suppressed == D("0.00"), "the point of the case"
    decision = evaluate(narrow, outcome, policy)
    assert decision.allowed, decision.reasons


def test_the_shipped_policy_asset_carries_a_delta_cap():
    assert SETTLEMENT_POLICY.max_added_matches >= 0
