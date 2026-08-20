"""Readers turn a file into raw rows plus whatever the source states about
itself — control totals, opening and closing balances.

A reader never interprets. It does not decide what a column means, drop a row it
thinks is junk, or coerce a type. Everything downstream of `rows` is the
interpreter's job, and everything a reader *does* drop must be counted, because
row conservation is only meaningful if the denominator is the real file.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from ...contracts import ReaderKind, ReaderSpec


@dataclass(frozen=True)
class SourceDocument:
    source: str
    doc_hash: str
    """sha256 of the file bytes. Two ingests of the same bytes are the same
    document — this is what makes re-ingest idempotent."""

    rows: list[dict[str, str]]
    """Raw values, verbatim. Blank rows are preserved: dropping them here would
    shrink the row-conservation denominator and hide a silent loss."""

    rows_in_file: int
    """Data rows present in the file, header excluded. The denominator."""

    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    control_total: Decimal | None = None
    stated: dict[str, str] = field(default_factory=dict)
    """Anything else the source asserted about itself, for evidence."""


class ReaderError(RuntimeError):
    pass


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path, spec_reader: ReaderSpec, source: str) -> SourceDocument:
    """Dispatch on reader kind. An unimplemented kind raises rather than
    returning an empty document that would read as 'a file with no rows'."""
    from .camt_reader import read_camt053
    from .csv_reader import read_csv

    if spec_reader.kind is ReaderKind.CSV:
        return read_csv(path, spec_reader, source)
    if spec_reader.kind is ReaderKind.CAMT053:
        return read_camt053(path, spec_reader, source)
    raise ReaderError(f"reader kind {spec_reader.kind.value!r} is not implemented yet")


__all__ = ["ReaderError", "SourceDocument", "read", "sha256_of"]
