"""CAMT.053 reader.

Flattens `Ntry` elements into the same row shape a CSV produces, so the
interpreter is identical for both. The value of CAMT here is that it *states*
its opening and closing balances (OPBD/CLBD), which gives the roll-forward proof
an aggregate check a bare CSV cannot offer.

Amount and sign live in separate places in CAMT — `Amt` is unsigned and
`CdtDbtInd` carries the direction — so the flattened row exposes both and a spec
maps them with SIGN_FROM_COLUMN.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree as ET

from ...contracts import ReaderSpec
from . import ReaderError, SourceDocument, sha256_of

CAMT_NS = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"
_NS = {"c": CAMT_NS}


def _text(node: ET.Element | None, path: str) -> str:
    if node is None:
        return ""
    found = node.find(path, _NS)
    return (found.text or "").strip() if found is not None else ""


def _decimal_or_none(value: str) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def read_camt053(path: Path, reader: ReaderSpec, source: str) -> SourceDocument:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ReaderError(f"{path.name} is not well-formed XML: {exc}") from exc

    stmt = root.find(".//c:Stmt", _NS)
    if stmt is None:
        raise ReaderError(f"{path.name} has no camt.053 Stmt element")

    balances: dict[str, Decimal | None] = {"OPBD": None, "CLBD": None}
    for bal in stmt.findall("c:Bal", _NS):
        code = _text(bal, "c:Tp/c:Cd")
        if code in balances:
            balances[code] = _decimal_or_none(_text(bal, "c:Amt"))

    entries = stmt.findall("c:Ntry", _NS)
    rows = [
        {
            "NtryRef": _text(entry, "c:NtryRef"),
            "Amt": _text(entry, "c:Amt"),
            "Ccy": (
                entry.find("c:Amt", _NS).get("Ccy", "")
                if entry.find("c:Amt", _NS) is not None
                else ""
            ),
            "CdtDbtInd": _text(entry, "c:CdtDbtInd"),
            "BookgDt": _text(entry, "c:BookgDt/c:Dt"),
            "AddtlNtryInf": _text(entry, "c:NtryDtls/c:AddtlNtryInf"),
        }
        for entry in entries
    ]

    return SourceDocument(
        source=source,
        doc_hash=sha256_of(path),
        rows=rows,
        rows_in_file=len(entries),
        opening_balance=balances["OPBD"],
        closing_balance=balances["CLBD"],
        stated={"statement_id": _text(stmt, "c:Id")},
    )
