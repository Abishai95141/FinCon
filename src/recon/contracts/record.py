"""Record — the canonical normalized row.

Deliberately domain-agnostic (CLAUDE.md invariant 7). Nothing here knows what a
charge, a payout or a GST invoice is. A profile decides what goes in `keys` and
what `side` means; the kernel only ever sees amounts, dates and opaque keys.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import Money


class Record(BaseModel):
    """One normalized row from one source.

    Immutable. A record is evidence — if a value needs correcting, that is a
    re-ingest producing a new record, not a mutation of this one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: str
    """Stable within a run. Referenced by proofs, so it must survive re-reads."""

    side: str
    """Which role this record plays in the profile's match — e.g. "orders",
    "settlement", "bank". Names are profile-defined; the kernel does not
    interpret them beyond grouping."""

    source: str
    """The adapter/source that produced it, e.g. "icici-current"."""

    source_row_id: str | None = None
    """The row's own id in the source, where it had one."""

    row_ordinal: int
    """Position in the source document. Gives a deterministic tie-break and lets
    row conservation point at a specific line."""

    posted_on: date

    amount: Money
    """Signed. Positive is an inflow to the account this side represents,
    negative an outflow. Sign convention is fixed here so no downstream code has
    to guess it."""

    currency: str
    """ISO 4217, uppercase."""

    keys: dict[str, str] = Field(default_factory=dict)
    """Normalized values the blocker may key on — profile-defined names. These
    have been through the adapter's parse verbs; they are not raw text."""

    group_ref: str | None = None
    """A grouping the *source* declared (e.g. a payout id present in the export).
    None means the source gave no grouping and it must be inferred — which is
    what makes subset-sum ambiguity reachable."""

    raw: dict[str, str] = Field(default_factory=dict)
    """Verbatim source fields, kept for evidence and for showing a human
    raw-vs-parsed. Never matched on — matching reads `keys`."""

    doc_hash: str
    """sha256 of the source document. Two records with the same doc_hash and
    row_ordinal are the same row; this is what makes re-ingest idempotent."""

    @field_validator("currency")
    @classmethod
    def _iso4217(cls, v: str) -> str:
        if len(v) != 3 or not v.isalpha() or v != v.upper():
            raise ValueError(f"currency must be an uppercase 3-letter ISO 4217 code, got {v!r}")
        return v

    @field_validator("row_ordinal")
    @classmethod
    def _non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("row_ordinal must be >= 0")
        return v

    natural_key: str = ""
    """What this row *claims to be*, from the fields the spec declares — not
    which row it is. Two rows sharing it assert the same economic event twice,
    which is what a duplicate is.

    Deliberately separate from `record_id`. Making identity *be* the natural key
    was the obvious move and it is wrong: on batch A exactly two natural keys
    collide, and they are precisely the planted duplicate — so a content-keyed
    id would delete the rows it exists to find, and invariant 8 would never see
    them go. Identity must stay unique; the collision is the signal."""

    key_occurrence: int = 0
    """This row's position among rows sharing its natural key, in file order.
    `0` is the first assertion of the event; anything above is a repeat.

    It is a window function — `row_number() over (partition by natural_key)` —
    evaluated once here, where the whole source is in hand, and carried as a
    per-record fact. That is what lets a rule ask about duplication with a
    *unary* predicate: the aggregation happens in the interpreter, never in a
    rule."""

    @property
    def lineage(self) -> str:
        """Where this row came from, in one string, for evidence lines."""
        return f"{self.source}#{self.row_ordinal}@{self.doc_hash[:12]}"
