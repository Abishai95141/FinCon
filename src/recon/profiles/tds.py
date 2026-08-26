"""The TDS / Form 26AS loop — the second one, and the point of having one.

"The engine is domain-agnostic" has been invariant 7 since P1 and was tested by
exactly one loop, which is not a test. A profile that only ever ran settlement
cannot tell you whether the generality is real or whether `engine/` quietly grew
gateway-shaped assumptions. This is the check, and it is deliberately as unlike
settlement as a reconciliation gets:

| | settlement | tds_26as |
|---|---|---|
| the two sides | one payment, seen twice | our expectation, and the state's record |
| what agrees | amount and date | `TAN + section + quarter` |
| period | a date window | a **quarter** of an April-to-March year |
| a break | the money went somewhere | somebody filed something wrong |
| the fix | a journal entry | usually a correction return by a third party |

**Nothing in `engine/` changed to add this.** If something had to, invariant 7
was false and it is better to find that out from a second loop than from a
customer.

**Why this is a loop and not a rule in the settlement loop.** A §194-O deduction
turns up inside a gateway settlement as an amount that does not tie, and the
settlement loop can only call it `E02` (a fee variance) or `E14` (unexplained).
Both are wrong, and `E14` is worse than it looks: TDS reconciles against a
*government* record on a *quarterly* cadence, so the investigation, the counterpart
and the calendar are all different. Routing it to the desk that chases gateway
fees sends somebody to argue with Razorpay about the Income Tax Department's
filing.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from ..contracts import Policy, ProofTier, Record, TaxonomyRegistry
from ..engine.tiers import MatchProfile
from ..engine.tolerance import TolerancePolicy
from ..intake import ingest, load_spec
from ..ledger.accounts import ChartOfAccounts
from ..loop import LoadedSources, Loop, SourceBinding, register
from .chart import load_chart

POLICY_FILE = Path("data/policy/tds_26as.json")
TAXONOMY_FILE = Path("data/taxonomy/codes.json")

#: An Indian financial year: April to March. The settlement loop's window is a
#: calendar quarter and this one is not, which is the first thing that would
#: break if a period were hardcoded anywhere upstream of a profile.
WINDOW: tuple[date, date] = (date(2026, 4, 1), date(2027, 3, 31))
OPENED_ON = date(2026, 4, 1)

PROFILE = MatchProfile(
    name="tds_26as",
    anchor_side="government",
    group_side="books",
    # One side negated, as in settlement — and for a reason worth writing down,
    # because the first version of this file had them both positive on the
    # argument that "both sides are positive assertions about the same tax".
    # That is true of the *meaning* and false of the arithmetic: a residual is a
    # signed sum, so two sides agreeing at 46.31 close to 92.62 rather than to
    # zero, and every single row came back `E14`. The sign is about the direction
    # of the comparison, never about the sign of the number in the file.
    side_signs={"government": 1, "books": -1},
    # 0.05 rather than settlement's 0.50. TDS is a statutory rate applied to a
    # known base, so it has one right answer to the paisa; anything above
    # rounding is a rate applied wrongly and must be raised, not absorbed. The
    # date window is 0 because the two sides carry the *same* transaction date —
    # a disagreement about when is a quarter error, which breaks the key rather
    # than stretching a tolerance.
    tolerance=TolerancePolicy(absolute=Decimal("0.05"), date_window_days=0),
    # **Not `tan`.** `strategies.viable` narrows candidate groups by
    # `counterparty_key` and then by amount, so a coarse key lets the tolerant
    # pass pair an anchor with any group from the same party whose amount is
    # within tolerance. Keyed on the deductor's TAN, this loop produced six false
    # matches: 26AS rows paired with ledger vouchers for a different section
    # entirely, because a deductor files many small deductions and ₹0.05 apart is
    # common when the amounts are tens of rupees.
    #
    # Settlement gets away with `gateway` because a payout is tens of thousands
    # and two of them landing within fifty paise is rare. That is luck, not a
    # property — the same path is open there and this loop is where it fired.
    counterparty_key="pairing",
    strategies=("exact", "tolerant"),
    # No consistency relation. Settlement has one because a gateway bills its
    # whole book on terms nobody publishes, so rows that disagree with their own
    # peers are the only way `E02` is visible. Here the rate *is* published — it
    # is in the Act — so a wrong rate is caught by the arithmetic and inventing a
    # population relation for it would be a second, weaker check on a fact we
    # already hold.
    consistency=None,
)

#: How a 26AS row and a ledger voucher are the same deduction. This is the
#: composite the profession already uses, plus the transaction date to keep a
#: group down to one deduction rather than a deductor's whole quarter.
#:
#: Composed here rather than in an adapter spec, deliberately: the government's
#: file has no column for our join key and never will, and a parse verb that
#: concatenated fields would be a spec that computes rather than reads. ADR-001
#: keeps the vocabulary closed; the domain knowledge lives in the profile.
JOIN_KEYS = ("tan", "section", "quarter")


def pairing_key(record: Record) -> str:
    """`TAN|section|quarter|date` — the string both sides must agree on.

    Every planted variance in `bench/generator/tds.py` is a disagreement about
    one component of this, which is what makes them separable: a quarter error
    and a section error are both "unmatched" to an amount-only reconciliation
    and are different desks in practice.
    """
    parts = [record.keys.get(k, "") for k in JOIN_KEYS]
    parts.append(record.posted_on.isoformat() if record.posted_on else "")
    return "|".join(parts)


def policy(path: Path | None = None) -> Policy:
    return Policy.model_validate_json((path or POLICY_FILE).read_text(encoding="utf-8"))


def taxonomy(path: Path | None = None) -> TaxonomyRegistry:
    """The *same* registry the settlement loop reads.

    One vocabulary across loops, not one per loop. `E03` means sub-unit rounding
    whether the unit is a gateway fee or a tax deposit, and minting a second code
    for it because this is a different file is how a taxonomy stops meaning
    anything. The six `X-TDS-*` codes are the ones that genuinely have no
    equivalent, and they are `PROVISIONAL` — they label and route, and they do
    not direct a posting until somebody promotes them with a written definition.
    """
    return TaxonomyRegistry.model_validate_json((path or TAXONOMY_FILE).read_text(encoding="utf-8"))


def chart() -> ChartOfAccounts:
    return load_chart("tds_26as")


SOURCES: tuple[SourceBinding, ...] = (
    SourceBinding(
        spec_id="traces-26as",
        filename="form26as.txt",
        side="government",
        role="anchor",
        external_key="",
    ),
    SourceBinding(
        spec_id="tds-ledger",
        filename="tds_ledger.csv",
        side="books",
        role="group",
        external_key="",
    ),
)

OUT_OF_SCOPE_UNFILED = (
    "status is not 'F' — the deductor's return for this quarter has not been "
    "accepted by TRACES yet, so the row is provisional and reconciling against "
    "it would be reconciling against something that can still change"
)


def load_sources(root: Path) -> LoadedSources:
    """Read one financial year's 26AS and TDS ledger into records.

    The composite pairing key is written onto each record's `source_row_id`,
    because that is the field `strategies._exact` reads to find the group an
    anchor names. Rewriting it here is the profile supplying domain knowledge to
    a domain-agnostic engine, which is the arrangement invariant 7 describes.

    **Every ingested row is returned.** A 26AS line whose status is not `F` is
    declared out of scope *with a reason* and still travels to the completeness
    audit — filtering it in this function would be the silent drop invariant 8
    exists to catch, and it would be invisible because it happens before
    anything counts.
    """
    pol = policy()
    results = {
        b.spec_id: ingest(load_spec(b.spec_id), root / b.filename, WINDOW, pol) for b in SOURCES
    }

    def keyed(binding: SourceBinding) -> list[tuple[str, Record]]:
        """Write the pairing key onto both fields the engine reads.

        `source_row_id` is what `strategies._exact` reads off the *anchor* to
        name a group; `group_ref` is what `tiers` buckets the *group* side by.
        Setting only the first leaves every group ungrouped and every anchor
        unmatched — 53 of 53 came back `E14` with the keys agreeing perfectly on
        both sides, because nothing had put them in the same bucket.

        In settlement the adapter spec supplies `group_ref` directly from a
        payout id. Here there is no such column: the government's file will never
        carry our join key, so the profile composes it.
        """
        rows = []
        for rec in results[binding.spec_id].records:
            ref = pairing_key(rec)
            rows.append(
                (
                    ref,
                    rec.model_copy(
                        update={
                            "source_row_id": ref,
                            "group_ref": ref,
                            # Also a *key*, because that is what the tolerant pass
                            # narrows candidates by. Without it the composite
                            # governs the exact match and nothing at all governs
                            # the tolerant one.
                            "keys": {**rec.keys, "pairing": ref},
                        }
                    ),
                )
            )
        return rows

    anchor_rows = keyed(SOURCES[0])
    group_rows = keyed(SOURCES[1])

    scope = {
        rec.record_id: OUT_OF_SCOPE_UNFILED
        for _, rec in anchor_rows
        if (rec.keys.get("status") or "F").upper() != "F"
    }

    proofs = [results[b.spec_id].proof for b in SOURCES]
    weakest = min(
        (p.provenance for p in proofs),
        key=lambda t: 0 if t is ProofTier.P0_ARITHMETIC else 1,
    )
    return LoadedSources(
        anchor_rows=anchor_rows,
        group_rows=group_rows,
        provenance=weakest,
        scope=scope,
        proofs=proofs,
        digests={p.source: p.doc_hash for p in proofs},
        strengths={p.source: p.strength for p in proofs},
    )


LOOP = register(
    Loop(
        name=PROFILE.name,
        profile=PROFILE,
        period=WINDOW,
        opened_on=OPENED_ON,
        sources=SOURCES,
        policy_file=POLICY_FILE,
        taxonomy_file=TAXONOMY_FILE,
        load=load_sources,
        policy=policy,
        taxonomy=taxonomy,
        chart=chart,
        description=(
            "Form 26AS from TRACES against the TDS receivable ledger: what the "
            "Income Tax Department says was deposited, against what the books "
            "expect to be credited. Matched on TAN, section and quarter — not on "
            "an amount and a date, and not against a contract."
        ),
    )
)
