"""Gate P6 — completeness and honest failure.

Gate: the four crash cases and three silent cases from the failure register each
produce a disposition instead, **and** a deliberately undisposed anchor makes the
completeness audit fail.

That last clause is the load-bearing one. An audit that only ever passes is
decorative — the same hazard as the dead T1 tier at P3 and the gate files that
collected nothing at P2. It is asserted directly, and mutation-tested at the end.
"""

from __future__ import annotations

import json
import pathlib
from datetime import date as _date
from decimal import Decimal as D
from pathlib import Path

import pytest
from bench.run import BATCHES, SETTLEMENT_3WAY, load_sides

from recon.contracts import AdapterSpec, ExceptionCode, ProofTier, Record
from recon.engine.completeness import CompletenessError, Disposition, audit
from recon.engine.tiers import run as run_tiers
from recon.intake import ADAPTER_DIR, ingest, load_spec

pytestmark = pytest.mark.gate

TMP = Path("/tmp/gate_p6")
WINDOW = (_date(2026, 7, 1), _date(2026, 10, 31))
HEADER = "Txn Date,Narration,Withdrawal Amt.,Deposit Amt.,Closing Balance\n"


@pytest.fixture(scope="module", autouse=True)
def _setup():
    if not (BATCHES / "A" / "labels.json").exists():
        pytest.skip("run `make gen` first — P6 reads the P0 batches")
    TMP.mkdir(exist_ok=True)


@pytest.fixture(scope="module")
def base_spec():
    return json.loads((ADAPTER_DIR / "icici-current.json").read_text())


def _rec(rid, side, amount, **kw):
    return Record(
        record_id=rid,
        side=side,
        source="s",
        row_ordinal=0,
        posted_on=_date(2026, 8, 14),
        amount=amount,
        currency="INR",
        doc_hash="h" * 8,
        **kw,
    )


# --------------------------------------------------------------------------
# the load-bearing test
# --------------------------------------------------------------------------


def test_a_deliberately_undisposed_anchor_makes_the_audit_fail():
    """If this passes, everything else in this file is decorative."""
    anchors = [_rec("b:0", "bank", "100.00"), _rec("b:1", "bank", "200.00")]
    groups = [_rec("s:0", "settlement", "100.00", group_ref="g")]

    report = audit(
        anchors=anchors,
        group_records=groups,
        matched_anchor_ids=["b:0"],
        matched_record_ids=["s:0"],
        exceptions=[],  # b:1 is mentioned nowhere
    )
    assert not report.complete
    assert report.undisposed_anchors == ["b:1"]
    assert report.anchors["b:1"] is Disposition.UNDISPOSED
    assert "INCOMPLETE" in report.render()
    with pytest.raises(CompletenessError):
        report.raise_if_incomplete()


def test_an_out_of_scope_declaration_without_a_reason_is_not_a_disposition():
    """A bare exclusion is indistinguishable from a silent drop."""
    anchors = [_rec("b:0", "bank", "100.00")]
    report = audit(
        anchors=anchors,
        group_records=[],
        matched_anchor_ids=[],
        matched_record_ids=[],
        exceptions=[],
        out_of_scope={"b:0": "   "},
    )
    assert not report.complete
    assert report.notes and "no reason" in report.notes[0]

    reasoned = audit(
        anchors=anchors,
        group_records=[],
        matched_anchor_ids=[],
        matched_record_ids=[],
        exceptions=[],
        out_of_scope={"b:0": "prior period"},
    )
    assert reasoned.complete
    assert reasoned.anchors["b:0"] is Disposition.OUT_OF_SCOPE


# --------------------------------------------------------------------------
# invariant 8 on the real batches
# --------------------------------------------------------------------------


@pytest.mark.parametrize("batch", ["A", "B"])
def test_every_input_has_a_disposition_on_the_real_batches(batch):
    bank, settlement, provenance = load_sides(batch).in_scope()
    outcome = run_tiers(
        [r for _, r in bank], [r for _, r in settlement], SETTLEMENT_3WAY, provenance
    )
    report = outcome.completeness
    assert report is not None
    report.raise_if_incomplete()
    assert Disposition.UNDISPOSED.value not in report.tally("anchors")
    assert Disposition.UNDISPOSED.value not in report.tally("records")


