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


def test_exceptions_cleared_counts_exceptions_and_not_added_matches():
    """It was `len(added)` — a field named for exceptions that had never counted
    one, reported in the record a human reads before approving.

    Asserting it on an inert rule proves nothing: no matches added and no
    exceptions cleared are both zero, so the alias passes too. This is the case
    where the two numbers genuinely differ, which is the only kind that can tell
    a real delta from a relabelled one.
    """
    history, _ = _history()
    outcome = regress(_rule(), history, SETTLEMENT_3WAY, SETTLEMENT_POLICY, taxonomy=TAXONOMY)

    assert len(outcome.added) == 1
    assert outcome.exceptions_cleared == 2, (
        "suppressing the duplicate resolves the payout's own exception and the "
        "one raised over its unclaimed group; only one match is added"
    )


def test_an_inert_rule_clears_nothing_and_removes_nothing():
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


def test_the_model_is_only_offered_actions_that_are_measured_and_performed():
    """`raise_advisory` was in the tool schema, in `MODELLED_ACTIONS`, and in no
    implementation. A rule using it promoted with zero objections and changed
    nothing — the cleanest-scoring rule the gate had ever seen, and a no-op.

    Three hand-typed lists is three chances to drift, so the schema takes the
    intersection of the two that are enforced.
    """
    from recon.engine.promotion import MODELLED_ACTIONS
    from recon.engine.rulestore import APPLIED_ACTIONS
    from recon.triage.induce import SCHEMA, applicable_actions

    offered = set(SCHEMA["properties"]["then"]["items"]["properties"]["kind"]["enum"])
    assert offered == set(applicable_actions())
    assert offered == {k.value for k in APPLIED_ACTIONS} & set(MODELLED_ACTIONS)


@pytest.mark.parametrize(
    ("action", "detectable"),
    [
        ({"kind": "set_tolerance", "amount": "500.00"}, "matches"),
        ({"kind": "normalize_key", "target": "gateway", "value": "x"}, "matches"),
        ({"kind": "raise_advisory", "target": "E06", "reason": "a repeat"}, "codes"),
        ({"kind": "suppress", "reason": "a repeat"}, "matches"),
    ],
)
def test_every_offered_action_changes_something_at_close(action: dict, detectable: str):
    """The check that would have caught it. An action a close cannot perform is
    indistinguishable from one that works — `unapplied` named three of them and
    nothing read the report."""
    field = "key_occurrence" if action["kind"] in {"raise_advisory", "suppress"} else "side"
    value = "0" if field == "key_occurrence" else "settlement"
    op = Operator.GT if field == "key_occurrence" else Operator.EQ
    rule = _rule(when=[{"field": field, "op": op, "value": value}], then=[action])

    off, on = close("A", rules=[]), close("A", rules=[rule])
    if detectable == "matches":
        assert len(on.matches) != len(off.matches) or len(on.exceptions) != len(off.exceptions)
    else:
        assert sorted(e.code for e in on.exceptions) != sorted(e.code for e in off.exceptions)


def test_book_to_reaches_a_posting():
    """Measured by a posting delta at promotion and reaching no posting at close
    — a rule approved for rerouting money it never rerouted."""
    rule = _rule(
        when=[{"field": "side", "op": Operator.EQ, "value": "bank"}],
        then=[{"kind": ActionKind.BOOK_TO, "target": "rounding"}],
    )
    off, on = close("A", rules=[]), close("A", rules=[rule])
    roles = lambda r: sorted({p.role.value for e in r.entries for p in e.postings})  # noqa: E731
    assert "rounding" in roles(on) and "rounding" not in roles(off)
