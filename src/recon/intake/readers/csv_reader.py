"""CSV reader with encoding fallback.

Uses `csv.reader` rather than `csv.DictReader` on purpose: DictReader silently
skips blank lines, and real bank exports end with them. Skipping them here would
remove them from the row-conservation denominator, so a genuinely lost row and a
trailing blank would look identical.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from ...contracts import ReaderSpec
from . import ReaderError, SourceDocument, sha256_of


def _decode(raw: bytes, encodings: list[str]) -> str:
    """Try each encoding in order. Bank exports are frequently Latin-1 even when
    they claim otherwise — securo carries the same fallback for the same reason."""
    for enc in encodings:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ReaderError(f"could not decode with any of {encodings}")


def read_csv(path: Path, reader: ReaderSpec, source: str) -> SourceDocument:
    text = _decode(path.read_bytes(), reader.encoding)
    # Strip a BOM if the file carries one; it would otherwise become part of the
    # first header name and every mapping onto that column would miss.
    text = text.lstrip("﻿")

    all_rows = list(csv.reader(io.StringIO(text), delimiter=reader.delimiter))
    header_index = reader.header_row - 1
    if header_index >= len(all_rows):
        raise ReaderError(f"header_row {reader.header_row} is past the end of {path.name}")

    header = [h.strip() for h in all_rows[header_index]]
    body = all_rows[header_index + 1 :]

    rows: list[dict[str, str]] = []
    for values in body:
        # Pad or trim to the header width so a short row is still addressable by
        # column name rather than raising and losing the row silently.
        padded = list(values[: len(header)]) + [""] * (len(header) - len(values))
        rows.append(dict(zip(header, padded, strict=True)))

    return SourceDocument(
        source=source,
        doc_hash=sha256_of(path),
        rows=rows,
        rows_in_file=len(body),
        stated={"header": ",".join(header)},
    )
