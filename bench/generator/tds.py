"""Form 26AS and a TDS receivable ledger, with the answer written down first.

The second loop, and the point of it. "The engine is domain-agnostic" has been
*asserted* since P1 and tested by exactly one loop, which is not a test — a
profile that only ever ran settlement cannot tell you whether the generality is
real or whether `engine/` has quietly grown gateway-shaped assumptions.

**This is a different reconciliation in every way that matters.** The two sides
are not two views of one payment: one is a company's own ledger of tax it
expects to be credited, and the other is what the Income Tax Department says was
actually deposited. They agree on `TAN + quarter + section`, not on an amount and
a date. The failures are administrative rather than arithmetic — a deductor filed
late, used the wrong PAN, or booked it to the wrong section — and the money never
moves between the two sides at all.

**Labels are written here, before the engine sees a row.** Every planted variance
carries its expected code, so scoring is against an answer authored independently
of whatever the engine happens to do. Rule 1: a fixture derived from actual
output asserts whatever we already do.

The file shapes are TRACES's: the 26AS text export is `^`-delimited, which is
why the adapter spec names that delimiter rather than a comma. What this does
*not* do is parse the real portal download end to end — that file carries section
banners, a summary block and a footer around the rows, and skipping past them is
a reader this build does not have. Stated in `docs/13-TDS.md` rather than
smoothed over.
"""

from __future__ import annotations

import csv
import json
import random
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

#: Fixed. A batch that changed between runs would make a regression
#: indistinguishable from a reseed.
SEED = 26_2026

#: The quarters a close covers. Indian TDS is filed quarterly and 26AS is
#: published against the quarter, not the month — which is itself a reason this
#: cannot be a rule inside the settlement loop, whose period is a date window.
QUARTERS = ("Q1", "Q2", "Q3", "Q4")
FY = "2026-27"

#: Sections that appear on a marketplace seller's 26AS. `194O` is the one that
#: matters here — 1% on e-commerce payments, deducted by the platform — and it is
#: exactly what currently lands in `E02` or `E14` in the settlement loop.
SECTIONS = {
    "194O": Decimal("0.01"),
    "194H": Decimal("0.05"),
    "194J": Decimal("0.10"),
    "194C": Decimal("0.02"),
}

DEDUCTORS = (
    ("MUMR12345A", "RAZORPAY SOFTWARE PRIVATE LIMITED"),
    ("BLRP54321B", "PAYU PAYMENTS PRIVATE LIMITED"),
    ("DELC98765C", "CASHFREE PAYMENTS INDIA PRIVATE LIMITED"),
    ("CHEA11223D", "AMAZON SELLER SERVICES PRIVATE LIMITED"),
    ("HYDF44556E", "FLIPKART INTERNET PRIVATE LIMITED"),
)

OUR_PAN = "AABCU9603R"


@dataclass
class Entry:
    """One deduction, as both sides would record it if nothing went wrong."""

    tan: str
    deductor: str
    section: str
    quarter: str
    paid_on: date
    amount_paid: Decimal
    tds: Decimal
    certificate: str

    #: What the *books* say, when they differ from 26AS. `None` means the two
    #: sides agree and this row is an ordinary match.
    variance: str | None = None
    ledger_overrides: dict = field(default_factory=dict)
    missing_from_26as: bool = False
    missing_from_ledger: bool = False


