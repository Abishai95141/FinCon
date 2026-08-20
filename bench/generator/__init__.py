"""Synthetic settlement corpus with complete ground truth.

    python -m bench.generator                # write batches A and B to data/batches/
    python -m bench.generator --check-only   # build and cross-check, write nothing

The generator is only worth as much as its labels. `check_batch` recomputes the
unreconciled total from the generated structures — never from the planted list —
so a bug in an injector shows up as a mismatch rather than as a batch whose
labels quietly agree with themselves.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from .build import build
from .emit import emit
from .model import ZERO, Batch, money

__all__ = ["CheckError", "build", "check_batch", "emit"]

DEFAULT_OUT = Path("data/batches")
# Batch A is worked against; B is held out for the P7 lift measurement and must
# never be used to tune anything.
BATCHES = (
    ("A", 20260801, date(2026, 8, 1)),
    ("B", 20260901, date(2026, 9, 1)),
)


class CheckError(AssertionError):
    """The batch is internally inconsistent. Never caught — an unusable batch
    must stop the run, not be emitted with a warning."""


def check_batch(batch: Batch) -> dict[str, Decimal]:
    """Recompute the unreconciled totals independently of the planted list.

    Bank leg: for every payout, the residual between what the contract says the
    bank should have received and what it did, plus credits with nothing behind
    them. Orders leg: settlement rows referencing a payment the order register
    does not contain.

    Raises CheckError if either recomputation disagrees with the labels.
    """
    bank_by_id = {b.line_id: b for b in batch.bank}
    banked = set(batch.payout_to_bank.values())

    bank_leg = ZERO
    for p in batch.payouts:
        line_id = batch.payout_to_bank.get(p.payout_id)
        if line_id is None:
            bank_leg += p.contract_net()  # settled but never banked this period
        else:
            bank_leg += abs(bank_by_id[line_id].amount - p.contract_net())
    for line in batch.bank:
        if line.amount > ZERO and line.line_id not in banked:
            bank_leg += line.amount  # credit with no settlement behind it

    # A payment exists in this batch if a charge carries it. Deriving this from
    # the order register instead would be wrong: ~8% of orders had their
    # payment_id dropped by the export, and those are a blocking difficulty
    # (recoverable on amount + date + email), not a missing order.
    known_payments = {c.payment_id for p in batch.payouts for c in p.charges}
    orders_leg = ZERO
    for p in batch.payouts:
        for r in p.refunds:
            if r.payment_id not in known_payments:
                orders_leg += abs(r.amount)

    declared_bank = money(sum((e.unreconciled for e in batch.planted if e.leg == "bank"), ZERO))
    declared_orders = money(sum((e.unreconciled for e in batch.planted if e.leg == "orders"), ZERO))
    bank_leg, orders_leg = money(bank_leg), money(orders_leg)

    if bank_leg != declared_bank:
        raise CheckError(
            f"[{batch.name}] bank leg: recomputed {bank_leg} != declared {declared_bank} "
            f"(delta {money(bank_leg - declared_bank)})"
        )
    if orders_leg != declared_orders:
        raise CheckError(
            f"[{batch.name}] orders leg: recomputed {orders_leg} != declared {declared_orders} "
            f"(delta {money(orders_leg - declared_orders)})"
        )

    # The closing balance must be reachable from the opening balance by the
    # movements alone — this is the roll-forward the intake layer will assert.
    rolled = money(batch.opening_balance + sum((b.amount for b in batch.bank), ZERO))
    if batch.bank and rolled != batch.bank[-1].running_balance:
        raise CheckError(
            f"[{batch.name}] roll-forward: {rolled} != stated {batch.bank[-1].running_balance}"
        )

    return {"bank_leg": bank_leg, "orders_leg": orders_leg}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bench.generator")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--check-only", action="store_true", help="build and verify, write nothing")
    args = ap.parse_args(argv)

    manifest: dict[str, dict] = {}
    for name, seed, start in BATCHES:
        batch = build(name, seed, start)
        totals = check_batch(batch)
        codes = sorted(e.code for e in batch.planted)
        print(
            f"batch {name}  seed={seed}  payouts={len(batch.payouts):>3}  "
            f"orders={len(batch.orders):>4}  bank={len(batch.bank):>3}  "
            f"defects={','.join(codes)}"
        )
        print(
            f"           unreconciled  bank_leg=₹{totals['bank_leg']:,}  "
            f"orders_leg=₹{totals['orders_leg']:,}   [cross-checked]"
        )
        if args.check_only:
            continue
        written = emit(batch, args.out / name)
        manifest[name] = {
            "seed": seed,
            "files": {k: _sha256(v) for k, v in sorted(written.items())},
        }

    if not args.check_only:
        mpath = args.out / "MANIFEST.json"
        mpath.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        print(f"\nwrote {args.out}/  + MANIFEST.json (sha256 per file)")
        for name, entry in sorted(manifest.items()):
            for fname, digest in entry["files"].items():
                print(f"  {name}/{fname:<12} {digest[:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
