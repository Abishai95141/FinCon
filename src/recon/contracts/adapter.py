"""AdapterSpec — a declarative source mapping.

**This file is the security boundary.** ADR-001: no generated code is executed.
A model authors one of these; a hand-written interpreter executes it. The parse
vocabulary is a closed enum, so an unknown verb is a validation error rather
than an exec, and there is nothing arbitrary for a spec to smuggle.

If you are about to add a verb that takes executable content — a lambda, a
Python expression, a format string evaluated at runtime — stop. That reopens the
hole this design exists to close.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import CONTRACT_VERSION


class ReaderKind(StrEnum):
    CSV = "csv"
    XLSX = "xlsx"
    CAMT053 = "camt053"
    OFX = "ofx"
    QIF = "qif"
    JSON = "json"


class CanonicalField(StrEnum):
    """Where a source column lands in a Record. Closed — a spec cannot invent a
    destination the kernel does not understand."""

    DATE = "date"
    AMOUNT = "amount"
    CURRENCY = "currency"
    COUNTERPARTY = "counterparty"
    REFERENCE = "reference"
    GROUP_REF = "group_ref"
    RUNNING_BALANCE = "running_balance"
    KEY = "key"
    """Writes into Record.keys under the mapping's `as_key` name."""
    RAW = "raw"
    """Carried as evidence only. Never matched on."""


class ParseVerb(StrEnum):
    """The complete parse vocabulary. Adding a member is a contract change."""

    TEXT = "text"
    DECIMAL = "decimal"
    DECIMAL_MINOR = "decimal_minor"
    """Integer minor units — 1842907 means 18429.07. Added in 1.3.0 after a
    real source was ingested 100x wrong: the value parsed cleanly as a decimal
    and no check could contradict it, because that source carried no control
    total. A missing verb does not fail loudly; it fails plausibly."""
    DATE = "date"
    REGEX = "regex"
    CONSTANT = "constant"
    INTEGER = "integer"
    LOWER = "lower"
    UNMAPPABLE = "unmappable"
    """No verb in this vocabulary can express the column. Declaring it is the
    honest alternative to reaching for the nearest verb and returning a
    plausible wrong number — the failure mode that made a source 100x wrong at
    1.3.0. Always fails the row, naming the column and the value it saw."""
    SIGN_FROM_COLUMN = "sign_from_column"
    """Amount lives in one column, its sign in another (split Dr/Cr exports)."""


#: Verbs a fixed `sign` may modify. Anywhere else it is a silent no-op.
_SIGNABLE = {ParseVerb.DECIMAL, ParseVerb.DECIMAL_MINOR}


class RejectWhen(StrEnum):
    ROW_BLANK = "row_blank"
    COLUMN_EMPTY = "column_empty"
    COLUMN_MATCHES = "column_matches"
    """Balance-summary rows that are formatted as transactions — see the
    adversarial set, ADV-09."""


class ReaderSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ReaderKind
    encoding: list[str] = Field(default_factory=lambda: ["utf-8"])
    """Tried in order. Real bank exports are often Latin-1."""
    header_row: int = 1
    delimiter: str = ","
    sheet: str | None = None

    @model_validator(mode="after")
    def _encodings_present(self) -> ReaderSpec:
        if not self.encoding:
            raise ValueError("at least one encoding must be listed")
        return self


