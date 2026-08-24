"""Gate P1 — contracts + canonical Record + ledger.

Gate: round-trip a hand-built journal through Beancount; an unbalanced entry is
*rejected*; a wrong closing balance *blocks* the close.

The contract tests assert the validators actually refuse bad input. A contract
whose validators pass everything is documentation, not a contract.
"""

from __future__ import annotations

import pathlib
from datetime import UTC, date, datetime
from decimal import Decimal as D

import pytest
from pydantic import ValidationError

from recon.contracts import (
    CONTRACT_VERSION,
    AdapterSpec,
    CanonicalField,
    ExceptionCode,
    FieldMap,
    MatchTier,
    ParseVerb,
    Proof,
    ProofLeg,
    ProofTier,
    ReaderKind,
    ReaderSpec,
    ReconException,
    Record,
    RegressionReport,
    Rule,
    RuleStatus,
)
from recon.contracts.rule import ActionKind, Operator, Predicate, RuleAction
from recon.ledger.accounts import AccountRole as Role
from recon.ledger.accounts import ChartOfAccounts
from recon.ledger.beancount_io import (
    CloseBlocked,
    JournalEntry,
    Posting,
    load,
    post_and_assert,
    render,
)
from recon.profiles.chart import load_chart

pytestmark = pytest.mark.gate

OPENED = date(2026, 8, 1)
PERIOD_END = date(2026, 8, 31)


def _payout_entry(entry_id: str = "M-0001", on: date = date(2026, 8, 14)) -> JournalEntry:
    return JournalEntry(
        entry_id=entry_id,
        entry_date=on,
        narration='payout "pout_00007" — 214 charges',
        proof_id="PRF-0001",
        postings=[
            Posting(Role.BANK, D("1842907.30")),
            Posting(Role.FEES, D("24313.70")),
            Posting(Role.CLEARING, D("-1867221.00")),
        ],
    )


# --------------------------------------------------------------------------
# the gate proper
# --------------------------------------------------------------------------


def test_journal_round_trips_through_beancount():
    entry = _payout_entry()
    assert entry.residual() == D("0.00")

    result = post_and_assert(
        [entry], load_chart("settlement_3way"), OPENED, PERIOD_END, {Role.BANK: D("1842907.30")}
    )
    assert not result.blocked, result.errors
    assert result.entries_loaded == 1

    # Metadata survives the round trip — a proof id that does not reach the
    # journal cannot be traced back from an auditor's side.
    loaded, errors = load(result.text)
    assert not errors
    txns = [d for d in loaded if getattr(d, "narration", None)]
    assert len(txns) == 1
    assert txns[0].meta["entry_id"] == "M-0001"
    assert txns[0].meta["proof_id"] == "PRF-0001"


def test_unbalanced_entry_is_rejected():
    bad = JournalEntry(
        "M-0002",
        date(2026, 8, 14),
        "postings do not sum to zero",
        [Posting(Role.BANK, D("100.00")), Posting(Role.INCOME, D("-90.00"))],
    )
    assert bad.residual() == D("10.00")
    result = post_and_assert([bad], load_chart("settlement_3way"), OPENED, PERIOD_END)
    assert result.blocked
    assert "ValidationError" in result.error_kinds
    with pytest.raises(CloseBlocked):
        result.raise_if_blocked()


def test_wrong_closing_balance_blocks_the_close():
    result = post_and_assert(
        [_payout_entry()],
        load_chart("settlement_3way"),
        OPENED,
        PERIOD_END,
        {Role.BANK: D("999999.00")},
    )
    assert result.blocked
    assert "BalanceError" in result.error_kinds
    with pytest.raises(CloseBlocked):
        result.raise_if_blocked()


def test_correct_closing_balance_lets_the_close_proceed():
    result = post_and_assert(
        [_payout_entry()],
        load_chart("settlement_3way"),
        OPENED,
        PERIOD_END,
        {Role.BANK: D("1842907.30")},
    )
    assert not result.blocked, result.errors
    result.raise_if_blocked()  # must not raise


