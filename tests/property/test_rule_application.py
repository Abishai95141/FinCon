"""A promoted rule must have an effect, and the effect must be governed.

`promote()` returned a signed record with an evidence hash and nothing read it:
`close()` took no rules and `fires_on` was reached only from the regression
simulator. Every control on the promotion path was deciding whether to grant a
permission that was never exercised — and a control over an effect that does not
happen passes any test written for it.

These pin the four things that must be true once a rule can act.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from bench.run import SETTLEMENT_3WAY, SETTLEMENT_POLICY, TAXONOMY, close, load_sides

from recon.contracts import ProofTier
from recon.contracts.rule import ActionKind, Operator, Rule, RuleStatus
from recon.engine import rulestore
from recon.engine.promotion import MatchHistory, evaluate, regress


def _rule(status: RuleStatus = RuleStatus.PROMOTED, **kw) -> Rule:
    base = dict(
        rule_id="R-TEST-01",
        profile="settlement_3way",
        when=[{"field": "key_occurrence", "op": Operator.GT, "value": "0"}],
        then=[{"kind": ActionKind.SUPPRESS, "reason": "a repeat of an already-asserted event"}],
    )
    base.update(kw)
    rule = Rule(**base)
    return rule if status is RuleStatus.DRAFT else rule.model_copy(update={"status": status})


def _history(batch: str = "A") -> tuple[MatchHistory, list]:
    result = close(batch, rules=[])
    sides = load_sides(batch)
    rows = [rec for _, rec in sides.settlement]
    return (
        MatchHistory(
            anchors=[rec for _, rec in sides.bank],
            group_records=rows,
            records=result.records,
            matches=[type("M", (), {"anchor_id": m.anchor_id})() for m in result.matches],
            exceptions=list(result.exceptions),
        ),
        rows,
    )


def test_a_rule_that_removes_value_from_a_close_is_refused():
    """The gap that let a strictly harmful rule through.

    Suppressing a duplicated export row scored 0 broken, 1 added, no postings
    moved — clean on every dimension the gate had — while against the labels it
    added a false match and destroyed a planted `E06` worth exactly the amount
    it removed. Refused on tier: raw records cannot prove a row is spurious,
    because they contain it.
    """
    history, rows = _history()
    outcome = regress(_rule(), history, SETTLEMENT_3WAY, SETTLEMENT_POLICY, taxonomy=TAXONOMY)

    assert outcome.value_suppressed != Decimal("0.00")
    assert not outcome.broken, "the harm is not a broken match — that is why it got through"

    decision = evaluate(_rule(), outcome, SETTLEMENT_POLICY, induced_on=rows)
    assert not decision.allowed
    assert any(str(outcome.value_suppressed) in r for r in decision.reasons)


def test_exceptions_cleared_counts_exceptions():
    """It was `len(added)` — a field named for exceptions that had never counted
    one, reported in the record a human reads before approving. A rule that
    suppresses nothing and adds nothing must clear nothing."""
    history, _ = _history()
    inert = _rule(when=[{"field": "source", "op": Operator.EQ, "value": "nothing-is-called-this"}])
    outcome = regress(inert, history, SETTLEMENT_3WAY, SETTLEMENT_POLICY, taxonomy=TAXONOMY)

    assert outcome.added == []
    assert outcome.exceptions_cleared == 0
    assert outcome.value_suppressed == Decimal("0.00")


@pytest.mark.parametrize("status", [RuleStatus.DRAFT, RuleStatus.REVOKED])
def test_an_unpromoted_rule_cannot_act(status: RuleStatus):
    """Enforced where the effect happens, not where rules are read. `load()`
    returns only promoted rules, but a caller may hand rules straight to a
    close — and nothing may act on an unapproved one whatever route it took."""
    _, rows = _history()
    applied = rulestore.apply([_rule(status)], rows, profile="settlement_3way")

    assert applied.scope == {}
    assert "R-TEST-01" in applied.unapplied, "silently ignoring it reads identical to applying it"


def test_a_rule_assisted_match_is_p1_and_names_the_rule():
    """The residual closes to zero either way; what differs is whose word the
    zero rests on. Claiming `P0 ARITHMETIC` after a suppression would launder a
    rule into arithmetic, which is what the ladder exists to prevent."""
    result = close("A", rules=[_rule()])
    assisted = [m for m in result.matches if m.proof.provenance is ProofTier.P1_RULE]

    assert assisted, "the rule changed the close but no match records that it did"
    for match in assisted:
        assert match.proof.rule_id == "R-TEST-01"
        assert match.proof.rule_version is not None
        assert match.proof.residual == Decimal("0.00")


def test_a_rules_suppressions_reach_the_decision_log():
    """`close()` handed the journal the caller's scope while the engine matched
    against its own. The two diverged the moment a rule could exclude a row, and
    the log went on describing the mapping it was passed — until `derive`
    refused to finish over inputs no event named."""
    result = close("A", rules=[_rule()])
    suppressed = [rid for rid, why in result.scope.items() if "R-TEST-01" in why]

    assert suppressed, "the rule fired but the close's scope does not record it"
    assert result.ok, "a close whose log cannot account for its own exclusions is not ok"
