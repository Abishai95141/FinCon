"""Sign in, create account, and the screen that lets somebody finish.

`auth.confirm` and `auth.resend` were implemented, granted in IAM, and
referenced nowhere in `ui.py` — so a new account was told "Confirm your email to
finish signing in" by a form that offered no way to do it. That is the defect
this codebase keeps finding, sitting in front of every new user.

The other half is a trade rather than a bug. One form used to decide sign-in or
sign-up from whether the address existed, which meant the failure text was
identical either way and the screen could not be used to find out who has an
account. Splitting the tabs costs exactly that, on the signup path only, because
create-account has to say "this address already has an account" or somebody who
typo'd is told it worked and then cannot sign in.

So these test both halves of that: that sign-in still says nothing, and that the
thing signup does say is bounded rather than free.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from recon.api import auth, throttle
from recon.api.app import app


@pytest.fixture
def client(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RECON_ENV", "dev")
    monkeypatch.setenv("RECON_AUTH", "local")
    monkeypatch.setenv("RECON_DEV_USERS", str(tmp_path / "users.json"))
    monkeypatch.setenv("RECON_RUNS_ROOT", str(tmp_path / "runs"))
    with TestClient(app, follow_redirects=False) as c:
        yield c


def _csrf(client: TestClient, path: str = "/login") -> str:
    body = client.get(path).text
    match = re.search(r"name='csrf' value='([^']*)'", body)
    assert match, f"{path} rendered no csrf field"
    return match.group(1)


# ------------------------------------------------------------- two named things


def test_the_two_modes_are_separate_urls_not_a_toggle(client):
    """Each is a destination, so the back button behaves and a link can point at
    the right one. A toggle would have been one screen pretending to be two."""
    signin = client.get("/login").text
    create = client.get("/login?create=1").text

    assert "action='/login'" in signin and "action='/signup'" not in signin
    assert "action='/signup'" in create and "action='/login'" not in create

    assert "Sign in" in signin and "Create your account" in create
    assert "tab-on' href='/login'" in signin
    assert "tab-on' href='/login?create=1'" in create

    # Each screen offers the other. A person on the wrong one must not be stuck.
    assert "/login?create=1" in signin
    assert "href='/login'" in create


def test_the_password_field_tells_the_browser_which_mode_it_is(client):
    """`current-password` on sign-in and `new-password` on create. Wrong and a
    password manager offers to fill a new account with an old credential, or
    offers to save an existing one as new."""
    assert "autocomplete='current-password'" in client.get("/login").text
    assert "autocomplete='new-password'" in client.get("/login?create=1").text


# ------------------------------------------------ sign-in still says nothing


def test_sign_in_cannot_be_used_to_find_out_who_has_an_account(client):
    """The property the merged form had, kept. Splitting the tabs costs it once
    on signup; it must not cost it twice."""
    token = _csrf(client)
    client.post(
        "/signup",
        data={"email": "real@acme.in", "password": "reconcile-october-2026", "csrf": token},
    )

    unknown = client.post(
        "/login",
        data={"email": "nobody@acme.in", "password": "reconcile-october-2026", "csrf": token},
    )
    wrong = client.post(
        "/login",
        data={"email": "real@acme.in", "password": "not-the-password-2026", "csrf": token},
    )

    assert unknown.status_code == wrong.status_code == 400

    def message(response) -> str:
        found = re.search(r"<div class='alert'>([^<]*)</div>", response.text)
        return found.group(1) if found else ""

    assert message(unknown), "sign-in failed with no message at all"
    assert message(unknown) == message(wrong), (
        f"the two failures are distinguishable: {message(unknown)!r} vs {message(wrong)!r}"
    )


# --------------------------------------------------- the leak, and its bound


def test_signup_says_the_address_is_taken(client):
    """The accepted leak, asserted so nobody removes it by accident and leaves
    somebody unable to explain why their account does not work."""
    token = _csrf(client, "/login?create=1")
    payload = {"email": "taken@acme.in", "password": "reconcile-october-2026", "csrf": token}

    first = client.post("/signup", data=payload)
    assert first.status_code in (303, 200)

    again = client.post("/signup", data=payload)
    assert again.status_code == 400
    assert "already" in again.text.lower()


def test_the_leak_is_bounded_rather_than_free(client):
    """Walking a list is the attack, and this is the only thing standing in its
    way. Five per window: a person creating one account never notices, and a
    thousand addresses take a fortnight per source address."""
    token = _csrf(client, "/login?create=1")

    statuses = [
        client.post(
            "/signup",
            data={
                "email": f"probe{i}@acme.in",
                "password": "reconcile-october-2026",
                "csrf": token,
            },
        ).status_code
        for i in range(throttle.SIGNUP.per_window + 3)
    ]

    assert 429 in statuses, (
        f"{len(statuses)} signup attempts from one address and none refused — "
        f"the enumeration oracle is unbounded"
    )
    assert statuses.index(429) <= throttle.SIGNUP.per_window + 1


def test_the_bound_counts_the_caller_not_the_address_being_asked_about(client):
    """Keyed on the email, one attacker walks a list at full speed by never
    repeating a value — which is exactly the attack."""
    import inspect

    source = inspect.getsource(throttle.Throttle.check)
    assert "email" not in source

    throttle.THROTTLE.check("signup", "1.2.3.4", throttle.SIGNUP)
    before = dict(throttle.THROTTLE._buckets)
    assert list(before) == [("signup", "1.2.3.4")]


def test_a_successful_sign_in_clears_the_caller(client):
    """Somebody who mistypes twice and then succeeds should not be two steps from
    a lockout for the rest of the window."""
    token = _csrf(client, "/login?create=1")
    client.post(
        "/signup",
        data={"email": "ok@acme.in", "password": "reconcile-october-2026", "csrf": token},
    )
    for _ in range(3):
        client.post(
            "/login", data={"email": "ok@acme.in", "password": "wrong-one-2026", "csrf": token}
        )

    good = client.post(
        "/login",
        data={"email": "ok@acme.in", "password": "reconcile-october-2026", "csrf": token},
    )
    assert good.status_code == 303
    assert ("signin", throttle.caller_of.__name__) not in throttle.THROTTLE._buckets
    assert not [k for k in throttle.THROTTLE._buckets if k[0] == "signin"]


# ------------------------------------------------------- the screen that was missing


def test_an_unconfirmed_account_is_taken_to_the_code(client, monkeypatch):
    """The bug. `NeedsConfirmation` was raised, `ui.py` referenced it nowhere,
    and the message arrived as a dead end."""

    class Stub:
        name, managed = "stub", True

        def sign_in(self, email, password):
            raise auth.NeedsConfirmation("Confirm your email to finish signing in.")

        def sign_up(self, email, password):
            raise AssertionError("sign-in must not create an account")

        def exists(self, email):
            return True

        def confirm(self, email, code):
            pass

        def resend(self, email):
            pass

    monkeypatch.setattr(auth, "build_identity", lambda: Stub())
    token = _csrf(client)
    response = client.post(
        "/login",
        data={"email": "new@acme.in", "password": "reconcile-october-2026", "csrf": token},
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/confirm")
    assert "new%40acme.in" in response.headers["location"]

    page = client.get("/confirm?email=new@acme.in").text
    assert "name='code'" in page, "the confirm screen has no field to type a code into"
    assert "/confirm/resend" in page, "no way to get another code"
    assert "new@acme.in" in page, "the screen does not say where the code went"


def test_confirming_uses_the_identity_and_sends_them_back_to_sign_in(client, monkeypatch):
    seen = {}

    class Stub:
        name, managed = "stub", True

        def sign_in(self, email, password):
            raise AssertionError

        def sign_up(self, email, password):
            raise AssertionError

        def exists(self, email):
            return True

        def confirm(self, email, code):
            seen["confirm"] = (email, code)

        def resend(self, email):
            seen["resend"] = email

    monkeypatch.setattr(auth, "build_identity", lambda: Stub())
    token = _csrf(client, "/confirm?email=new@acme.in")

    done = client.post("/confirm", data={"email": "new@acme.in", "code": "123456", "csrf": token})
    assert seen["confirm"] == ("new@acme.in", "123456")
    assert done.status_code == 200
    assert "confirmed" in done.text.lower()
    assert "action='/login'" in done.text, "confirmed and then offered no way in"

    again = client.post("/confirm/resend", data={"email": "new@acme.in", "csrf": token})
    assert seen["resend"] == "new@acme.in"
    assert again.status_code == 200


def test_the_password_is_not_carried_through_the_confirm_screen(client):
    """One step saved is not worth a password in a browser's history and a
    proxy's access log."""
    page = client.get("/confirm?email=new@acme.in").text
    assert "type='password'" not in page
    assert "name='password'" not in page


