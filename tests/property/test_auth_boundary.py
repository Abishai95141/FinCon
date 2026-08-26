"""What a session may do, and what it may not.

Auth is the one place in this product where a bug is not a wrong number but an
open door, so the properties here are about refusal rather than about function.
The login working is asserted by the P14 gate; this file is about the ways it
must fail.

The tenant tests are the load-bearing ones. `docs/09-PRODUCT-DIRECTION.md`
promises that each account has its own records, and the way that promise breaks
is not a missing feature — it is a route that takes an id and does not check
whose it is. So one account creates a close and another asks for it by name, on
every surface that serves one.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from recon import loop as looplib
from recon.api import auth
from recon.api.app import app
from recon.api.auth import AuthError, ConfigError, LocalIdentity, User
from tests.conftest import close_and_wait, signed_in_client

LOOP = "settlement_3way"
BATCH = "A"
SECRET = b"a-test-signing-key-of-adequate-length"


# ----------------------------------------------------------------- sessions


def test_a_session_survives_a_round_trip_and_nothing_else_does():
    user = User(user_id="u-1", email="controller@acme.in")
    token = auth.issue(user, SECRET)

    assert auth.read(token, SECRET) == user
    assert auth.read(token, b"a-different-key-of-adequate-length!!") is None, "wrong key accepted"
    assert auth.read(token[:-4] + "aaaa", SECRET) is None, "tampered signature accepted"
    assert auth.read("", SECRET) is None
    assert auth.read("not-even-a-token", SECRET) is None
    assert auth.read("a.b", SECRET) is None


def test_a_forged_payload_cannot_promote_itself():
    """The attack the signature exists to stop: edit the claims, keep the shape."""
    import base64
    import json

    body = (
        base64.urlsafe_b64encode(
            json.dumps({"u": "somebody-else", "e": "x@y.z", "x": time.time() + 999}).encode()
        )
        .decode()
        .rstrip("=")
    )
    forged = f"{body}.{'A' * 43}"
    assert auth.read(forged, SECRET) is None


def test_an_expired_session_is_not_a_session():
    user = User(user_id="u-1", email="c@a.in")
    assert auth.read(auth.issue(user, SECRET, ttl=-1), SECRET) is None
    assert auth.read(auth.issue(user, SECRET, ttl=60), SECRET) == user


# ------------------------------------------------------------- credentials


def test_an_unknown_address_and_a_wrong_password_are_indistinguishable(tmp_path: Path):
    """Otherwise the login form is an account-enumeration oracle."""
    store = LocalIdentity(tmp_path / "users.json")
    store.sign_up("known@acme.in", "correct-horse-battery")

    with pytest.raises(AuthError) as wrong:
        store.sign_in("known@acme.in", "not-the-password-x")
    with pytest.raises(AuthError) as absent:
        store.sign_in("stranger@acme.in", "not-the-password-x")
    assert str(wrong.value) == str(absent.value)


def test_a_password_is_never_stored(tmp_path: Path):
    path = tmp_path / "users.json"
    LocalIdentity(path).sign_up("c@acme.in", "correct-horse-battery")
    body = path.read_text()
    assert "correct-horse-battery" not in body
    assert "salt" in body and "hash" in body


def test_a_short_password_is_refused(tmp_path: Path):
    with pytest.raises(AuthError):
        LocalIdentity(tmp_path / "users.json").sign_up("c@acme.in", "short")


def test_an_address_is_normalised_so_one_person_is_one_account(tmp_path: Path):
    store = LocalIdentity(tmp_path / "users.json")
    first = store.sign_up("  Controller@Acme.IN ", "correct-horse-battery")
    assert store.sign_in("controller@acme.in", "correct-horse-battery") == first
    with pytest.raises(AuthError):
        store.sign_up("CONTROLLER@ACME.IN", "correct-horse-battery")


# ------------------------------------------------------- refusing to start


def test_a_development_credential_store_cannot_reach_production(monkeypatch):
    """The guard that makes `LocalIdentity` safe to ship in the package.

    Checked at build time rather than at the point of use: a check on the login
    path would let the app come up healthy and fail only when someone signs in,
    by which time it is deployed.
    """
    monkeypatch.setenv("RECON_AUTH", "local")
    monkeypatch.setenv("RECON_ENV", "production")
    with pytest.raises(ConfigError) as refused:
        auth.build_identity()
    assert "development credential store" in str(refused.value)

    monkeypatch.setenv("RECON_ENV", "dev")
    assert auth.build_identity().name == "local"


def test_an_absent_session_secret_is_fatal_outside_dev(monkeypatch):
    monkeypatch.delenv("RECON_SESSION_SECRET", raising=False)
    monkeypatch.setenv("RECON_ENV", "production")
    with pytest.raises(ConfigError):
        auth.session_secret()

    monkeypatch.setenv("RECON_ENV", "dev")
    assert auth.session_secret()  # ephemeral, and logging everyone out is the point


def test_an_unknown_auth_backend_is_refused_rather_than_defaulted(monkeypatch):
    monkeypatch.setenv("RECON_AUTH", "whatever")
    with pytest.raises(ConfigError):
        auth.build_identity()


def test_cognito_refuses_to_start_without_a_pool(monkeypatch):
    """It must not fall back to the development store when misconfigured — that
    is the one failure mode that turns a deploy into an open door."""
    monkeypatch.setenv("RECON_AUTH", "cognito")
    monkeypatch.delenv("RECON_COGNITO_POOL_ID", raising=False)
    monkeypatch.delenv("RECON_COGNITO_CLIENT_ID", raising=False)
    with pytest.raises(ConfigError) as refused:
        auth.build_identity()
    assert "Refusing to start" in str(refused.value)


# --------------------------------------------------------------- the doors


def test_every_account_route_refuses_an_anonymous_caller(tmp_path, monkeypatch):
    monkeypatch.setattr(looplib, "RUNS", tmp_path / "runs")
    anon = TestClient(app, follow_redirects=False)

    for path in ("/periods", "/periods/anything", "/sources", "/settings"):
        assert anon.get(path).status_code == 303, path
        assert anon.get(path).headers["location"] == "/login"

    for path in ("/v1/runs", "/v1/runs/x", "/v1/runs/x/export", "/v1/runs/x/events"):
        assert anon.get(path).status_code == 401, path

    # And the ones that must stay open, because an auditor has no account.
    for path in ("/login", "/verify", "/v1/contracts", "/v1/loops", "/healthz", "/openapi.json"):
        assert anon.get(path).status_code == 200, path


def test_a_form_post_without_its_token_is_refused(tmp_path, monkeypatch):
    client, _, _ = signed_in_client(monkeypatch, tmp_path)
    refused = client.post("/periods/close", data={"loop": LOOP, "source_set": BATCH})
    assert refused.status_code == 403
    assert "expired" in refused.text.lower()


def test_the_session_cookie_is_not_reachable_from_a_script(tmp_path, monkeypatch):
    monkeypatch.setattr(looplib, "RUNS", tmp_path / "runs")
    monkeypatch.setenv("RECON_DEV_USERS", str(tmp_path / "users.json"))
    client = TestClient(app, follow_redirects=False)
    csrf = re.search(r"name='csrf' value='([^']*)'", client.get("/login?create=1").text).group(1)
    payload = {"email": "c@acme.in", "password": "correct-horse-battery", "csrf": csrf}
    client.post("/signup", data=payload)
    reply = client.post("/login", data=payload)

    # The *session* cookie by name. Reading `headers["set-cookie"]` takes
    # whichever one came last, and once the auth pages started refreshing the
    # CSRF cookie that stopped being the one this test is about — it passed or
    # failed on the wrong header.
    session = [
        value
        for key, value in reply.headers.raw
        if key.lower() == b"set-cookie" and value.decode().startswith(auth.SESSION_COOKIE)
    ]
    assert session, f"no {auth.SESSION_COOKIE} cookie was set at all"
    header = session[0].decode().lower()
    assert "httponly" in header, "the session cookie is readable by a script"
    assert "samesite=lax" in header, "the session cookie rides a cross-site post"


# --------------------------------------------------------------- isolation


def test_one_account_cannot_read_another_accounts_close(tmp_path, monkeypatch):
    """The promise the login exists to keep.

    Not a missing feature when it breaks — a route that takes a run id and does
    not check whose it is. So the second account asks for the first's run *by
    name*, which is exactly what an attacker would do.
    """
    alice, alice_id, _ = signed_in_client(monkeypatch, tmp_path / "a", email="alice@acme.in")
    page = close_and_wait(alice, loop=LOOP, source_set=BATCH)
    run_id = str(page.url).rsplit("/", 1)[-1]
    assert alice.get(f"/v1/runs/{run_id}").status_code == 200

    bob, bob_id, _ = signed_in_client(monkeypatch, tmp_path / "b", email="bob@acme.in")
    assert bob_id != alice_id

    assert bob.get(f"/v1/runs/{run_id}").status_code == 422, "bob read alice's close"
    assert bob.get(f"/v1/runs/{run_id}/export").status_code == 422
    assert bob.get(f"/v1/runs/{run_id}/events").status_code == 422
    assert bob.get("/v1/runs").json() == [], "bob's run list is not his own"
    assert run_id not in bob.get("/periods").text


def test_a_tenant_is_not_a_parameter(tmp_path, monkeypatch):
    """Every finding in the control-plane audit reduces to "the caller supplied
    its own permission". Identity is the same shape: a route that accepted a
    tenant would let a caller name someone else's."""
    client, _, _ = signed_in_client(monkeypatch, tmp_path)
    spec = client.get("/openapi.json").json()
    banned = {"tenant", "user", "user_id", "account", "owner", "runs_dir", "workspace"}
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            names = {p["name"] for p in op.get("parameters", [])}
            assert not (banned & names), f"{method.upper()} {path} takes {sorted(banned & names)}"


def _form(client: TestClient, **fields) -> dict:
    return {**fields, "csrf": client.cookies.get(auth.CSRF_COOKIE, "")}
