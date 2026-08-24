"""What a regression can and cannot see, as relations.

`regress()` computed a match delta and nothing else, so two of the five action
kinds were unmeasurable and refused as such. Refusing was safe and left the
vocabulary partly decorative: a rule author could never use `normalize_key` or
`book_to` at all.

They were not the same problem.

**`normalize_key` was always match-shaped.** Rewriting a key changes what is
comparable, which changes which rows pair. The regression simply never applied
it — an omission, not a limit, and a real one: applied, an alias rule on this
corpus **breaks a match**, which the old regression reported as `0 broken`.

**`book_to` genuinely is not.** It changes where money posts, not which rows
pair, so a match-delta regression is blind to it by construction. That needed a
second dimension: replay the posting layer with and without the rule and diff
the journal. On this corpus a single `book_to` reroutes three entries and
₹173,180.12 while breaking no match and adding none.

The relations below are about the *dimensions*, not about these two rules. They
are what has to hold for a delta to mean anything on inputs nobody has seen.
"""

from __future__ import annotations

import random
import re
from decimal import Decimal

import pytest
from bench.arms import deterministic
from bench.run import SETTLEMENT_3WAY, SETTLEMENT_POLICY, TAXONOMY, load_sides
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from recon.contracts import ProofTier
from recon.contracts.rule import ActionKind, Operator, Predicate, Rule, RuleAction
from recon.engine.blocking import BlockingPolicy
from recon.engine.blocking import build as build_candidates
from recon.engine.promotion import MatchHistory, evaluate, regress

SLOW = settings(
    max_examples=6, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)


@pytest.fixture(scope="module", autouse=True)
def _batches_exist():
    from pathlib import Path

    if not Path("data/batches/A/labels.json").exists():
        pytest.skip("run `make gen` first")


@pytest.fixture(scope="module")
def history():
    sides = load_sides("A")
    rows = [r for _, r in sides.settlement]
    candidates = build_candidates([r for _, r in sides.anchors], rows, BlockingPolicy())
    base = deterministic.run(
        sides.bank,
        sides.settlement,
        SETTLEMENT_3WAY,
        SETTLEMENT_POLICY,
        ProofTier.P0_ARITHMETIC,
        candidates,
        sides.scope,
    )
    return MatchHistory(
        anchors=[r for _, r in sides.bank],
        group_records=rows,
        records={r.record_id: r for _, r in sides.bank + sides.settlement},
        matches=[type("M", (), {"anchor_id": m.anchor_id})() for m in base.matches],
        exceptions=list(base.exceptions),
    )


def _rule(rule_id: str, *actions: RuleAction, field: str = "side", value: str = "bank") -> Rule:
    return Rule(
        rule_id=rule_id,
        profile="settlement_3way",
        when=[Predicate(field=field, op=Operator.EQ, value=value)],
        then=list(actions),
    )


# --------------------------------------------------------------------------
# absent is not zero
# --------------------------------------------------------------------------


def test_a_posting_delta_is_absent_when_the_layer_was_not_replayed(history):
    """`None` means nobody looked; an empty delta means somebody looked and
    nothing moved. Collapsing them would report an unmeasured rule as safe,
    which is the failure the whole dimension exists to fix."""
    rule = _rule("R-BOOK", RuleAction(kind=ActionKind.BOOK_TO, target="disputes"))
    assert regress(rule, history, SETTLEMENT_3WAY, SETTLEMENT_POLICY).postings is None
    replayed = regress(
        rule, history, SETTLEMENT_3WAY, SETTLEMENT_POLICY, taxonomy=TAXONOMY
    ).postings
    assert replayed is not None


def test_no_action_kind_is_left_unmeasurable(history):
    """Every kind the vocabulary offers must be simulable, or a rule using it
    can never be promoted and the vocabulary is partly decorative."""
    from recon.engine.promotion import MODELLED_ACTIONS

    assert {k.value for k in ActionKind} <= MODELLED_ACTIONS


# --------------------------------------------------------------------------
# the delta measures the rule, not the run
# --------------------------------------------------------------------------