def test_guessing_a_six_digit_code_is_bounded(client, monkeypatch):
    class Stub:
        name, managed = "stub", True

        def sign_in(self, email, password):
            raise AssertionError

        def sign_up(self, email, password):
            raise AssertionError

        def exists(self, email):
            return True

        def confirm(self, email, code):
            raise auth.AuthError("That code is not right.")

        def resend(self, email):
            pass

    monkeypatch.setattr(auth, "build_identity", lambda: Stub())
    token = _csrf(client, "/confirm?email=new@acme.in")

    statuses = [
        client.post(
            "/confirm",
            data={"email": "new@acme.in", "code": f"{i:06d}", "csrf": token},
        ).status_code
        for i in range(throttle.CONFIRM.per_window + 3)
    ]
    assert 429 in statuses, "a six-digit code can be guessed as fast as HTTP allows"


def test_resending_is_counted_against_the_same_bound(client, monkeypatch):
    """An unbounded resend is a way to make somebody else's inbox unusable, and
    the pool's own allowance is fifty a day."""
    import inspect

    from recon.api import ui

    source = inspect.getsource(ui.confirm_resend)
    assert '"confirm"' in source, "resend has a bucket of its own, so the two do not add up"


# -------------------------------------------------------------- honest limits


def test_the_throttle_does_not_claim_to_be_shared():
    """It is per-process and resets on deploy. With one task that is the whole
    system; with two it is half a bound, and a surface reporting otherwise would
    be overstating a control."""
    state = throttle.THROTTLE.state()
    assert state["shared_across_tasks"] is False
    assert state["scope"] == "this process"


def test_a_first_time_visitor_can_submit_the_very_first_form(client):
    """The bug this file's fixtures could not see.

    The page minted a token and the cookie got a *different* one, because
    `new_csrf()` was called twice for one render. Every other test in this repo
    starts from a client that already holds a cookie, so the only person who ever
    hit it was somebody arriving at FinCon for the first time — which is every
    real new user and no test.

    Then the fix had its own version: the auth pages are f-strings, so a
    `{{csrf}}` placeholder renders as the literal `{csrf}` and the token still
    never lands.
    """
    from recon.api.ui import CSRF_SLOT

    for path in ("/login", "/login?create=1", "/confirm?email=new@acme.in"):
        fresh = TestClient(app, follow_redirects=False)
        body = fresh.get(path).text

        assert CSRF_SLOT not in body, f"{path} rendered the placeholder itself"
        assert "{csrf}" not in body, f"{path} rendered an f-string-escaped brace"

        token = re.search(r"name='csrf' value='([^']*)'", body).group(1)
        assert token, f"{path} rendered an empty token"
        assert token == fresh.cookies.get(auth.CSRF_COOKIE), (
            f"{path} put one token in the form and another in the cookie, so the "
            f"first submit by a first-time visitor is a 403"
        )