@pytest.mark.parametrize("batch", ["A", "B"])
def test_every_unmatched_anchor_and_unclaimed_group_carries_an_exception(batch):
    """Before P6 the E06 payout's bank line and two unclaimed groups — 57 records
    on batch A — ended the run mentioned nowhere."""
    bank, settlement, provenance = load_sides(batch).in_scope()
    outcome = run_tiers(
        [r for _, r in bank], [r for _, r in settlement], SETTLEMENT_3WAY, provenance
    )
    named = {rid for e in outcome.exceptions for rid in e.record_ids}
    named |= {rid for e in outcome.exceptions for s in (e.alternatives or []) for rid in s}

    for anchor_id in outcome.unmatched_anchors:
        assert anchor_id in named, f"anchor {anchor_id} unmatched and unmentioned"
    for group_ref in outcome.unmatched_groups:
        rows = [r for _, r in settlement if r.group_ref == group_ref]
        assert any(r.record_id in named for r in rows), f"group {group_ref} unmentioned"

    assert any(e.code == ExceptionCode.E14_UNEXPLAINED for e in outcome.exceptions)


def test_e14_states_facts_rather_than_guessing_a_cause():
    """The engine knows an item did not match and what it is worth, not why.
    Force-fitting `E06` or `E01` would put a guess where rules key on codes."""
    bank, settlement, provenance = load_sides("A").in_scope()
    outcome = run_tiers(
        [r for _, r in bank], [r for _, r in settlement], SETTLEMENT_3WAY, provenance
    )
    from recon.contracts import TaxonomyRegistry

    taxonomy = TaxonomyRegistry.model_validate_json(
        pathlib.Path("data/taxonomy/codes.json").read_text(encoding="utf-8")
    )
    e14 = [e for e in outcome.exceptions if e.code == ExceptionCode.E14_UNEXPLAINED]
    assert e14
    for exc in e14:
        assert taxonomy.escalates(exc.code)
        assert exc.blocks_close
        assert exc.amount > 0
        assert exc.evidence, "an E14 must carry the facts it does have"
        assert exc.alternatives is None, "E14 asserts nothing about competing subsets"


def test_records_named_in_an_exceptions_alternatives_count_as_explained():
    """E09 names its competing subsets in `alternatives`, not `record_ids`. Those
    rows are anything but unmentioned."""
    bank, settlement, provenance = load_sides("A").in_scope()
    outcome = run_tiers(
        [r for _, r in bank], [r for _, r in settlement], SETTLEMENT_3WAY, provenance
    )
    e09 = next(e for e in outcome.exceptions if e.code == ExceptionCode.E09_NETTING_AMBIGUITY)
    listed = {rid for s in e09.alternatives for rid in s}
    assert listed
    for rid in listed:
        assert outcome.completeness.records[rid] is Disposition.EXCEPTED


# --------------------------------------------------------------------------
# the register's silent matching cases
# --------------------------------------------------------------------------


def test_partial_payment_is_no_longer_silent():
    """Register case: bank ₹600 against a ₹1,000 invoice used to yield
    matches=0, exceptions=[], unmatched=1."""
    outcome = run_tiers(
        [_rec("b:0", "bank", "600.00", keys={"gateway": "x"})],
        [_rec("s:0", "settlement", "1000.00", group_ref="g", keys={"gateway": "x"})],
        SETTLEMENT_3WAY,
        ProofTier.P0_ARITHMETIC,
    )
    assert outcome.matches == []
    assert outcome.exceptions, "a partial payment must not end the run unmentioned"
    outcome.completeness.raise_if_incomplete()


def test_one_invoice_two_credits_is_no_longer_silent():
    outcome = run_tiers(
        [
            _rec("b:0", "bank", "400.00", keys={"gateway": "x"}),
            _rec("b:1", "bank", "600.00", keys={"gateway": "x"}),
        ],
        [_rec("s:0", "settlement", "1000.00", group_ref="g", keys={"gateway": "x"})],
        SETTLEMENT_3WAY,
        ProofTier.P0_ARITHMETIC,
    )
    assert outcome.matches == []
    assert len(outcome.exceptions) >= 2, "both credits and the group must be named"
    outcome.completeness.raise_if_incomplete()