def test_rerouting_to_where_it_already_books_moves_nothing(history):
    """A no-op must read as a no-op. `E14` books to suspense; a rule sending it
    to suspense changes nothing, and a dimension that reported movement here
    would report movement for everything."""
    rule = _rule("R-NOOP", RuleAction(kind=ActionKind.BOOK_TO, target="suspense"))
    delta = regress(rule, history, SETTLEMENT_3WAY, SETTLEMENT_POLICY, taxonomy=TAXONOMY).postings
    assert delta is not None
    assert not delta.moved, delta.summary()
    assert delta.value_moved == Decimal("0.00")


def test_rerouting_somewhere_else_moves_exactly_what_it_reroutes(history):
    """The other half. The value moved must equal the value on the entries that
    changed account — a count of entries says nothing about whether it was ₹30
    or ₹3,000,000."""
    rule = _rule("R-DISPUTE", RuleAction(kind=ActionKind.BOOK_TO, target="disputes"))
    delta = regress(rule, history, SETTLEMENT_3WAY, SETTLEMENT_POLICY, taxonomy=TAXONOMY).postings
    assert delta.moved
    assert delta.value_moved > 0
    assert sum(delta.before.values()) == sum(delta.after.values()), (
        "rerouting changed the number of entries; it should only change where they book"
    )


@given(seed=st.integers(min_value=0, max_value=2**30))
@SLOW
def test_the_posting_delta_is_invariant_to_record_order(history, seed):
    """A delta that depends on how a file was sorted is measuring the file."""
    rule = _rule("R-DISPUTE", RuleAction(kind=ActionKind.BOOK_TO, target="disputes"))
    base = regress(rule, history, SETTLEMENT_3WAY, SETTLEMENT_POLICY, taxonomy=TAXONOMY).postings

    shuffled = list(history.group_records)
    random.Random(seed).shuffle(shuffled)
    other = MatchHistory(
        anchors=history.anchors,
        group_records=shuffled,
        records=history.records,
        matches=history.matches,
        exceptions=history.exceptions,
    )
    again = regress(rule, other, SETTLEMENT_3WAY, SETTLEMENT_POLICY, taxonomy=TAXONOMY).postings
    assert base.rerouted == again.rerouted
    assert base.value_moved == again.value_moved


# --------------------------------------------------------------------------
# normalize_key
# --------------------------------------------------------------------------


def test_a_key_rewrite_is_simulated_and_its_effect_is_visible(history):
    """The omission, made concrete. Rewriting the counterparty key on this
    corpus **breaks a match** — and the regression used to report `0 broken`
    because it never applied the rule at all."""
    rule = _rule(
        "R-ALIAS",
        RuleAction(kind=ActionKind.NORMALIZE_KEY, target="gateway", value="rzp"),
        field="keys.gateway",
        value="razorpay",
    )
    outcome = regress(rule, history, SETTLEMENT_3WAY, SETTLEMENT_POLICY)
    assert outcome.unmodelled == []
    assert outcome.broken, "the rewrite has no measured effect — it is not being applied"


def test_rewriting_a_key_to_its_current_value_changes_nothing(history):
    """Idempotence, and a no-op check the simulation could easily fail: setting
    `gateway` to `razorpay` on rows where it already is must break nothing."""
    rule = _rule(
        "R-SAME",
        RuleAction(kind=ActionKind.NORMALIZE_KEY, target="gateway", value="razorpay"),
        field="keys.gateway",
        value="razorpay",
    )
    outcome = regress(rule, history, SETTLEMENT_3WAY, SETTLEMENT_POLICY)
    assert outcome.broken == [] and outcome.added == []


# --------------------------------------------------------------------------
# closed vocabulary
# --------------------------------------------------------------------------


