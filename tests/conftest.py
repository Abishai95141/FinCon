"""Which tests need a live model, derived rather than declared.

The P12 gates are excluded from `make test` by filename because they can call
DeepSeek and CLAUDE.md rule 1 forbids an offline mode. Excluding the *file*
excluded everything in it — including assertions that never touch a model: the
closed parse vocabulary, the producer table, the AST guard keeping model text
out of the posting layer. Those only ran when someone had a key and chose to
pay, and four of them were quietly stale by 2026-08-24, one of them a security
assertion about ADR-001.

So the split is computed, not written down. A test is `live` if it constructs a
`ModelEdge` — in its own body, or in any fixture it pulls in. The first version
of this file keyed on a fixture named `edge`, which is exactly the hand-kept
list it was meant to replace: `gate_p12c` builds its edge inside `authored` and
was mis-marked immediately.
"""

from __future__ import annotations

import inspect

import pytest

#: What the model edge is called at its construction site. A test or fixture
#: whose source names it reaches a real model when it runs.
EDGE = "ModelEdge"


def _reaches_model(func) -> bool:
    try:
        return EDGE in inspect.getsource(func)
    except (OSError, TypeError):
        return False


def pytest_collection_modifyitems(items):
    for item in items:
        sources = [getattr(item, "function", None)]
        for defs in getattr(item, "_fixtureinfo", None).name2fixturedefs.values():
            sources.extend(d.func for d in defs)
        if any(f is not None and _reaches_model(f) for f in sources):
            item.add_marker(pytest.mark.live)


def pytest_configure(config):
    config.addinivalue_line("markers", "live: reaches a real model; needs DEEPSEEK_API_KEY")


# --------------------------------------------------------------------------
# building a genuinely promoted rule
# --------------------------------------------------------------------------


def promoted(rule, *, actor: str = "test-approver", policy_ref: str = "settlement-in@v1"):
    """A rule with a real `PromotionEvent` on it.

    Tests used to reach `PROMOTED` with `model_copy(update={"status": ...})`,
    which **bypasses pydantic validators** — so they produced rules the contract
    forbids: promoted, and named by nobody. That went unnoticed for as long as
    `rulestore.apply` looked only at `status`; the moment a close began checking
    the approval itself, sixteen tests turned red at once and every one of them
    was right to.

    The event here is synthetic and says so. It is not evidence that anything was
    regressed — `recon.engine.promotion.promote` is the only thing that produces
    a real one. What it does is let a test exercise an admissible rule without
    quietly asserting that an inadmissible one is fine.
    """
    from datetime import UTC, datetime

    from recon.contracts.rule import PromotionEvent, RuleStatus

    return rule.model_copy(
        update={
            "status": RuleStatus.PROMOTED,
            "promotion": PromotionEvent(
                promoted_by=actor,
                promoted_at=datetime(2026, 8, 25, tzinfo=UTC),
                policy_ref=policy_ref,
                evidence_hash="synthetic-fixture-not-a-regression",
                matches_checked=0,
                matches_broken=0,
                matches_added=0,
                exceptions_cleared=0,
                sample_added=[],
            ),
        }
    )


# --------------------------------------------------------------------------
# an authenticated browser, and the tenant it writes into
# --------------------------------------------------------------------------


def signed_in_client(
    monkeypatch, tmp_path, *, email: str = "controller@acme.in", sample: bool = True
):
    """A `TestClient` with a real session, and the runs directory it will use.

    Real in the sense that matters: the account is created through the login
    form, the cookie is the one the server signed, and every subsequent request
    carries it. A test that forged a session cookie would be testing its own
    forgery rather than the login.

    Returns `(client, user_id, runs_root)`. `runs_root` is where this account's
    closes land — `service.runs_root(None) / user_id` — which is what makes
    tenant isolation checkable rather than asserted.
    """
    import re

    from fastapi.testclient import TestClient

    from recon import loop as looplib
    from recon import service
    from recon.api.app import app as fastapi_app

    monkeypatch.setenv("RECON_ENV", "dev")
    monkeypatch.setenv("RECON_AUTH", "local")
    monkeypatch.setenv("RECON_DEV_USERS", str(tmp_path / "users.json"))
    monkeypatch.setattr(looplib, "RUNS", tmp_path / "runs")
    # A tenant's own files go to the sandbox so a test never writes into the
    # repository. `BATCH_ROOT` is left alone — those are the read-only shipped
    # examples, and MCP and the benchmark both read them directly.
    monkeypatch.setattr(service, "TENANT_SOURCES", tmp_path / "sources")

    client = TestClient(fastapi_app, follow_redirects=True)
    page = client.get("/login")
    csrf = re.search(r"name='csrf' value='([^']*)'", page.text).group(1)
    reply = client.post(
        "/login",
        data={"email": email, "password": "reconcile-october-2026", "csrf": csrf},
    )
    assert reply.status_code == 200 and "/periods" in str(reply.url), reply.text[:400]

    from recon.api import auth

    user = auth.read(client.cookies[auth.SESSION_COOKIE], auth.session_secret())
    assert user is not None, "the login set a cookie this server cannot read back"

    if sample:
        # The first thing a real account does. Source files are per-tenant now, so
        # a fresh account genuinely has nothing to close — a fixture that reached
        # into the shared batches would be testing a path no user has.
        loaded = client.post("/sources/sample", data={"csrf": client.cookies[auth.CSRF_COOKIE]})
        assert loaded.status_code == 200, loaded.text[:300]
    return client, user.user_id, (tmp_path / "runs" / user.user_id)