# --------------------------------------------------------------------------
# the register's crash cases
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,mutate,filename,content",
    [
        ("unsupported reader kind", {"reader_kind": "xlsx"}, "any.csv", HEADER),
        ("malformed xml", {"reader_kind": "camt053"}, "bad.xml", "<Document><unclosed>"),
        ("empty file", {}, "empty.csv", ""),
        ("header_row past end", {"header_row": 99}, "short.csv", HEADER),
    ],
)
def test_unreadable_sources_report_instead_of_raising(base_spec, name, mutate, filename, content):
    """`ingest()`'s docstring promised this. Before P6 the reader raised straight
    through and one bad file killed the whole close."""
    spec = json.loads(json.dumps(base_spec))
    if "reader_kind" in mutate:
        spec["reader"]["kind"] = mutate["reader_kind"]
    if "header_row" in mutate:
        spec["reader"]["header_row"] = mutate["header_row"]
    path = TMP / filename
    path.write_text(content, encoding="utf-8")

    result = ingest(AdapterSpec.model_validate(spec), path, WINDOW)
    assert not result.ok, name
    assert result.proof.strength == "failed"
    assert result.records == []
    assert result.proof.failed[0].detail, "a failed source must say why"


@pytest.mark.parametrize(
    "label,target",
    [
        ("missing file", Path("/tmp/gate_p6/definitely-not-here.csv")),
        ("a directory where a file was expected", Path("/tmp/gate_p6")),
    ],
)
def test_os_level_failures_also_report_instead_of_raising(base_spec, label, target):
    """P6 first caught only `ReaderError`. A **missing** file — the likeliest
    source failure of all, the download that never happened — raises
    `FileNotFoundError` from `read_bytes()` and sailed straight past, so the run
    still died. Found by the post-P6 verification sweep, not by this gate."""
    result = ingest(AdapterSpec.model_validate(base_spec), target, WINDOW)
    assert not result.ok, label
    assert result.proof.strength == "failed"
    assert "could not be read" in result.proof.failed[0].detail


def test_header_only_file_fails_rather_than_reading_as_a_clean_month(base_spec):
    """Register case: `declared · parsed=0/0 · ok=True`. A failed fetch and a
    genuinely empty period are indistinguishable from the file, so this
    escalates instead of guessing."""
    path = TMP / "hdr.csv"
    path.write_text(HEADER, encoding="utf-8")
    result = ingest(AdapterSpec.model_validate(base_spec), path, WINDOW)
    assert not result.ok
    assert result.proof.strength == "failed"
    detail = result.proof.failed[0].detail
    assert "zero records" in detail and "empty period" in detail


def test_unmappable_declares_the_gap_instead_of_guessing(base_spec):
    """The alternative to a near-miss verb. A source whose amount column cannot
    be expressed fails loudly and names the column."""
    spec = json.loads(json.dumps(base_spec))
    for field in spec["fields"]:
        if field["to"] == "amount" and field.get("sign") == "cr":
            field["parse"] = "unmappable"
            field.pop("strip", None)
            field.pop("sign", None)
    result = ingest(AdapterSpec.model_validate(spec), BATCHES / "A" / "bank_icici.csv", WINDOW)
    assert not result.ok
    assert result.records == [], (
        "a partial ingest is how a whole class of rows goes missing quietly — "
        "an unmappable column must stop the source, not just its own rows"
    )
    detail = result.proof.failed[0].detail
    assert "UNMAPPABLE" in detail
    assert "Deposit Amt." in detail, "the failure must name the column"
    assert "Escalate" in detail, "it must say what to do next"


def test_healthy_sources_are_unaffected():
    """P6 tightened four things. None of them may change a good run."""
    for spec_id, filename, strength in [
        ("icici-current", "bank_icici.csv", "verified"),
        ("icici-camt", "bank_icici_camt053.xml", "verified"),
        ("shopify-orders", "orders.csv", "declared"),
        ("gateway-settlement", "settlement.csv", "declared"),
    ]:
        result = ingest(load_spec(spec_id), BATCHES / "A" / filename, WINDOW)
        assert result.ok, (spec_id, [c.detail for c in result.proof.failed])
        assert result.proof.strength == strength
        assert result.records


@pytest.mark.parametrize("batch", ["A", "B"])
def test_p3_numbers_are_unchanged_by_p6(batch):
    """Completeness reporting adds exceptions. It must not add or remove a match."""
    bank, settlement, provenance = load_sides(batch).in_scope()
    outcome = run_tiers(
        [r for _, r in bank], [r for _, r in settlement], SETTLEMENT_3WAY, provenance
    )
    tiers = outcome.by_tier()
    assert tiers.get("T0", 0) + tiers.get("T1", 0) == 20
    assert all(m.proof.residual == D("0.00") for m in outcome.matches)
