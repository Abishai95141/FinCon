"""The same server, reachable over the network, with OAuth in front of it.

Stdio works because the process is already inside somebody's trust boundary —
they started it, on their machine, as themselves. Over HTTP none of that holds,
and the honest consequence is that **this module refuses to serve an
unauthenticated MCP endpoint on anything but loopback.** A remote MCP server
with no authorization is not a smaller version of this product; it is every
account's decision log on a public port.

**We do not implement OAuth.** FastMCP ships `AWSCognitoProvider`, an
`OIDCProxy` over a Cognito user pool: it fills Cognito's missing Dynamic Client
Registration by registering clients itself, serves RFC 9728 protected-resource
metadata so a client can discover where to authorize, verifies Cognito's JWTs
against its published keys, and handles the consent screen. Writing that
ourselves would be a fortnight and a supply of novel bugs in the one place a bug
is unrecoverable.

The tenant then comes from the token's `sub`, which is the same string
`CognitoIdentity` stores as `user_id` — so an agent and the person whose account
it acts for read one set of records. That is the whole reason to host this.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

#: Where the server is reachable from *outside*. OAuth cannot be configured
#: without it: the authorization URLs a client is redirected to, and the audience
#: a token is bound to, are both absolute. Guessing it from a request header is
#: how an attacker chooses your issuer for you.
PUBLIC_URL_VAR = "FINCON_PUBLIC_URL"

#: The path the MCP endpoint is mounted at. A client is given
#: `{public_url}{MOUNT}`, and nothing derives it from a request.
MOUNT = "/mcp"

#: Addresses where "anyone who can reach the port" already means "anyone who can
#: read the files anyway", so an unauthenticated endpoint adds no exposure.
#:
#: `0.0.0.0` was in this set for one commit and it is the opposite of loopback —
#: it is *every* interface. The container inherited `FINCON_MCP_HOST=0.0.0.0`,
#: the refusal did not fire, and a test run of the image served an
#: unauthenticated MCP endpoint on all of them. Caught by running the container
#: and reading its own banner, which said so in plain words.
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class TransportError(RuntimeError):
    """Nothing is configured, and the bind address makes that unsafe.

    Recoverable at the caller: `mount_mcp` catches this and serves the web app
    without an MCP endpoint, because refusing to run a site over an endpoint
    nobody has set up yet would be the tail wagging the dog.
    """


class AuthorityUnavailable(RuntimeError):
    """Cognito *was* configured and could not be reached or does not exist.

    Deliberately **not** a `TransportError`, and deliberately not caught. If
    somebody set five variables they intend an authenticated endpoint, and the
    two ways to get this wrong are not the same:

    * unset — decline the endpoint, serve the site, say so in the banner
    * set and broken — stop, and let the deployment roll back

    Degrading the second into the first is how a container comes up healthy
    while the "Agent access" page reads *live* — because `describe()` sees five
    variables and cannot see a 404 from the pool they name — and an operator
    hands a colleague a URL that answers nothing.
    """


@dataclass(frozen=True)
class Settings:
    """Everything the HTTP transport needs, read from the environment once.

    A frozen object rather than scattered `os.environ` reads, so `describe()`
    can tell a configuration page exactly what is set and what is missing —
    which is what stops that page printing a URL nobody can connect to.
    """

    public_url: str = ""
    user_pool_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    region: str = ""
    host: str = "127.0.0.1"
    port: int = 8138

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            public_url=os.environ.get(PUBLIC_URL_VAR, "").rstrip("/"),
            user_pool_id=os.environ.get("COGNITO_USER_POOL_ID", ""),
            client_id=os.environ.get("COGNITO_CLIENT_ID", ""),
            client_secret=os.environ.get("COGNITO_CLIENT_SECRET", ""),
            region=os.environ.get("AWS_REGION", ""),
            host=os.environ.get("FINCON_MCP_HOST", "127.0.0.1"),
            port=int(os.environ.get("FINCON_MCP_PORT", "8138")),
        )

    @property
    def missing(self) -> list[str]:
        """Which variables stand between this and an authenticated endpoint.

        Named rather than counted, the same way a loop names the source file that
        has not arrived. "3 settings missing" is not something anybody can act on.
        """
        wanted = {
            PUBLIC_URL_VAR: self.public_url,
            "COGNITO_USER_POOL_ID": self.user_pool_id,
            "COGNITO_CLIENT_ID": self.client_id,
            "COGNITO_CLIENT_SECRET": self.client_secret,
            "AWS_REGION": self.region,
        }
        return sorted(name for name, value in wanted.items() if not value)

    @property
    def authenticated(self) -> bool:
        return not self.missing

    @property
    def loopback_only(self) -> bool:
        return self.host in LOOPBACK

    @property
    def endpoint(self) -> str:
        """The URL a client is configured with, or "" when there is not one.

        Empty is the correct answer for an undeployed server, and a caller that
        renders it must say so rather than substituting a plausible localhost
        address a colleague cannot reach.
        """
        return f"{self.public_url}{MOUNT}" if self.public_url else ""


def auth_provider(settings: Settings):
    """Cognito, wired by FastMCP. Returns `None` when nothing is configured.

    `require_authorization_consent="remember"` because an agent reconnecting on
    every session and re-prompting a person each time trains them to click
    through it, which is the opposite of what a consent screen is for.
    """
    if not settings.authenticated:
        return None

    from fastmcp.server.auth.providers.aws import AWSCognitoProvider

    return AWSCognitoProvider(
        user_pool_id=settings.user_pool_id,
        client_id=settings.client_id,
        client_secret=settings.client_secret,
        aws_region=settings.region,
        base_url=settings.public_url,
        redirect_path="/auth/callback",
        required_scopes=["openid", "email"],
        require_authorization_consent="remember",
    )


def build(settings: Settings | None = None):
    """The FastMCP server, configured for HTTP, or a refusal.

    The refusal is the load-bearing part. An unauthenticated endpoint is served
    only on loopback, where "anyone who can reach the port" already means
    "anyone who can read the files anyway" — so the exposure is not new. Bound to
    anything else without Cognito, this raises and names what is missing.
    """
    settings = settings or Settings.from_env()
    from .server import mcp

    if settings.authenticated:
        try:
            mcp.auth = auth_provider(settings)
        except Exception as exc:
            raise AuthorityUnavailable(
                f"Cognito is configured and unusable: pool {settings.user_pool_id!r} in "
                f"{settings.region!r} did not answer OIDC discovery ({type(exc).__name__}). "
                f"Check the pool id, the region, and that the app client exists. Refusing "
                f"to start rather than serving a page that says the endpoint is live."
            ) from exc
        return mcp

    if not settings.loopback_only:
        raise TransportError(
            f"refusing to serve MCP on {settings.host} without authorization. "
            f"Set {', '.join(settings.missing)} to put Cognito in front of it, or bind "
            f"to 127.0.0.1. An unauthenticated remote MCP endpoint is every account's "
            f"decision log on a public port."
        )

    mcp.auth = None
    return mcp


def describe(settings: Settings | None = None) -> dict:
    """What a configuration page may truthfully say about this transport."""
    settings = settings or Settings.from_env()
    return {
        "authenticated": settings.authenticated,
        "endpoint": settings.endpoint,
        "missing": settings.missing,
        "host": settings.host,
        "port": settings.port,
        "loopback_only": settings.loopback_only,
        "mount": MOUNT,
        "issuer": (
            f"https://cognito-idp.{settings.region}.amazonaws.com/{settings.user_pool_id}"
            if settings.authenticated
            else ""
        ),
    }


def serve(settings: Settings | None = None) -> None:
    """Run it. `make mcp-http`."""
    settings = settings or Settings.from_env()
    server = build(settings)
    server.run(
        transport="http",
        host=settings.host,
        port=settings.port,
        path=MOUNT,
    )


def main() -> None:
    import sys

    try:
        serve()
    except (TransportError, AuthorityUnavailable) as exc:
        print(f"recon-mcp-http: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()


__all__ = [
    "MOUNT",
    "PUBLIC_URL_VAR",
    "AuthorityUnavailable",
    "Settings",
    "TransportError",
    "auth_provider",
    "build",
    "describe",
    "serve",
]
