"""Metamorphic relations — an oracle from outside the system.

Every other test here was written by the same person who wrote the code, so it
can only confirm what that person believed. Eleven shallow proxies got through
that way, and none was found by review. A metamorphic relation is different in
kind: it makes no claim about what the answer *is*, only about how the answer
must **relate** to itself when the input changes in a way that should not
matter. It is stated in domain terms, so a control that is merely self-consistent
fails it.

That is not theoretical. `Policy.max_selectivity_pct` shipped with a mutation
test that killed it — the code was reachable and enforced. It survived one
commit. `test_a_rules_verdict_is_invariant_to_padding` below refuted it: the
same rule, still firing on the same 502 rows, went from refused to allowed when
1,500 unrelated rows were added. **A mutant proves code is reachable. A relation
proves it means something.** Those are different questions and only the second
one was ever in doubt.

The transformations are generated rather than hand-picked, so the inputs are not
ones the author chose. Example counts are small on purpose: each relation runs a
real close, and a suite nobody waits for is a suite nobody runs.

**Which of these are demonstrated to bite, and which are only guards.** A
property test that cannot fail is worse than none, so each was mutation-probed
when written:

    padding            DEMONSTRATED — refutes the reintroduced selectivity cap
    out-of-scope       DEMONSTRATED — refutes an engine that ignores the scope map
    row order          VACUOUS ON THIS CORPUS — see its docstring
    key rename         guard — no mutation constructed
    drop unmatched     guard — no mutation constructed
    predicate order    guard — no mutation constructed
    generality symmetry guard — no mutation constructed

Marked rather than quietly assumed. A guard is still worth having — it costs
nothing and catches a regression the day the corpus grows a case for it — but it
is not evidence that anything is currently checked.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal

import pytest
from bench.arms import deterministic
from bench.run import SETTLEMENT_3WAY, SETTLEMENT_POLICY, load_sides
from hypothesis import HealthCheck, event, given, settings
from hypothesis import strategies as st

from recon.contracts import ProofTier, Record
from recon.contracts.rule import ActionKind, Operator, Predicate, Rule, RuleAction
from recon.engine.promotion import MatchHistory, evaluate, generalises, regress

BATCHES = pytest.importorskip("pathlib").Path("data/batches")
SLOW = settings(
    max_examples=8,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


@pytest.fixture(scope="module", autouse=True)
def _batches_exist():
    if not (BATCHES / "A" / "labels.json").exists():
        pytest.skip("run `make gen` first")


@pytest.fixture(scope="module")
def sides():
    return load_sides("A")


def _close(bank, settlement, scope):
    return deterministic.run(
        bank,
        settlement,
        SETTLEMENT_3WAY,
        SETTLEMENT_POLICY,
        ProofTier.P0_ARITHMETIC,
        scope,
    )


def _fingerprint(outcome):
    """Everything the run decided, in a form that ignores nothing that matters
    and nothing that does not: pairs, how each was found, and what was raised."""
    return (
        tuple(sorted((a, tuple(sorted(g))) for a, g in outcome.pairs.items())),
        tuple(sorted(outcome.tiers.items())),
        tuple(sorted((e.code, str(e.amount)) for e in outcome.exceptions)),
    )


@pytest.fixture(scope="module")
def baseline(sides):
    return _fingerprint(_close(sides.bank, sides.settlement, sides.scope))


# --------------------------------------------------------------------------
# relations over the close
# --------------------------------------------------------------------------


def _contest(sides) -> tuple[list, list]:
    """Make one anchor genuinely contested, and return (anchors, settlement).

    Batch A has none: zero of 23 anchors have two groups within tolerance, so
    every relation about ambiguity was unfalsifiable on it.

    Two steps, and the first was not obvious. Cloning a group is not enough —
    `T0` matches on the anchor's *exact reference*, so an anchor that names its
    group is resolved by name before ambiguity can arise. The anchor's reference
    is stripped so it falls to `T1`, and only then does a cloned group of equal
    total actually compete.

    That is a fact about the engine worth stating: `T0` is immune to this class
    of ambiguity by construction, and only referenceless anchors can be
    contested.
    """
    from collections import defaultdict

    groups = defaultdict(list)
    for ext, record in sides.settlement:
        if record.group_ref:
            groups[record.group_ref].append((ext, record))
    ref = next(r for r in sorted(groups) if any(a.source_row_id == r for _, a in sides.anchors))
    anchors = [
        (ext, a.model_copy(update={"source_row_id": None}) if a.source_row_id == ref else a)
        for ext, a in sides.anchors
    ]
    twin = [
        (
            f"{ext}-twin",
            record.model_copy(
                update={
                    "record_id": f"{record.record_id}-twin",
                    "group_ref": f"{ref}-twin",
                    "natural_key": f"{record.natural_key}|twin",
                }
            ),
        )
        for ext, record in groups[ref]
    ]
    return anchors, [*sides.settlement, *twin]


def _contested_anchor_count(anchors, settlement) -> int:
    """How many anchors have more than one group within tolerance."""
    from collections import defaultdict

    totals = defaultdict(Decimal)
    for _, record in settlement:
        if record.group_ref:
            totals[record.group_ref] += record.amount
    tolerance = SETTLEMENT_3WAY.tolerance.absolute
    return sum(
        1
        for _, anchor in anchors
        if sum(1 for t in totals.values() if abs(anchor.amount - t) <= tolerance) > 1
    )


def test_two_equally_viable_groups_produce_no_match(sides):
    """**The relation that discovers.** An anchor with two groups equally within
    tolerance must produce no match at all.

    This is CLAUDE.md's banned pattern stated as a relation — "subset-sum
    returning the first solution found... silently produces confident wrong
    answers" — and it applies to the tiers too. Resolving ambiguity by taking
    the first candidate is *deterministic*, so an order-invariance relation
    cannot see it. This one can.
    """
    anchors, contested = _contest(sides)
    reached = _contested_anchor_count(anchors, contested)
    # `event()` needs a Hypothesis context; this relation has no generated
    # input, so the assertion carries the whole weight. Either way the rule is
    # the same: a relation that cannot reach the state it constrains fails.
    assert reached >= 1, "the injection produced no contest — the relation would be vacuous"

    uncontested = _close(sides.bank, sides.settlement, sides.scope)
    anchor_pairs = [(e, a) for e, a in anchors]
    stripped = [(e, a) for e, a in anchor_pairs if a.source_row_id is None]
    assert stripped, "the fixture must strip exactly one anchor's reference"
    victim = stripped[0][0]

    with_contest = _close(
        [(e, a) for e, a in sides.bank if e != victim]
        + [p for p in anchor_pairs if p[0] == victim],
        contested,
        sides.scope,
    )
    # The discriminating half: it *was* matched before the contest existed, so
    # the absence below is the contest doing the work and not the fixture being
    # broken. (`or True` sat here for one commit and ruff caught it — a vacuous
    # assertion is a shallow proxy the linter found and my review did not.)
    assert victim in uncontested.pairs, "the fixture anchor was never matched to begin with"
    assert victim not in with_contest.pairs, (
        "an anchor with two equally viable groups was matched to one of them — "
        "ambiguity resolved rather than reported"
    )


@given(seed=st.integers(min_value=0, max_value=2**30))
@SLOW
def test_the_outcome_is_invariant_to_input_row_order(sides, baseline, seed):
    """A statement is the same statement whichever order its lines arrive in.

    Run on the contested corpus, with the state asserted, so it cannot silently
    go vacuous the way it was: batch A alone has no contested anchor, and
    mutating `run()` to take the first viable group left every relation green.

    Honest about what it is, measured not assumed: the engine iterates
    `sorted(grouped.items())`, so order-independence holds by construction —
    and removing that sort is **still** not detectable, because `run` refuses on
    anything but a single candidate, so the order of candidates is never
    observed. The sort is redundant *given* the ambiguity refusal, and load
    bearing only if that refusal is ever relaxed.

    So this relation confirms a property rather than discovering one. It is kept
    because the pair matters: relax `len(viable) != 1` and the sort becomes the
    difference between deterministic and not, and the relation above would fire
    first. The one that discovers today is `test_two_equally_viable_groups...`.
    """
    anchors, contested = _contest(sides)
    reached = _contested_anchor_count(anchors, contested)
    event(f"contested anchors: {reached}")
    assert reached >= 1

    rng = random.Random(seed)
    bank, settlement = list(sides.bank), list(contested)
    rng.shuffle(bank)
    rng.shuffle(settlement)
    assert _fingerprint(_close(bank, settlement, sides.scope)) == _fingerprint(
        _close(list(reversed(bank)), list(reversed(settlement)), sides.scope)
    )


@given(
    amount=st.decimals(min_value=Decimal("1.00"), max_value=Decimal("999999.00"), places=2),
    day=st.integers(min_value=0, max_value=60),
)
@SLOW
def test_an_out_of_scope_record_changes_nothing(sides, baseline, amount, day):
    """Declaring a record out of scope must remove it from consideration, not
    perturb what remains. If a debit nobody reconciles can move a match, scope is
    not a boundary — it is a suggestion."""
    noise = Record(
        record_id="icici-camt:mr-noise",
        side="bank",
        source="icici-camt",
        row_ordinal=9999,
        posted_on=date(2026, 8, 1) + timedelta(days=day),
        amount=-amount,
        currency="INR",
        doc_hash="h" * 8,
        keys={"entry_ref": "bl_mr_noise"},
        raw={"AddtlNtryInf": "SALARY/OUT OF SCOPE"},
    )
    bank = [*sides.bank, ("bl_mr_noise", noise)]
    scope = {**sides.scope, noise.record_id: "debit — not part of the settlement loop"}
    assert _fingerprint(_close(bank, sides.settlement, scope)) == baseline


@given(new_name=st.text(alphabet="abcdefghijklmnopqrstuvwxyz-", min_size=3, max_size=18))
@SLOW
def test_renaming_a_match_key_on_both_sides_preserves_the_matches(sides, baseline, new_name):
    """Keys exist to be compared. Renaming one consistently across both sides
    changes what it is called and nothing about which rows agree — unless
    something is keying on the literal value, which would be a hidden
    domain assumption inside a domain-agnostic engine (invariant 7).
    """

    def rename(pairs):
        out = []
        for ext, record in pairs:
            if record.keys.get("gateway") == "razorpay":
                record = record.model_copy(update={"keys": {**record.keys, "gateway": new_name}})
            out.append((ext, record))
        return out

    renamed = _fingerprint(_close(rename(sides.bank), rename(sides.settlement), sides.scope))
    assert len(renamed[0]) == len(baseline[0])
    assert renamed[1] == baseline[1], "the tier split moved when only a name changed"


@given(seed=st.integers(min_value=0, max_value=2**30))
@SLOW
def test_dropping_an_unmatched_anchor_disturbs_no_match(sides, baseline, seed):
    """An anchor nothing matched contributes nothing. Removing it must leave
    every proven match exactly as it was — otherwise matches depend on the
    company an anchor keeps, not on the arithmetic."""
    base = _close(sides.bank, sides.settlement, sides.scope)
    matched = set(base.pairs)
    unmatched = [
        (ext, rec)
        for ext, rec in sides.bank
        if ext not in matched and rec.record_id not in sides.scope
    ]
    if not unmatched:
        pytest.skip("batch A has no unmatched anchor to drop")
    victim = unmatched[random.Random(seed).randrange(len(unmatched))]

    after = _close([p for p in sides.bank if p is not victim], sides.settlement, sides.scope)
    assert after.pairs == base.pairs
    assert after.tiers == base.tiers


# --------------------------------------------------------------------------
# relations over the promotion gate
# --------------------------------------------------------------------------


def _advisory(*predicates: Predicate) -> Rule:
    return Rule(
        rule_id="R-MR",
        profile="settlement_3way",
        when=list(predicates),
        then=[RuleAction(kind=ActionKind.RAISE_ADVISORY, target="E06", reason="metamorphic probe")],
    )


@pytest.fixture(scope="module")
def history(sides):
    base = _close(sides.bank, sides.settlement, sides.scope)
    return MatchHistory(
        anchors=[rec for _, rec in sides.bank],
        group_records=[rec for _, rec in sides.settlement],
        records={rec.record_id: rec for _, rec in sides.bank + sides.settlement},
        matches=[type("M", (), {"anchor_id": m.anchor_id})() for m in base.matches],
    )


def _verdict(rule, history, induced_on, held_out):
    outcome = regress(rule, history, SETTLEMENT_3WAY, SETTLEMENT_POLICY)
    return evaluate(
        rule, outcome, SETTLEMENT_POLICY, held_out=held_out, induced_on=induced_on
    ).allowed


@given(swap=st.booleans())
@SLOW
def test_a_rules_verdict_is_invariant_to_predicate_order(sides, history, swap):
    """`when [A, B]` and `when [B, A]` are the same rule. A gate that judged them
    differently would be judging the text."""
    a = Predicate(field="keys.row_type", op=Operator.EQ, value="refund")
    b = Predicate(field="keys.gateway", op=Operator.EQ, value="razorpay")
    rows = [rec for _, rec in sides.settlement]
    first = _verdict(_advisory(a, b), history, rows, rows)
    second = _verdict(_advisory(b, a), history, rows, rows)
    assert first == second


@given(pad=st.integers(min_value=0, max_value=4000))
@SLOW
def test_a_rules_verdict_is_invariant_to_padding(sides, history, pad):
    """**The relation that refuted `max_selectivity_pct`.**

    Adding rows a rule never mentions changes nothing about the rule. It still
    fires on exactly the same records and would still flag exactly the same
    items. A verdict that moves is measuring the corpus.

    Kept after the control it killed was deleted, so a replacement is refuted
    the same way rather than shipping and being discovered later.
    """
    rows = [rec for _, rec in sides.settlement]
    broad = _advisory(Predicate(field="keys.row_type", op=Operator.IN, value=["charge", "fee"]))

    padded = rows + [
        rec.model_copy(
            update={"record_id": f"mr-pad:{i}", "keys": {**rec.keys, "row_type": "refund"}}
        )
        for i, rec in enumerate((rows * 10)[:pad])
    ]
    fires_before = generalises(broad, rows).fires
    fires_after = generalises(broad, padded).fires
    assert fires_after == fires_before, "the padding was supposed to be irrelevant"

    other = load_sides("B")
    reference = [rec for _, rec in other.settlement]
    # The reference denominator must be untouched by anything done to the
    # induction set. This is now true *by construction* — breadth is measured on
    # the reference — rather than by the padding happening to stay under a cap.
    assert generalises(broad, reference).sampled == len(reference)

    assert _verdict(broad, history, rows, reference) == _verdict(
        broad, history, padded, reference
    ), (
        f"the same rule, still firing on the same {fires_before} rows, changed "
        f"verdict when {pad} unrelated rows were added to the induction set"
    )


def test_generality_is_symmetric_between_batches(sides):
    """If a rule generalises from A to B it must generalise from B to A. An
    asymmetric answer would mean the check is reading something about the batch
    rather than about the rule."""
    other = load_sides("B")
    rule = _advisory(Predicate(field="keys.row_type", op=Operator.EQ, value="refund"))
    a_rows = [rec for _, rec in sides.settlement]
    b_rows = [rec for _, rec in other.settlement]
    assert generalises(rule, b_rows).generalises == generalises(rule, a_rows).generalises


def test_the_order_relation_is_vacuous_on_this_corpus_and_says_so(sides):
    """Pins the measurement behind the docstring above.

    If this ever fails, batch A has grown an anchor with competing groups and
    `test_the_outcome_is_invariant_to_input_row_order` has stopped being a guard
    and started being a check — which is good news, and the docstring above needs
    correcting rather than the test.
    """
    from collections import defaultdict

    groups = defaultdict(list)
    for _, record in sides.settlement:
        if record.group_ref:
            groups[record.group_ref].append(record)
    totals = {ref: sum((r.amount for r in rows), Decimal("0.00")) for ref, rows in groups.items()}
    tolerance = SETTLEMENT_3WAY.tolerance.absolute
    contested = [
        ext
        for ext, anchor in sides.anchors
        if sum(1 for t in totals.values() if abs(anchor.amount + t) <= tolerance) > 1
    ]
    assert contested == [], (
        f"batch A now has {len(contested)} contested anchor(s) — the order relation "
        f"is no longer vacuous, update its docstring"
    )


# --------------------------------------------------------------------------
# the registry is the only place that knows what a code means
# --------------------------------------------------------------------------


def test_no_module_outside_the_registry_holds_a_literal_set_of_code_ids():
    """The architectural fitness function for P11's claim.

    P11 established that facts about a code are registry data. P12 then wrote
    `DERIVED_CODES = frozenset({"E09", "E13"})` into the triage module and left
    `HONESTY_CODES` in the contracts package — the same failure, one phase later,
    in two files. Nothing caught it because the claim lived only in prose.

    An AST walk is the check: any collection literal containing two or more code
    ids, outside the registry, is a fact about codes living somewhere it cannot
    be governed. Uses the same technique that already enforces ADR-001 in
    `gate_p2`, so it costs no new dependency.
    """
    import ast
    import re as _re
    from pathlib import Path

    code_id = _re.compile(r"^(E[0-9]{2}|X-[A-Z][A-Z0-9-]{2,31})$")
    # Only the seeded-id enum. The registry *module* defines the schema, not the
    # instances — ids come from `data/taxonomy/codes.json`. Mutation found this:
    # exempting `taxonomy.py` let `escalates()` be rewritten to read a hardcoded
    # set and every test still passed.
    allowed = {Path("src/recon/contracts/exception.py")}
    offenders: list[str] = []

    for path in sorted(Path("src/recon").rglob("*.py")):
        if path in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Set | ast.List | ast.Tuple):
                continue
            literals = [
                e.value
                for e in node.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            ]
            hits = [v for v in literals if code_id.match(v)]
            if len(hits) >= 2:
                offenders.append(f"{path}:{node.lineno} {hits}")

    assert not offenders, (
        "facts about exception codes must live in the registry, not in a literal "
        f"collection of ids: {offenders}"
    )


def test_a_minted_code_can_carry_every_property_a_seeded_code_can():
    """The relation that would have caught it, stated behaviourally.

    P11's claim is that a code discovered later is a first-class code. That is
    only true if every question the system asks about a code can be answered for
    a minted one. While `escalation_is_correct` lived as `HONESTY_CODES` in
    Python, no `X-` code could ever be an honesty code however honest it was —
    the property existed and was unreachable through the lifecycle.
    """
    import json
    from pathlib import Path

    from recon.contracts import TaxonomyRegistry
    from recon.engine.taxonomy import accept, promote, propose

    registry = TaxonomyRegistry.model_validate(
        json.loads(Path("data/taxonomy/codes.json").read_text(encoding="utf-8"))
    )
    minted = promote(
        accept(
            propose(
                registry,
                code="X-CANNOT-DETERMINE",
                title="the source does not carry enough to decide",
                definition="A finding we can see but cannot attribute from the data present.",
                actor="agent:triage",
            ),
            "X-CANNOT-DETERMINE",
            actor="meera",
            owner="controller",
        ),
        "X-CANNOT-DETERMINE",
        actor="meera",
        definition="A finding we can see but cannot attribute from the data present.",
    )

    seeded = registry["E14"]
    fresh = minted["X-CANNOT-DETERMINE"]
    assert set(type(fresh).model_fields) == set(type(seeded).model_fields)

    # Every behavioural question, asked of both.
    for probe in (minted.escalates, minted.route, minted.assignable, minted.booking_for):
        probe("E14")
        probe("X-CANNOT-DETERMINE")

    # Set the property on the minted code and require the *behaviour* to follow.
    # Asserting `fresh.escalation_is_correct` alone was a shallow proxy: it tests
    # that a field can be assigned, which stays true even if `escalates()` reads
    # a hardcoded set of seeded ids and ignores the field entirely. Mutation
    # caught exactly that.
    assert not minted.escalates("X-CANNOT-DETERMINE")
    honest = minted.model_copy(
        update={
            "codes": {
                **minted.codes,
                "X-CANNOT-DETERMINE": fresh.model_copy(update={"escalation_is_correct": True}),
            }
        }
    )
    assert honest.escalates("X-CANNOT-DETERMINE"), (
        "a minted code cannot be an honesty code — the property is declared but "
        "the behaviour does not read it"
    )
    assert honest.escalates("E14"), "seeded codes must keep working"


def test_the_spec_author_is_told_every_per_verb_requirement():
    """The contract enforces four per-verb rules and the tool schema stated one,
    in prose. A model proposing `parse=constant` without `value` was refused for
    a rule nobody had given it — twice, in five live runs.

    Checked in **both** directions, and the first version was not: it iterated
    over what the data claimed, so deleting a requirement from the data made the
    test pass with nothing left to check. That is a control measuring one
    direction of harm, which is the failure this project keeps finding in its own
    gates. Here the required set is *derived* — omit each candidate argument and
    see what actually raises — and compared against what the author is told.
    """
    import pydantic

    from recon.contracts.adapter import VERB_REQUIREMENTS, CanonicalField, FieldMap, ParseVerb
    from recon.triage.normalize import _verb_help

    CANDIDATES = {
        "source": "col",
        "value": "x",
        "fmt": "YYYY-MM-DD",
        "pattern": "x",
        "sign_column": "c",
    }
    help_text = _verb_help()

    for verb in ParseVerb:
        derived = set()
        for argument in CANDIDATES:
            missing = {k: v for k, v in CANDIDATES.items() if k != argument}
            try:
                FieldMap(to=CanonicalField.RAW, parse=verb, **missing)
            except pydantic.ValidationError:
                derived.add(argument)

        claimed = set(VERB_REQUIREMENTS.get(verb.value, ()))
        # `source` is required by every verb but `constant`, and the help says so
        # once rather than repeating it; the per-verb data carries the extras.
        assert claimed - {"source"} == derived - {"source"}, (
            f"{verb.value}: the contract enforces {sorted(derived)} and the author "
            f"is told {sorted(claimed)}"
        )
        for argument in derived:
            assert f"`{argument}`" in help_text, (
                f"{verb.value} is refused without `{argument}` and nobody says so"
            )
