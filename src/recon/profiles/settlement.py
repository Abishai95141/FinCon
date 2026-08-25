"""The settlement three-way loop, as configuration the product owns.

These lived in `bench/run.py` until 2026-08-25, which meant the profile, the
policy, the taxonomy, the chart and the period were all defined inside the
benchmark. A close could not be configured without importing the harness that
scores it — the same entanglement A1 exists to remove, one level up from the
pipeline itself. Nothing here knows about batches, labels, arms or scorecards.

`CLAUDE.md`'s file map has always described `profiles/` as "loop definitions as
data". This is the settlement loop's, and a second loop lands beside it rather
than inside the engine (invariant 7).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from ..contracts import Policy, ProofTier, Record, TaxonomyRegistry
from ..engine.consistency import RelationSpec
from ..engine.tiers import MatchProfile
from ..engine.tolerance import TolerancePolicy
from ..intake import ingest, load_spec
from ..ledger.accounts import ChartOfAccounts
from ..loop import LoadedSources, Loop, SourceBinding, register
from .chart import load_chart

POLICY_FILE = Path("data/policy/settlement_3way.json")
TAXONOMY_FILE = Path("data/taxonomy/codes.json")

#: The period this loop closes. A fact about the loop, not about a test batch.
WINDOW: tuple[date, date] = (date(2026, 7, 1), date(2026, 10, 31))
OPENED_ON = date(2026, 7, 1)

PROFILE = MatchProfile(
    name="settlement_3way",
    anchor_side="bank",
    group_side="settlement",
    # A bank credit and the settlement rows behind it are the same money seen
    # from two sides, so the group side is negated for the residual to close.
    side_signs={"bank": 1, "settlement": -1},
    tolerance=TolerancePolicy(absolute=Decimal("0.50"), date_window_days=3),
    counterparty_key="gateway",
    # A fee shares its charge's payment_id; without this the solver reports
    # subsets that mix a charge from one group with a fee from another.
    cohesion_key="payment_id",
    # `partial_payment` sits after `tolerant` and before `subset_sum`: a credit
    # that closes inside tolerance is an ordinary match, and one that does not
    # is only a partial payment when the reference already identifies the
    # payout. Anything still unmatched after that is the solver's problem.
    strategies=("exact", "tolerant", "partial_payment", "subset_sum"),
    # A fee is levied on the charge sharing its payment_id, and a gateway bills
    # its whole book on one set of terms. Rows that do not follow the relation
    # their own peers follow are a finding — which is how `E02` is visible at
    # all, given that no contract or rate appears anywhere in the export.
    consistency=RelationSpec(
        peer_key="gateway",
        link_key="payment_id",
        row_type_key="row_type",
        subject="fee",
        base="charge",
    ),
)


def policy(path: Path | None = None) -> Policy:
    """Authority, loaded from disk like an adapter spec so a change shows in a
    diff — and supplied out of band, never by the thing being judged."""
    return Policy.model_validate_json((path or POLICY_FILE).read_text(encoding="utf-8"))


def taxonomy(path: Path | None = None) -> TaxonomyRegistry:
    """The vocabulary, loaded like the policy: a separate versioned input."""
    return TaxonomyRegistry.model_validate_json((path or TAXONOMY_FILE).read_text(encoding="utf-8"))


def chart() -> ChartOfAccounts:
    """Domain data (invariant 7), which is why it loads from the profile rather
    than being named anywhere in `engine/`."""
    return load_chart("settlement_3way")


#: Which adapter reads which file, as data. A surface can say "your October
#: bank statement has not arrived" before any close is attempted, because it
#: knows what the loop expects without having to try.
SOURCES: tuple[SourceBinding, ...] = (
    SourceBinding(
        spec_id="icici-camt",
        filename="bank_icici_camt053.xml",
        side="bank",
        role="anchor",
        external_key="entry_ref",
    ),
    SourceBinding(
        spec_id="gateway-settlement",
        filename="settlement.csv",
        side="settlement",
        role="group",
        external_key="",
    ),
)

OUT_OF_SCOPE_DEBIT = (
    "debit — the settlement loop reconciles receipts; outgoing payments "
    "belong to the AP and payroll loops"
)


def load_sources(root: Path) -> LoadedSources:
    """Read one period's sources into records.

    Bank comes from the CAMT rendering because it carries `NtryRef`, which is
    the id a statement line is called by. The CSV is the same account and
    ingests identically (proved at P2).

    **Every ingested record is returned.** This loop reconciles money coming
    *in*, so debits are declared out of scope *with a reason* and travel to the
    completeness audit rather than being filtered away. A credit is in scope
    whether or not it looks like a gateway payout: a receipt nobody can
    attribute is the case a controller most wants raised, and recognising it by
    the very key it is missing would drop it.

    A group row whose source gave it no id keeps its record id as the name it
    is shown under. The benchmark's version dropped those rows — before the
    completeness audit could see them — which is exactly the silent-filter
    shape invariant 8 exists to catch. It never fired on these batches, which
    is why it survived eleven phases: a filter over an empty set is invisible.
    """
    pol = policy()
    results = {
        b.spec_id: ingest(load_spec(b.spec_id), root / b.filename, WINDOW, pol) for b in SOURCES
    }

    def named(binding: SourceBinding) -> list[tuple[str, Record]]:
        out = results[binding.spec_id].records
        if binding.external_key:
            return [(rec.keys.get(binding.external_key) or rec.record_id, rec) for rec in out]
        return [(rec.source_row_id or rec.record_id, rec) for rec in out]

    anchor_rows = named(SOURCES[0])
    group_rows = named(SOURCES[1])

    proofs = [results[b.spec_id].proof for b in SOURCES]
    weakest = min(
        (p.provenance for p in proofs),
        key=lambda t: 0 if t is ProofTier.P0_ARITHMETIC else 1,
    )
    return LoadedSources(
        anchor_rows=anchor_rows,
        group_rows=group_rows,
        provenance=weakest,
        scope={rec.record_id: OUT_OF_SCOPE_DEBIT for _, rec in anchor_rows if rec.amount <= 0},
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
            "Bank statement against gateway settlement: two independent records "
            "of the same money. The order register is a third leg and is not "
            "reconciled here."
        ),
    )
)
