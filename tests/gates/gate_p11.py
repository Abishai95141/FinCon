"""Gate P11 — open taxonomy.

Gate: a novel finding gets a `PROPOSED` code, appears in triage, routes to an
owner, and is proven unable to affect a posting. Promotion requires a named
human and a written definition.

Written before the implementation. The phase exists because the agent arrives at
P12 and a closed enum gives it two options when it meets something new: pick the
nearest wrong code, or crash. Both are worse than saying "this is a kind of
thing I have not seen before" — but only if saying it grants no power.

Four ways to build an open taxonomy that is actually a hole:

* **Open means anything goes.** If the contract accepts any string, a typo is a
  new category and the audit trail fills with codes nobody defined. The *shape*
  is validated by the contract and the *meaning* by a registry; a code that
  resolves in neither must fail the close.
* **A proposal that grants itself authority.** A `CodeDefinition` arriving with
  `status: promoted` is audit finding `F1` wearing a taxonomy costume.
* **A check that only refuses.** A gate that refuses every proposed code proves
  nothing — it is indistinguishable from having no taxonomy. The posting rule
  must *honour* a promoted code's booking for the refusal of a proposed one to
  mean anything.
* **A permission nobody exercises.** "Cannot affect a posting" is trivially true
  while nothing consults the code at all. So the posting rule reads the code's
  booking, and the same code proves it before and after promotion.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal as D
from pathlib import Path

import pytest

pytestmark = pytest.mark.gate

BATCHES = Path("data/batches")
TAXONOMY_FILE = Path("data/taxonomy/codes.json")


@pytest.fixture(scope="module", autouse=True)
def _batches_exist():
    if not (BATCHES / "A" / "labels.json").exists():
        pytest.skip("run `make gen` first")


@pytest.fixture
def registry():
    from recon.contracts import TaxonomyRegistry

    return TaxonomyRegistry.model_validate_json(TAXONOMY_FILE.read_text(encoding="utf-8"))


@pytest.fixture
def proposed(registry):
    """A novel finding an agent could not have named yesterday."""
    from recon.engine.taxonomy import propose

    return propose(
        registry,
        code="X-FX-TIMING",
        title="FX rate moved between capture and settlement",
        definition="The gateway converted at a rate we cannot reproduce from the "
        "rate table on the settlement date.",
        actor="agent:triage",
        books_to="fee_variance",
        owner="treasury",
    )


def _exc(code, amount="1000.00", **kw):
    from recon.contracts import ReconException

    return ReconException(
        exception_id=kw.pop("exception_id", "EXC-T1"),
        code=code,
        as_of=kw.pop("as_of", date(2026, 8, 14)),
        amount=amount,
        record_ids=kw.pop("record_ids", ["r1"]),
        **kw,
    )


# --------------------------------------------------------------------------
# the gate proper
# --------------------------------------------------------------------------


def test_a_novel_finding_gets_a_proposed_code(proposed):
    from recon.contracts import CodeStatus

    entry = proposed["X-FX-TIMING"]
    assert entry.status is CodeStatus.PROPOSED
    assert entry.proposed_by == "agent:triage"
    assert entry.definition


def test_a_proposed_code_appears_in_triage_and_routes_to_an_owner(proposed):
    from recon.triage.worklist import build

    items = build([_exc("X-FX-TIMING", "4210.55")], proposed, as_of=date(2026, 8, 20))
    assert len(items) == 1
    assert items[0].owner, "an exception nobody owns is an exception nobody works"
    assert items[0].code.code == "X-FX-TIMING"


def test_a_proposed_code_routes_to_the_fallback_not_to_the_owner_it_claimed(proposed):
    """It may route. It may not choose *who* — naming an owner is a claim about
    someone else's queue, and a proposal cannot make it."""
    from recon.triage.worklist import build

    assert proposed["X-FX-TIMING"].owner == "treasury"
    item = build([_exc("X-FX-TIMING")], proposed, as_of=date(2026, 8, 20))[0]
    assert item.owner == proposed.default_owner
    assert item.owner != "treasury"


