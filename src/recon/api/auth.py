"""Identity and sessions for the surface. Not for the kernel.

`close.py`, `engine/` and `journal/` know nothing about users, and must not: a
reconciliation is true or false regardless of who asked for it. What identity
decides is *whose records* — a storage prefix — and that is a surface concern.

The split, which is the whole design:

* **Credentials live in Cognito.** Hashing, lockout, password policy, recovery
  and later MFA are not things a governance product should hand-roll.
* **The session is ours.** Cognito returns tokens; the server exchanges them for
  its own signed `HttpOnly; Secure; SameSite=Lax` cookie and no JWT ever reaches
  the browser. The app is server-rendered and ships no JavaScript, so there is
  nothing in the page that could hold a token safely anyway.
* **A tenant is resolved from the session, never from the request.** There is no
  parameter through which a caller can name someone else's data — the same rule
  the rest of this surface follows for authority, applied to identity.

`LocalIdentity` exists so the suite and a laptop can run with no AWS. It is a
real credential store — scrypt, per-user salt, constant-time compare — not a
stub. What makes it safe is that the app **refuses to start with it** unless
`RECON_ENV=dev`, and every page it serves carries a banner saying so. A dev
backend that could silently reach production would be the shallow proxy this
codebase exists to avoid.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

SESSION_COOKIE = "fincon_session"
CSRF_COOKIE = "fincon_csrf"
SESSION_TTL = 12 * 60 * 60
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


class AuthError(Exception):
    """A credential problem, phrased for a human and safe to show them.

    Deliberately one exception for "no such account" and "wrong password": the
    two must be indistinguishable to a caller, or the login form becomes an
    account-enumeration oracle.
    """


class ConfigError(RuntimeError):
    """The deployment is not safe to start. Raised at import of the app rather
    than on the first request, so a misconfiguration fails a deploy instead of
    surfacing as a 500 to whoever logs in first."""


@dataclass(frozen=True)
class User:
    user_id: str
    """Opaque and stable. Cognito's `sub`, or a uuid4 locally. Never the email —
    an address changes, and a tenant prefix that changes orphans a tenant."""

    email: str

    @property
    def initials(self) -> str:
        head = self.email.split("@")[0]
        parts = [p for p in head.replace(".", " ").replace("_", " ").split() if p]
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        return (parts[0][:2] if parts else head[:2] or "?").upper()


class NeedsConfirmation(AuthError):
    """The account exists and its email has not been confirmed yet.

    A subclass rather than a message, because the surface has to *do* something
    different: show the code form instead of the password form. Distinguishing
    it is safe where the plain `AuthError` is not — it only ever follows a
    correct password, so it reveals nothing an attacker did not already have.
    """


class Identity(Protocol):
    name: str
    managed: bool

    def sign_up(self, email: str, password: str) -> User: ...
    def sign_in(self, email: str, password: str) -> User: ...
    def exists(self, email: str) -> bool: ...
    def confirm(self, email: str, code: str) -> None: ...
    def resend(self, email: str) -> None: ...


# --------------------------------------------------------------------------
# local — a real store, fenced to dev
# --------------------------------------------------------------------------


class LocalIdentity:
    """scrypt with a per-user salt, in a JSON file. Dev and tests only."""

    name = "local"
    managed = False

    def __init__(self, path: Path | None = None):
        self.path = path or Path(os.environ.get("RECON_DEV_USERS", "data/dev/users.json"))

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, records: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(records, indent=2, sort_keys=True), encoding="utf-8")

    def exists(self, email: str) -> bool:
        return _norm(email) in self._load()

    def sign_up(self, email: str, password: str) -> User:
        email = _norm(email)
        _check_password(password)
        records = self._load()
        if email in records:
            raise AuthError("An account with that email already exists. Sign in instead.")
        salt = secrets.token_bytes(16)
        records[email] = {
            "user_id": str(uuid.uuid4()),
            "salt": salt.hex(),
            "hash": hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT).hex(),
        }
        self._save(records)
        return User(user_id=records[email]["user_id"], email=email)

    def confirm(self, email: str, code: str) -> None:
        """Nothing to confirm — a local account has no email behind it. Present
        so the two backends satisfy one protocol rather than the surface asking
        which one it is talking to."""
        raise AuthError("This development account needs no confirmation.")

    def resend(self, email: str) -> None:
        raise AuthError("This development account needs no confirmation.")

    def sign_in(self, email: str, password: str) -> User:
        email = _norm(email)
        record = self._load().get(email)
        if record is None:
            # Spend the same work anyway. A fast "no such user" and a slow "wrong
            # password" are an enumeration oracle with a stopwatch.
            hashlib.scrypt(password.encode(), salt=b"\x00" * 16, **_SCRYPT)
            raise AuthError("Email or password is incorrect.")
        candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(record["salt"]), **_SCRYPT)
        if not hmac.compare_digest(candidate.hex(), record["hash"]):
            raise AuthError("Email or password is incorrect.")
        return User(user_id=record["user_id"], email=email)


# --------------------------------------------------------------------------
# cognito
# --------------------------------------------------------------------------


class CognitoIdentity:
    """Amazon Cognito, driven through its API rather than its hosted UI.

    Hosted UI cannot be the split-view login, and the login is the first thing a
    customer sees. `SignUp` and `InitiateAuth` give the primitives without the
    chrome; the tokens are exchanged for our own cookie and discarded.
    """

    name = "cognito"
    managed = True

    def __init__(
        self,
        pool_id: str | None = None,
        client_id: str | None = None,
        region: str | None = None,
        client_secret: str | None = None,
    ):
        self.pool_id = pool_id or os.environ.get("RECON_COGNITO_POOL_ID", "")
        self.client_id = client_id or os.environ.get("RECON_COGNITO_CLIENT_ID", "")
        self.region = region or os.environ.get("AWS_REGION", "ap-south-1")
        # A confidential client: this server is the only caller and it holds a
        # secret, so every auth call carries a SECRET_HASH. A public client would
        # be simpler and would mean anyone who learns the client id can drive the
        # pool's sign-up endpoint.
        self._secret = client_secret or os.environ.get("RECON_COGNITO_CLIENT_SECRET", "")
        if not (self.pool_id and self.client_id):
            raise ConfigError(
                "RECON_AUTH=cognito needs RECON_COGNITO_POOL_ID and "
                "RECON_COGNITO_CLIENT_ID. Refusing to start rather than falling "
                "back to a development credential store."
            )

    def _hash(self, username: str) -> str:
        """Cognito's HMAC over `username + client_id`, keyed by the client secret."""
        digest = hmac.new(
            self._secret.encode(), (username + self.client_id).encode(), hashlib.sha256
        ).digest()
        return base64.b64encode(digest).decode()

    def _signup_secret(self, username: str) -> dict:
        """`SignUp` spells it `SecretHash`; `InitiateAuth` spells the same value
        `SECRET_HASH` inside `AuthParameters`. Two spellings, one hash, and a
        clever comprehension that tried to derive one from the other is how a
        typo becomes an auth outage."""
        return {"SecretHash": self._hash(username)} if self._secret else {}

    def _auth_secret(self, username: str) -> dict:
        return {"SECRET_HASH": self._hash(username)} if self._secret else {}

    def _client(self):
        import boto3  # imported here so the package is optional off AWS

        return boto3.client("cognito-idp", region_name=self.region)

    def exists(self, email: str) -> bool:
        """Whether an address is known. Used only to decide which form to show;
        never exposed on a failed sign-in, where the answer would enumerate."""
        from botocore.exceptions import ClientError

        try:
            self._client().admin_get_user(UserPoolId=self.pool_id, Username=_norm(email))
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "UserNotFoundException":
                return False
            raise
        return True

    def sign_up(self, email: str, password: str) -> User:
        from botocore.exceptions import ClientError

        email = _norm(email)
        _check_password(password)
        try:
            reply = self._client().sign_up(
                ClientId=self.client_id,
                Username=email,
                Password=password,
                UserAttributes=[{"Name": "email", "Value": email}],
                **self._signup_secret(email),
            )
        except ClientError as exc:
            raise _cognito_error(exc) from exc
        return User(user_id=reply["UserSub"], email=email)

    def sign_in(self, email: str, password: str) -> User:
        from botocore.exceptions import ClientError

        email = _norm(email)
        try:
            reply = self._client().initiate_auth(
                ClientId=self.client_id,
                AuthFlow="USER_PASSWORD_AUTH",
                AuthParameters={
                    "USERNAME": email,
                    "PASSWORD": password,
                    **self._auth_secret(email),
                },
            )
        except ClientError as exc:
            raise _cognito_error(exc) from exc
        # The id token is read once, for the subject, and then dropped. Nothing
        # downstream takes a JWT, so nothing downstream can be fooled by one.
        claims = _unverified_claims(reply["AuthenticationResult"]["IdToken"])
        return User(user_id=claims["sub"], email=claims.get("email", email))

    def confirm(self, email: str, code: str) -> None:
        from botocore.exceptions import ClientError

        email = _norm(email)
        try:
            self._client().confirm_sign_up(
                ClientId=self.client_id,
                Username=email,
                ConfirmationCode=code.strip(),
                **self._signup_secret(email),
            )
        except ClientError as exc:
            raise _cognito_error(exc) from exc

    def resend(self, email: str) -> None:
        from botocore.exceptions import ClientError

        email = _norm(email)
        try:
            self._client().resend_confirmation_code(
                ClientId=self.client_id, Username=email, **self._signup_secret(email)
            )
        except ClientError as exc:
            raise _cognito_error(exc) from exc