class FieldMap(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    to: CanonicalField
    source: str | None = None
    """Source column name. None only for CONSTANT."""
    parse: ParseVerb
    as_key: str | None = None
    """Required when `to` is KEY — the name inside Record.keys."""

    fmt: str | None = None
    """Date format for DATE, e.g. "DD-MM-YY"."""
    tz: str | None = None
    strip: list[str] = Field(default_factory=list)
    """Literal substrings removed before parsing — currency symbols, separators."""
    pattern: str | None = None
    """Regex for REGEX. Capped at 200 chars; an unbounded model-authored pattern
    is a denial-of-service, not a mapping."""
    value: str | None = None
    """Literal for CONSTANT."""
    sign_column: str | None = None
    sign_when_negative: str | None = None
    """For SIGN_FROM_COLUMN: the column carrying the sign, and the value in it
    that means negative."""
    sign: Literal["dr", "cr"] | None = None
    """Fixed sign for DECIMAL, for exports that split debits and credits into
    two columns: each column gets its own mapping, one "dr", one "cr". Added in
    contract 1.1.0 — a new optional field, so a minor bump."""

    @model_validator(mode="after")
    def _verb_has_its_arguments(self) -> FieldMap:
        if self.parse is ParseVerb.CONSTANT:
            if self.value is None:
                raise ValueError("CONSTANT requires `value`")
        elif not self.source:
            raise ValueError(f"{self.parse!r} requires `source`")

        if self.parse is ParseVerb.DATE and not self.fmt:
            raise ValueError("DATE requires `fmt`")
        if self.parse is ParseVerb.REGEX:
            if not self.pattern:
                raise ValueError("REGEX requires `pattern`")
            if len(self.pattern) > 200:
                raise ValueError("pattern longer than 200 chars — refused as a DoS risk")
        if self.parse is ParseVerb.SIGN_FROM_COLUMN and not self.sign_column:
            raise ValueError("SIGN_FROM_COLUMN requires `sign_column`")
        if self.sign is not None and self.parse not in _SIGNABLE:
            raise ValueError("`sign` applies to DECIMAL only — elsewhere it is a silent no-op")
        if self.to is CanonicalField.KEY and not self.as_key:
            raise ValueError("mapping to KEY requires `as_key`")
        return self


class RejectRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    when: RejectWhen
    reason: str
    """Row conservation counts rejections and needs a reason for each — a
    dropped row without one is a silent loss."""
    column: str | None = None
    pattern: str | None = None

    @model_validator(mode="after")
    def _reject_is_specified(self) -> RejectRule:
        if not self.reason:
            raise ValueError("a reject rule must state a reason")
        if self.when is RejectWhen.COLUMN_EMPTY and not self.column:
            raise ValueError("COLUMN_EMPTY requires `column`")
        if self.when is RejectWhen.COLUMN_MATCHES and not (self.column and self.pattern):
            raise ValueError("COLUMN_MATCHES requires `column` and `pattern`")
        return self


class AdapterSpec(BaseModel):
    """A complete, executable-by-interpreter source mapping."""

    model_config = ConfigDict(extra="forbid")

    contract_version: str = CONTRACT_VERSION
    spec_id: str
    version: int = 1
    source: str
    side: str
    """Which role records from this source play — profile-defined."""

    reader: ReaderSpec
    fields: list[FieldMap]
    reject: list[RejectRule] = Field(default_factory=list)
    currency: str = "INR"

    authored_by: str | None = None
    """"human" or a model id. Recorded so first-use approval can be enforced on
    model-authored specs specifically."""
    approved_by: str | None = None
    approved_at: str | None = None

    @model_validator(mode="after")
    def _spec_produces_a_record(self) -> AdapterSpec:
        targets = {f.to for f in self.fields}
        missing = {CanonicalField.DATE, CanonicalField.AMOUNT} - targets
        if missing:
            raise ValueError(
                f"spec cannot produce a Record: no mapping for {sorted(m.value for m in missing)}"
            )
        key_names = [f.as_key for f in self.fields if f.to is CanonicalField.KEY]
        if len(key_names) != len(set(key_names)):
            raise ValueError("two field maps write the same key name")
        return self

    @property
    def ref(self) -> str:
        return f"{self.spec_id}@v{self.version}"

    @property
    def needs_first_use_approval(self) -> bool:
        """Model-authored specs are approved once by a human before they are
        trusted (build plan, problem P3). Human-authored specs are not."""
        return self.authored_by != "human" and self.approved_by is None