def test_a_proposed_code_cannot_direct_a_posting(proposed):
    """Half the pair. The code asks for `fee_variance`; unattributed cash goes to
    suspense until a human says otherwise."""
    from recon.contracts import Record
    from recon.ledger.accounts import AccountRole
    from recon.ledger.posting_rules import entries_for

    anchor = Record(
        record_id="r1",
        side="bank",
        source="s",
        row_ordinal=0,
        posted_on=date(2026, 8, 14),
        amount=D("1000.00"),
        currency="INR",
        doc_hash="h" * 8,
    )
    entries, declined = entries_for(
        matches=[],
        exceptions=[_exc("X-FX-TIMING")],
        records={"r1": anchor},
        anchor_side="bank",
        taxonomy=proposed,
    )
    roles = {p.role for p in entries[0].postings}
    assert roles == {AccountRole.BANK, AccountRole.SUSPENSE}
    assert AccountRole.FEE_VARIANCE not in roles
    assert any("X-FX-TIMING" in d and "not promoted" in d for d in declined), declined


def test_the_same_code_directs_a_posting_once_promoted(proposed):
    """The other half. Without this the refusal above proves nothing — a gate
    that refuses everything is indistinguishable from having no taxonomy."""
    from recon.contracts import Record
    from recon.engine.taxonomy import accept, promote
    from recon.ledger.accounts import AccountRole
    from recon.ledger.posting_rules import entries_for

    live = promote(
        accept(proposed, "X-FX-TIMING", actor="meera", owner="treasury"),
        "X-FX-TIMING",
        actor="meera",
        definition="Settlement FX differs from the rate table on the settlement "
        "date; the delta books to fee variance pending the gateway's rate file.",
    )
    anchor = Record(
        record_id="r1",
        side="bank",
        source="s",
        row_ordinal=0,
        posted_on=date(2026, 8, 14),
        amount=D("1000.00"),
        currency="INR",
        doc_hash="h" * 8,
    )
    entries, declined = entries_for(
        matches=[],
        exceptions=[_exc("X-FX-TIMING")],
        records={"r1": anchor},
        anchor_side="bank",
        taxonomy=live,
    )
    roles = {p.role for p in entries[0].postings}
    assert AccountRole.FEE_VARIANCE in roles
    assert not declined


def test_promotion_requires_a_named_human_and_a_written_definition(proposed):
    from recon.contracts import TaxonomyViolation
    from recon.engine.taxonomy import accept, promote

    accepted = accept(proposed, "X-FX-TIMING", actor="meera", owner="treasury")
    for actor, definition in (
        ("", "a real definition, long enough to mean something"),
        ("   ", "x" * 40),
    ):
        with pytest.raises(TaxonomyViolation):
            promote(accepted, "X-FX-TIMING", actor=actor, definition=definition)
    with pytest.raises(TaxonomyViolation, match="definition"):
        promote(accepted, "X-FX-TIMING", actor="meera", definition="fx thing")


def test_a_code_cannot_skip_the_lifecycle(proposed):
    """`PROPOSED -> PROVISIONAL -> PROMOTED`. Jumping straight to full authority
    is how a proposal grants itself the thing the lifecycle exists to withhold."""
    from recon.contracts import TaxonomyViolation
    from recon.engine.taxonomy import promote

    with pytest.raises(TaxonomyViolation, match="provisional"):
        promote(
            proposed,
            "X-FX-TIMING",
            actor="meera",
            definition="a definition long enough to satisfy the written requirement",
        )


# --------------------------------------------------------------------------
# the proposal cannot grant itself anything
# --------------------------------------------------------------------------


