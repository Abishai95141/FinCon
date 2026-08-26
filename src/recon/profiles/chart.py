"""Loading a chart of accounts from a profile asset.

`SETTLEMENT_CHART` sat in `ledger/accounts.py` from P1 until now, with
`Assets:Bank:HDFC` written into kernel code. Invariant 7 says the engine is
domain-agnostic and anything domain-specific belongs in a profile; the file's own
docstring admitted it and deferred the move. Three phases cited that docstring
and none moved it, which is the same failure as the known-broken table: a claim
recorded is not a claim enforced.

The engine keeps the *vocabulary* — `AccountRole` — and the *shape* —
`ChartOfAccounts`. Which account a role maps to is one company's fact and lives
in `data/profiles/`, loaded like the policy and the taxonomy, and pinned by
digest in the decision log for the same reason they are.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from ..ledger.accounts import AccountRole, ChartOfAccounts

if TYPE_CHECKING:
    from ..engine.diagnose import DiagnosisRules

PROFILE_DIR = Path("data/profiles")


class ProfileError(ValueError):
    """The profile asset is missing or does not describe a usable chart.

    Raised rather than defaulted. A chart that silently falls back to something
    is a chart that posts one company's money into another's accounts.
    """


def load_chart(profile: str, directory: Path | None = None) -> ChartOfAccounts:
    path = (directory or PROFILE_DIR) / f"{profile}.json"
    if not path.exists():
        raise ProfileError(f"no chart for profile {profile!r} at {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    try:
        accounts = {AccountRole(role): name for role, name in raw["accounts"].items()}
    except (KeyError, ValueError) as exc:
        raise ProfileError(f"{path}: {exc}") from exc
    if not raw.get("currency"):
        raise ProfileError(
            f"{path} declares no currency. A chart without one would take whatever "
            f"the engine happened to default to, which is how a USD source gets "
            f"posted as INR."
        )
    return ChartOfAccounts(currency=raw["currency"], accounts=accounts)


def load_diagnosis(profile: str, directory: Path | None = None) -> DiagnosisRules | None:
    """How a loop reads its own near misses, from its profile file.

    Loaded rather than written in Python for the reason `codes.json` exists: a
    fact about a code belongs in `data/`, and an AST guard in
    `tests/property/test_metamorphic.py` fails on a code-id literal anywhere
    else. P12 wrote two frozensets of them back into code one phase after that
    rule was made, in two modules — the guard is what stops the third time.

    `None` when a profile declares none, which is correct for a loop keyed on a
    single reference: there are no parts for a near miss to differ on.
    """
    from ..engine.diagnose import DiagnosisRules

    path = (directory or PROFILE_DIR) / f"{profile}.json"
    if not path.exists():
        raise ProfileError(f"no profile at {path}")
    raw = json.loads(path.read_text(encoding="utf-8")).get("diagnosis")
    if not raw:
        return None

    try:
        return DiagnosisRules(
            by_difference={
                frozenset(part.split("+")): code for part, code in raw["by_difference"].items()
            },
            by_absence={side: tuple(codes) for side, codes in raw["by_absence"].items()},
            absence_reason=raw.get("absence_reason", ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProfileError(f"{path}: diagnosis is malformed — {exc}") from exc
