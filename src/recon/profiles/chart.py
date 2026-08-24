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

from ..ledger.accounts import AccountRole, ChartOfAccounts

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