def test_a_proposal_arrives_proposed_whatever_it_asked_for(registry):
    """Audit finding `F1` in a taxonomy costume. The status is assigned by the
    registry, never read from the proposal."""
    from recon.contracts import CodeStatus
    from recon.engine.taxonomy import propose

    after = propose(
        registry,
        code="X-SNEAKY",
        title="looks fine",
        definition="a definition long enough to satisfy the written requirement",
        actor="agent:triage",
        status=CodeStatus.PROMOTED,
        promoted_by="nobody",
    )
    assert after["X-SNEAKY"].status is CodeStatus.PROPOSED
    assert after["X-SNEAKY"].promoted_by is None


def test_an_agent_may_not_mint_a_canonical_code(registry):
    """`E15` would sit in the canonical space beside codes a human ratified. A
    discovered code keeps its `X-` origin in its id forever, because a decision
    log from last quarter has to resolve it and renaming on promotion would
    break every reference."""
    from recon.contracts import TaxonomyViolation
    from recon.engine.taxonomy import propose

    with pytest.raises(TaxonomyViolation, match="namespace"):
        propose(
            registry,
            code="E15",
            title="mine now",
            definition="a definition long enough to satisfy the written requirement",
            actor="agent:triage",
        )


def test_a_proposal_cannot_overwrite_an_existing_code(registry):
    from recon.contracts import TaxonomyViolation
    from recon.engine.taxonomy import propose

    with pytest.raises(TaxonomyViolation, match="already"):
        propose(
            registry,
            code="E09",
            title="redefining ambiguity",
            definition="a definition long enough to satisfy the written requirement",
            actor="agent:triage",
        )


def test_the_registry_is_frozen(registry):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        registry.default_owner = "me"


def test_mutating_the_registry_returns_a_new_one(registry, proposed):
    assert "X-FX-TIMING" in proposed
    assert "X-FX-TIMING" not in registry, "the original registry was mutated in place"


# --------------------------------------------------------------------------
# the authority matrix
# --------------------------------------------------------------------------


def test_every_status_declares_its_authority():
    from recon.contracts import AUTHORITY, CodeStatus

    assert set(AUTHORITY) == set(CodeStatus)


def test_the_lifecycle_grants_powers_one_at_a_time():
    """The table, asserted rather than described. Each step adds exactly what it
    is meant to add."""
    from recon.contracts import AUTHORITY, CodeStatus

    proposed = AUTHORITY[CodeStatus.PROPOSED]
    provisional = AUTHORITY[CodeStatus.PROVISIONAL]
    promoted = AUTHORITY[CodeStatus.PROMOTED]
    retired = AUTHORITY[CodeStatus.RETIRED]

    assert proposed.may_label and not proposed.may_route_to_named_owner
    assert not proposed.may_fire_rule and not proposed.may_direct_posting

    assert provisional.may_route_to_named_owner
    assert not provisional.may_fire_rule and not provisional.may_direct_posting

    assert promoted.may_fire_rule and promoted.may_direct_posting

    assert not retired.assignable
    assert retired.may_label, "an old decision log still has to resolve its codes"


def test_only_a_promoted_code_may_fire_a_rule(proposed):
    from recon.contracts import CodeStatus

    for status in CodeStatus:
        entry = proposed["X-FX-TIMING"].model_copy(update={"status": status})
        assert entry.authority.may_fire_rule == (status is CodeStatus.PROMOTED)


def test_a_rule_keyed_on_a_non_promoted_code_is_refused(proposed):
    """The promotion gate learns about the taxonomy. A rule may not act on a
    category nobody has ratified — that is how a proposed code would acquire
    power by the side door."""
    from recon.contracts.rule import ActionKind, Operator, Predicate, Rule, RuleAction
    from recon.engine.promotion import RegressionOutcome, evaluate
    from tests.gates.gate_p8 import _policy

    rule = Rule(
        rule_id="R-FX",
        profile="promo_test",
        when=[Predicate(field="code", op=Operator.EQ, value="X-FX-TIMING")],
        then=[RuleAction(kind=ActionKind.SET_TOLERANCE, amount="0.30")],
    )
    outcome = RegressionOutcome(
        ran_at=datetime.now(UTC),
        policy_ref="settlement-in@v1",
        rule_ref=rule.ref,
        matches_checked=5,
    )
    decision = evaluate(rule, outcome, _policy(), taxonomy=proposed)
    assert not decision.allowed
    assert any("X-FX-TIMING" in r and "promoted" in r for r in decision.reasons), decision.reasons


