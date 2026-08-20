"""Scenario composition and defect injection.

All randomness comes from an explicitly-passed random.Random. Nothing here
reads the clock or the global RNG — a seed must reproduce a batch exactly.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal

from .model import (
    ZERO,
    BankLine,
    Batch,
    Charge,
    Fee,
    Gateway,
    Order,
    Payout,
    PlantedException,
    Refund,
    money,
)

GATEWAYS = (
    Gateway("razorpay", Decimal("0.024"), money("2.00")),
    Gateway("cashfree", Decimal("0.021"), money("3.00")),
)

# How many of each defect to plant. Counts, not probabilities — the labels
# must be exact, and "roughly three" is not a ground truth.
DEFAULT_DEFECTS = {
    "E01": 1,  # payout settles in period, banks after period end
    "E02": 1,  # gateway charged above the contract fee tier
    "E06": 1,  # a charge duplicated in the settlement export
    "E07": 1,  # chargeback reversing a prior-period order
    "E08": 1,  # bank credit with no settlement behind it
    "E09": 1,  # two disjoint subsets sum to the same payout
    "T1": 2,  # truncated bank reference — recoverable at T1, not an exception
}


def _fee_for(gw: Gateway, gross: Decimal) -> Decimal:
    return money(-(gross * gw.contract_pct + gw.contract_fixed))


def build(
    name: str,
    seed: int,
    period_start: date,
    days: int = 30,
    payout_count: int = 22,
    charges_per_payout: tuple[int, int] = (6, 18),
    defects: dict[str, int] | None = None,
) -> Batch:
    rng = random.Random(seed)
    defects = dict(DEFAULT_DEFECTS if defects is None else defects)
    period_end = period_start + timedelta(days=days - 1)

    batch = Batch(
        name=name,
        seed=seed,
        period_start=period_start,
        period_end=period_end,
        opening_balance=money("1240118.22"),
    )

    seq = {"order": 0, "charge": 0, "refund": 0, "fee": 0, "payout": 0, "bank": 0}

    def nid(kind: str, prefix: str) -> str:
        seq[kind] += 1
        return f"{prefix}{seq[kind]:05d}"

    # ---- clean payouts -------------------------------------------------
    for _ in range(payout_count):
        gw = GATEWAYS[rng.randrange(len(GATEWAYS))]
        settled = period_start + timedelta(days=rng.randrange(days))
        payout = Payout(nid("payout", "pout_"), gw.name, settled)

        for _ in range(rng.randint(*charges_per_payout)):
            gross = money(rng.randrange(19900, 899900) / Decimal(100))
            pay_id = nid("charge", "pay_")
            charge = Charge(
                nid("charge", "ch_"), pay_id, settled - timedelta(days=rng.randrange(3)), gross
            )
            payout.charges.append(charge)
            fee = _fee_for(gw, gross)
            payout.fees.append(Fee(nid("fee", "fee_"), charge.charge_id, fee, fee))

            # An order sits behind every charge. Some lost their payment_id in
            # the export, which forces the amount+date+email blocking path.
            has_ref = rng.random() > 0.08
            batch.orders.append(
                Order(
                    order_id=nid("order", "ord_"),
                    order_date=charge.charge_date,
                    gross=gross,
                    payment_id=pay_id if has_ref else None,
                    email=f"c{rng.randrange(10**6):06d}@example.in",
                )
            )

            if rng.random() < 0.05:
                payout.refunds.append(
                    Refund(nid("refund", "rfnd_"), pay_id, settled, money(-gross))
                )

        batch.payouts.append(payout)

    # ---- defects -------------------------------------------------------
    used: set[str] = set()

    def pick_payout() -> Payout:
        pool = [p for p in batch.payouts if p.payout_id not in used]
        chosen = pool[rng.randrange(len(pool))]
        used.add(chosen.payout_id)
        return chosen

    for _ in range(defects.get("E02", 0)):
        p = pick_payout()
        gw = next(g for g in GATEWAYS if g.name == p.gateway)
        # Gateway billed the standard tier; the contract says the >3Cr tier.
        variance = ZERO
        for fee in p.fees:
            charge = next(c for c in p.charges if c.charge_id == fee.charge_id)
            billed = money(
                -(
                    charge.gross * (gw.contract_pct + Decimal("0.005"))
                    + gw.contract_fixed
                    + money("1.00")
                )
            )
            variance += fee.contract_amount - billed
            fee.amount = billed
        batch.planted.append(
            PlantedException(
                "E02",
                money(variance),
                p.payout_id,
                f"gateway billed above contract tier on {len(p.fees)} rows",
            )
        )

    for _ in range(defects.get("E06", 0)):
        p = pick_payout()
        src = p.charges[0]
        dup = Charge(nid("charge", "ch_"), src.payment_id, src.charge_date, src.gross)
        dup_fee = _fee_for(next(g for g in GATEWAYS if g.name == p.gateway), src.gross)
        p.charges.append(dup)
        p.fees.append(Fee(nid("fee", "fee_"), dup.charge_id, dup_fee, dup_fee))
        # The bank paid the correct amount; the export double-counted.
        batch.credit_adjust[p.payout_id] = money(dup.gross + dup_fee)
        batch.planted.append(
            PlantedException(
                "E06",
                money(dup.gross + dup_fee),
                dup.charge_id,
                f"charge {src.charge_id} duplicated as {dup.charge_id} in the export",
            )
        )

    for _ in range(defects.get("E07", 0)):
        p = pick_payout()
        amount = money("-18700.00")
        # payment_id from a prior period — deliberately absent from batch.orders.
        p.refunds.append(Refund(nid("refund", "cb_"), "pay_prior_00042", p.settled_on, amount))
        batch.planted.append(
            PlantedException(
                "E07",
                money(-amount),
                p.payout_id,
                "chargeback reverses a prior-period order — no order in this batch to link",
                leg="orders",
            )
        )

    ambiguous_ids: set[str] = set()
    for _ in range(defects.get("E09", 0)):
        gw = GATEWAYS[0]
        settled = period_start + timedelta(days=days - 4)
        p = Payout(nid("payout", "pout_"), gw.name, settled)
        # a + b == c + d, equal cardinality, so identical fees on either side.
        halves = [(money("41000.00"), money("48400.00")), (money("44200.00"), money("45200.00"))]
        for a, b in halves:
            for gross in (a, b):
                pay_id = nid("charge", "pay_")
                ch = Charge(nid("charge", "ch_"), pay_id, settled, gross)
                p.charges.append(ch)
                fee = _fee_for(gw, gross)
                p.fees.append(Fee(nid("fee", "fee_"), ch.charge_id, fee, fee))
                batch.orders.append(
                    Order(
                        ch.charge_id.replace("ch_", "ord_"),
                        settled,
                        gross,
                        pay_id,
                        f"c{rng.randrange(10**6):06d}@example.in",
                    )
                )
        batch.payouts.append(p)
        ambiguous_ids.add(p.payout_id)
        batch.ungrouped.append(p.payout_id)
        used.add(p.payout_id)
        subsets = [
            [p.charges[0].charge_id, p.charges[1].charge_id],
            [p.charges[2].charge_id, p.charges[3].charge_id],
        ]
        # Only one half is banked, but which half is unknowable from the data.
        half_net = money(
            p.charges[0].gross + p.charges[1].gross + p.fees[0].amount + p.fees[1].amount
        )
        batch.credit_adjust[p.payout_id] = money(p.actual_net() - half_net)
        batch.planted.append(
            PlantedException(
                "E09",
                half_net,
                p.payout_id,
                "two disjoint subsets sum to the bank credit; no unique answer exists",
                ambiguous_subsets=subsets,
            )
        )

    timing_payouts = {pick_payout().payout_id for _ in range(defects.get("E01", 0))}
    for pid in sorted(timing_payouts):
        p = next(x for x in batch.payouts if x.payout_id == pid)
        batch.planted.append(
            PlantedException(
                "E01", p.contract_net(), pid, "settled in period, banked after period end"
            )
        )

    # ---- bank file -----------------------------------------------------
    # Truncate to 8 chars: "pout_00007" -> "pout_000", which loses the
    # discriminating digits so the reference no longer matches any payout_id.
    # The earlier [:12] was a no-op on a 10-char id, so no T1 case existed and
    # the tolerant tier had nothing to exercise it.
    truncate_budget = defects.get("T1", 0)
    eligible = [
        p.payout_id
        for p in batch.payouts
        if p.payout_id not in timing_payouts and p.payout_id not in ambiguous_ids
    ]
    truncated: list[str] = sorted(eligible)[:truncate_budget]
    batch.truncated_refs = list(truncated)
    for p in batch.payouts:
        if p.payout_id in timing_payouts:
            continue  # banked next period — absent by construction
        credit = money(p.actual_net() - batch.credit_adjust.get(p.payout_id, ZERO))
        if p.payout_id in ambiguous_ids:
            narration = f"NEFT/{p.gateway.upper()}/SETTLEMENT"  # no reference at all
        else:
            ref = p.payout_id[:8] if p.payout_id in truncated else p.payout_id
            narration = f"NEFT/{p.gateway.upper()}/{ref}/SETTLEMENT"
        line = BankLine(nid("bank", "bl_"), p.settled_on + timedelta(days=1), credit, narration)
        batch.bank.append(line)
        batch.payout_to_bank[p.payout_id] = line.line_id

    for _ in range(defects.get("E08", 0)):
        amount = money("1160.00")
        line = BankLine(
            nid("bank", "bl_"),
            period_start + timedelta(days=days - 6),
            amount,
            "IMPS/UNKNOWN COUNTERPARTY/NO REF",
        )
        batch.bank.append(line)
        batch.planted.append(
            PlantedException(
                "E08", amount, line.line_id, "bank credit with no settlement behind it"
            )
        )

    # Non-gateway noise. Never gateway-shaped, so it must not be matched.
    for label, amt in (
        ("VENDOR PAYMENT/ACME PACKAGING", money("-84200.00")),
        ("SALARY/AUG", money("-612000.00")),
        ("GST/CHALLAN", money("-149300.00")),
    ):
        batch.bank.append(
            BankLine(
                nid("bank", "bl_"),
                period_start + timedelta(days=rng.randrange(days)),
                amt,
                label,
            )
        )

    batch.bank.sort(key=lambda b: (b.posted_on, b.line_id))
    running = batch.opening_balance
    for line in batch.bank:
        running = money(running + line.amount)
        line.running_balance = running

    return batch