def _cognito_error(exc) -> AuthError:
    """Cognito's error code, as the exception this surface should raise.

    Returns rather than raises, and returns an *instance* rather than a string:
    an earlier draft had a `_message()` helper that raised for one code and
    returned for the rest, which is the kind of control flow that reads fine
    once and wrongly forever after.
    """
    code = exc.response["Error"]["Code"]
    if code == "UserNotConfirmedException":
        return NeedsConfirmation("Confirm your email to finish signing in.")
    if code in {"NotAuthorizedException", "UserNotFoundException"}:
        return AuthError("Email or password is incorrect.")
    if code == "UsernameExistsException":
        return AuthError("An account with that email already exists. Sign in instead.")
    if code == "InvalidPasswordException":
        return AuthError("That password does not meet the policy for this account.")
    if code == "CodeMismatchException":
        return AuthError("That code is not right. Check the email and try again.")
    if code == "ExpiredCodeException":
        return AuthError("That code has expired. Ask for a new one.")
    if code == "LimitExceededException":
        return AuthError("Too many attempts. Wait a few minutes and try again.")
    return AuthError(exc.response["Error"].get("Message", "Sign-in failed."))


def _unverified_claims(token: str) -> dict:
    """The payload of a token we just received over TLS from Cognito itself.

    Not verified, and it does not need to be: this is the response to our own
    authenticated call, not a bearer token handed to us by a client. Nothing
    else in this system ever reads a JWT, which is why there is no verification
    path to get wrong.
    """
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