def test_a_rule_keyed_on_a_promoted_code_is_allowed(registry):
    from recon.contracts.rule import ActionKind, Operator, Predicate, Rule, RuleAction
    from recon.engine.promotion import RegressionOutcome, evaluate
    from tests.gates.gate_p8 import _policy

    rule = Rule(
        rule_id="R-E02",
        profile="promo_test",
        when=[Predicate(field="code", op=Operator.EQ, value="E02")],
        then=[RuleAction(kind=ActionKind.SET_TOLERANCE, amount="0.30")],
    )
    outcome = RegressionOutcome(
        ran_at=datetime.now(UTC),
        policy_ref="settlement-in@v1",
        rule_ref=rule.ref,
        matches_checked=5,
    )
    assert evaluate(rule, outcome, _policy(), taxonomy=registry).allowed


# --------------------------------------------------------------------------
# open, but not "anything goes"
# --------------------------------------------------------------------------


def test_the_contract_accepts_a_code_that_did_not_exist_when_it_was_written():
    exc = _exc("X-SOMETHING-NEW")
    assert exc.code == "X-SOMETHING-NEW"


def test_a_malformed_code_is_refused_by_the_contract():
    from pydantic import ValidationError

    for bad in ("", "e09", "E9", "hello world", "X-", "X-ab", "'; DROP TABLE"):
        with pytest.raises(ValidationError):
            _exc(bad)


def test_a_code_that_resolves_nowhere_fails_the_close(registry):
    """Shape is not meaning. A well-formed id nobody defined is exactly the
    typo-becomes-a-category failure this phase exists to prevent."""
    from recon.contracts import TaxonomyViolation
    from recon.triage.worklist import build

    with pytest.raises(TaxonomyViolation, match="X-GHOST"):
        build([_exc("X-GHOST")], registry, as_of=date(2026, 8, 20))


def test_every_code_the_close_raises_resolves_in_the_registry(tmp_path):
    from bench.run import close

    result = close("A", journal_dir=tmp_path)
    unknown = [e.code for e in result.exceptions if e.code not in result.taxonomy]
    assert unknown == [], unknown


# --------------------------------------------------------------------------
# retirement — a code stops being assignable without becoming unreadable
# --------------------------------------------------------------------------


def test_a_retired_code_cannot_be_assigned_to_a_new_finding(registry):
    from recon.contracts import TaxonomyViolation
    from recon.engine.taxonomy import retire

    after = retire(registry, "E12", actor="meera", superseded_by="E11")
    assert not after.assignable("E12")
    with pytest.raises(TaxonomyViolation, match="retired"):
        after.check_assignable("E12")


def test_a_retired_code_still_resolves_for_an_old_decision(registry):
    """An audit of last quarter has to read. Retiring a code that would then stop
    resolving would make the record unreadable by the act of tidying it."""
    from recon.engine.taxonomy import retire

    after = retire(registry, "E12", actor="meera", superseded_by="E11")
    entry = after["E12"]
    assert entry.title
    assert entry.superseded_by == "E11"
    assert entry.authority.may_label


# --------------------------------------------------------------------------
# triage — ranked and routed, deterministically
# --------------------------------------------------------------------------


