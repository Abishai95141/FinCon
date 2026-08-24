"""The AdapterSpec interpreter.

Reads a declarative spec and produces Records. This is the *only* thing that
executes a spec, and it executes it by dispatching into a fixed table of
functions (recon.intake.verbs.REGISTRY) — never by evaluating anything the spec
contains. See ADR-001.

A row that cannot be parsed becomes a Rejection with a reason, never a silently
dropped line: row conservation depends on every departure being counted.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal

from ..contracts import AdapterSpec, CanonicalField, Record
from ..contracts.adapter import RejectWhen
from . import verbs
from .readers import SourceDocument


class SpecError(ValueError):
    """The spec names something outside the closed vocabulary. A spec error,
    never an execution — ADR-001."""


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
                # Keys exist to be compared across sources, and two sources
                # rarely agree on case — a gateway is "RAZORPAY" in a bank
                # narration and "razorpay" in a settlement column. Casefolding
                # on write makes keys comparable by construction instead of
                # relying on every consumer to remember. Case is preserved in
                # `raw`, which is evidence and never matched on.
                keys[fm.as_key or ""] = str(value).casefold()
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
                # Placeholder. Real identity needs the natural key and this
                # row's position within it, and neither is knowable until every
                # row is parsed — see `_assign_identity` below.
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

    records = _assign_identity(records, spec)
    return Interpreted(records=records, rejections=rejections, running_balances=balances)


def _natural_key_of(record: Record, names: list[str]) -> str:
    """Read the declared fields off a parsed record.

    Closed vocabulary, like everything else a spec can name: `keys.<name>` reads
    a match key, anything else must be a canonical field. An unknown name is a
    spec error rather than an attribute lookup, so a model-authored spec cannot
    reach `raw` — which is untrusted source text — and make the *engine* branch
    on it.
    """
    parts: list[str] = []
    for name in names:
        if name.startswith("keys."):
            parts.append(str(record.keys.get(name[5:], "")))
        elif name in _NATURAL_KEY_FIELDS:
            parts.append(str(_NATURAL_KEY_FIELDS[name](record)))
        else:
            raise SpecError(
                f"natural_key names {name!r}, which is not a readable field. "
                f"Known: {sorted(_NATURAL_KEY_FIELDS)} or keys.<name>"
            )
    return "|".join(parts)


#: What a natural key may be built from. `raw` is absent on purpose.
_NATURAL_KEY_FIELDS = {
    "source": lambda r: r.source,
    "side": lambda r: r.side,
    "source_row_id": lambda r: r.source_row_id or "",
    "group_ref": lambda r: r.group_ref or "",
    "amount": lambda r: f"{r.amount:.2f}",
    "currency": lambda r: r.currency,
    "posted_on": lambda r: r.posted_on.isoformat(),
}


def _assign_identity(records: list[Record], spec: AdapterSpec) -> list[Record]:
    """Give every row a stable, unique id and its position within its partition.

    Identity was `source:ordinal`, which is neither stable nor meaningful:
    `gateway-settlement:266` names a different row in every batch, so a rule
    keyed on it fires happily on held-out data — on rows unrelated to the case
    it came from. That made the behavioural generality check unsound, which is
    why a structural ban on identity predicates existed at all.

    `source:natural-key-hash:occurrence` is stable (the same event yields the
    same id wherever it appears) and unique (occurrence separates repeats). A
    source declaring no natural key keeps positional ids and its proof says so.
    """
    if not spec.natural_key:
        return records

    seen: dict[str, int] = {}
    out: list[Record] = []
    for record in sorted(records, key=lambda r: r.row_ordinal):
        key = _natural_key_of(record, spec.natural_key)
        occurrence = seen.get(key, 0)
        seen[key] = occurrence + 1
        digest = hashlib.sha256(f"{spec.source}|{key}".encode()).hexdigest()[:12]
        out.append(
            record.model_copy(
                update={
                    "record_id": f"{spec.source}:{digest}:{occurrence}",
                    "natural_key": key,
                    "key_occurrence": occurrence,
                }
            )
        )
    return out
