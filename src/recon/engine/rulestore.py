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
from pathlib import Path

from ..contracts import Record
from ..contracts.rule import ActionKind, Rule, RuleStatus
from .rules import fires_on

STORE = Path(__file__).resolve().parents[3] / "data" / "rules"

#: Actions this module knows how to carry out during a close. An action outside
#: it is reported by name and changes nothing — the `unmodelled` discipline from
#: the regression gate, on the other side of promotion. A rule silently doing
#: nothing is indistinguishable from a rule working.
APPLIED_ACTIONS = frozenset({ActionKind.SUPPRESS})


class Applied:
    """What a rule set did to one close."""

    def __init__(
        self,
        scope: dict[str, str],
        ruled_groups: dict[str, Rule],
        unapplied: dict[str, list[str]],
    ) -> None:
        self.scope = scope
        self.ruled_groups = ruled_groups
        self.unapplied = unapplied

    @property
    def summary(self) -> str:
        parts = [f"{len(self.scope)} row(s) suppressed"]
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


def apply(rules: list[Rule], records: list[Record], *, profile: str) -> Applied:
    """Work out what a rule set removes from a close, and why.

    Returns the exclusions rather than performing them, so the caller merges
    them into the one `scope` mapping the completeness audit already walks.
    """
    scope: dict[str, str] = {}
    ruled: dict[str, Rule] = {}
    unapplied: dict[str, list[str]] = {}

    for rule in rules:
        if rule.profile != profile:
            continue
        if rule.status is not RuleStatus.PROMOTED or rule.revoked_at is not None:
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
        if ActionKind.SUPPRESS not in kinds:
            continue
        reason = next(
            (a.reason for a in rule.then if a.kind is ActionKind.SUPPRESS and a.reason), ""
        )
        for record in records:
            if fires_on(rule, record):
                scope[record.record_id] = f"suppressed by {rule.rule_id}: {reason}"[:300]
                if record.group_ref:
                    ruled[record.group_ref] = rule
    return Applied(scope=scope, ruled_groups=ruled, unapplied=unapplied)