def test_the_worklist_ranks_by_cash_impact_and_age(registry):
    """Found by mutation: the first version of this test used amounts that
    already sorted correctly on money alone, so deleting the age factor entirely
    left it green. The case that discriminates is a *smaller* item that is old
    enough to outrank a bigger fresh one — ₹1,000 sitting for fifty days beats
    ₹20,000 from yesterday, which is the whole reason age is in the score."""
    from recon.triage.worklist import build

    items = build(
        [
            _exc("E01", "1000.00", exception_id="small-old", as_of=date(2026, 7, 1)),
            _exc("E01", "20000.00", exception_id="big-new", as_of=date(2026, 8, 19)),
            _exc("E01", "50.00", exception_id="tiny-new", as_of=date(2026, 8, 19)),
        ],
        registry,
        as_of=date(2026, 8, 20),
    )
    assert [i.exception.exception_id for i in items] == ["small-old", "big-new", "tiny-new"]
    assert [i.rank for i in items] == [1, 2, 3]
    assert items[0].cash_impact_paise < items[1].cash_impact_paise, (
        "the top item must be the smaller one, or age contributed nothing"
    )


def test_ranking_ties_break_deterministically(registry):
    """A worklist that shuffles between runs on identical data is a worklist
    nobody trusts."""
    from recon.triage.worklist import build

    same = [
        _exc("E01", "500.00", exception_id=eid, as_of=date(2026, 8, 1))
        for eid in ("zebra", "alpha", "middle")
    ]
    order = [i.exception.exception_id for i in build(same, registry, as_of=date(2026, 8, 20))]
    assert order == ["alpha", "middle", "zebra"]
    assert order == [
        i.exception.exception_id
        for i in build(list(reversed(same)), registry, as_of=date(2026, 8, 20))
    ]


def test_ranking_is_integer_arithmetic(registry):
    """CLAUDE.md rule 4. A ranking score that drifts on float rounding would
    reorder a worklist between runs for no reason anyone could explain."""
    from recon.triage.worklist import build

    item = build([_exc("E01", "1234.56")], registry, as_of=date(2026, 8, 20))[0]
    assert isinstance(item.score, int)
    assert isinstance(item.cash_impact_paise, int)


def test_every_exception_reaches_the_worklist_exactly_once(tmp_path):
    """Invariant 8's shape again: an exception nobody routes is an exception
    nobody works, and the worklist is where a human meets the tail."""
    from bench.run import close

    result = close("A", journal_dir=tmp_path)
    assert result.worklist
    assert len(result.worklist) == len(result.exceptions)
    assert {i.exception.exception_id for i in result.worklist} == {
        e.exception_id for e in result.exceptions
    }
    assert all(i.owner for i in result.worklist)


def test_the_worklist_shows_which_items_carry_an_unratified_code(proposed):
    from recon.triage.worklist import build

    items = build(
        [_exc("X-FX-TIMING", "500.00"), _exc("E01", "500.00", exception_id="EXC-T2")],
        proposed,
        as_of=date(2026, 8, 20),
    )
    novel = next(i for i in items if i.code.code == "X-FX-TIMING")
    ratified = next(i for i in items if i.code.code == "E01")
    assert novel.authority_note and "proposed" in novel.authority_note.lower()
    assert ratified.authority_note is None


# --------------------------------------------------------------------------
# the record
# --------------------------------------------------------------------------


def test_proposing_a_code_is_recorded(registry, tmp_path):
    from recon.contracts import EventKind
    from recon.engine.taxonomy import propose
    from recon.journal import Journal, read

    journal = Journal(tmp_path / "t.jsonl")
    propose(
        registry,
        code="X-NEW-THING",
        title="a new thing",
        definition="a definition long enough to satisfy the written requirement",
        actor="agent:triage",
        journal=journal,
    )
    events = read(tmp_path / "t.jsonl")
    assert [e.kind for e in events] == [EventKind.CODE_PROPOSED]
    assert events[0].actor == "agent:triage"
    assert events[0].payload.code == "X-NEW-THING"
    assert events[0].payload.granted == "label only"


def test_a_refused_promotion_of_a_code_is_recorded(proposed, tmp_path):
    from recon.contracts import EventKind, TaxonomyViolation
    from recon.engine.taxonomy import promote
    from recon.journal import Journal, read

    journal = Journal(tmp_path / "t.jsonl")
    with pytest.raises(TaxonomyViolation):
        promote(proposed, "X-FX-TIMING", actor="meera", definition="too short", journal=journal)
    events = read(tmp_path / "t.jsonl")
    assert [e.kind for e in events] == [EventKind.PROPOSAL_REFUSED]
    assert events[0].payload.proposal_kind == "exception_code"


