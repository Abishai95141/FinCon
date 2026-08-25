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

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
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
class RuleEffect:
    """What one promoted rule actually did to one close.

    Recorded as it happens rather than derived by differencing two closes: a
    close cannot run itself twice, and a fact the run observes about itself is
    cheaper and harder to fake than one reconstructed afterwards.

    `observable` is the whole point. Four action kinds could be promoted and do
    nothing, and `raise_advisory` was declared modelled while implemented
    nowhere — a rule using it outscored every real rule by being inert on every
    dimension. A permission granted for an effect nobody measures is the shape
    this project keeps rediscovering, so the close now measures it.
    """

    rule_id: str
    rule_version: int
    fired: int
    suppressed: int = 0
    advisories_applied: int = 0
    keys_normalized: int = 0
    postings_redirected: int = 0
    tolerance_widened: bool = False
    unapplied: tuple[str, ...] = ()

    @property
    def observable(self) -> bool:
        """Whether this rule changed anything a human could point at."""
        return bool(
            self.suppressed
            or self.advisories_applied
            or self.keys_normalized
            or self.postings_redirected
            or self.tolerance_widened
        )

    def summary(self) -> str:
        if not self.fired:
            return f"{self.rule_id}: fired on nothing"
        moved = [
            f"{n} {name}"
            for n, name in (
                (self.suppressed, "suppressed"),
                (self.advisories_applied, "re-coded"),
                (self.keys_normalized, "normalised"),
                (self.postings_redirected, "re-booked"),
            )
            if n
        ]
        if self.tolerance_widened:
            moved.append("tolerance widened")
        tail = ", ".join(moved) if moved else "NO OBSERVABLE EFFECT"
        note = f" ({'/'.join(self.unapplied)} not applied)" if self.unapplied else ""
        return f"{self.rule_id}: fired on {self.fired} row(s) -> {tail}{note}"


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
    effects: dict[str, RuleEffect] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        parts = [f"{len(self.scope)} row(s) suppressed", f"{len(self.advisories)} advisory"]
        for rule_id, kinds in sorted(self.unapplied.items()):
            parts.append(f"{rule_id}: {'/'.join(kinds)} not applied at close")
        return "; ".join(parts)


def bundle_digest(rules: list[Rule]) -> str:
    """Which promoted rule set was active, as one stable id.

    A decision that names the bundle that produced it is the shape OPA's
    decision log uses: a year later you can fetch the same rules instead of
    taking a proof's word for what a rule id meant at the time.
    """
    if not rules:
        return "empty"
    body = json.dumps(sorted(r.model_dump_json() for r in rules), sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()[:16]


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
    effects: dict[str, RuleEffect] = {}

    for rule in rules:
        if rule.profile != profile:
            continue
        if not simulate and (rule.status is not RuleStatus.PROMOTED or rule.revoked_at is not None):
            # Enforced where the effect happens rather than where rules are read.
            # `load()` only returns promoted rules, but a caller may hand rules
            # straight to `close()` — and the whole point of the gate is that
            # nothing acts on an unapproved one, whatever route it arrived by.
            unapplied.setdefault(rule.rule_id, []).append(f"status={rule.status.value}")
            effects[rule.rule_id] = RuleEffect(
                rule_id=rule.rule_id,
                rule_version=rule.version,
                fired=0,
                unapplied=tuple(unapplied[rule.rule_id]),
            )
            continue
        kinds = {action.kind for action in rule.then}
        missing = sorted(k.value for k in kinds - APPLIED_ACTIONS)
        if missing:
            unapplied[rule.rule_id] = missing
        fired = frozenset(r.record_id for r in records if fires_on(rule, r))
        effects[rule.rule_id] = RuleEffect(
            rule_id=rule.rule_id,
            rule_version=rule.version,
            fired=len(fired),
            keys_normalized=len(fired) if ActionKind.NORMALIZE_KEY in kinds else 0,
            tolerance_widened=any(
                a.kind is ActionKind.SET_TOLERANCE and a.amount is not None for a in rule.then
            ),
            unapplied=tuple(missing),
        )

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
        effects[rule.rule_id] = replace(
            effects[rule.rule_id],
            suppressed=sum(1 for r in records if r.record_id in fired),
        )
    return Applied(
        scope=scope,
        ruled_groups=ruled,
        unapplied=unapplied,
        advisories=advisories,
        effects=effects,
    )


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


def inert_across(closes: Iterable[Iterable[RuleEffect]]) -> dict[str, int]:
    """Rules that moved nothing in *every* close they were offered.

    The per-close finding is deliberately not a refusal: a rule can be honestly
    inert on one batch, the way a duplicate-suppression rule is on a batch with
    no duplicates. What is never honest is a rule that has been promoted, has
    run, and has never once moved anything — that is a permission granted for an
    effect that does not exist, which is the failure this project keeps
    rediscovering.

    Returns rule id -> how many closes it was inert in. A rule absent from the
    result moved something at least once. Judging *how many* is policy's, not
    this function's: the arithmetic is here and the bar is elsewhere.
    """
    seen: dict[str, int] = {}
    moved: set[str] = set()
    for effects in closes:
        for effect in effects:
            seen[effect.rule_id] = seen.get(effect.rule_id, 0) + 1
            if effect.observable:
                moved.add(effect.rule_id)
    return {rid: n for rid, n in sorted(seen.items()) if rid not in moved}
