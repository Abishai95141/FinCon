"""A close measures what each promoted rule actually did to it.

Four action kinds could be promoted and do nothing. `raise_advisory` was in the
enum, in the tool schema and in `MODELLED_ACTIONS` with no implementation at
all, and a rule using it outscored every real rule by being inert on every
dimension the gate had. None of that was visible from a close: the log recorded
that a rule *existed*, never that it *moved* anything.

So the close records it, in band, on real output — not by differencing two runs
(a close cannot run itself twice) but as a fact the run observes about itself.
"""

from __future__ import annotations

import pytest
from bench.run import close

from recon.contracts import EventKind
from recon.contracts.rule import ActionKind, Operator, Predicate, Rule, RuleAction, RuleStatus
from recon.engine import rulestore
from recon.journal import read
from tests.conftest import promoted


def _rule(rule_id: str, action: dict, field: str = "key_occurrence", op=Operator.GT, value="0"):
    return promoted(
        Rule(
            rule_id=rule_id,
            profile="settlement_3way",
            when=[Predicate(field=field, op=op, value=value)],
            then=[RuleAction(**action)],
        )
    )


REAL = {"kind": ActionKind.RAISE_ADVISORY, "target": "E06", "reason": "a repeat"}
SUPPRESS = {"kind": ActionKind.SUPPRESS, "reason": "a repeat"}


def test_the_shipped_rule_records_an_observable_effect():
    result = close("A")
    assert result.rule_effects, "the promoted store acted and the close said nothing"
    for effect in result.rule_effects:
        assert effect.observable, effect.summary()
    assert not result.inert_rules


@pytest.mark.parametrize(
    ("name", "action", "predicate"),
    [
        (
            "advisory onto a P0-derived exception",
            {**REAL, "target": "E03"},
            ("group_ref", Operator.EQ, "pout_00004"),
        ),
        ("fires on nothing at all", REAL, ("source", Operator.EQ, "nothing-is-called-this")),
        # `pout_00001` matched cleanly, so no exception names its rows and
        # there is nothing for a `book_to` to re-route. Pointing this case at
        # the duplicate rows was wrong: those *are* named by an exception, so
        # the rule genuinely re-booked a posting and was correctly observable.
        (
            "book_to on rows no exception names",
            {"kind": ActionKind.BOOK_TO, "target": "rounding"},
            ("group_ref", Operator.EQ, "pout_00001"),
        ),
    ],
)
def test_a_rule_that_moves_nothing_is_recorded_as_inert(name, action, predicate):
    """Each of these promotes cleanly and changes nothing. Before A3 a close
    could not tell them apart from a rule that worked."""
    extra = {}
    if predicate:
        extra = {"field": predicate[0], "op": predicate[1], "value": predicate[2]}
    result = close("A", rules=[_rule("R-INERT", action, **extra)])

    assert result.inert_rules == ["R-INERT"], name
    effect = next(e for e in result.rule_effects if e.rule_id == "R-INERT")
    assert not effect.observable
    assert "NO OBSERVABLE EFFECT" in effect.summary() or "fired on nothing" in effect.summary()


def test_a_real_suppression_is_not_mistaken_for_a_no_op():
    """The half that would make the check useless if it failed."""
    result = close("A", rules=[_rule("R-SUP", SUPPRESS)])
    effect = next(e for e in result.rule_effects if e.rule_id == "R-SUP")
    assert effect.observable and effect.suppressed == 2, effect.summary()
    assert not result.inert_rules


def test_every_promoted_rule_reaches_the_decision_log():
    """A rule acting is a decision. The log recorded that a rule existed and
    never that it moved anything."""
    result = close(
        "A",
        rules=[
            _rule("R-SUP", SUPPRESS),
            _rule("R-NIL", REAL, field="source", op=Operator.EQ, value="nope"),
        ],
    )
    events = [e for e in read(result.journal_path) if e.kind is EventKind.RULE_APPLIED]

    by_ref = {e.payload.rule_ref: e for e in events}
    assert set(by_ref) == {"R-SUP@v1", "R-NIL@v1"}
    assert by_ref["R-SUP@v1"].outcome == "observable"
    assert by_ref["R-NIL@v1"].outcome == "inert"
    assert by_ref["R-SUP@v1"].payload.suppressed == 2


def test_an_unpromoted_rule_is_recorded_as_having_done_nothing():
    """Refused with a reason, not in silence — a close where a rule was quietly
    dropped looks identical to one where it worked.

    The refusal now lands in `inadmissible` rather than in `rule_effects`,
    because a close checks the approval *before* the rule reaches the applier:
    an unapproved rule should not get as far as being measured. `rulestore.apply`
    keeps its own status check for callers that reach it directly.
    """
    draft = _rule("R-DRAFT", SUPPRESS).model_copy(update={"status": RuleStatus.DRAFT})
    result = close("A", rules=[draft])

    assert not any(e.rule_id == "R-DRAFT" for e in result.rule_effects), "a draft rule acted"
    assert "R-DRAFT" in result.inadmissible
    assert any("not promoted" in r for r in result.inadmissible["R-DRAFT"])


def test_inert_on_one_batch_is_not_a_finding_but_inert_on_every_batch_is():
    """The distinction the per-close record deliberately does not make. A
    duplicate-suppression rule is honestly inert on a batch with no duplicates;
    a rule that has never once moved anything is a permission granted for an
    effect that does not exist."""
    real = _rule("R-REAL", REAL)
    nil = _rule("R-NIL", REAL, field="source", op=Operator.EQ, value="nope")
    runs = [close(b, rules=[real, nil]).rule_effects for b in ("A", "B")]

    inert = rulestore.inert_across(runs)
    assert "R-NIL" in inert and inert["R-NIL"] == 2
    assert "R-REAL" not in inert, "a rule that moved something in any close is not inert"


def test_which_advisory_wins_does_not_depend_on_the_order_rules_were_passed():
    """Two advisories can touch one exception. Picking `touching[0]` meant the
    answer depended on the caller's list order — a worse property than
    arbitrary. The loser reads as inert either way, which is the signal."""
    a = _rule("R-AAA", {**REAL, "target": "E06"})
    b = _rule("R-BBB", {**REAL, "target": "E03"})

    forward = close("A", rules=[a, b])
    backward = close("A", rules=[b, a])

    assert forward.outcome_digest == backward.outcome_digest
    assert forward.inert_rules == backward.inert_rules == ["R-BBB"]


def test_the_applier_still_refuses_an_unpromoted_rule_that_reaches_it_directly():
    """Defence in depth, and no longer reachable through a close.

    `admissible` refuses an unapproved rule before it gets near the applier, so
    `rulestore.apply`'s own status check is now only on the path of a caller
    that goes straight to `run_tiers`. That is still a real path — the
    regression takes it — and a branch nothing exercises is a branch that rots,
    so it is covered here rather than assumed.
    """
    from bench.run import SETTLEMENT_3WAY, load_sides

    draft = _rule("R-DIRECT", SUPPRESS).model_copy(update={"status": RuleStatus.DRAFT})
    rows = [rec for _, rec in load_sides("A").settlement]
    applied = rulestore.apply([draft], rows, profile=SETTLEMENT_3WAY.name)

    assert applied.scope == {}, "an unpromoted rule suppressed rows"
    assert "R-DIRECT" in applied.unapplied
    effect = applied.effects["R-DIRECT"]
    assert effect.fired == 0 and not effect.observable
    assert "status=draft" in effect.unapplied, "refused, and the refusal left no trace"
