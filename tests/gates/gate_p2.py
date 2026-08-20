"""Gate P2 — intake: readers, spec interpreter, five proofs.

Gate: both hand-written specs ingest cleanly, and a deliberately corrupted spec
is caught by roll-forward rather than by inspection.

The corruption tests are the point of this gate. A proof that only passes on
good input is decorative — what makes it real is that it fails on input a human
reading the output would call fine.
"""

from __future__ import annotations

import ast
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from recon.contracts import AdapterSpec, ParseVerb, ProofTier
from recon.intake import ADAPTER_DIR, ingest, load_spec
from recon.intake.proofs import CheckStatus
from recon.intake.verbs import REGISTRY

pytestmark = pytest.mark.gate

BATCHES = Path("data/batches")
WINDOW = (date(2026, 7, 1), date(2026, 10, 31))

# spec_id -> (filename, expected strength)
SOURCES = {
    "icici-current": ("bank_icici.csv", "verified"),
    "icici-camt": ("bank_icici_camt053.xml", "verified"),
    "shopify-orders": ("orders.csv", "declared"),
    "gateway-settlement": ("settlement.csv", "declared"),
}


def _check(result, name):
    return next(c for c in result.proof.checks if c.name == name)


@pytest.fixture(scope="module", autouse=True)
def _batches_exist():
    if not (BATCHES / "A" / "bank_icici.csv").exists():
        pytest.skip("run `make gen` first — P2 reads the P0 batches")


# --------------------------------------------------------------------------
# the gate proper
# --------------------------------------------------------------------------


@pytest.mark.parametrize("batch", ["A", "B"])
@pytest.mark.parametrize("spec_id", sorted(SOURCES))
def test_hand_written_specs_ingest_cleanly(batch, spec_id):
    filename, expected_strength = SOURCES[spec_id]
    result = ingest(load_spec(spec_id), BATCHES / batch / filename, WINDOW)
    assert result.ok, [(c.name, c.detail) for c in result.proof.failed]
    assert result.records
    assert result.proof.strength == expected_strength


def test_corrupted_amount_column_is_caught_by_roll_forward():
    """The gate's core claim. Pointing the credit amount at the running-balance
    column is a plausible mistake: both are money, both parse, and every row
    still yields a Record. Inspection sees nothing wrong."""
    raw = json.loads((ADAPTER_DIR / "icici-current.json").read_text())
    for field in raw["fields"]:
        if field["to"] == "amount" and field.get("sign") == "cr":
            field["source"] = "Closing Balance"

    result = ingest(AdapterSpec.model_validate(raw), BATCHES / "A" / "bank_icici.csv", WINDOW)

    clean = ingest(load_spec("icici-current"), BATCHES / "A" / "bank_icici.csv", WINDOW)
    assert result.proof.rows_parsed == clean.proof.rows_parsed, (
        "the corrupted spec must parse exactly as many rows as the good one — "
        "if it parses fewer, it is caught trivially and roll-forward proves nothing"
    )
    assert not result.ok
    failed = {c.name for c in result.proof.failed}
    assert failed == {"balance_roll_forward"}, (
        f"roll-forward must be what catches this, got {failed}"
    )
    detail = _check(result, "balance_roll_forward").detail
    assert "row " in detail and "delta" in detail, "the failure must localise the row and the delta"


def test_wrong_date_format_is_caught_rather_than_reported_as_weak():
    """A spec that parses nothing is a broken spec, not a weakly-evidenced
    intake. 'declared' means we got data we could not fully verify; getting
    nothing is a different thing and must not borrow that label."""
    raw = json.loads((ADAPTER_DIR / "icici-current.json").read_text())
    for field in raw["fields"]:
        if field["to"] == "date":
            field["fmt"] = "DD-MM-YYYY"

    result = ingest(AdapterSpec.model_validate(raw), BATCHES / "A" / "bank_icici.csv", WINDOW)
    assert result.proof.rows_parsed == 0
    assert result.proof.strength == "failed"
    assert _check(result, "row_conservation").status is CheckStatus.FAIL


def test_sources_without_balances_degrade_honestly():
    """No control total and no balances means the substantive checks cannot run.
    That is 'declared', and its records may claim only P3 — not a pass."""
    result = ingest(load_spec("shopify-orders"), BATCHES / "A" / "orders.csv", WINDOW)
    assert result.ok
    assert not result.proof.verified
    assert result.proof.strength == "declared"
    assert result.proof.provenance is ProofTier.P3_DECLARED
    assert _check(result, "balance_roll_forward").status is CheckStatus.SKIP
    assert _check(result, "control_total").status is CheckStatus.SKIP

    verified = ingest(load_spec("icici-current"), BATCHES / "A" / "bank_icici.csv", WINDOW)
    assert verified.proof.provenance is ProofTier.P0_ARITHMETIC