def test_promoting_a_code_is_recorded(proposed, tmp_path):
    from recon.contracts import EventKind
    from recon.engine.taxonomy import accept, promote
    from recon.journal import Journal, read

    journal = Journal(tmp_path / "t.jsonl")
    accepted = accept(proposed, "X-FX-TIMING", actor="meera", owner="treasury", journal=journal)
    promote(
        accepted,
        "X-FX-TIMING",
        actor="meera",
        definition="a definition long enough to satisfy the written requirement",
        journal=journal,
    )
    kinds = [e.kind for e in read(tmp_path / "t.jsonl")]
    assert kinds == [EventKind.CODE_ACCEPTED, EventKind.CODE_PROMOTED]


def test_the_close_pins_the_taxonomy_it_ran_under(tmp_path):
    """Same reason the policy bytes are pinned: a run judged under a vocabulary
    nobody approved should be visible in the record, not invisible in memory."""
    import hashlib

    from bench.run import close

    from recon.contracts import EventKind
    from recon.journal import read

    result = close("A", journal_dir=tmp_path)
    header = next(e for e in read(result.journal_path) if e.kind is EventKind.CLOSE_STARTED)
    assert header.payload.taxonomy_digest == hashlib.sha256(TAXONOMY_FILE.read_bytes()).hexdigest()
    assert header.payload.taxonomy_ref


# --------------------------------------------------------------------------
# the shipped asset
# --------------------------------------------------------------------------


def test_the_seeded_codes_are_ratified_with_written_definitions(registry):
    from recon.contracts import CodeStatus

    seeded = [c for c in registry.codes.values() if c.code.startswith("E")]
    assert len(seeded) == 14
    for entry in seeded:
        assert entry.status is CodeStatus.PROMOTED, entry.code
        assert len(entry.definition) > 30, f"{entry.code} has no written definition"
        assert entry.promoted_by, entry.code
        assert entry.owner, f"{entry.code} routes nowhere"


def test_the_honesty_codes_book_nowhere_on_their_own(registry):
    """`E09`, `E13` and `E14` mean "no answer", "we ran out of compute" and "I do
    not know". A code that means "I do not know" must not carry an opinion about
    where the money goes — suspense is the absence of a decision, and that is the
    correct one."""
    from recon.ledger.accounts import AccountRole

    for code in ("E09", "E13", "E14"):
        assert registry.booking_for(code) is AccountRole.SUSPENSE, code