def _quarter_of(day: date) -> str:
    return QUARTERS[((day.month - 4) % 12) // 3]


def _certificate(rng: random.Random) -> str:
    return f"{rng.choice('ABCDEFGH')}{rng.randint(1000000, 9999999)}"


def build(rng: random.Random, count: int = 60) -> list[Entry]:
    """A year of deductions, then the planted variances.

    The proportions are not a guess. Reconciling 26AS is mostly clean rows with
    a tail of administrative failures, and a batch that was half broken would
    make a match rate meaningless in the other direction.
    """
    entries: list[Entry] = []
    for index in range(count):
        tan, deductor = DEDUCTORS[index % len(DEDUCTORS)]
        section = list(SECTIONS)[index % len(SECTIONS)]
        rate = SECTIONS[section]
        # An Indian financial year runs April to March, so month 13 of the year
        # is January of the next one. Arithmetic on a calendar that starts in
        # April is exactly the kind of domain fact a profile carries and the
        # engine must not.
        offset = index % 12
        paid_on = date(2026 + (1 if offset >= 9 else 0), ((3 + offset) % 12) + 1, 1 + (index % 27))
        gross = (Decimal(rng.randint(40_000, 900_000)) / 100).quantize(Decimal("0.01"))
        entries.append(
            Entry(
                tan=tan,
                deductor=deductor,
                section=section,
                quarter=_quarter_of(paid_on),
                paid_on=paid_on,
                amount_paid=gross,
                tds=(gross * rate).quantize(Decimal("0.01")),
                certificate=_certificate(rng),
            )
        )

    # ---- the tail, planted deliberately ------------------------------------
    #
    # Each of these is a real thing that happens to a real company, and each has
    # a different owner: a deposit failure is chased with the deductor, a PAN
    # error needs a correction return, and a quarter error resolves itself by
    # moving. A loop that called all of them "unmatched" would be the tool this
    # project exists not to be.

    def take(n: int) -> list[Entry]:
        picked = rng.sample([e for e in entries if e.variance is None], n)
        return picked

    for entry in take(4):
        # Deducted from our payment, never deposited with the government. Our
        # books expect the credit; 26AS has never heard of it.
        entry.variance = "X-TDS-NOT-DEPOSITED"
        entry.missing_from_26as = True

    for entry in take(3):
        # Filed against the wrong PAN. The credit exists somewhere and it is not
        # ours, which looks identical to not-deposited from our side alone —
        # the difference is only visible because the deductor's own quarterly
        # total still ties.
        entry.variance = "X-TDS-PAN-MISMATCH"
        entry.missing_from_26as = True
        entry.ledger_overrides["pan_filed"] = "AABCU9603Q"

    for entry in take(3):
        # Deposited in the next quarter. Both sides have it; they disagree about
        # when, which is a timing difference and clears itself.
        entry.variance = "X-TDS-QUARTER-ERROR"
        nxt = QUARTERS[(QUARTERS.index(entry.quarter) + 1) % len(QUARTERS)]
        entry.ledger_overrides["quarter"] = entry.quarter
        entry.quarter = nxt

    for entry in take(3):
        # Booked under the wrong section. Same money, same quarter, and the rate
        # a reviewer would check it against is now the wrong one.
        entry.variance = "X-TDS-SECTION-MISMATCH"
        entry.ledger_overrides["section"] = entry.section
        entry.section = "194J" if entry.section != "194J" else "194C"

    for entry in take(3):
        # Deducted at the wrong rate. The amount paid agrees and the tax does
        # not, which is the one variance in this loop that is arithmetic.
        entry.variance = "X-TDS-RATE-DIFF"
        entry.ledger_overrides["tds"] = entry.tds
        entry.tds = (entry.tds * Decimal("0.80")).quantize(Decimal("0.01"))

    for entry in take(2):
        # Sub-rupee. Real, ignorable, and it must not read as a finding — the
        # settlement loop's `E03` covers exactly this and is reused rather than
        # given a new name, because a second code for one phenomenon is how a
        # taxonomy stops meaning anything.
        entry.variance = "E03"
        entry.ledger_overrides["tds"] = entry.tds
        entry.tds = entry.tds + Decimal("0.03")

    for entry in take(2):
        # In 26AS and not in our books. Somebody deducted tax on a payment we
        # never recorded — which is a receivable we did not know we had, and the
        # only variance here that is in our favour.
        entry.variance = "X-TDS-UNBOOKED"
        entry.missing_from_ledger = True

    return entries


def _write_26as(path: Path, entries: list[Entry]) -> None:
    """The government's side, in the shape TRACES exports.

    `^`-delimited, because that is what the portal's text download uses. The
    banners and summary block a real file wraps around these rows are not here —
    see the module docstring.
    """
    rows = [
        [
            "sr_no",
            "deductor_tan",
            "deductor_name",
            "section",
            "financial_year",
            "quarter",
            "transaction_date",
            "status",
            "amount_paid",
            "tax_deducted",
            "tax_deposited",
            "certificate_no",
            "deductee_pan",
        ]
    ]
    serial = 0
    for entry in entries:
        if entry.missing_from_26as:
            continue
        serial += 1
        pan = entry.ledger_overrides.get("pan_filed", OUR_PAN)
        rows.append(
            [
                str(serial),
                entry.tan,
                entry.deductor,
                entry.section,
                FY,
                entry.quarter,
                entry.paid_on.isoformat(),
                "F",
                f"{entry.amount_paid:.2f}",
                f"{entry.tds:.2f}",
                f"{entry.tds:.2f}",
                entry.certificate,
                pan,
            ]
        )
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle, delimiter="^").writerows(rows)


def _write_ledger(path: Path, entries: list[Entry]) -> None:
    """Our side: what the books expect to be credited."""
    rows = [
        [
            "voucher_id",
            "deductor_tan",
            "section",
            "quarter",
            "invoice_date",
            "amount_billed",
            "tds_receivable",
            "counterparty",
        ]
    ]
    for index, entry in enumerate(entries, start=1):
        if entry.missing_from_ledger:
            continue
        rows.append(
            [
                f"TDS-{index:05d}",
                entry.tan,
                entry.ledger_overrides.get("section", entry.section),
                entry.ledger_overrides.get("quarter", entry.quarter),
                entry.paid_on.isoformat(),
                f"{entry.amount_paid:.2f}",
                f"{entry.ledger_overrides.get('tds', entry.tds):.2f}",
                entry.deductor,
            ]
        )
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(rows)


def _write_labels(path: Path, entries: list[Entry]) -> None:
    """The answer, authored before the engine runs.

    Scoring against this is the only version that means anything: a fixture read
    back out of a close asserts whatever the close happens to do.
    """
    planted = [
        {
            "tan": e.tan,
            "section": e.section,
            "quarter": e.quarter,
            "certificate_no": e.certificate,
            "transaction_date": e.paid_on.isoformat(),
            "expected_code": e.variance,
            "tds_per_26as": f"{e.tds:.2f}",
            "tds_per_books": f"{e.ledger_overrides.get('tds', e.tds):.2f}",
            "absent_from": (
                "26as" if e.missing_from_26as else "ledger" if e.missing_from_ledger else None
            ),
        }
        for e in entries
        if e.variance is not None
    ]
    clean = [e for e in entries if e.variance is None]
    path.write_text(
        json.dumps(
            {
                "loop": "tds_26as",
                "financial_year": FY,
                "deductee_pan": OUR_PAN,
                "rows_total": len(entries),
                "expected_matches": len(clean),
                "planted": planted,
                "by_code": {
                    code: sum(1 for p in planted if p["expected_code"] == code)
                    for code in sorted({p["expected_code"] for p in planted})
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def generate(root: Path, count: int = 60) -> dict:
    """Write one period's 26AS, ledger and labels. Returns the manifest entry."""
    root.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    entries = build(rng, count)

    _write_26as(root / "form26as.txt", entries)
    _write_ledger(root / "tds_ledger.csv", entries)
    _write_labels(root / "labels.json", entries)

    return {
        "loop": "tds_26as",
        "rows": len(entries),
        "planted": sum(1 for e in entries if e.variance is not None),
        "seed": SEED,
    }
