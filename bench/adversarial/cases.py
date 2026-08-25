"""Adversarial cases, authored at P0 before any engine exists.

Read CLAUDE.md rule 1 before touching this file. These cases exist to be hard,
not to be passed. Editing a case so the engine handles it is teaching to the
test and destroys the only independent signal this benchmark has.

Legitimate edits: adding a case, correcting a factual error in `situation`,
tightening `correct_behaviour` where it was genuinely ambiguous. Not legitimate:
relaxing `correct_behaviour` because the engine does something else.

This module deliberately imports nothing from `recon`. tests/gates/gate_p0.py
asserts that, so the cases cannot drift toward engine internals.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Case:
    id: str
    situation: str  # what the data looks like
    trap: str  # the plausible wrong answer
    correct_behaviour: str  # what a correct system does — the assertion target
    expect: str  # code or tier the engine should land on


CASES: tuple[Case, ...] = (
    Case(
        "ADV-01-duplicate-different-ref",
        "The same charge appears twice with different row ids and different "
        "reference strings, one day apart.",
        "Treat them as two genuine charges because the references differ.",
        "Flag as a probable duplicate on amount + payment_id and escalate. Do not "
        "auto-suppress — differing references are exactly the case where "
        "suppression silently deletes real revenue.",
        "E06",
    ),
    Case(
        "ADV-02-two-valid-subsets",
        "Four charges where a+b == c+d, equal cardinality so fees tie too, and a "
        "bank credit equal to that sum. No payout grouping in the export.",
        "Return the first subset the solver finds and report a confident match.",
        "Detect that more than one subset satisfies the constraint and escalate as "
        "ambiguous. There is no correct assignment to pick.",
        "E09",
    ),
    Case(
        "ADV-03-chargeback-after-close",
        "A chargeback posts in September reversing an order settled and closed in "
        "July. No matching order in the current batch.",
        "Report it as an unexplained bank movement, or link it to a same-amount "
        "order from the current period.",
        "Recognise it as a prior-period reversal, book to the disputes reserve by "
        "policy, and leave reopening as a human decision.",
        "E07",
    ),
    Case(
        "ADV-04-fx-moved-between-capture-and-settlement",
        "A charge captured at one rate settles at another. Gross and net differ by "
        "more than rounding but less than a fee tier.",
        "Absorb the difference into the fee tolerance and match anyway.",
        "Attribute the difference to FX rather than fees, and clear it only if it "
        "sits inside the stated FX policy tolerance. Consuming fee tolerance for "
        "an FX movement hides a real fee variance later.",
        "E03",
    ),
    Case(
        "ADV-05-truncated-reference",
        "The bank narration carries the payout reference cut to twelve characters.",
        "Fail to match, because exact reference comparison misses.",
        "Recover at T1 on amount + date window + counterparty, and record in the "
        "proof that the reference was partial.",
        "T1",
    ),
    Case(
        "ADV-06-counterparty-renamed-midperiod",
        "The gateway's bank narration changes from RAZORPAY to RAZORPAY SOFTWARE "
        "PVT on the 14th. Same account, same payouts.",
        "Treat post-14th credits as a new, unknown counterparty.",
        "Resolve both strings to one counterparty and match throughout. A rename "
        "must not read as a new payer.",
        "T1",
    ),
    Case(
        "ADV-07-two-payouts-same-day-same-amount",
        "Two distinct payouts, same gateway, same date, identical net, and both "
        "bank references truncated to the same prefix.",
        "Match either payout to either credit — the arithmetic works both ways.",
        "Recognise the assignment is not unique and escalate, or disambiguate on a "
        "field that genuinely distinguishes them. Do not pick arbitrarily.",
        "E09",
    ),
    Case(
        "ADV-08-zero-and-negative-payout",
        "A payout whose refunds exceed its charges, producing a net debit, plus a "
        "second payout netting exactly zero.",
        "Skip both — a payout is assumed to be a positive credit.",
        "Handle the debit as a bank debit and the zero payout as a real settled "
        "payout with a zero movement. Neither may silently vanish from the counts.",
        "T0",
    ),
    Case(
        "ADV-09-balance-summary-row",
        "The bank export contains rows whose narration is a balance summary "
        "('SALDO DO DIA'-style), formatted identically to transactions.",
        "Ingest them as transactions, inflating both row count and movement total.",
        "Reject at intake with a stated reason. Row conservation must account for "
        "them as rejections, not drop them silently.",
        "reject",
    ),
    Case(
        "ADV-10-settlement-file-covers-two-periods",
        "The settlement export includes a payout from the previous period whose "
        "bank credit is not in this statement.",
        "Raise it as an unmatched exception against this period.",
        "Scope to the period under close and exclude it, or carry it explicitly as "
        "an opening item. An out-of-period row is not an exception.",
        "out_of_scope",
    ),
    # ---------------------------------------------------------------------
    # Authored 2026-08-25, not at P0. Flagged because it matters: the other ten
    # were written before any engine existed, and this one was written by
    # somebody who knows exactly what this engine does and does not handle. It
    # was committed red — the engine reported `E14 unexplained` — before any
    # implementation, which is the closest a late case can get to the
    # independence the original ten have for free. Treat its evidential weight
    # accordingly.
    # ---------------------------------------------------------------------
    Case(
        "ADV-11-partial-payment",
        "A bank credit arrives against a payout it references correctly, for "
        "materially less than the payout's net. The rest was never paid.",
        "Widen tolerance until the residual fits and record a clean match — or, "
        "having refused that, report it as unexplained when the group is in fact "
        "identified and the shortfall is known to the paisa.",
        "Identify the group, quantify the shortfall, and raise `E04` naming both. "
        "The money that arrived is reconciled; the remainder is an open "
        "receivable and must stay in the unreconciled total (invariant 1). Never "
        "absorb it into tolerance: a tolerance wide enough to swallow a partial "
        "payment is wide enough to swallow a theft, and `E14` is a worse answer "
        "than `E04` because it discards facts the engine already has.",
        "E04",
    ),
    Case(
        "ADV-12-partial-payment-looks-like-a-fee",
        "A payout is short by an amount close to what this gateway's fee would "
        "be on a payout that size.",
        "Book the shortfall as an unbilled fee. The number is plausible and the "
        "payout then ties exactly.",
        "Raise `E04`. A shortfall that resembles a fee is not evidence of a fee — "
        "the fee rows are in the export and this is not one of them. Inventing "
        "the most plausible explanation for missing money is how a reconciliation "
        "system launders a loss into an expense.",
        "E04",
    ),
)


def by_expectation() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for case in CASES:
        out.setdefault(case.expect, []).append(case.id)
    return {k: sorted(v) for k, v in sorted(out.items())}
