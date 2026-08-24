"""Identity, the natural key, and the one grammar production they buy.

Two problems were tangled here and untangling them is the whole file.

**Identity did not identify.** `record_id` was `source:ordinal`, so
`gateway-settlement:266` named a different row in every batch. A rule keyed on
it fired happily on held-out data — on rows unrelated to the case it came from —
which made the behavioural generality check unsound. A structural ban on
identity predicates existed only to paper over that.

**And a correct rule was unsayable.** "Suppress the row the export asserted
twice" is maximally general: it names no row, holds of any batch, and transfers
to a second loop unchanged. It was expressible only by naming the two rows,
which the ban then refused. Two constraints on *different axes* — arity, and
generality — were being enforced as one.

The fix is one production. `natural_key` says what a row claims to be;
`key_occurrence` is its position among rows claiming the same thing, which is
`row_number() over (partition by natural_key)` evaluated once at intake. A rule
can then ask about duplication with a **unary** predicate, because the
aggregation happened in the interpreter.

The obvious shortcut — make identity *be* the natural key — is wrong, and the
data says so: on batch A exactly two natural keys collide and they are precisely
the planted duplicate, so a content-keyed id would delete the rows it exists to
find and invariant 8 would never see them go.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from bench.arms import deterministic
from bench.run import SETTLEMENT_3WAY, SETTLEMENT_POLICY, load_sides

from recon.contracts import ProofTier
from recon.contracts.rule import ActionKind, Operator, Predicate, Rule, RuleAction
from recon.engine.blocking import BlockingPolicy
from recon.engine.blocking import build as build_candidates
from recon.engine.promotion import MatchHistory, evaluate, generalises, regress
from recon.engine.rules import select
from recon.engine.tiers import run as run_tiers
from recon.engine.verifier import verify
from recon.intake import ADAPTER_DIR, load_spec

BATCHES = Path("data/batches")


@pytest.fixture(scope="module", autouse=True)
def _batches_exist():
    if not (BATCHES / "A" / "labels.json").exists():
        pytest.skip("run `make gen` first")


@pytest.fixture(scope="module")
def sides():
    return {b: load_sides(b) for b in ("A", "B")}


DEDUP = Rule(
    rule_id="R-DEDUP",
    profile="settlement_3way",
    when=[Predicate(field="key_occurrence", op=Operator.GT, value="0")],
    then=[RuleAction(kind=ActionKind.SUPPRESS, reason="the export asserted this event twice")],
)


# --------------------------------------------------------------------------
# identity
# --------------------------------------------------------------------------


@pytest.mark.parametrize("batch", ["A", "B"])
def test_identity_is_unique(sides, batch):
    """The property a content-derived id most easily loses. A collision is a
    row deleted with no disposition, which invariant 8 cannot see because the
    row never reaches it."""
    rows = [r for _, r in sides[batch].bank + sides[batch].settlement]
    dupes = [k for k, n in Counter(r.record_id for r in rows).items() if n > 1]
    assert dupes == [], dupes


@pytest.mark.parametrize("batch", ["A", "B"])
def test_identity_is_not_positional(sides, batch):
    """`source:ordinal` is what made an id-keyed rule fire on unrelated rows in
    another batch. An id must not be derivable from where a row happened to sit."""
    for _, record in sides[batch].settlement:
        assert record.record_id != f"{record.source}:{record.row_ordinal}"
        assert record.natural_key, "a declared source must yield a natural key"


def test_an_id_shared_across_batches_denotes_the_same_claimed_event(sides):
    """The invariant, corrected by the data.

    "No id may appear in two batches" was too strong, and running it said so:
    one does — the `E07` chargeback, which reverses the *same* prior-period
    payment in both batches. Identical claimed event, so identical identity is
    right. What was wrong before was the opposite: `gateway-settlement:266`
    existed in both batches and named **different** rows, so an id-keyed rule
    scored as general because it fired on strangers.
    """
    a = {r.record_id: r for _, r in sides["A"].settlement}
    b = {r.record_id: r for _, r in sides["B"].settlement}
    for record_id in set(a) & set(b):
        assert a[record_id].natural_key == b[record_id].natural_key, record_id


def test_an_id_keyed_rule_no_longer_fires_on_strangers(sides):
    """The behavioural check that the structural ban was standing in for.

    A rule naming rows from batch A must find nothing to say about batch B. Under
    positional ids it found two — unrelated rows that happened to sit at the same
    offsets — and passed the generality check on them.
    """
    victims = [r.record_id for _, r in sides["A"].settlement if r.key_occurrence > 0]
    assert len(victims) == 2
    pinned = Rule(
        rule_id="R-PINNED",
        profile="settlement_3way",
        when=[Predicate(field="record_id", op=Operator.IN, value=victims)],
        then=[RuleAction(kind=ActionKind.SUPPRESS, reason="those two rows")],
    )
    assert select(pinned, [r for _, r in sides["A"].settlement]).count == 2
    assert select(pinned, [r for _, r in sides["B"].settlement]).count == 0
    assert not generalises(pinned, [r for _, r in sides["B"].settlement]).generalises


def test_the_duplicate_is_the_only_thing_with_a_repeated_key(sides):
    """Exactly the planted `E06`, found as a property rather than by naming rows."""
    repeats = [r for _, r in sides["A"].settlement if r.key_occurrence > 0]
    externals = {sides["A"].settlement[i][0] for i in range(len(sides["A"].settlement))}
    assert len(repeats) == 2, [r.natural_key for r in repeats]
    assert externals  # the fixture is real


def test_a_natural_key_cannot_reach_untrusted_source_text():
    """`raw` is the document's own words. A spec that could name it would let a
    model-authored spec make the *engine* branch on attacker-controlled text —
    indirect prompt injection with a longer fuse."""
    from recon.intake.spec import SpecError, _natural_key_of

    record = next(r for _, r in load_sides("A").settlement)
    for reachable in ("raw", "keys", "doc_hash", "record_id", "__class__"):
        with pytest.raises(SpecError, match="not a readable field"):
            _natural_key_of(record, [reachable])
    assert _natural_key_of(record, ["amount"]) == f"{record.amount:.2f}"


def test_every_shipped_spec_declares_a_natural_key():
    """Positional identity still exists as a fallback for a source that declares
    none. This keeps that path from being the one we actually rely on."""
    for path in sorted(ADAPTER_DIR.glob("*.json")):
        spec = load_spec(json.loads(path.read_text())["spec_id"])
        assert spec.natural_key, f"{spec.spec_id} declares no natural key"


# --------------------------------------------------------------------------
# the production it buys
# --------------------------------------------------------------------------


def test_a_duplicate_is_expressible_without_naming_a_row(sides):
    """The rule that had no path through the system. One unary predicate over a
    partition-relative field."""
    assert all(p.field == "key_occurrence" for p in DEDUP.when)
    for batch in ("A", "B"):
        rows = [r for _, r in sides[batch].settlement]
        assert select(DEDUP, rows).count == 2, batch


def test_the_duplicate_rule_generalises_to_the_held_out_batch(sides):
    """It was induced from A's duplicate and fires on B's, which is a different
    payment under a different id. That is what a rule is."""
    outcome = generalises(DEDUP, [r for _, r in sides["B"].settlement])
    assert outcome.generalises
    assert outcome.fires == 2


def test_the_duplicate_rule_creates_a_real_proven_match(sides):
    """Not merely 'adds a pair'. Suppressing the two repeated rows makes group
    `pout_00011` sum to exactly the bank credit it never matched, and the
    independent verifier re-derives it from the records."""
    a = sides["A"]
    ext = {r.record_id: e for e, r in a.bank + a.settlement}
    suppressed = set(select(DEDUP, [r for _, r in a.settlement]).matched)
    assert sorted(ext[r] for r in suppressed) == ["ch_00493", "fee_00247"]

    kept = [r for _, r in a.settlement if r.record_id not in suppressed]
    after = run_tiers(
        [r for _, r in a.anchors],
        kept,
        SETTLEMENT_3WAY,
        ProofTier.P0_ARITHMETIC,
        policy=SETTLEMENT_POLICY,
    )
    match = next(m for m in after.matches if ext[m.anchor_id] == "bl_00011")
    assert match.tier.value == "T0"
    assert match.proof.residual == 0
    records = {r.record_id: r for _, r in a.bank + a.settlement}
    assert verify(match.proof, records, SETTLEMENT_POLICY).proven


def test_the_duplicate_rule_survives_the_whole_promotion_gate(sides):
    """Regression, generality and every other control, on the real batch."""
    a, b = sides["A"], sides["B"]
    rows = [r for _, r in a.settlement]
    candidates = build_candidates([r for _, r in a.anchors], rows, BlockingPolicy())
    base = deterministic.run(
        a.bank,
        a.settlement,
        SETTLEMENT_3WAY,
        SETTLEMENT_POLICY,
        ProofTier.P0_ARITHMETIC,
        candidates,
        a.scope,
    )
    history = MatchHistory(
        anchors=[r for _, r in a.bank],
        group_records=rows,
        records={r.record_id: r for _, r in a.bank + a.settlement},
        matches=[type("M", (), {"anchor_id": m.anchor_id})() for m in base.matches],
    )
    outcome = regress(DEDUP, history, SETTLEMENT_3WAY, SETTLEMENT_POLICY)
    assert outcome.unmodelled == []
    assert outcome.broken == []
    assert len(outcome.added) == 1, outcome.added

    decision = evaluate(
        DEDUP,
        outcome,
        SETTLEMENT_POLICY,
        held_out=[r for _, r in b.settlement],
        induced_on=rows,
    )
    assert decision.allowed, decision.reasons


# --------------------------------------------------------------------------
# what the benchmark's own labels assert
# --------------------------------------------------------------------------


def test_the_label_for_the_duplicated_payout_does_not_balance(sides):
    """Pins the finding so it cannot quietly disappear.

    `payout_membership` records which rows *belong to* a payout, and for the
    planted `E06` that includes the duplicated row. So the labelled answer for
    `bl_00011` sums to ₹90,259.47 against a credit of ₹84,769.72 — a linkage
    that is true and an equation that does not balance.

    `auto-match` scores against that label. An arm naming the linkage scores
    **correct**; the deterministic arm refuses it (invariant 2 — a match without
    a passing proof is not a match) and scores a **miss**. So the metric has been
    rewarding unprovable answers since P3 and penalising the engine for
    declining them.

    The label is not wrong — it is a linkage label, and it is accurate. It is
    the *metric* that was reading it as a reconciliation. `unprovable matches`
    is what tells the two apart, and this test is why it exists.
    """
    from decimal import Decimal

    from bench.metrics import truth_pairs

    truth = truth_pairs(BATCHES / "A" / "labels.json")
    by_ext = {e: r for e, r in sides["A"].bank + sides["A"].settlement}
    claimed = truth["bl_00011"]
    total = sum((by_ext[e].amount for e in claimed if e in by_ext), Decimal("0.00"))
    anchor = by_ext["bl_00011"].amount

    assert anchor == Decimal("84769.72")
    assert total == Decimal("90259.47")
    assert abs(anchor - total) > SETTLEMENT_3WAY.tolerance.absolute, (
        "the labelled pairing now balances — if the generator changed, this "
        "finding needs rewriting rather than deleting"
    )


def test_the_deterministic_arm_reports_no_unprovable_match(sides):
    """Invariant 2, measured rather than asserted. Every match it reports
    carries a proof the verifier re-derives, so the count is zero by
    construction — and if it ever is not, the invariant has been broken."""
    from bench.arms import deterministic
    from bench.metrics import unprovable_matches

    from recon.engine.blocking import BlockingPolicy
    from recon.engine.blocking import build as build_candidates

    a = sides["A"]
    candidates = build_candidates(
        [r for _, r in a.anchors], [r for _, r in a.settlement], BlockingPolicy()
    )
    result = deterministic.run(
        a.bank,
        a.settlement,
        SETTLEMENT_3WAY,
        SETTLEMENT_POLICY,
        ProofTier.P0_ARITHMETIC,
        candidates,
        a.scope,
    )
    by_ext = {e: r for e, r in a.bank + a.settlement}
    assert unprovable_matches(result, by_ext, SETTLEMENT_3WAY.tolerance.absolute) == 0


def test_an_unprovable_pairing_is_counted(sides):
    """The detector, exercised on a pairing built to not balance. A counter that
    has never counted is not a measurement — `false_matches` taught that."""
    from bench.arms import ArmResult
    from bench.metrics import unprovable_matches

    a = sides["A"]
    by_ext = {e: r for e, r in a.bank + a.settlement}
    anchor = next(e for e, r in a.anchors)
    wrong = next(e for e, r in a.settlement if r.group_ref)
    arm = ArmResult(name="x", pairs={anchor: frozenset({wrong})}, tiers={"t": 1})
    assert unprovable_matches(arm, by_ext, SETTLEMENT_3WAY.tolerance.absolute) == 1
