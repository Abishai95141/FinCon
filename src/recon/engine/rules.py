"""Predicate evaluation over records. The interpreter half of ADR-001.

A rule is data a model may author, so nothing here compiles, imports or
evaluates anything. A predicate is a `(field, op, value)` triple; the field
vocabulary is closed and resolved by a lookup table, and an operator outside the
enum is unreachable because the contract rejects it before this module sees it.

Regex is the one place a model could hand us something expensive, so
`MATCHES` is anchored and the pattern length is capped by the contract (200
chars). An unanchored `(a+)+$` against a long string is a denial of service, not
a clever rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from ..contracts import Record
from ..contracts.rule import Operator, Predicate, Rule

#: Closed field vocabulary. A field outside this map is a spec error, not an
#: attribute lookup — `getattr(record, field)` would let a proposal reach
#: anything a Record happens to expose, now or after a future refactor.
FIELDS: dict[str, callable] = {
    "record_id": lambda r: r.record_id,
    "side": lambda r: r.side,
    "source": lambda r: r.source,
    "group_ref": lambda r: r.group_ref or "",
    "source_row_id": lambda r: r.source_row_id or "",
    "amount": lambda r: r.amount,
    "currency": lambda r: r.currency,
    "posted_on": lambda r: r.posted_on.isoformat(),
    # Partition-relative. `key_occurrence` is `row_number() over (partition by
    # natural_key)`, computed once at intake where the whole source is in hand
    # and carried as a per-record fact — so a rule can ask about duplication
    # with a *unary* predicate and the aggregation never happens at rule time.
    #
    # This is the production that closes the hole. "Suppress the duplicated
    # row" was previously expressible only by naming the row, because nothing
    # in the vocabulary could say "another row already asserted this". It was
    # maximally general — it names no row, holds of any batch, transfers to a
    # second loop unchanged — and it was unsayable. Two constraints on
    # different axes (arity, and generality) were being enforced as one.
    "key_occurrence": lambda r: r.key_occurrence,
    "natural_key": lambda r: r.natural_key,
}

MAX_SUBJECT = 500
"""Regex is applied to at most this many characters. A cap the proposer cannot
raise is the difference between a slow rule and an outage."""


class RuleError(ValueError):
    """A rule referenced something outside the closed vocabulary."""


def resolve_field(record: Record, field: str):
    """`keys.x` reads a match key; anything else must be a named field."""
    if field.startswith("keys."):
        return record.keys.get(field[5:], "")
    try:
        return FIELDS[field](record)
    except KeyError:
        raise RuleError(
            f"{field!r} is not a rule field. Known: {sorted(FIELDS)} or keys.<name>"
        ) from None


def _as_decimal(value) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def matches(predicate: Predicate, record: Record) -> bool:
    actual = resolve_field(record, predicate.field)
    expected = predicate.value

    if predicate.op is Operator.IN:
        return str(actual) in {str(v) for v in expected}
    if predicate.op is Operator.MATCHES:
        # Full match, deliberately: an unanchored pattern matches far more than
        # its author intended, and "it worked on the sample" is how a suppress
        # rule quietly eats a ledger.
        #
        # `fullmatch`, not `re.match(f"(?:{p})$")`. The wrapped form turned an
        # author's `^pout_` into `(?:^pout_)$`, which can never match anything —
        # so a rule reading perfectly fired on *nothing*, on the very batch it
        # was induced from, while its regression reported no broken matches and
        # looked entirely safe. Found at P12 when every model-authored pattern
        # using `^` silently selected zero rows.
        #
        # Under `fullmatch` an author's own `^`/`$` are harmless, so nothing
        # strips them: a mutation proved that branch was never load-bearing, and
        # defensive code no test can distinguish is code that rots.
        return re.fullmatch(str(expected).strip(), str(actual)[:MAX_SUBJECT]) is not None
    if predicate.op is Operator.EQ:
        return str(actual) == str(expected)
    if predicate.op is Operator.NEQ:
        return str(actual) != str(expected)

    left, right = _as_decimal(actual), _as_decimal(expected)
    if left is None or right is None:
        # A numeric comparison against something that is not a number is False,
        # not an exception: one unorderable row must not stop a close.
        return False
    return {
        Operator.GT: left > right,
        Operator.GTE: left >= right,
        Operator.LT: left < right,
        Operator.LTE: left <= right,
    }[predicate.op]


def fires_on(rule: Rule, record: Record) -> bool:
    """All predicates must hold. `when` is never empty — the contract refuses a
    rule with no conditions, because it would match everything."""
    return all(matches(p, record) for p in rule.when)


@dataclass(frozen=True)
class Selection:
    matched: list[str]

    @property
    def count(self) -> int:
        return len(self.matched)


def select(rule: Rule, records: list[Record]) -> Selection:
    return Selection(matched=[r.record_id for r in records if fires_on(rule, r)])
