"""Ablation runner.

    python -m bench.run              # batch A
    python -m bench.run --batch B

At P3 this compares the deterministic arm against the securo baseline on
auto-match and false-match rate. P6 extends it to the full four arms and eight
metrics; the shape here is the shape it grows into.
"""

from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
from pathlib import Path

from recon.contracts import ProofTier, Record
from recon.engine.tiers import MatchProfile
from recon.engine.tolerance import TolerancePolicy
from recon.intake import ingest, load_spec

from .arms import deterministic, securo_baseline
from .metrics import Scorecard, render_table, score, truth_pairs

BATCHES = Path("data/batches")
WINDOW = (date(2026, 7, 1), date(2026, 10, 31))

SETTLEMENT_3WAY = MatchProfile(
    name="settlement_3way",
    anchor_side="bank",
    group_side="settlement",
    # A bank credit and the settlement rows behind it are the same money seen
    # from two sides, so the group side is negated for the residual to close.
    side_signs={"bank": 1, "settlement": -1},
    tolerance=TolerancePolicy(absolute=Decimal("0.50"), date_window_days=3),
    counterparty_key="gateway",
)


def load_sides(
    batch: str,
) -> tuple[list[tuple[str, Record]], list[tuple[str, Record]], ProofTier]:
    """Bank comes from the CAMT rendering because it carries NtryRef, which is
    the id the labels use. The CSV is the same account and ingests identically
    (proved at P2); using the CAMT here keeps scoring traceable to ground truth
    without a second id mapping to get wrong."""
    root = BATCHES / batch
    bank_result = ingest(load_spec("icici-camt"), root / "bank_icici_camt053.xml", WINDOW)
    settle_result = ingest(load_spec("gateway-settlement"), root / "settlement.csv", WINDOW)

    # Only gateway credits are candidates. Salary, GST and vendor debits carry
    # no gateway key, so they are excluded by the data rather than by a rule.
    bank = [
        (rec.keys["entry_ref"], rec)
        for rec in bank_result.records
        if rec.keys.get("gateway") and rec.amount > 0
    ]
    settlement = [(rec.source_row_id, rec) for rec in settle_result.records if rec.source_row_id]

    weakest = min(
        (bank_result.proof.provenance, settle_result.proof.provenance),
        key=lambda t: 0 if t is ProofTier.P0_ARITHMETIC else 1,
    )
    return bank, settlement, weakest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bench.run")
    ap.add_argument("--batch", default="A")
    args = ap.parse_args(argv)

    bank, settlement, provenance = load_sides(args.batch)
    truth = truth_pairs(BATCHES / args.batch / "labels.json")

    cards: list[Scorecard] = [
        score(securo_baseline.run_raw(bank, settlement), truth),
        score(securo_baseline.run_grouped(bank, settlement), truth),
        score(deterministic.run(bank, settlement, SETTLEMENT_3WAY, provenance), truth),
    ]

    print(
        f"batch {args.batch}  ·  {len(bank)} gateway credits  ·  {len(settlement)} settlement rows"
    )
    print(f"true pairs (payouts banked in period): {len(truth)}\n")
    print(render_table(cards))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