@given(
    account=st.text(alphabet="abcdefghijklmnopqrstuvwxyz:", min_size=3, max_size=24).filter(
        lambda v: (
            v
            not in {
                r.value
                for r in __import__("recon.ledger.accounts", fromlist=["AccountRole"]).AccountRole
            }
        )
    )
)
@SLOW
def test_book_to_outside_the_chart_is_refused(history, account):
    """Generated destinations, not one hand-picked string. `book_to` names an
    account role and the roles are a closed set — an unknown one is a spec
    error, so the posting layer never has to know a rule exists."""
    rule = _rule("R-ELSEWHERE", RuleAction(kind=ActionKind.BOOK_TO, target=account))
    outcome = regress(rule, history, SETTLEMENT_3WAY, SETTLEMENT_POLICY, taxonomy=TAXONOMY)
    decision = evaluate(rule, outcome, SETTLEMENT_POLICY)
    assert not decision.allowed
    assert any("not an account role" in r for r in decision.reasons), decision.reasons


# --------------------------------------------------------------------------
# what the model is told must be what the engine can read
# --------------------------------------------------------------------------


def test_the_induction_prompt_offers_every_readable_field():
    """The drift that made three induced rules look like model failure.

    The predicate vocabulary was a hand-written sentence in the tool schema. The
    engine grew `key_occurrence` and `natural_key`; the sentence did not. So the
    model could not write a duplicate-suppression rule — the only correct rule
    available on this corpus — because it was never told the field existed, and
    the refusals read as incompetence rather than as a stale string.

    Same rule as `DERIVED_CODES` and the chart of accounts: facts about a
    vocabulary come from the thing that owns it.
    """
    from recon.engine.rules import FIELDS
    from recon.triage.induce import _FIELD_HELP, readable_fields

    assert set(readable_fields()) == set(FIELDS)
    for name in FIELDS:
        assert name in _FIELD_HELP, f"{name} is readable but the prompt never mentions it"


def test_the_model_is_shown_every_field_it_is_told_it_may_use():
    """Telling and showing must agree. Showing less is how it wrote predicates
    that selected nothing: `side eq "bank"` on a rule meant to act on settlement
    rows is a coherent sentence about facts it could not see."""
    from recon.engine.rules import FIELDS
    from recon.triage.induce import fact_of

    sides = load_sides("A")
    record = next(r for _, r in sides.settlement)
    fact = fact_of(record)
    assert set(FIELDS) <= set(fact)
    assert all(f"keys.{k}" in fact for k in record.keys)


def test_the_proposer_is_told_every_threshold_it_is_judged_by():
    """A criterion the gate enforces and the prompt omits produces a refusal the
    proposer could not have avoided. Both drifts have the same shape: a sentence
    about a control, retyped away from the control."""
    from recon.engine.promotion import MODELLED_ACTIONS
    from recon.triage.induce import acceptance_criteria

    text = acceptance_criteria(SETTLEMENT_POLICY)
    assert f"{Decimal(SETTLEMENT_POLICY.max_reference_selectivity):.0%}" in text
    assert str(SETTLEMENT_POLICY.max_added_matches) in text
    assert SETTLEMENT_POLICY.ref in text
    for action in MODELLED_ACTIONS:
        assert action in text, f"the gate simulates {action} but the proposer is never told"


def test_the_criteria_state_the_standard_and_never_the_answer():
    """The line between publishing a policy and teaching to the test. If this
    paragraph ever names a readable field, it has stopped stating what makes a
    rule acceptable and started dictating which rule to write — and a promotion
    after that measures the prompt, not the model."""
    from recon.engine.rules import FIELDS
    from recon.triage.induce import acceptance_criteria

    text = acceptance_criteria(SETTLEMENT_POLICY)
    named = [f for f in FIELDS if re.search(rf"\b{re.escape(f)}\b", text)]
    assert not named, f"the criteria name {named}; that is the answer, not the standard"


def test_the_proposer_is_told_that_removing_value_is_refused():
    """The drift I introduced while fixing drift.

    The value control landed after `acceptance_criteria` was written, so for one
    commit the gate refused on a ground the proposer was never told — which is
    precisely the failure that made three induced rules read as incompetence.
    A control the proposer cannot see produces a refusal it could not avoid.
    """
    from recon.triage.induce import acceptance_criteria

    text = acceptance_criteria(SETTLEMENT_POLICY).lower()
    assert "value" in text and ("attested" in text or "p2" in text)