def test_row_conservation_accounts_for_the_trailing_blank_rows():
    """The generator emits two trailing blank rows, as the real export does.
    They must be rejected *with a reason*, not silently dropped by the reader."""
    result = ingest(load_spec("icici-current"), BATCHES / "A" / "bank_icici.csv", WINDOW)
    assert result.proof.rows_in_file == result.proof.rows_parsed + result.proof.rows_rejected
    assert result.proof.rows_rejected == 2
    assert {r.reason for r in result.rejections} == {"blank_footer"}
    assert all(r.reason for r in result.rejections)


def test_the_same_account_agrees_across_two_formats():
    """CSV and CAMT.053 describe the same movements. Disagreement means one of
    the two specs is wrong, and neither file alone would reveal it."""
    csv_result = ingest(load_spec("icici-current"), BATCHES / "A" / "bank_icici.csv", WINDOW)
    camt_result = ingest(load_spec("icici-camt"), BATCHES / "A" / "bank_icici_camt053.xml", WINDOW)
    csv_total = sum((r.amount for r in csv_result.records), Decimal("0.00"))
    camt_total = sum((r.amount for r in camt_result.records), Decimal("0.00"))
    assert csv_total == camt_total
    assert len(csv_result.records) == len(camt_result.records)


def test_re_ingest_is_idempotent():
    spec, path = load_spec("icici-current"), BATCHES / "A" / "bank_icici.csv"
    first, second = ingest(spec, path, WINDOW), ingest(spec, path, WINDOW)
    assert first.document.doc_hash == second.document.doc_hash
    assert [r.record_id for r in first.records] == [r.record_id for r in second.records]
    assert [r.amount for r in first.records] == [r.amount for r in second.records]
    assert _check(first, "idempotence").status is CheckStatus.PASS


def test_group_ref_is_absent_where_the_source_declared_none():
    """The E09 payout's settlement rows carry no payout_id. If the interpreter
    invented a grouping here, the ambiguity would never become reachable."""
    result = ingest(load_spec("gateway-settlement"), BATCHES / "A" / "settlement.csv", WINDOW)
    ungrouped = [r for r in result.records if r.group_ref is None]
    assert ungrouped, "no ungrouped rows — the E09 case is not reaching the engine"
    assert all(r.group_ref for r in result.records if r not in ungrouped)


# --------------------------------------------------------------------------
# ADR-001 — the security boundary, asserted structurally
# --------------------------------------------------------------------------


def test_parse_vocabulary_is_complete():
    """Every enum member has an implementation. verbs.py asserts this at import,
    so a member added without one fails on import rather than at runtime on
    someone's statement — this test pins that guarantee."""
    assert set(REGISTRY) == set(ParseVerb)


def test_intake_executes_nothing_dynamic():
    """ADR-001 is irreversible and the whole security argument rests on it. A
    spec is data; if intake ever gained eval/exec/compile, a model-authored spec
    would become a code path."""
    banned = {"eval", "exec", "compile", "__import__"}
    offenders: list[str] = []
    for path in sorted(Path("src/recon/intake").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in banned
            ):
                offenders.append(f"{path}:{node.lineno} {node.func.id}()")
            if isinstance(node, ast.Attribute) and node.attr in {"system", "popen"}:
                offenders.append(f"{path}:{node.lineno} .{node.attr}")
    assert not offenders, f"intake must execute nothing dynamic: {offenders}"


def test_spec_with_an_unknown_verb_is_rejected_before_anything_runs():
    raw = json.loads((ADAPTER_DIR / "icici-current.json").read_text())
    raw["fields"][0]["parse"] = "exec_python"
    with pytest.raises(ValidationError):
        AdapterSpec.model_validate(raw)


def test_shipped_specs_are_human_authored_and_valid():
    """P2 ships hand-written specs only. A model-authored spec would need
    first-use approval, and nothing has been approved yet."""
    for spec_id in SOURCES:
        spec = load_spec(spec_id)
        assert spec.authored_by == "human", f"{spec_id} is not hand-written"
        assert not spec.needs_first_use_approval
        assert spec.contract_version.startswith("1.")