def test_assertion_is_dated_after_period_end_not_on_it():
    """Beancount checks a balance directive at the *start* of its date. An entry
    posted on period_end would be invisible to an assertion dated period_end, so
    a real closing balance would read as wrong. Proves the offset is
    load-bearing rather than decorative."""
    last_day = _payout_entry("M-0003", on=PERIOD_END)
    closing = D("1842907.30")

    correct = post_and_assert(
        [last_day], load_chart("settlement_3way"), OPENED, PERIOD_END, {Role.BANK: closing}
    )
    assert not correct.blocked, correct.errors

    # Same journal, assertion dated ON period_end — the naive version.
    naive = render(
        [last_day], load_chart("settlement_3way"), OPENED, [(PERIOD_END, Role.BANK, closing)]
    )
    _, errors = load(naive)
    assert any(e.kind == "BalanceError" for e in errors), (
        "the naive same-day assertion should fail; if it passes, the offset in "
        "assert_closing_balance is not doing anything"
    )


# --------------------------------------------------------------------------
# contracts — validators must refuse, not just describe
# --------------------------------------------------------------------------


def test_contract_version_is_semver_and_stamped_on_models():
    parts = CONTRACT_VERSION.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)
    proof = Proof(
        proof_id="P1",
        match_id="M1",
        tier=MatchTier.T0_EXACT,
        provenance=ProofTier.P0_ARITHMETIC,
        legs=[ProofLeg(side="bank", record_ids=["r1"], subtotal=D("10.00"))],
        residual=D("0.00"),
        tolerance_allowed=D("0.50"),
        tolerance_used=D("0.00"),
    )
    assert proof.contract_version == CONTRACT_VERSION


def test_money_refuses_float():
    """float is banned in the engine and ledger. Accepting it at the contract
    boundary would launder it past that rule."""
    with pytest.raises(ValidationError):
        ProofLeg(side="bank", record_ids=["r1"], subtotal=1842907.30)
    assert ProofLeg(side="bank", record_ids=["r1"], subtotal="1842907.304").subtotal == D(
        "1842907.30"
    )


def test_record_is_frozen_and_validates_currency():
    rec = Record(
        record_id="r1",
        side="bank",
        source="icici",
        row_ordinal=0,
        posted_on=date(2026, 8, 14),
        amount="100.00",
        currency="INR",
        doc_hash="a" * 64,
    )
    assert rec.lineage.startswith("icici#0@")
    with pytest.raises(ValidationError):
        rec.amount = D("1.00")  # frozen
    for bad in ("inr", "RUPEE", "IN"):
        with pytest.raises(ValidationError):
            Record(
                record_id="r",
                side="s",
                source="x",
                row_ordinal=0,
                posted_on=date(2026, 8, 14),
                amount="1.00",
                currency=bad,
                doc_hash="a",
            )


@pytest.mark.parametrize(
    "provenance,kwargs",
    [
        (ProofTier.P1_RULE, {}),
        (ProofTier.P2_ATTESTED, {}),
        (ProofTier.P3_DECLARED, {}),
    ],
)
def test_proof_provenance_must_carry_its_evidence(provenance, kwargs):
    """A P1 proof that does not name its rule, or a P3 that does not state its
    gap, is a tier label with nothing behind it."""
    with pytest.raises(ValidationError):
        Proof(
            proof_id="P",
            match_id="M",
            tier=MatchTier.T1_TOLERANT,
            provenance=provenance,
            legs=[ProofLeg(side="a", record_ids=["r"], subtotal="1.00")],
            residual="0.00",
            tolerance_allowed="0.50",
            tolerance_used="0.00",
            **kwargs,
        )


