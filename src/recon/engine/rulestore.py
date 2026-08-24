"""Where a promoted rule lives, and what applying one does to a close.

A rule was promotable and inert. `promote()` returned a `PromotedRule` with an
evidence hash and a named approver, and then nothing read it: `close()` took no
rules, and `fires_on` was reached only from the regression simulator. So the
whole gate — the regression, the generality check, the selectivity cap — decided
whether to grant a permission that was never exercised. A control over an effect
that does not happen is theatre, and it passes every test you write for it.

Two things make application honest:

**A suppressed row is disposed of, not dropped.** Suppression routes through the
same `out_of_scope` channel a caller uses, so invariant 8 still sees the row and
`audit` still refuses a blank reason. The reason names the rule.

**A match that needed a rule is `P1 RULE`, not `P0 ARITHMETIC`.** The residual
does close to zero — but only once you accept the suppression, and that is a
promoted rule's word rather than the raw records'. Claiming P0 would launder a
rule into arithmetic, which is the one thing the tier ladder exists to prevent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from ..contracts import Record
from ..contracts.rule import ActionKind, Rule, RuleStatus
from .rules import fires_on

STORE = Path(__file__).resolve().parents[3] / "data" / "rules"

#: Actions a close can actually carry out. Two lists have to agree for a rule to
#: be safe to promote: `promotion.MODELLED_ACTIONS` says the regression can
#: *measure* an action, this one says a close can *perform* it. Only the first
#: was ever checked, so `set_tolerance`, `book_to` and `normalize_key` promoted
#: on clean regressions and did nothing at all. The functions below are the
#: single implementation of each — the regression calls them too, so what is
#: measured and what happens cannot drift apart.
#:
#: Listed one by one on purpose. `frozenset(ActionKind)` was shorter and said
#: something false: it declared every action performed *by construction*, so a
#: sixth kind added to the enum would be auto-certified as implemented and the
#: guard below would never fire. Each entry names the function that carries it
#: out, and `tests/property/test_rule_application.py` fails on an entry whose
#: close-time effect cannot be observed.
APPLIED_ACTIONS = frozenset(
    {
        ActionKind.SUPPRESS,  # -> `scope`, below
        ActionKind.RAISE_ADVISORY,  # -> `tiers._advise`
        ActionKind.SET_TOLERANCE,  # -> `tolerance_for`
        ActionKind.NORMALIZE_KEY,  # -> `normalize`
        ActionKind.BOOK_TO,  # -> `booking_overrides`
    }
)


@dataclass(frozen=True)
class Advisory:
    """A rule's claim about what an exception *is*.

    `raise_advisory` sat in the action enum, was offered to the model in the
    induction prompt, and was declared modelled in `MODELLED_ACTIONS` — with no
    implementation anywhere. A rule using it regressed to `0 broken, 0 added, no
    value suppressed`, reported `unmodelled=[]`, promoted without a single
    objection, and changed nothing at all: same matches, same exceptions, same
    codes. It was the cleanest-scoring rule the gate had ever seen and it was a
    no-op, which is worse than a refusal because it looks like a success.
    """

    rule_id: str
    rule_version: int
    code: str
    records: frozenset[str]
    reason: str


@dataclass(frozen=True)
class Applied:
    """What a rule set did to one close."""

    scope: dict[str, str]
    ruled_groups: dict[str, Rule]
    unapplied: dict[str, list[str]]
    advisories: list[Advisory] = field(default_factory=list)

    @property
    def summary(self) -> str:
        parts = [f"{len(self.scope)} row(s) suppressed", f"{len(self.advisories)} advisory"]
        for rule_id, kinds in sorted(self.unapplied.items()):
            parts.append(f"{rule_id}: {'/'.join(kinds)} not applied at close")
        return "; ".join(parts)


def load(profile: str, store: Path | None = None) -> list[Rule]:
    """Promoted rules for a profile. Absent file means none — an empty rule set
    is a real state, not a missing one."""
    path = (store or STORE) / f"{profile}.json"
    if not path.exists():
        return []
    raw = json.loads(path.read_text())
    return [Rule(**entry) for entry in raw["promoted"]]


def save(promoted: list[Rule], profile: str, store: Path | None = None) -> Path:
    path = (store or STORE) / f"{profile}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"profile": profile, "promoted": [json.loads(r.model_dump_json()) for r in promoted]}
    path.write_text(json.dumps(body, indent=2) + "\n")
    return path


def apply(
    rules: list[Rule], records: list[Record], *, profile: str, simulate: bool = False
) -> Applied:
    """Work out what a rule set removes from a close, and why.

    Returns the exclusions rather than performing them, so the caller merges
    them into the one `scope` mapping the completeness audit already walks.

    `simulate` skips the status check and belongs to exactly one caller: the
    regression, whose entire question is what a rule *would* do once promoted.
    A close never passes it.
    """
    scope: dict[str, str] = {}
    ruled: dict[str, Rule] = {}
    unapplied: dict[str, list[str]] = {}
    advisories: list[Advisory] = []

    for rule in rules:
        if rule.profile != profile:
            continue
        if not simulate and (rule.status is not RuleStatus.PROMOTED or rule.revoked_at is not None):
            # Enforced where the effect happens rather than where rules are read.
            # `load()` only returns promoted rules, but a caller may hand rules
            # straight to `close()` — and the whole point of the gate is that
            # nothing acts on an unapproved one, whatever route it arrived by.
            unapplied.setdefault(rule.rule_id, []).append(f"status={rule.status.value}")
            continue
        kinds = {action.kind for action in rule.then}
        missing = sorted(k.value for k in kinds - APPLIED_ACTIONS)
        if missing:
            unapplied[rule.rule_id] = missing
        fired = frozenset(r.record_id for r in records if fires_on(rule, r))

        for action in rule.then:
            if action.kind is ActionKind.RAISE_ADVISORY and fired:
                advisories.append(
                    Advisory(
                        rule_id=rule.rule_id,
                        rule_version=rule.version,
                        code=action.target or "",
                        records=fired,
                        reason=action.reason or "",
                    )
                )

        if ActionKind.SUPPRESS not in kinds:
            continue
        reason = next(
            (a.reason for a in rule.then if a.kind is ActionKind.SUPPRESS and a.reason), ""
        )
        for record in records:
            if record.record_id in fired:
                scope[record.record_id] = f"suppressed by {rule.rule_id}: {reason}"[:300]
                if record.group_ref:
                    ruled[record.group_ref] = rule
    return Applied(scope=scope, ruled_groups=ruled, unapplied=unapplied, advisories=advisories)


def tolerance_for(rules: list[Rule], profile):
    """The matching profile a rule set asks for.

    A `set_tolerance` rule widens the budget for the whole run, which is what
    the regression has always measured — so the close applies it the same way
    rather than inventing per-record budgets the gate never saw.
    """
    from dataclasses import replace

    asked = [
        Decimal(a.amount)
        for rule in rules
        for a in rule.then
        if a.kind is ActionKind.SET_TOLERANCE and a.amount is not None
    ]
    if not asked:
        return profile
    return replace(profile, tolerance=replace(profile.tolerance, absolute=max(asked)))


def normalize(rules: list[Rule], records: list[Record]) -> list[Record]:
    """Key rewrites, applied before matching.

    Rewriting a key changes what is comparable, which changes which rows pair.
    """
    out = records
    for rule in rules:
        rewrites = [a for a in rule.then if a.kind is ActionKind.NORMALIZE_KEY]
        if not rewrites:
            continue
        hit = {r.record_id for r in out if fires_on(rule, r)}
        out = [
            r
            if r.record_id not in hit
            else r.model_copy(update={"keys": {**r.keys, **{a.target: a.value for a in rewrites}}})
            for r in out
        ]
    return out


def booking_overrides(
    rules: list[Rule], exceptions: list, records: dict[str, Record]
) -> dict[str, object]:
    """Which exceptions a `book_to` rule reroutes, and to where.

    An exception is rerouted when the rule fires on a record it names. The rule
    supplies the destination; nothing here reads model output, and the posting
    layer still cannot — it takes a plain mapping.
    """
    from ..ledger.accounts import AccountRole

    overrides: dict[str, object] = {}
    for rule in rules:
        bookings = [a for a in rule.then if a.kind is ActionKind.BOOK_TO]
        if not bookings:
            continue
        try:
            destination = AccountRole(bookings[-1].target)
        except ValueError:
            # An account role outside the chart is a spec error, not a posting.
            # The refusal is `evaluate`'s to make; here it reroutes nothing.
            continue
        for exception in exceptions:
            named = set(getattr(exception, "record_ids", []))
            if any(records.get(rid) is not None and fires_on(rule, records[rid]) for rid in named):
                overrides[exception.exception_id] = destination
    return overrides
