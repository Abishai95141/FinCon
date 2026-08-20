"""Journal rendering and the close gate.

Beancount is the arbiter, not a formatter we trust ourselves to satisfy: a
journal is rendered to text, loaded back through the real loader, and whatever
the loader says is the answer. An entry that does not balance and a balance
assertion that does not hold both come back as loader errors, which is exactly
the gate P1 asks for.

Balance-assertion footgun, handled here so no caller has to remember it:
beancount checks a `balance` directive **at the start of its date**, before that
day's postings. Asserting a closing balance on the period-end date would check
the balance *before* the last day's movements. `assert_closing_balance` posts
the directive on period_end + 1 day.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from beancount import loader
from beancount.core import data as bc_data

from ..contracts import Money
from .accounts import AccountRole, ChartOfAccounts

_META_KEY_RE = re.compile(r"^[a-z][a-zA-Z0-9_-]*$")


class CloseBlocked(RuntimeError):
    """The close cannot complete. Raised only by CloseResult.raise_if_blocked()
    — the result object is the normal path so a scorecard can render the block
    rather than crash on it."""


@dataclass(frozen=True)
class Posting:
    role: AccountRole
    amount: Decimal
    """Signed, in the chart's currency. Debits positive, credits negative —
    the beancount convention, so no sign flipping happens at render time."""


@dataclass(frozen=True)
class JournalEntry:
    entry_id: str
    entry_date: date
    narration: str
    postings: list[Posting]
    proof_id: str | None = None
    meta: dict[str, str] = field(default_factory=dict)

    def residual(self) -> Decimal:
        return sum((p.amount for p in self.postings), Decimal("0.00"))


@dataclass(frozen=True)
class LedgerError:
    kind: str
    message: str
    lineno: int | None = None


@dataclass(frozen=True)
class CloseResult:
    blocked: bool
    errors: list[LedgerError]
    entries_loaded: int
    text: str

    def raise_if_blocked(self) -> None:
        if self.blocked:
            detail = "; ".join(f"{e.kind}: {e.message}" for e in self.errors) or "unknown"
            raise CloseBlocked(detail)

    @property
    def error_kinds(self) -> set[str]:
        return {e.kind for e in self.errors}


def _fmt(amount: Decimal) -> str:
    return f"{amount:.2f}"


def _esc(value: str) -> str:
    """Beancount string literals are double-quoted; Python's !r would emit
    single quotes and the lexer rejects them."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def render(
    entries: list[JournalEntry],
    chart: ChartOfAccounts,
    opened_on: date,
    assertions: list[tuple[date, AccountRole, Decimal]] | None = None,
) -> str:
    """Render a journal to beancount text.

    `assertions` are (as_of_date, role, expected) and are written verbatim —
    use assert_closing_balance() rather than hand-rolling the date offset.
    """
    lines: list[str] = [f'option "operating_currency" "{chart.currency}"', ""]
    for account in chart.all_accounts():
        lines.append(f"{opened_on.isoformat()} open {account} {chart.currency}")
    lines.append("")

    for entry in sorted(entries, key=lambda e: (e.entry_date, e.entry_id)):
        narration = _esc(entry.narration)
        lines.append(f'{entry.entry_date.isoformat()} * "{narration}"')
        lines.append(f'  entry_id: "{_esc(entry.entry_id)}"')
        if entry.proof_id:
            lines.append(f'  proof_id: "{_esc(entry.proof_id)}"')
        for key, value in sorted(entry.meta.items()):
            if not _META_KEY_RE.match(key):
                raise ValueError(f"metadata key {key!r} is not a valid beancount key")
            lines.append(f'  {key}: "{_esc(str(value))}"')
        for posting in entry.postings:
            lines.append(f"  {chart[posting.role]}  {_fmt(posting.amount)} {chart.currency}")
        lines.append("")

    for as_of, role, expected in sorted(assertions or [], key=lambda a: (a[0], a[1].value)):
        lines.append(
            f"{as_of.isoformat()} balance {chart[role]}  {_fmt(expected)} {chart.currency}"
        )

    return "\n".join(lines) + "\n"


def load(text: str) -> tuple[list[bc_data.Directive], list[LedgerError]]:
    """Round-trip through the real beancount loader. Errors are the verdict."""
    entries, errors, _options = loader.load_string(text)
    return entries, [
        LedgerError(
            kind=type(err).__name__,
            message=getattr(err, "message", str(err)),
            lineno=getattr(getattr(err, "source", None) or {}, "get", lambda *_: None)("lineno"),
        )
        for err in errors
    ]


def assert_closing_balance(period_end: date, role: AccountRole, expected: Decimal):
    """Build a balance assertion that checks the balance *after* period_end.

    Beancount evaluates a balance directive at the start of its date, so the
    assertion is dated period_end + 1.
    """
    return (period_end + timedelta(days=1), role, expected)


def post_and_assert(
    entries: list[JournalEntry],
    chart: ChartOfAccounts,
    opened_on: date,
    period_end: date,
    closing_balances: dict[AccountRole, Money] | None = None,
) -> CloseResult:
    """Render, load, and report whether the close may proceed.

    Blocked when any entry fails to balance or any closing assertion does not
    hold. Nothing here warns-and-continues: a blocked close is blocked.
    """
    assertions = [
        assert_closing_balance(period_end, role, expected)
        for role, expected in sorted((closing_balances or {}).items(), key=lambda kv: kv[0].value)
    ]
    text = render(entries, chart, opened_on, assertions)
    loaded, errors = load(text)
    return CloseResult(
        blocked=bool(errors),
        errors=errors,
        entries_loaded=sum(1 for d in loaded if isinstance(d, bc_data.Transaction)),
        text=text,
    )