def test_proof_rejects_impossible_shapes():
    base = dict(
        proof_id="P",
        match_id="M",
        tier=MatchTier.T0_EXACT,
        provenance=ProofTier.P0_ARITHMETIC,
        residual="0.00",
    )
    with pytest.raises(ValidationError):  # no legs proves nothing
        Proof(legs=[], tolerance_allowed="0.50", tolerance_used="0.00", **base)
    with pytest.raises(ValidationError):  # used > allowed
        Proof(
            legs=[ProofLeg(side="a", record_ids=["r"], subtotal="1.00")],
            tolerance_allowed="0.50",
            tolerance_used="9.00",
            **base,
        )
    with pytest.raises(ValidationError):  # a record claimed twice in one leg
        ProofLeg(side="a", record_ids=["r", "r"], subtotal="1.00")


def test_e09_must_show_its_competing_subsets():
    common = dict(exception_id="E-1", as_of=date(2026, 8, 31), amount="87250.40")
    with pytest.raises(ValidationError):
        ReconException(code=ExceptionCode.E09_NETTING_AMBIGUITY, **common)
    with pytest.raises(ValidationError):  # the same subset twice is one answer
        ReconException(
            code=ExceptionCode.E09_NETTING_AMBIGUITY,
            alternatives=[["a", "b"], ["b", "a"]],
            **common,
        )
    # Overlapping alternatives ARE legitimate: two valid answers may share a
    # row. Contract 1.1.0 required disjointness, which was a modelling error —
    # it would have forced the engine to hide real ambiguity. See 1.2.0.
    ReconException(
        code=ExceptionCode.E09_NETTING_AMBIGUITY,
        alternatives=[["a", "b"], ["b", "c"]],
        **common,
    )
    ok = ReconException(
        code=ExceptionCode.E09_NETTING_AMBIGUITY, alternatives=[["a", "b"], ["c", "d"]], **common
    )
    # Whether escalating is the right answer is a fact about the *category*, so
    # since P12 it is registry data rather than a frozenset of ids in this
    # package. An exception carries a code; what the code means is not its to
    # know.
    from recon.contracts import TaxonomyRegistry

    taxonomy = TaxonomyRegistry.model_validate_json(
        pathlib.Path("data/taxonomy/codes.json").read_text(encoding="utf-8")
    )
    assert taxonomy.escalates(ok.code)
    assert not taxonomy.escalates(ExceptionCode.E01_TIMING)


def test_rule_cannot_be_promoted_while_it_breaks_history():
    """Superseded and tightened at P8 / contract 2.0.0.

    This originally asserted that a `RegressionReport` with `matches_broken > 0`
    blocked promotion. It did — but the report was attached *by the proposer*,
    so a spotless one authorised anything, and it counted only breakage while the
    real danger (a rule that merely *adds* matches) went unmeasured. Promotion
    now requires a `PromotionEvent` that only `recon.engine.promotion.promote()`
    can produce, by re-running the regression against real history.

    What survives here is the contract half: `PROMOTED` is unreachable without
    that event. The behaviour half lives in gate_p8.
    """
    base = dict(
        rule_id="R-023",
        profile="settlement_3way",
        when=[Predicate(field="keys.gateway", op=Operator.EQ, value="razorpay")],
        then=[RuleAction(kind=ActionKind.BOOK_TO, target="Expenses:GatewayFees:Variance")],
    )
    clean = RegressionReport(
        ran_at=datetime.now(UTC),
        matches_checked=1400,
        matches_broken=0,
        exceptions_would_clear=14,
    )

    # A self-attached report — however spotless — no longer authorises anything.
    with pytest.raises(ValidationError, match="PromotionEvent"):
        Rule(status=RuleStatus.PROMOTED, regression=clean, **base)
    with pytest.raises(ValidationError, match="PromotionEvent"):
        Rule(status=RuleStatus.PROMOTED, **base)

    draft = Rule(regression=clean, **base)
    assert draft.status is RuleStatus.DRAFT
    assert draft.ref == "R-023@v1"
    assert draft.promoted_by is None