# --------------------------------------------------------------------------
# sessions — signed, ours, and short-lived
# --------------------------------------------------------------------------


def _sign(payload: bytes, secret: bytes) -> str:
    mac = hmac.new(secret, payload, hashlib.sha256).digest()
    return f"{_b64(payload)}.{_b64(mac)}"


def issue(user: User, secret: bytes, *, ttl: int = SESSION_TTL, now: float | None = None) -> str:
    body = json.dumps(
        {"u": user.user_id, "e": user.email, "x": int((now or time.time()) + ttl)},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return _sign(body, secret)


def read(token: str, secret: bytes, *, now: float | None = None) -> User | None:
    """The session, or None. Never raises — a bad cookie is an anonymous
    visitor, not a server error, and a forged one must be indistinguishable
    from an absent one to whoever sent it."""
    try:
        body_b64, mac_b64 = token.split(".", 1)
        body = _unb64(body_b64)
        expected = hmac.new(secret, body, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(mac_b64)):
            return None
        claims = json.loads(body)
        if float(claims["x"]) < (now or time.time()):
            return None
        return User(user_id=str(claims["u"]), email=str(claims["e"]))
    except Exception:
        # Deliberately broad. Every malformed cookie in the world arrives here,
        # and each one means exactly the same thing: not signed in.
        return None


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def new_csrf() -> str:
    return secrets.token_urlsafe(24)


def csrf_ok(cookie: str | None, submitted: str | None) -> bool:
    """Double-submit, compared in constant time.

    `SameSite=Lax` already keeps the session cookie off a cross-site POST, so
    this is the second lock rather than the only one. Both, because the whole
    product is about not relying on one control.
    """
    return bool(cookie) and bool(submitted) and hmac.compare_digest(cookie, submitted)


# --------------------------------------------------------------------------
# configuration — resolved once, refused loudly
# --------------------------------------------------------------------------


def _norm(email: str) -> str:
    return email.strip().lower()


MIN_PASSWORD = 12


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise AuthError(f"Use at least {MIN_PASSWORD} characters.")


def is_dev() -> bool:
    return os.environ.get("RECON_ENV", "dev").lower() == "dev"


def build_identity() -> Identity:
    """The configured credential store, or a refusal.

    `local` outside dev is the one combination that must never start. It is not
    checked at the point of use — a check on the login path would let the app
    come up healthy and fail only when someone tries to sign in.
    """
    choice = os.environ.get("RECON_AUTH", "local").lower()
    if choice == "cognito":
        return CognitoIdentity()
    if choice == "local":
        if not is_dev():
            raise ConfigError(
                "RECON_AUTH=local is a development credential store and "
                "RECON_ENV is not 'dev'. Set RECON_AUTH=cognito, or set "
                "RECON_ENV=dev if this really is a laptop."
            )
        return LocalIdentity()
    raise ConfigError(f"RECON_AUTH must be 'cognito' or 'local', got {choice!r}")


def session_secret() -> bytes:
    """The signing key for session cookies.

    Outside dev an absent secret is fatal. In dev an ephemeral one is generated,
    which logs everyone out on restart — visible, correct, and much better than
    a constant that could be copied into a deployment.
    """
    raw = os.environ.get("RECON_SESSION_SECRET", "")
    if raw:
        return raw.encode()
    if not is_dev():
        raise ConfigError(
            "RECON_SESSION_SECRET is not set. Sessions would be signed with a "
            "key that changes on every restart, or worse, a shared default."
        )
    return _EPHEMERAL


_EPHEMERAL = secrets.token_bytes(32)


def tenant_prefix(user: User) -> str:
    """Where this account's records live. Derived from the session's user id and
    from nothing a request can influence."""
    return f"tenants/{user.user_id}"