def test_the_contract_itself_refuses_a_promoted_code_with_no_definition():
    """Found by mutation. `promote()` checks this, but the *contract* is what
    guards a registry hand-edited on disk — and a promoted code is one that
    directs money, so "fx thing" arriving through the file must not load."""
    from pydantic import ValidationError

    from recon.contracts import CodeDefinition, CodeStatus

    base = dict(
        code="X-HAND-EDITED",
        title="added by hand",
        status=CodeStatus.PROMOTED,
        proposed_by="meera",
        proposed_at=datetime(2026, 8, 1, tzinfo=UTC),
        promoted_by="meera",
        promoted_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    with pytest.raises(ValidationError, match="written definition"):
        CodeDefinition(**base, definition="fx thing")
    with pytest.raises(ValidationError, match="named human"):
        CodeDefinition(**{**base, "promoted_by": "  "}, definition="x" * 40)

    ok = CodeDefinition(**base, definition="x" * 40)
    assert ok.is_ratified


def test_a_registry_key_that_disagrees_with_its_code_is_refused(registry):
    """The file is hand-editable. A key/code mismatch would make `resolve` and
    the entry disagree about what a code is called."""
    from pydantic import ValidationError

    from recon.contracts import TaxonomyRegistry

    raw = json.loads(registry.model_dump_json())
    raw["codes"]["E01"]["code"] = "E02"
    with pytest.raises(ValidationError, match="does not match"):
        TaxonomyRegistry.model_validate(raw)


def test_the_registry_names_who_approved_it(registry):
    assert registry.approved_by
    assert registry.version >= 1
    assert registry.ref


def test_the_taxonomy_asset_is_valid_json_and_round_trips(registry):
    from recon.contracts import TaxonomyRegistry

    again = TaxonomyRegistry.model_validate(json.loads(registry.model_dump_json()))
    assert again == registry


# --------------------------------------------------------------------------
# nothing measured changed
# --------------------------------------------------------------------------


def test_p10_numbers_are_unchanged(tmp_path):
    """P10's figures were taken on the unruled engine, before any rule could be
    promoted, so that is what they are compared against. Passing `rules=[]` is
    not a convenience — a close now loads the promoted store by default, and
    checking a later phase's improvement against an earlier phase's baseline
    would report a regression every time the system got better."""
    from bench.run import close

    card = {c.arm: c for c in close("A", journal_dir=tmp_path, rules=[]).cards}["deterministic"]
    assert card.produced == 20
    assert card.false_matches == 0
    assert card.exceptions.surfaced == 4
    assert card.exceptions.classified == 1


def test_a_promoted_rule_only_ever_improves_on_that_baseline(tmp_path):
    """The other half, and the one that would catch a promoted rule making
    things worse: the shipped store must not do worse than the bare engine on
    any headline number. A rule that trades a finding for a match passes every
    delta check and fails this."""
    from bench.run import close

    bare = {c.arm: c for c in close("A", journal_dir=tmp_path / "a", rules=[]).cards}
    ruled = {c.arm: c for c in close("A", journal_dir=tmp_path / "b").cards}
    before, after = bare["deterministic"], ruled["deterministic"]

    assert after.correct >= before.correct
    assert after.false_matches <= before.false_matches
    assert after.exceptions.surfaced >= before.exceptions.surfaced
    assert after.exceptions.classified >= before.exceptions.classified


def test_the_worklist_says_how_far_the_routing_actually_spread(tmp_path):
    """The uncomfortable number. Routing works and has nothing to discriminate
    on, because every exception this engine raises is an honesty code and
    honesty codes all belong to the controller. A dispersion of 1 says
    classification is the bottleneck in a way a green test cannot."""
    from bench.run import close

    from recon.triage.worklist import summarise

    bare = summarise(close("A", journal_dir=tmp_path / "a", rules=[]).worklist)
    assert "1 owner(s): controller" in bare
    assert "nothing to discriminate" in bare

    # And what breaking the bottleneck looks like. `R-DUP-06` re-codes one E14
    # to E06, which the registry routes to gateway-ops rather than the
    # controller — so the dispersion this test was written to complain about
    # rises for the first time. One rule, one desk, and the number moves.
    ruled = summarise(close("A", journal_dir=tmp_path / "b").worklist)
    assert "2 owner(s)" in ruled and "gateway-ops" in ruled


def test_dispersion_rises_when_the_codes_actually_differ(registry):
    """The other half — the summary is measuring something, not asserting a
    conclusion. Give it exceptions that classify and the routing spreads."""
    from recon.triage.worklist import build, summarise

    items = build(
        [
            _exc("E02", "500.00", exception_id="a"),
            _exc("E07", "500.00", exception_id="b"),
            _exc("E11", "500.00", exception_id="c"),
        ],
        registry,
        as_of=date(2026, 8, 20),
    )
    assert {i.owner for i in items} == {"gateway-ops", "disputes", "master-data"}
    assert "3 owner(s)" in summarise(items)
    assert "nothing to discriminate" not in summarise(items)


def test_the_registry_ref_travels_with_the_worklist(tmp_path):
    from bench.run import close

    result = close("A", journal_dir=tmp_path)
    assert result.taxonomy.ref == "settlement-taxonomy@v1"


# --------------------------------------------------------------------------
# the contract refuses, rather than merely constructs (P1's rule, applied here)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "override,message",
    [
        ({"title": "  "}, "title"),
        ({"proposed_by": ""}, "who proposed"),
        ({"status": "retired"}, "retired without a date"),
    ],
)
def test_a_code_definition_refuses_what_it_cannot_stand_behind(override, message):
    from pydantic import ValidationError

    from recon.contracts import CodeDefinition

    base = dict(
        code="X-CHECKS",
        title="a title",
        definition="a definition long enough to satisfy the written requirement",
        proposed_by="meera",
        proposed_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    with pytest.raises(ValidationError, match=message):
        CodeDefinition(**{**base, **override})


@pytest.mark.parametrize(
    "override,message",
    [
        ({"approved_by": "  "}, "who approved"),
        ({"default_owner": ""}, "fallback owner"),
    ],
)
def test_a_registry_refuses_what_it_cannot_stand_behind(registry, override, message):
    from pydantic import ValidationError

    from recon.contracts import TaxonomyRegistry

    raw = json.loads(registry.model_dump_json())
    with pytest.raises(ValidationError, match=message):
        TaxonomyRegistry.model_validate({**raw, **override})


def test_a_supersession_pointing_at_nothing_is_refused(registry):
    """`superseded_by` is the pointer a reader follows out of a retired code. One
    that dangles turns tidying up into a dead end."""
    from pydantic import ValidationError

    from recon.contracts import TaxonomyRegistry

    raw = json.loads(registry.model_dump_json())
    raw["codes"]["E12"]["superseded_by"] = "X-DOES-NOT-EXIST"
    with pytest.raises(ValidationError, match="unknown"):
        TaxonomyRegistry.model_validate(raw)


@pytest.mark.parametrize(
    "call,message",
    [
        ("propose_blank_actor", "who made it"),
        ("accept_blank_actor", "who granted it"),
        ("accept_no_owner", "queue"),
        ("accept_wrong_status", "not proposed"),
        ("retire_blank_actor", "who did it"),
        ("retire_unknown_supersede", "not a code"),
    ],
)
def test_every_lifecycle_step_refuses_an_unnamed_or_impossible_move(proposed, call, message):
    from recon.contracts import TaxonomyViolation
    from recon.engine.taxonomy import accept, propose, retire

    fields = dict(
        title="t",
        definition="a definition long enough to satisfy the written requirement",
    )
    moves = {
        "propose_blank_actor": lambda: propose(proposed, code="X-Z", actor="  ", **fields),
        "accept_blank_actor": lambda: accept(proposed, "X-FX-TIMING", actor="", owner="ops"),
        "accept_no_owner": lambda: accept(proposed, "X-FX-TIMING", actor="meera", owner=" "),
        "accept_wrong_status": lambda: accept(proposed, "E09", actor="meera", owner="ops"),
        "retire_blank_actor": lambda: retire(proposed, "E09", actor=""),
        "retire_unknown_supersede": lambda: retire(
            proposed, "E09", actor="meera", superseded_by="X-GHOST"
        ),
    }
    with pytest.raises(TaxonomyViolation, match=message):
        moves[call]()


def test_an_empty_worklist_says_so_rather_than_rendering_nothing():
    from recon.triage.worklist import summarise

    assert "empty" in summarise([])


def test_the_summary_counts_unratified_items(proposed):
    from recon.triage.worklist import build, summarise

    items = build(
        [_exc("X-FX-TIMING", "100.00"), _exc("E01", "100.00", exception_id="b")],
        proposed,
        as_of=date(2026, 8, 20),
    )
    assert "1 carry an unratified code" in summarise(items)


def test_authority_of_reads_through_the_matrix(registry, proposed):
    from recon.contracts import AUTHORITY, CodeStatus

    assert registry.authority_of("E09") == AUTHORITY[CodeStatus.PROMOTED]
    assert proposed.authority_of("X-FX-TIMING") == AUTHORITY[CodeStatus.PROPOSED]
