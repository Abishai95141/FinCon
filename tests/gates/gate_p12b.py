"""Gate P12, part 2 — rule induction.

The model reads how a human resolved an exception and proposes a **Rule**: data
in a closed vocabulary, interpreted by hand-written code (ADR-001). The proposal
then goes through the P8 promotion gate unchanged.

Two controls this file adds, both because P8's gate cannot see the failure:

* **A regression that could not model the action reports `absent`, not zero.**
  `regress()` has simulated `SET_TOLERANCE` only since P8; STATUS has carried
  "`NORMALIZE_KEY` regresses as a no-op" as a known gap ever since. A rule whose
  effect the regression does not simulate comes back `0 broken, 0 added` — which
  reads as safe and means *unmeasured*. That is CLAUDE.md's "an unmeasured thing
  reported as zero", inside the one gate that exists to stop unsafe rules.

* **A rule that fires nowhere but on the data it was induced from is a
  correction, not a rule.** The regression gate structurally cannot catch this:
  an id-specific rule breaks no history and adds exactly what it was written to
  add. Residual risk `P19` — "induced rule overfits, right on history and wrong
  on future" — has been open since the build plan with "needs post-promotion
  monitoring" beside it. Held-out batch B is the monitoring, before the fact.

Real calls. Same rules as part 1: no mock, loud failure without a key.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from bench.run import SETTLEMENT_POLICY

pytestmark = pytest.mark.gate

BATCHES = Path("data/batches")
KEY = os.environ.get("DEEPSEEK_API_KEY")


@pytest.fixture(autouse=True)
def _preconditions(request):
    """Fails loudly for tests that reach a model, and gets out of the way for
    the ones that do not.

    Was module-scoped and unconditional, so half this file — the closed parse
    vocabulary, the producer table, the AST guard keeping model-authored text
    out of the posting layer — ran only when someone had a key and chose to pay
    for a run. Four of those assertions were stale by 2026-08-24.
    """
    if not (BATCHES / "A" / "labels.json").exists():
        pytest.skip("run `make gen` first")
    if request.node.get_closest_marker("live") and not KEY:
        pytest.fail("DEEPSEEK_API_KEY is not set — P12 has no offline mode (CLAUDE.md rule 1)")


@pytest.fixture(scope="module")
def edge():
    from recon.triage.client import ModelEdge

    return ModelEdge()


@pytest.fixture(scope="module")
def closed(tmp_path_factory):
    from bench.run import close

    return close("A", journal_dir=tmp_path_factory.mktemp("p12b"))


@pytest.fixture(scope="module")
def held_out(tmp_path_factory):
    from bench.run import close

    return close("B", journal_dir=tmp_path_factory.mktemp("p12b-b"))


def _resolution(action: str):
    from recon.contracts import Resolution

    return Resolution(
        resolved_by="meera", resolved_at=datetime(2026, 8, 20, tzinfo=UTC), action=action
    )


@pytest.fixture(scope="module")
def induced(closed, edge):
    """Three exceptions resolved by a human, in their own words, each turned
    into a rule proposal by the model."""
    from recon.triage.induce import induce

    cases = [
        (
            "84769.72",
            "The gateway export double-counted a charge and its fee: ch_00493 repeats "
            "ch_00228 under the same payment_id. Suppress the repeated rows.",
        ),
        (
            "1160.00",
            "Unidentified receipt. Hold it in unapplied cash until treasury identifies "
            "the payer; do not guess it into revenue.",
        ),
        (
            "43684.26",
            "Settled inside the period, banked after period end. It clears itself next "
            "period — raise an advisory rather than an exception.",
        ),
    ]
    out = []
    for amount, action in cases:
        exception = next(e for e in closed.exceptions if str(e.amount) == amount)
        out.append(
            induce(
                exception=exception,
                resolution=_resolution(action),
                records=closed.records,
                taxonomy=closed.taxonomy,
                profile_name="settlement_3way",
                edge=edge,
                policy=SETTLEMENT_POLICY,
            )
        )
    return out


# --------------------------------------------------------------------------
# the proposal is data, not code
# --------------------------------------------------------------------------


def test_three_resolutions_produce_three_rule_proposals(induced):
    assert len(induced) == 3
    assert all(i.exception_id for i in induced)


def test_a_proposal_is_a_validated_rule_or_nothing(induced):
    from recon.contracts.rule import Rule

    for item in induced:
        if item.rule is not None:
            assert isinstance(item.rule, Rule)
            assert item.rule.when and item.rule.then
        else:
            assert item.refusals, "a proposal produced no rule and no reason"


def test_an_action_outside_the_closed_vocabulary_is_refused(closed, edge):
    """ADR-001 is irreversible and this is where a model first authors something
    the engine will execute. An unknown verb is a validation error, never a
    thing we try."""
    from recon.triage.induce import build_rule

    rule, reasons = build_rule(
        {
            "rule_id": "R-EVAL",
            "when": [{"field": "keys.gateway", "op": "eq", "value": "razorpay"}],
            "then": [{"kind": "exec_python", "target": "os.system('rm -rf /')"}],
        },
        profile_name="settlement_3way",
    )
    assert rule is None
    # The reason has to name the problem. Mutation found this asserting only
    # that *a* reason existed, so a refusal saying "silent" passed — and a
    # refusal nobody can act on is barely better than none.
    assert any("not a valid Rule" in r for r in reasons), reasons


def test_a_predicate_operator_outside_the_enum_is_refused():
    from recon.triage.induce import build_rule

    rule, reasons = build_rule(
        {
            "rule_id": "R-OP",
            "when": [{"field": "amount", "op": "starts_with", "value": "5"}],
            "then": [{"kind": "raise_advisory", "reason": "x"}],
        },
        profile_name="settlement_3way",
    )
    assert rule is None
    assert any("not a valid Rule" in r for r in reasons), reasons


def test_the_induction_path_executes_nothing_dynamic():
    import ast

    banned = {"eval", "exec", "compile", "__import__"}
    for path in (Path("src/recon/triage/induce.py"), Path("src/recon/engine/rules.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in banned, f"{path}:{node.lineno} {node.func.id}()"


# --------------------------------------------------------------------------
# the regression must be able to model what it is measuring
# --------------------------------------------------------------------------


def test_an_action_the_regression_cannot_model_is_reported_absent_not_zero(closed):
    """The gap STATUS has carried since P8, closed by refusing rather than by
    pretending. `BOOK_TO` changes where money posts, not which rows match, so a
    match-delta regression has nothing to say about it — and `0 added` would
    read as 'safe' when it means 'unmeasured'."""
    from bench.run import SETTLEMENT_3WAY, SETTLEMENT_POLICY

    from recon.contracts.rule import ActionKind, Operator, Predicate, Rule, RuleAction
    from recon.engine.promotion import MatchHistory, evaluate, regress

    rule = Rule(
        rule_id="R-BOOK",
        profile="settlement_3way",
        when=[Predicate(field="keys.gateway", op=Operator.EQ, value="razorpay")],
        then=[RuleAction(kind=ActionKind.BOOK_TO, target="Expenses:GatewayFees")],
    )
    history = MatchHistory(
        anchors=[r for r in closed.records.values() if r.side == "bank"],
        group_records=closed.settlement_records,
        records=closed.records,
        matches=[],
    )
    outcome = regress(rule, history, SETTLEMENT_3WAY, SETTLEMENT_POLICY)
    assert outcome.unmodelled == [], (
        "book_to is modelled now — a posting delta measures it. The absent-not-"
        "zero discipline moved to actions nothing simulates, not to this one"
    )
    assert outcome.postings is None, (
        "no taxonomy was supplied, so the posting delta is absent rather than "
        "empty — which is the distinction the whole control rests on"
    )

    decision = evaluate(rule, outcome, SETTLEMENT_POLICY)
    assert not decision.allowed
    assert any("Expenses:GatewayFees" in r for r in decision.reasons), decision.reasons


def test_the_actions_the_regression_does_model_are_named(closed):
    from recon.engine.promotion import MODELLED_ACTIONS

    assert "set_tolerance" in MODELLED_ACTIONS
    assert "suppress" in MODELLED_ACTIONS
    assert "book_to" in MODELLED_ACTIONS, (
        "book_to became modelled when the regression grew a posting delta; this "
        "asserted the opposite for two commits because the live gates only run "
        "with a key and `make test` excludes them"
    )


def test_suppression_is_actually_simulated_and_creates_a_real_match(closed):
    """The duplicate case, end to end. `ch_00493` repeats `ch_00228` under the
    same payment_id; with both it and its fee suppressed, group `pout_00011`
    sums to exactly the bank credit it never matched. A regression that reported
    `0 added` here would be measuring nothing."""
    from bench.run import SETTLEMENT_3WAY, SETTLEMENT_POLICY

    from recon.contracts.rule import ActionKind, Operator, Predicate, Rule, RuleAction
    from recon.engine.promotion import MatchHistory, regress

    # Stated as a property, not as two hardcoded ids. The old version named
    # `gateway-settlement:266/267`, which stopped meaning anything the moment
    # identity became content-derived — and naming them was the thing that had
    # no path through the gate anyway.
    rule = Rule(
        rule_id="R-DUP",
        profile="settlement_3way",
        when=[Predicate(field="key_occurrence", op=Operator.GT, value="0")],
        then=[RuleAction(kind=ActionKind.SUPPRESS, reason="duplicated export rows")],
    )
    anchors = [r for r in closed.records.values() if r.side == "bank"]
    history = MatchHistory(
        anchors=anchors,
        group_records=closed.settlement_records,
        records=closed.records,
        matches=[type("M", (), {"anchor_id": m.anchor_id})() for m in closed.matches],
    )
    outcome = regress(rule, history, SETTLEMENT_3WAY, SETTLEMENT_POLICY)
    assert outcome.unmodelled == []
    assert outcome.added, "suppressing the duplicate did not create the match it should"
    assert outcome.broken == []


# --------------------------------------------------------------------------
# a rule must generalise, or it is a correction wearing a rule's clothes
# --------------------------------------------------------------------------


def test_a_rule_keyed_on_specific_rows_is_refused_as_a_correction(closed, held_out):
    """Residual risk `P19`, caught before promotion instead of after — and now
    caught **behaviourally**, which is the whole point of fixing identity.

    A structural ban on identity predicates used to sit in front of this check,
    because record ids were positional: `gateway-settlement:266` existed in
    every batch and named a different row in each, so an id-keyed rule fired on
    strangers and the firing count called it general. Identity is content-derived
    now, so a rule naming rows from batch A finds nothing to say about batch B,
    and the shape judgment is gone.
    """
    from recon.contracts.rule import ActionKind, Operator, Predicate, Rule, RuleAction
    from recon.engine.promotion import generalises

    victims = [r.record_id for r in closed.settlement_records if r.key_occurrence > 0]
    assert len(victims) == 2, "batch A's duplicate rows are the fixture"
    rule = Rule(
        rule_id="R-DUP",
        profile="settlement_3way",
        when=[Predicate(field="record_id", op=Operator.IN, value=victims)],
        then=[RuleAction(kind=ActionKind.SUPPRESS, reason="duplicated export rows")],
    )
    on_a = generalises(rule, closed.settlement_records)
    on_b = generalises(rule, held_out.settlement_records)
    assert on_a.fires == 2, "the rule does not even fire on the batch it came from"
    assert on_b.fires == 0, (
        "an id-keyed rule still reaches held-out data — identity is positional again"
    )
    assert not on_b.generalises
    assert "CORRECTION" in on_b.summary()


def test_the_same_intent_expressed_as_a_property_does_generalise(closed, held_out):
    """The half that makes the refusal above mean something. The *identical
    intent* — suppress what the export asserted twice — stated as a property
    rather than as two row ids fires on both batches and passes.

    Before `key_occurrence` existed there was no way to say this, so a correct
    rule had no path through the system at all: unsayable as a property, refused
    as a list of rows.
    """
    from recon.contracts.rule import ActionKind, Operator, Predicate, Rule, RuleAction
    from recon.engine.promotion import generalises

    general = Rule(
        rule_id="R-DEDUP",
        profile="settlement_3way",
        when=[Predicate(field="key_occurrence", op=Operator.GT, value="0")],
        then=[RuleAction(kind=ActionKind.SUPPRESS, reason="asserted twice")],
    )
    assert generalises(general, closed.settlement_records).fires == 2
    assert generalises(general, held_out.settlement_records).generalises


def test_a_rule_keyed_on_a_property_does_generalise(closed, held_out):
    """The other half. A gate that refuses every induced rule is indistinguishable
    from having no induction."""
    from recon.contracts.rule import ActionKind, Operator, Predicate, Rule, RuleAction
    from recon.engine.promotion import generalises

    rule = Rule(
        rule_id="R-FEE",
        profile="settlement_3way",
        when=[Predicate(field="keys.row_type", op=Operator.EQ, value="fee")],
        then=[RuleAction(kind=ActionKind.RAISE_ADVISORY, target="E06", reason="fee row")],
    )
    assert generalises(rule, closed.settlement_records).fires > 0
    assert generalises(rule, held_out.settlement_records).generalises


def test_promotion_refuses_a_rule_that_fires_nowhere_else(closed, held_out):
    from bench.run import SETTLEMENT_3WAY, SETTLEMENT_POLICY

    from recon.contracts import PolicyViolation
    from recon.contracts.rule import ActionKind, Operator, Predicate, Rule, RuleAction
    from recon.engine.promotion import MatchHistory, promote, regress

    rule = Rule(
        rule_id="R-ONEOFF",
        profile="settlement_3way",
        when=[Predicate(field="record_id", op=Operator.EQ, value="gateway-settlement:266")],
        then=[RuleAction(kind=ActionKind.SUPPRESS, reason="one row")],
    )
    history = MatchHistory(
        anchors=[r for r in closed.records.values() if r.side == "bank"],
        group_records=closed.settlement_records,
        records=closed.records,
        matches=[],
    )
    outcome = regress(rule, history, SETTLEMENT_3WAY, SETTLEMENT_POLICY)
    with pytest.raises(PolicyViolation, match="correction"):
        promote(
            rule,
            outcome,
            SETTLEMENT_POLICY,
            actor="meera",
            held_out=held_out.settlement_records,
        )


# --------------------------------------------------------------------------
# the induced rules, measured
# --------------------------------------------------------------------------


def test_what_the_model_proposed_is_reported_rule_by_rule(induced, closed, held_out, capsys):
    """The gate's sentence is 'the scorecard attributes the improvement rule by
    rule'. Printed whatever the outcome, because a phase that only reports its
    successes is the marketing document P9 refused to write."""
    from recon.triage.induce import report

    print("\n" + report(induced, held_out=held_out.settlement_records))
    out = capsys.readouterr().out
    for item in induced:
        assert item.exception_id in out


def test_every_induction_is_recorded(closed, edge, tmp_path):
    from recon.contracts import EventKind
    from recon.journal import Journal, read
    from recon.triage.induce import induce

    journal = Journal(tmp_path / "i.jsonl")
    exception = next(e for e in closed.exceptions if str(e.amount) == "1160.00")
    induce(
        exception=exception,
        resolution=_resolution("Hold it in unapplied cash."),
        records=closed.records,
        taxonomy=closed.taxonomy,
        profile_name="settlement_3way",
        edge=edge,
        policy=SETTLEMENT_POLICY,
        journal=journal,
    )
    kinds = [e.kind for e in read(tmp_path / "i.jsonl")]
    assert EventKind.RULE_INDUCED in kinds or EventKind.PROPOSAL_REFUSED in kinds


def test_rule_induced_now_has_a_real_producer():
    from recon.contracts import PRODUCERS, EventKind

    assert not PRODUCERS[EventKind.RULE_INDUCED].startswith("P")
    assert not PRODUCERS[EventKind.ADAPTER_AUTHORED].startswith("P"), (
        "adapter synthesis is built; a producer table still naming the phase "
        "that will build it is a stub outliving its stub"
    )


# --------------------------------------------------------------------------
# a rule that fires on nothing is not a safe rule, it is an unmeasured one
# --------------------------------------------------------------------------


def test_a_pattern_the_author_anchored_still_matches(closed):
    """A bug of mine, found by running induction rather than by reading it.

    `MATCHES` wrapped the pattern as `(?:{p})$`, so a model writing `^pout_` got
    `(?:^pout_)$` — which can never match anything. The rule read perfectly, and
    fired on **zero rows of the batch it was induced from**, while its regression
    reported `0 broken, 0 added` and looked entirely safe.
    """
    from recon.contracts.rule import Operator, Predicate
    from recon.engine.rules import matches

    record = next(r for r in closed.settlement_records if r.group_ref)
    for pattern in ("pout_.*", "^pout_.*$", "pout_[0-9]+"):
        predicate = Predicate(field="group_ref", op=Operator.MATCHES, value=pattern)
        assert matches(predicate, record), pattern


def test_matches_is_a_full_match_not_a_substring_search(closed):
    """The other direction. An unanchored pattern selecting far more than its
    author meant is how a suppress rule quietly eats a ledger."""
    from recon.contracts.rule import Operator, Predicate
    from recon.engine.rules import matches

    record = next(r for r in closed.settlement_records if r.group_ref)
    assert not matches(Predicate(field="group_ref", op=Operator.MATCHES, value="pout"), record), (
        "a bare 'pout' must not match 'pout_00011' — that is a substring, not the value"
    )


def test_a_rule_that_fires_on_nothing_it_came_from_is_refused(closed):
    """`0 broken, 0 added` is what a rule that does nothing at all looks like,
    and it is indistinguishable from a safe one until you ask whether it fires."""
    from bench.run import SETTLEMENT_3WAY, SETTLEMENT_POLICY

    from recon.contracts.rule import ActionKind, Operator, Predicate, Rule, RuleAction
    from recon.engine.promotion import MatchHistory, evaluate, regress

    inert = Rule(
        rule_id="R-INERT",
        profile="settlement_3way",
        when=[Predicate(field="keys.row_type", op=Operator.EQ, value="does-not-exist")],
        then=[RuleAction(kind=ActionKind.RAISE_ADVISORY, target="E06", reason="never fires")],
    )
    # The real matches, so the regression measures a delta against history
    # rather than counting every existing match as an addition.
    history = MatchHistory(
        anchors=[r for r in closed.records.values() if r.side == "bank"],
        group_records=closed.settlement_records,
        records=closed.records,
        matches=[type("M", (), {"anchor_id": m.anchor_id})() for m in closed.matches],
    )
    outcome = regress(inert, history, SETTLEMENT_3WAY, SETTLEMENT_POLICY)
    assert outcome.broken == [] and outcome.added == [], "the fixture must look 'safe'"

    decision = evaluate(inert, outcome, SETTLEMENT_POLICY, induced_on=closed.settlement_records)
    assert not decision.allowed
    assert any("does not implement the resolution" in r for r in decision.reasons)


def test_a_rule_that_does_fire_clears_the_fires_check(closed):
    """Isolated to the control under test. `keys.row_type == fee` selects 48% of
    rows, so it is now refused by the *selectivity* cap — a different control.
    Asserting overall approval here would make this test fail whenever an
    unrelated guard was added, which is how a suite becomes brittle and then
    gets loosened."""
    from bench.run import SETTLEMENT_3WAY, SETTLEMENT_POLICY

    from recon.contracts.rule import ActionKind, Operator, Predicate, Rule, RuleAction
    from recon.engine.promotion import MatchHistory, evaluate, regress

    live = Rule(
        rule_id="R-LIVE",
        profile="settlement_3way",
        when=[Predicate(field="keys.row_type", op=Operator.EQ, value="fee")],
        then=[RuleAction(kind=ActionKind.RAISE_ADVISORY, target="E06", reason="fee row")],
    )
    history = MatchHistory(
        anchors=[r for r in closed.records.values() if r.side == "bank"],
        group_records=closed.settlement_records,
        records=closed.records,
        matches=[type("M", (), {"anchor_id": m.anchor_id})() for m in closed.matches],
    )
    outcome = regress(live, history, SETTLEMENT_3WAY, SETTLEMENT_POLICY)
    decision = evaluate(live, outcome, SETTLEMENT_POLICY, induced_on=closed.settlement_records)
    assert not any("does not implement the resolution" in r for r in decision.reasons), (
        decision.reasons
    )


# --------------------------------------------------------------------------
# breadth: the control that was here has been deleted
# --------------------------------------------------------------------------


def test_an_over_broad_rule_is_refused_on_the_reference_population(closed, held_out):
    """The control that was deleted, restored in the form that survives MR7.

    The first version measured the share of whatever corpus was passed in, and
    a metamorphic relation refuted it: the same rule, still firing on the same
    502 rows, went from refused to allowed when 1,500 unrelated rows were added.
    The denominator is now a fixed **reference** population the rule never saw —
    the out-of-bag form — so padding the batch under test cannot move it.
    """
    from bench.run import SETTLEMENT_3WAY, SETTLEMENT_POLICY

    from recon.contracts.rule import ActionKind, Operator, Predicate, Rule, RuleAction
    from recon.engine.promotion import MatchHistory, evaluate, generalises, regress

    broad = Rule(
        rule_id="R-BROAD",
        profile="settlement_3way",
        when=[Predicate(field="keys.row_type", op=Operator.IN, value=["charge", "fee"])],
        then=[RuleAction(kind=ActionKind.RAISE_ADVISORY, target="E06", reason="everything")],
    )
    reference = held_out.settlement_records
    fired = generalises(broad, reference)
    assert fired.fires > len(reference) // 2, "fixture must be over-broad on the reference"

    history = MatchHistory(
        anchors=[r for r in closed.records.values() if r.side == "bank"],
        group_records=closed.settlement_records,
        records=closed.records,
        matches=[type("M", (), {"anchor_id": m.anchor_id})() for m in closed.matches],
    )
    outcome = regress(broad, history, SETTLEMENT_3WAY, SETTLEMENT_POLICY)
    assert outcome.broken == [] and outcome.added == [], (
        "it must look harmless to the delta checks, or this proves nothing"
    )

    decision = evaluate(
        broad,
        outcome,
        SETTLEMENT_POLICY,
        held_out=reference,
        induced_on=closed.settlement_records,
    )
    assert not decision.allowed
    assert any("reference rows" in r for r in decision.reasons), decision.reasons


def test_a_narrow_rule_still_promotes_under_the_reference_cap(closed, held_out):
    """The other half. The dedup rule fires on 2 of 536 reference rows — general,
    and nowhere near broad. A cap that refused it would refuse the one rule this
    phase exists to promote.

    This asserted `decision.allowed` until 2026-08-24, when the same rule turned
    out to be strictly harmful for a reason no cap can see: it removes ₹5,489.75
    of real value and destroys the planted `E06` that names it. So the claim
    narrows to what this test is actually about — the *cap* does not fire on a
    narrow rule — and the rule is refused by exactly one control, which is not
    this one.
    """
    from bench.run import SETTLEMENT_3WAY, SETTLEMENT_POLICY

    from recon.contracts.rule import ActionKind, Operator, Predicate, Rule, RuleAction
    from recon.engine.promotion import MatchHistory, evaluate, regress

    dedup = Rule(
        rule_id="R-DEDUP",
        profile="settlement_3way",
        when=[Predicate(field="key_occurrence", op=Operator.GT, value="0")],
        then=[RuleAction(kind=ActionKind.SUPPRESS, reason="asserted twice")],
    )
    history = MatchHistory(
        anchors=[r for r in closed.records.values() if r.side == "bank"],
        group_records=closed.settlement_records,
        records=closed.records,
        matches=[type("M", (), {"anchor_id": m.anchor_id})() for m in closed.matches],
    )
    outcome = regress(dedup, history, SETTLEMENT_3WAY, SETTLEMENT_POLICY)
    assert len(outcome.added) == 1, "the dedup rule must create the bl_00011 match"
    decision = evaluate(
        dedup,
        outcome,
        SETTLEMENT_POLICY,
        held_out=held_out.settlement_records,
        induced_on=closed.settlement_records,
    )
    assert not any("reference rows" in r for r in decision.reasons), (
        "the selectivity cap must not be what refuses a rule firing on 2 of 536"
    )
    assert len(decision.reasons) == 1 and "of value" in decision.reasons[0], decision.reasons


def test_a_rule_cannot_reach_a_field_outside_the_closed_vocabulary(closed):
    """Found by mutation, and it is the security-relevant one.

    Replacing the field table with `getattr(record, field)` lets a
    model-authored predicate read anything a `Record` happens to expose —
    including `raw`, which is the **untrusted source document text**. A rule
    predicating on attacker-controlled narration is indirect prompt injection
    with a longer fuse: the text stops being data the model reads and becomes
    data the *engine* branches on.
    """
    from recon.contracts.rule import Operator, Predicate
    from recon.engine.rules import RuleError, matches, resolve_field

    record = next(r for r in closed.records.values() if (r.raw or {}).get("AddtlNtryInf"))
    for reachable in ("raw", "keys", "doc_hash", "row_ordinal", "__class__"):
        with pytest.raises(RuleError, match="not a rule field"):
            resolve_field(record, reachable)

    with pytest.raises(RuleError):
        matches(Predicate(field="raw", op=Operator.MATCHES, value=".*"), record)

    # And the vocabulary that IS open stays open.
    assert resolve_field(record, "record_id") == record.record_id
    assert resolve_field(record, "keys.entry_ref") == record.keys.get("entry_ref", "")
