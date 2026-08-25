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

from ..contracts import Policy, TaxonomyRegistry
from ..engine.consistency import RelationSpec
from ..engine.tiers import MatchProfile
from ..engine.tolerance import TolerancePolicy
from ..ledger.accounts import ChartOfAccounts
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
