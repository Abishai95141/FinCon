"""The AdapterSpec interpreter.

Reads a declarative spec and produces Records. This is the *only* thing that
executes a spec, and it executes it by dispatching into a fixed table of
functions (recon.intake.verbs.REGISTRY) — never by evaluating anything the spec
contains. See ADR-001.

A row that cannot be parsed becomes a Rejection with a reason, never a silently
dropped line: row conservation depends on every departure being counted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from ..contracts import AdapterSpec, CanonicalField, Record
from ..contracts.adapter import RejectWhen
from . import verbs
from .readers import SourceDocument


@dataclass(frozen=True)
class Rejection:
    row_ordinal: int
    reason: str
    detail: str = ""


@dataclass(frozen=True)
class Interpreted:
    records: list[Record]
    rejections: list[Rejection]
    running_balances: list[tuple[int, Decimal]]
    """(row_ordinal, stated balance) where the spec mapped RUNNING_BALANCE.
    Feeds the per-row roll-forward check."""


def _row_is_blank(row: dict[str, str]) -> bool:
    return all(not (v or "").strip() for v in row.values())


def _rejected_by(spec: AdapterSpec, row: dict[str, str]) -> str | None:
    for rule in spec.reject:
        if rule.when is RejectWhen.ROW_BLANK and _row_is_blank(row):
            return rule.reason
        if rule.when is RejectWhen.COLUMN_EMPTY and not (row.get(rule.column or "") or "").strip():
            return rule.reason
        if rule.when is RejectWhen.COLUMN_MATCHES:
            value = row.get(rule.column or "") or ""
            if rule.pattern and re.search(rule.pattern, value, re.IGNORECASE):
                return rule.reason
    return None


def interpret(spec: AdapterSpec, doc: SourceDocument) -> Interpreted:
    records: list[Record] = []
    rejections: list[Rejection] = []
    balances: list[tuple[int, Decimal]] = []

    amount_maps = [f for f in spec.fields if f.to is CanonicalField.AMOUNT]

    for ordinal, row in enumerate(doc.rows):
        reason = _rejected_by(spec, row)
        if reason is not None:
            rejections.append(Rejection(ordinal, reason))
            continue

        fields: dict[str, object] = {}
        keys: dict[str, str] = {}
        raw: dict[str, str] = {}
        amount: Decimal | None = None
        failure: verbs.ParseError | None = None

        for fm in spec.fields:
            if fm.to is CanonicalField.AMOUNT:
                continue  # handled below — several columns may feed one amount
            try:
                value = verbs.apply(fm, row)
            except verbs.ParseError as exc:
                # A missing optional field is not a failed row; a missing
                # required one is. DATE is required, the rest are best-effort.
                if fm.to is CanonicalField.DATE:
                    failure = exc
                    break
                continue
            if fm.to is CanonicalField.KEY:
                keys[fm.as_key or ""] = str(value)
            elif fm.to is CanonicalField.RAW:
                raw[fm.source or fm.as_key or "raw"] = str(value)
            elif fm.to is CanonicalField.RUNNING_BALANCE:
                if isinstance(value, Decimal):
                    balances.append((ordinal, value))
            else:
                fields[fm.to.value] = value

        if failure is None:
            # Split Dr/Cr exports map two columns onto AMOUNT; the first that
            # yields a value wins. Both empty means no movement on this row.
            for fm in amount_maps:
                try:
                    parsed = verbs.apply(fm, row)
                except verbs.ParseError:
                    continue
                if isinstance(parsed, Decimal):
                    amount = parsed
                    break
            if amount is None:
                failure = verbs.ParseError(
                    "amount", "", "no amount column yielded a value on this row"
                )

        if failure is not None:
            rejections.append(Rejection(ordinal, "unparseable", str(failure)))
            continue

        records.append(
            Record(
                record_id=f"{spec.source}:{ordinal}",
                side=spec.side,
                source=spec.source,
                source_row_id=str(fields.get("reference") or "") or None,
                row_ordinal=ordinal,
                posted_on=fields["date"],  # type: ignore[arg-type]
                amount=amount,
                currency=str(fields.get("currency") or spec.currency),
                keys=keys,
                group_ref=str(fields["group_ref"]) if fields.get("group_ref") else None,
                raw=raw or {k: (v or "") for k, v in row.items()},
                doc_hash=doc.doc_hash,
            )
        )

    return Interpreted(records=records, rejections=rejections, running_balances=balances)
