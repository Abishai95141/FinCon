"""Render a Batch to source-shaped files plus its ground-truth labels.

The data files are deliberately messy — locale decimals, split Dr/Cr columns,
two-digit years — because that is what the intake layer has to survive. The
label file is clean, and is the only thing a grader should read.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

from .model import Batch, money

CAMT_NS = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"


def _inr(value: Decimal) -> str:
    """Indian grouping with a rupee symbol, as the ICICI export writes it."""
    sign, digits = ("-", -value) if value < 0 else ("", value)
    whole, frac = f"{digits:.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join([*parts, tail])
    return f"{sign}₹{whole}.{frac}"


def _rows_of(batch: Batch) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for p in batch.payouts:
        # An ungrouped payout omits its payout_id — the matcher must infer the
        # grouping, which is what makes the E09 ambiguity reachable.
        pid = "" if p.payout_id in batch.ungrouped else p.payout_id
        fee_by_charge = {f.charge_id: f for f in p.fees}
        for c in p.charges:
            rows.append(
                {
                    "row_id": c.charge_id,
                    "row_type": "CHARGE",
                    "payout_id": pid,
                    "gateway": p.gateway,
                    "payment_id": c.payment_id,
                    "value_date": c.charge_date.isoformat(),
                    "amount": f"{c.gross:.2f}",
                }
            )
            f = fee_by_charge.get(c.charge_id)
            if f is not None:
                rows.append(
                    {
                        "row_id": f.fee_id,
                        "row_type": "FEE",
                        "payout_id": pid,
                        "gateway": p.gateway,
                        "payment_id": c.payment_id,
                        "value_date": c.charge_date.isoformat(),
                        "amount": f"{f.amount:.2f}",
                    }
                )
        for r in p.refunds:
            rows.append(
                {
                    "row_id": r.refund_id,
                    "row_type": "CHARGEBACK" if r.refund_id.startswith("cb_") else "REFUND",
                    "payout_id": pid,
                    "gateway": p.gateway,
                    "payment_id": r.payment_id,
                    "value_date": r.refund_date.isoformat(),
                    "amount": f"{r.amount:.2f}",
                }
            )
    return rows


#: Logical key -> filename. The manifest keys off the same map the writer uses,
#: so a rename cannot leave the verifier looking for a file nobody writes.
FILENAMES = {
    "orders": "orders.csv",
    "settlement": "settlement.csv",
    "settlement_novel": "settlement_psp_v2.csv",
    "bank_csv": "bank_icici.csv",
    "bank_camt": "bank_icici_camt053.xml",
    "labels": "labels.json",
}


def emit(batch: Batch, out: Path) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    orders = out / FILENAMES["orders"]
    with orders.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Order ID", "Created At", "Total", "Payment Id", "Email"])
        for o in sorted(batch.orders, key=lambda x: x.order_id):
            w.writerow(
                [
                    o.order_id,
                    o.order_date.isoformat(),
                    f"{o.gross:.2f}",
                    o.payment_id or "",
                    o.email,
                ]
            )
    written["orders"] = orders

    settlement = out / FILENAMES["settlement"]
    rows = _rows_of(batch)
    with settlement.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    written["settlement"] = settlement

    # The same movements in a format nothing has a spec for: semicolon
    # delimiter, a two-line preamble, renamed columns, DD.MM.YYYY dates and
    # amounts in minor units. P12's gate is that a model authors a spec for this
    # without configuration, and the check is not inspection — it is that the
    # rows it yields must equal the rows the known-good spec yields from
    # `settlement.csv`. Two formats describing the same account is the same
    # cross-format check P2 already runs for CSV against CAMT.
    novel = out / FILENAMES["settlement_novel"]
    with novel.open("w", newline="", encoding="utf-8") as fh:
        fh.write(f"# {batch.name} settlement export v2.1\n")
        fh.write("# generated by the PSP, do not edit\n")
        w = csv.writer(fh, delimiter=";")
        w.writerow(
            [
                "txn_ref",
                "kind",
                "merchant_batch",
                "psp",
                "auth_code",
                "booking_timestamp",
                "amount_minor",
                "ccy",
            ]
        )
        for row in rows:
            minor = round(Decimal(row["amount"]) * 100)
            w.writerow(
                [
                    row["row_id"],
                    row["row_type"],
                    row["payout_id"],
                    row["gateway"],
                    row["payment_id"],
                    date.fromisoformat(row["value_date"]).strftime("%d.%m.%Y"),
                    minor,
                    "INR",
                ]
            )
    written["settlement_novel"] = novel

    # Bank, rendered two ways from the same lines: a messy CSV and a CAMT.053.
    # Same account, same movements — the intake layer may consume either.
    bank_csv = out / FILENAMES["bank_csv"]
    with bank_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Txn Date", "Narration", "Withdrawal Amt.", "Deposit Amt.", "Closing Balance"])
        for line in batch.bank:
            dr = _inr(-line.amount) if line.amount < 0 else ""
            cr = _inr(line.amount) if line.amount > 0 else ""
            w.writerow(
                [
                    line.posted_on.strftime("%d-%m-%y"),
                    line.narration,
                    dr,
                    cr,
                    _inr(line.running_balance),
                ]
            )
        w.writerow([])  # trailing blank rows, as the real export emits
        w.writerow([])
    written["bank_csv"] = bank_csv

    ET.register_namespace("", CAMT_NS)
    doc = ET.Element(f"{{{CAMT_NS}}}Document")
    stmt = ET.SubElement(ET.SubElement(doc, f"{{{CAMT_NS}}}BkToCstmrStmt"), f"{{{CAMT_NS}}}Stmt")
    ET.SubElement(stmt, f"{{{CAMT_NS}}}Id").text = f"{batch.name}-icici"
    for tag, amt in (
        ("OPBD", batch.opening_balance),
        ("CLBD", batch.bank[-1].running_balance if batch.bank else batch.opening_balance),
    ):
        bal = ET.SubElement(stmt, f"{{{CAMT_NS}}}Bal")
        ET.SubElement(ET.SubElement(bal, f"{{{CAMT_NS}}}Tp"), f"{{{CAMT_NS}}}Cd").text = tag
        ET.SubElement(bal, f"{{{CAMT_NS}}}Amt", Ccy="INR").text = f"{amt:.2f}"
    for line in batch.bank:
        ntry = ET.SubElement(stmt, f"{{{CAMT_NS}}}Ntry")
        ET.SubElement(ntry, f"{{{CAMT_NS}}}NtryRef").text = line.line_id
        ET.SubElement(ntry, f"{{{CAMT_NS}}}Amt", Ccy="INR").text = f"{abs(line.amount):.2f}"
        ET.SubElement(ntry, f"{{{CAMT_NS}}}CdtDbtInd").text = "CRDT" if line.amount > 0 else "DBIT"
        ET.SubElement(
            ET.SubElement(ntry, f"{{{CAMT_NS}}}BookgDt"), f"{{{CAMT_NS}}}Dt"
        ).text = line.posted_on.isoformat()
        ET.SubElement(
            ET.SubElement(ntry, f"{{{CAMT_NS}}}NtryDtls"), f"{{{CAMT_NS}}}AddtlNtryInf"
        ).text = line.narration
    bank_xml = out / FILENAMES["bank_camt"]
    ET.ElementTree(doc).write(bank_xml, encoding="utf-8", xml_declaration=True)
    written["bank_camt"] = bank_xml

    labels = out / FILENAMES["labels"]
    labels.write_text(json.dumps(_labels(batch), indent=2, sort_keys=True), encoding="utf-8")
    written["labels"] = labels
    return written


def _leg_total(batch: Batch, leg: str) -> Decimal:
    return money(sum((e.unreconciled for e in batch.planted if e.leg == leg), money(0)))


def _labels(batch: Batch) -> dict:
    """Complete ground truth. Everything a grader needs, nothing it must infer."""
    return {
        "batch": batch.name,
        "seed": batch.seed,
        "period": [batch.period_start.isoformat(), batch.period_end.isoformat()],
        "opening_balance": f"{batch.opening_balance:.2f}",
        "closing_balance": f"{batch.bank[-1].running_balance:.2f}" if batch.bank else None,
        "counts": {
            "orders": len(batch.orders),
            "payouts": len(batch.payouts),
            "bank_lines": len(batch.bank),
            "settlement_rows": len(_rows_of(batch)),
        },
        # payout_id -> the rows that truly belong to it, and its bank line.
        "payout_membership": {
            p.payout_id: {
                "bank_line": batch.payout_to_bank.get(p.payout_id),
                "charges": sorted(c.charge_id for c in p.charges),
                "refunds": sorted(r.refund_id for r in p.refunds),
                "fees": sorted(f.fee_id for f in p.fees),
                "contract_net": f"{p.contract_net():.2f}",
                "actual_net": f"{p.actual_net():.2f}",
            }
            for p in sorted(batch.payouts, key=lambda x: x.payout_id)
        },
        # order_id -> payment_id, or null where the export dropped the reference.
        "order_to_payment": {
            o.order_id: o.payment_id for o in sorted(batch.orders, key=lambda x: x.order_id)
        },
        "expected_exceptions": [
            {k: (f"{v:.2f}" if isinstance(v, Decimal) else v) for k, v in asdict(e).items()}
            for e in sorted(batch.planted, key=lambda e: (e.code, e.subject))
        ],
        "expected_unreconciled": {
            "bank_leg": f"{_leg_total(batch, 'bank'):.2f}",
            "orders_leg": f"{_leg_total(batch, 'orders'):.2f}",
        },
        "ungrouped_payouts": sorted(batch.ungrouped),
        "truncated_ref_payouts": sorted(batch.truncated_refs),
    }