def test_rule_actions_cannot_suppress_silently():
    with pytest.raises(ValidationError):
        RuleAction(kind=ActionKind.SUPPRESS)
    assert RuleAction(kind=ActionKind.SUPPRESS, reason="balance summary row").reason


def test_adapter_spec_vocabulary_is_closed():
    """ADR-001 is the whole security argument. An unknown verb must be a
    validation error, never something the interpreter tries to run."""
    reader = ReaderSpec(kind=ReaderKind.CSV, encoding=["utf-8", "latin-1"])
    minimal = [
        FieldMap(to=CanonicalField.DATE, source="Txn Date", parse=ParseVerb.DATE, fmt="DD-MM-YY"),
        FieldMap(
            to=CanonicalField.AMOUNT,
            source="Deposit Amt.",
            parse=ParseVerb.DECIMAL,
            strip=["₹", ","],
        ),
    ]
    spec = AdapterSpec(
        spec_id="icici-current",
        source="icici-current",
        side="bank",
        reader=reader,
        fields=minimal,
        authored_by="human",
        currency="INR",
    )
    assert spec.ref == "icici-current@v1"
    assert not spec.needs_first_use_approval

    with pytest.raises(ValidationError):  # verb outside the enum
        FieldMap(to=CanonicalField.AMOUNT, source="x", parse="exec_python")
    with pytest.raises(ValidationError):  # DATE without a format
        FieldMap(to=CanonicalField.DATE, source="x", parse=ParseVerb.DATE)
    with pytest.raises(ValidationError):  # unbounded regex refused
        FieldMap(
            to=CanonicalField.REFERENCE, source="x", parse=ParseVerb.REGEX, pattern="(a+)+" * 60
        )
    with pytest.raises(ValidationError):  # cannot build a Record without an amount
        AdapterSpec(spec_id="s", source="s", side="bank", reader=reader, fields=[minimal[0]])


def test_model_authored_spec_needs_first_use_approval():
    spec = AdapterSpec(
        spec_id="cashfree",
        source="cashfree",
        side="settlement",
        reader=ReaderSpec(kind=ReaderKind.CSV),
        fields=[
            FieldMap(to=CanonicalField.DATE, source="d", parse=ParseVerb.DATE, fmt="YYYY-MM-DD"),
            FieldMap(to=CanonicalField.AMOUNT, source="a", parse=ParseVerb.DECIMAL),
        ],
        authored_by="claude-opus-5",
        currency="INR",
    )
    assert spec.needs_first_use_approval
    assert not spec.model_copy(update={"approved_by": "meera"}).needs_first_use_approval


def test_contracts_survive_a_json_round_trip():
    """They are a public surface; a caller reconstructs them from JSON."""
    proof = Proof(
        proof_id="PRF-1",
        match_id="M-1",
        tier=MatchTier.T2_SUBSET_SUM,
        provenance=ProofTier.P1_RULE,
        rule_id="R-023",
        rule_version=3,
        legs=[
            ProofLeg(side="bank", record_ids=["b1"], subtotal="1842907.30"),
            ProofLeg(side="settlement", record_ids=["s1", "s2"], subtotal="-1842907.30"),
        ],
        residual="0.00",
        tolerance_allowed="0.50",
        tolerance_used="0.00",
    )
    assert Proof.model_validate_json(proof.model_dump_json()) == proof
    assert '"residual":"0.00"' in proof.model_dump_json()  # money serializes as a string


def test_chart_must_be_complete_and_well_formed():
    with pytest.raises(ValidationError):  # missing roles
        ChartOfAccounts(accounts={Role.BANK: "Assets:Bank:HDFC"})
    partial = dict(load_chart("settlement_3way").accounts)
    partial[Role.BANK] = "not an account"
    with pytest.raises(ValidationError):
        ChartOfAccounts(accounts=partial)
