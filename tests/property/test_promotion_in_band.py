"""A rule's approval is checked where it acts, not only where it was granted.

`engine/promotion.py` was 20/20 never executed in a close. It produced a signed
record with an approver, a policy reference and an evidence hash, and nothing
downstream read any of it: `rulestore.load` checked `status == PROMOTED` and
stopped there. Two things followed, both measured rather than supposed:

- a rule approved under `some-other-policy@v99` acted unchanged in a close
  governed by `settlement-in@v1`;
- a promoted suppress rule aimed at a matched group took a close from 20 matches
  to 19, with `ok=True`, no inert rules, and nothing flagged anywhere.

The second is invariant 5 with a batch in front of it. Promotion measured
breakage against the history the rule was promoted on; nobody measured it
against the close being run.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest
from bench.run import close
from pydantic import ValidationError

from recon.contracts.rule import (
    ActionKind,
    Operator,
    Predicate,
    Rule,
    RuleAction,
    RuleStatus,
)
from recon.engine.promotion import admissible, broken_by_rules
from tests.conftest import promoted

DEDUP = [Predicate(field="key_occurrence", op=Operator.GT, value="0")]
ADVISORY = [RuleAction(kind=ActionKind.RAISE_ADVISORY, target="E06", reason="a repeat")]


def _rule(rule_id: str, when=None, then=None) -> Rule:
    return Rule(
        rule_id=rule_id, profile="settlement_3way", when=when or DEDUP, then=then or ADVISORY
    )


def test_promotion_actually_executes_during_a_close():
    """The literal claim. `engine/promotion.py` ran zero times in a close; the
    admissibility check is now on the path every rule takes to act."""
    import sys

    executed: list[str] = []

    def tracer(frame, event, arg):
        if event == "call" and frame.f_code.co_filename.endswith("engine/promotion.py"):
            executed.append(frame.f_code.co_name)
        return None

    sys.settrace(tracer)
    try:
        close("A")
    finally:
        sys.settrace(None)

    assert "admissible" in executed, "promotion still does not run in a close"


def test_an_approval_granted_under_another_policy_does_not_act_here():
    """Policy is where the ceilings live. A rule approved when the tolerance
    ceiling was higher does not get to keep acting after it drops — an approval
    nobody re-examines is a permission with no expiry."""
    stale = promoted(_rule("R-STALE"), policy_ref="some-other-policy@v99")
    result = close("A", rules=[stale])

    assert not any(e.rule_id == "R-STALE" for e in result.rule_effects)
    assert "R-STALE" in result.inadmissible
    assert any("not the bar in force" in r for r in result.inadmissible["R-STALE"])


def test_a_promoted_rule_named_by_nobody_does_not_act():
    """The contract forbids a promoted rule with no promotion event, and
    `model_copy(update=...)` walks straight past the validator that says so."""
    anonymous = _rule("R-ANON").model_copy(update={"status": RuleStatus.PROMOTED})
    result = close("A", rules=[anonymous])

    assert "R-ANON" in result.inadmissible
    assert any("nobody is named" in r for r in result.inadmissible["R-ANON"])


def test_a_revoked_rule_does_not_act():
    revoked = promoted(_rule("R-GONE")).model_copy(
        update={"revoked_at": datetime(2026, 8, 1, tzinfo=UTC)}
    )
    result = close("A", rules=[revoked])

    assert "R-GONE" in result.inadmissible
    assert any("revoked" in r for r in result.inadmissible["R-GONE"])


def test_an_empty_approver_is_refused_by_the_contract_before_admissibility():
    """`admissible` checks for a blank approver and cannot be made to fire,
    because `PromotionEvent` already refuses one. Recorded rather than deleted:
    the clause is defence in depth over a guarantee that currently holds, and a
    test asserting *where* the refusal happens is worth more than one asserting
    a clause it cannot reach."""
    with pytest.raises(ValidationError):
        promoted(_rule("R-BLANK"), actor="   ")

    assert "promotion names no approver" in inspect.getsource(admissible)


def test_a_rule_that_breaks_a_match_in_this_batch_blocks_the_close():
    """Invariant 5, measured against the batch in front of us rather than the
    history the rule was promoted on. `RuleEffect` cannot see this: it measures
    whether a rule *moved* something, not whether the movement was a loss."""
    killer = promoted(
        _rule(
            "R-KILL",
            when=[Predicate(field="group_ref", op=Operator.EQ, value="pout_00001")],
            then=[RuleAction(kind=ActionKind.SUPPRESS, reason="because")],
        )
    )
    base = close("A", rules=[])
    result = close("A", rules=[killer])

    assert len(result.matches) < len(base.matches)
    assert result.matches_broken_by_rules, "a match was destroyed and nothing said so"
    assert not result.ok, "invariant 5 is not advisory"


def test_the_shipped_bundle_breaks_nothing():
    """The half that would make the check useless if it failed."""
    result = close("A")
    assert result.matches_broken_by_rules == []
    assert result.inadmissible == {}
    assert result.ok


def test_a_close_with_no_rules_pays_nothing_for_the_check():
    """The baseline pass runs only when there is a bundle that could have broken
    something. With no rules there is nothing to blame and nothing to compare."""
    result = close("A", rules=[])
    assert result.matches_broken_by_rules == []
    assert result.ok


@pytest.mark.parametrize("batch", ["A", "B"])
def test_broken_by_rules_names_the_anchor_and_not_a_count(batch):
    """A count says something went wrong; an anchor id says which close to open."""
    killer = promoted(
        _rule(
            "R-KILL",
            when=[Predicate(field="group_ref", op=Operator.NEQ, value="nothing-matches-this")],
            then=[RuleAction(kind=ActionKind.SUPPRESS, reason="everything")],
        )
    )
    base = close(batch, rules=[])
    result = close(batch, rules=[killer])

    assert set(result.matches_broken_by_rules) <= {m.anchor_id for m in base.matches}
    assert result.matches_broken_by_rules == broken_by_rules(base.matches, result.matches)
