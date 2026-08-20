"""The parse vocabulary — the security boundary from ADR-001.

Every verb is a plain function in REGISTRY. There is no eval, no exec, no
dynamic import, and no code path where a value out of a spec becomes something
executed. A verb outside the enum cannot be constructed (pydantic rejects it);
a verb inside the enum with no implementation fails at *import* via the
completeness assertion at the bottom of this file, not at runtime on someone's
statement.

If you are adding a verb that takes executable content — an expression, a
lambda, a format string evaluated at runtime — stop and re-read ADR-001.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from ..contracts import ParseVerb
from ..contracts.adapter import FieldMap

# Date tokens a spec may use, mapped to strptime directives. Closed on purpose:
# passing a raw strptime string through would let a spec reach formats we have
# never tested against real exports.
_DATE_TOKENS = {
    "YYYY": "%Y",
    "YY": "%y",
    "MM": "%m",
    "DD": "%d",
    "HH": "%H",
    "mm": "%M",
    "SS": "%S",
}
_TOKEN_RE = re.compile("|".join(sorted(_DATE_TOKENS, key=len, reverse=True)))

MAX_PATTERN_LEN = 200


class ParseError(ValueError):
    """A value did not parse. Carries the field so a rejection can name it."""

    def __init__(self, field: str, value: str, detail: str) -> None:
        super().__init__(f"{field}: {detail} (got {value!r})")
        self.field = field
        self.value = value
        self.detail = detail


def _strip(value: str, fm: FieldMap) -> str:
    for token in fm.strip:
        value = value.replace(token, "")
    return value.strip()


def parse_text(value: str, fm: FieldMap, row: dict[str, str]) -> str:
    return _strip(value, fm)


def parse_lower(value: str, fm: FieldMap, row: dict[str, str]) -> str:
    return _strip(value, fm).lower()


def parse_constant(value: str, fm: FieldMap, row: dict[str, str]) -> str:
    return fm.value or ""


def parse_integer(value: str, fm: FieldMap, row: dict[str, str]) -> int:
    raw = _strip(value, fm)
    try:
        return int(raw)
    except ValueError as exc:
        raise ParseError(fm.source or "?", value, "not an integer") from exc


def parse_decimal(value: str, fm: FieldMap, row: dict[str, str]) -> Decimal:
    raw = _strip(value, fm)
    if not raw:
        raise ParseError(fm.source or "?", value, "empty")
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise ParseError(fm.source or "?", value, "not a decimal") from exc
    if fm.sign == "dr":
        amount = -abs(amount)
    elif fm.sign == "cr":
        amount = abs(amount)
    return amount


def parse_date(value: str, fm: FieldMap, row: dict[str, str]) -> date:
    raw = _strip(value, fm)
    fmt = _TOKEN_RE.sub(lambda m: _DATE_TOKENS[m.group()], fm.fmt or "")
    try:
        return datetime.strptime(raw, fmt).date()
    except ValueError as exc:
        raise ParseError(fm.source or "?", value, f"does not match {fm.fmt}") from exc


def parse_regex(value: str, fm: FieldMap, row: dict[str, str]) -> str:
    pattern = fm.pattern or ""
    if len(pattern) > MAX_PATTERN_LEN:
        raise ParseError(fm.source or "?", value, "pattern exceeds the length cap")
    match = re.search(pattern, value)
    if match is None:
        raise ParseError(fm.source or "?", value, f"no match for {pattern!r}")
    # Group 1 when the pattern captures, otherwise the whole match.
    return match.group(1) if match.groups() else match.group(0)


def parse_sign_from_column(value: str, fm: FieldMap, row: dict[str, str]) -> Decimal:
    """Amount in one column, its sign in another — split Dr/Cr exports."""
    amount = parse_decimal(value, fm, row)
    marker = (row.get(fm.sign_column or "") or "").strip()
    if fm.sign_when_negative is not None and marker == fm.sign_when_negative:
        return -abs(amount)
    return abs(amount)


REGISTRY: dict[ParseVerb, Callable[[str, FieldMap, dict[str, str]], object]] = {
    ParseVerb.TEXT: parse_text,
    ParseVerb.LOWER: parse_lower,
    ParseVerb.CONSTANT: parse_constant,
    ParseVerb.INTEGER: parse_integer,
    ParseVerb.DECIMAL: parse_decimal,
    ParseVerb.DATE: parse_date,
    ParseVerb.REGEX: parse_regex,
    ParseVerb.SIGN_FROM_COLUMN: parse_sign_from_column,
}

# A verb in the enum with no implementation is an import-time failure, not a
# runtime surprise on a customer's file.
_missing = set(ParseVerb) - set(REGISTRY)
if _missing:
    raise RuntimeError(
        f"ParseVerb members with no implementation: {sorted(v.value for v in _missing)}"
    )


def apply(fm: FieldMap, row: dict[str, str]) -> object:
    """Run one field mapping against one raw row."""
    raw = "" if fm.source is None else (row.get(fm.source) or "")
    return REGISTRY[fm.parse](raw, fm, row)
