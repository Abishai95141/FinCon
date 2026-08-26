"""The hosted transport, and the account it acts for.

Stdio works because the process is inside somebody's trust boundary already —
they started it, on their machine, as themselves, and `RECON_TENANT` is a note
to self. Over HTTP every part of that is false, so two things have to hold and
both are tested here against real behaviour rather than against a docstring:

**The account comes from the token.** Not from an environment variable, not from
a header a client controls, and above all not from a tool parameter. A caller
that could name an account could name someone else's, and an MCP caller may be a
model.

**An unauthenticated endpoint does not bind to the network.** The refusal is the
feature. A remote MCP server with no authorization is not a smaller version of
this product; it is every account's decision log on a public port.

The page tests are here for the same reason the probe exists: a configuration
screen that printed the URL this *will* have once it is deployed would be the
purest form of the thing this codebase bans — a surface that looks passed with
no capability behind it.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

from recon.mcp import http as mcphttp
from recon.mcp import probe as mcpprobe
from tests.conftest import signed_in_client

PORT = 8141
CONFIGURED = {
    "FINCON_PUBLIC_URL": "https://app.fincon.example",
    "COGNITO_USER_POOL_ID": "ap-south-1_TESTPOOL",
    "COGNITO_CLIENT_ID": "test-client-id",
    "COGNITO_CLIENT_SECRET": "test-client-secret",
    "AWS_REGION": "ap-south-1",
}


@pytest.fixture
def unconfigured(monkeypatch: pytest.MonkeyPatch):
    for name in CONFIGURED:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("RECON_TENANT", raising=False)
    return monkeypatch


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch):
    for name, value in CONFIGURED.items():
        monkeypatch.setenv(name, value)
    return monkeypatch


# ------------------------------------------------------------ it really serves


@pytest.fixture(scope="module")
def http_server():
    """A real process, speaking Streamable HTTP on loopback.

    In-process would test our own object graph. The whole point of a transport
    is what happens between two processes, and every way this fails in practice
    — the module not importing, the port not binding, the mount path being
    wrong — is invisible from inside the process that configured it.
    """
    env = {
        **os.environ,
        "FINCON_MCP_PORT": str(PORT),
        "FINCON_MCP_HOST": "127.0.0.1",
    }
    for name in CONFIGURED:
        env.pop(name, None)

    proc = subprocess.Popen(
        [sys.executable, "-m", "recon.mcp.http"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    url = f"http://127.0.0.1:{PORT}{mcphttp.MOUNT}"
    for _ in range(80):
        if proc.poll() is not None:
            pytest.fail(f"the server exited: {proc.stderr.read().decode()[-500:]}")
        try:
            urllib.request.urlopen(url, timeout=1)
            break
        except urllib.error.HTTPError:
            break  # bound and answering; a bare GET is not a valid MCP request
        except Exception:
            time.sleep(0.25)
    else:
        proc.terminate()
        pytest.fail("the server never bound")

    yield url
    proc.terminate()
    proc.wait(timeout=10)


def test_the_same_tools_are_reachable_over_http(http_server):
    """Same server, second transport. A hosted surface that quietly exposed a
    different tool set than the one the page describes would be worse than none."""
    from fastmcp import Client

    async def go():
        async with Client(http_server) as client:
            tools = sorted(t.name for t in await client.list_tools())
            result = await client.call_tool("get_contracts", {})
            return tools, (result.data or {}).get("contract_version", "")

    tools, version = asyncio.run(go())
    assert tools == list(mcpprobe.catalog().tools and [t.name for t in mcpprobe.catalog().tools])
    assert version, "the contract version did not come back over the wire"


def test_the_authority_boundary_holds_over_http_too(http_server):
    """The schemas are generated once and served by both transports, so this
    should be true by construction — which is exactly the kind of claim that
    turns out to be false when somebody adds a transport-specific wrapper."""
    from fastmcp import Client

    async def go():
        async with Client(http_server) as client:
            return {t.name: t.inputSchema for t in await client.list_tools()}

    for name, schema in asyncio.run(go()).items():
        if name == mcpprobe.STATELESS_TOOL:
            continue
        offending = mcpprobe.AUTHORITY_PARAMS & set((schema or {}).get("properties", {}))
        assert not offending, f"{name} accepts authority over HTTP: {sorted(offending)}"


# --------------------------------------------------------------- whose account


def test_the_account_comes_from_the_token_not_the_environment(monkeypatch):
    """The reason to host this at all.

    `RECON_TENANT` is set to one account and the token names another. The token
    must win — it is the only one of the two that somebody had to authenticate
    to obtain.
    """
    import fastmcp.server.dependencies as deps

    from recon.mcp import server

    monkeypatch.setenv("RECON_TENANT", "the-env-account")

    class FakeToken:
        subject = "the-token-account"

    monkeypatch.setattr(deps, "get_access_token", lambda: FakeToken())
    assert server._tenant_id() == "the-token-account"

    monkeypatch.setattr(deps, "get_access_token", lambda: None)
    assert server._tenant_id() == "the-env-account"


def test_a_token_subject_matching_a_web_session_reaches_the_same_records(tmp_path, monkeypatch):
    """One account, two surfaces. `CognitoIdentity` stores Cognito's `sub` as
    `user_id`, so a token's subject and a session's account are the same string —
    and if they ever stop being, an agent silently reads an empty workspace while
    its owner is looking at a full one."""
    import fastmcp.server.dependencies as deps

    from recon import service
    from recon.mcp import server

    _client, user_id, runs_root = signed_in_client(monkeypatch, tmp_path)

    class FakeToken:
        subject = user_id

    monkeypatch.setattr(deps, "get_access_token", lambda: FakeToken())
    assert server._runs() == runs_root
    assert server._runs() == service.runs_root(None) / user_id


@pytest.mark.parametrize("hostile", ["../other", "a/b", "..", "", "x\\y"])
def test_a_tenant_id_cannot_walk_out_of_the_runs_directory(hostile, monkeypatch):
    """A `sub` is a UUID and `RECON_TENANT` is whatever somebody typed. Both are
    data from outside, and one of them ends up in a path."""
    from recon.mcp.server import ToolRefusal, _tenant_root

    if hostile == "":
        assert _tenant_root(hostile) is None
        return
    with pytest.raises(ToolRefusal):
        _tenant_root(hostile)


# ------------------------------------------------------------------ it refuses


def test_an_unauthenticated_server_will_not_bind_to_the_network(unconfigured):
    """The load-bearing refusal. Loopback is fine — anyone who can reach the port
    can read the files anyway — and anything else is not."""
    settings = mcphttp.Settings.from_env()
    assert not settings.authenticated

    local = mcphttp.build(mcphttp.Settings(host="127.0.0.1"))
    assert local.auth is None

    with pytest.raises(mcphttp.TransportError) as caught:
        mcphttp.build(mcphttp.Settings(host="0.0.0.0.1"))
    message = str(caught.value)
    assert "without authorization" in message
    for name in CONFIGURED:
        assert name in message, f"the refusal does not name {name}"


def test_a_configured_server_puts_cognito_in_front(configured, monkeypatch):
    """We do not implement OAuth, so what is worth testing is the half we do own:
    that the right pool, client and public URL reach FastMCP's provider.

    The provider performs OIDC discovery against the real Cognito endpoint inside
    its constructor — which is correct of it, and fails fast on a pool that does
    not exist. That also means constructing one with fixture credentials would
    make this test require the network, so the constructor is recorded rather than
    run. What FastMCP does with these arguments is FastMCP's business and is
    covered by the live test below.
    """
    settings = mcphttp.Settings.from_env()
    assert settings.authenticated
    assert settings.missing == []
    assert settings.endpoint == f"{CONFIGURED['FINCON_PUBLIC_URL']}{mcphttp.MOUNT}"

    seen = {}

    class Recorder:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr("fastmcp.server.auth.providers.aws.AWSCognitoProvider", Recorder)
    provider = mcphttp.auth_provider(settings)

    assert isinstance(provider, Recorder)
    assert seen["user_pool_id"] == CONFIGURED["COGNITO_USER_POOL_ID"]
    assert seen["client_id"] == CONFIGURED["COGNITO_CLIENT_ID"]
    assert seen["aws_region"] == CONFIGURED["AWS_REGION"]
    assert seen["base_url"] == CONFIGURED["FINCON_PUBLIC_URL"]
    assert "openid" in seen["required_scopes"]
    assert seen["require_authorization_consent"] == "remember", (
        "re-prompting on every reconnect trains people to click through consent"
    )


@pytest.mark.live
def test_the_real_cognito_pool_answers_discovery():
    """The other half, against the pool that actually exists.

    Marked `live` because it needs the network — `make test` runs offline. This
    is what catches a pool id that was renamed or a region that is wrong, which
    the recorder above cannot see.
    """
    pool = os.environ.get("COGNITO_USER_POOL_ID")
    region = os.environ.get("AWS_REGION")
    if not (pool and region):
        pytest.skip("no Cognito pool configured in this environment")

    url = f"https://cognito-idp.{region}.amazonaws.com/{pool}/.well-known/openid-configuration"
    with urllib.request.urlopen(url, timeout=10) as response:
        body = response.read().decode()
    assert '"authorization_endpoint"' in body
    assert pool in body


def test_missing_settings_are_named_not_counted(monkeypatch):
    """ "3 settings missing" is not something anybody can act on."""
    for name, value in CONFIGURED.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("COGNITO_CLIENT_SECRET")

    settings = mcphttp.Settings.from_env()
    assert settings.missing == ["COGNITO_CLIENT_SECRET"]
    assert not settings.authenticated
    assert settings.endpoint, "a public url was set and the endpoint went missing with it"


# ------------------------------------------------------- the page tells no lies


def test_the_page_prints_no_url_before_there_is_one(tmp_path, unconfigured):
    """The defect this whole module exists to avoid."""
    client, _user_id, _runs = signed_in_client(unconfigured, tmp_path)
    body = client.get("/agent").text

    hosted = body.split("Hosted access")[1].split("Local access")[0]
    assert "not deployed" in hosted
    assert "https://" not in hosted, f"a URL appeared before deployment: {hosted[:200]}"
    for name in CONFIGURED:
        assert name in hosted, f"the panel does not say {name} is needed"


def test_the_page_offers_the_url_once_it_exists(tmp_path, configured):
    client, user_id, _runs = signed_in_client(configured, tmp_path)
    body = client.get("/agent").text

    hosted = body.split("Hosted access")[1].split("Local access")[0]
    assert "live" in hosted
    endpoint = f"{CONFIGURED['FINCON_PUBLIC_URL']}{mcphttp.MOUNT}"
    assert endpoint in hosted
    assert f"claude mcp add --transport http fincon {endpoint}" in hosted
    assert CONFIGURED["COGNITO_USER_POOL_ID"] in hosted, "the issuer is not shown"

    assert "RECON_TENANT" not in hosted, (
        "the hosted panel still asks for an account id; over OAuth the account is "
        "the token's subject and a client that pastes one is naming its own"
    )
    assert user_id in body, "the stdio panel lost this account's id"


def test_both_transports_are_offered_and_told_apart(tmp_path, configured):
    """A page showing two ways to connect must make clear which is which — the
    stdio one carries an account id and the hosted one must not."""
    client, _user_id, _runs = signed_in_client(configured, tmp_path)
    body = client.get("/agent").text

    assert body.index("Hosted access") < body.index("Local access"), (
        "the local form is offered before the hosted one on a deployed instance"
    )
    assert "claude mcp add-json" in body
    assert "claude mcp add --transport http" in body


def test_the_endpoint_is_a_function_of_configuration_and_nothing_else():
    """A client is told where to send a token, so that address must come from
    the operator rather than from whatever host header a request arrived with —
    the classic way an attacker chooses your issuer for you.

    Tested by value rather than by grepping the source for the word "request",
    which is what the first version of this did: it failed on a comment
    explaining why requests are not consulted.
    """
    a = mcphttp.Settings(public_url="https://one.example")
    b = mcphttp.Settings(public_url="https://two.example")

    assert a.endpoint == f"https://one.example{mcphttp.MOUNT}"
    assert b.endpoint == f"https://two.example{mcphttp.MOUNT}"
    assert a.endpoint == mcphttp.Settings(public_url="https://one.example").endpoint

    # Host and port are where the process listens, not where a client connects.
    # A deployment behind an ALB has 0.0.0.0:8138 locally and an https:// name
    # outside, and conflating the two hands out an unreachable address.
    behind_a_proxy = mcphttp.Settings(public_url="https://one.example", host="0.0.0.0", port=8138)
    assert behind_a_proxy.endpoint == a.endpoint
    assert mcphttp.Settings(host="127.0.0.1", port=9999).endpoint == ""


def test_the_mount_path_is_pinned_because_clients_are_configured_with_it():
    """`/mcp` is a compatibility commitment, not an implementation detail.

    The round-trip tests above cannot catch a rename: the fixture builds its URL
    from `MOUNT` too, so both sides move together and everything still passes.
    What a rename actually breaks is every client already configured with the old
    URL, which no test in this repository can observe — so the constant is pinned
    here, and changing it has to be a deliberate act with a version bump beside
    it rather than a tidy-up.
    """
    assert mcphttp.MOUNT == "/mcp"
    assert mcphttp.Settings(public_url="https://x.example").endpoint == "https://x.example/mcp"


def test_the_check_probes_the_transport_a_client_would_use(tmp_path, configured, monkeypatch):
    """On a deployed instance, checking stdio would prove the wrong thing very
    convincingly: the local process starts fine while the endpoint an agent
    connects to is down, and the page says "server answered"."""
    called = {}

    def fake_http(url, **_kwargs):
        called["url"] = url
        return mcpprobe.Probe(ok=True, command=url, cwd="", tenant=None, tools=("x",))

    def fake_stdio(**_kwargs):
        called["stdio"] = True
        return mcpprobe.Probe(ok=True, command="stdio", cwd="", tenant=None, tools=("x",))

    monkeypatch.setattr(mcpprobe, "probe_http", fake_http)
    monkeypatch.setattr(mcpprobe, "probe", fake_stdio)

    client, _user_id, _runs = signed_in_client(configured, tmp_path)
    token = re.search(r"name='csrf' value='([^']*)'", client.get("/agent").text).group(1)
    client.post("/agent/check", data={"csrf": token})

    assert called.get("url") == f"{CONFIGURED['FINCON_PUBLIC_URL']}{mcphttp.MOUNT}"
    assert "stdio" not in called, "a deployed instance checked the local process instead"


def test_a_protected_endpoint_reads_as_up_not_as_broken():
    """401 is the right answer from a configured endpoint. Reporting it as a
    failure would send an operator hunting a problem that is the control working."""
    import fastmcp

    class Boom:
        def __init__(self, *_a, **_k):
            pass

        async def __aenter__(self):
            raise RuntimeError("401 Unauthorized: invalid_token")

        async def __aexit__(self, *_a):
            return False

    original = fastmcp.Client
    fastmcp.Client = Boom
    try:
        result = mcpprobe.probe_http("https://app.fincon.example/mcp", timeout=5)
    finally:
        fastmcp.Client = original

    assert result.ok, "a protected endpoint was reported as unreachable"
    assert not result.error
    assert "authorization" in result.hint.lower()


def test_the_page_and_the_endpoint_do_not_share_a_path(tmp_path, monkeypatch):
    """Both were at `/mcp` for one commit and the router resolved it by
    registration order — a GET reached the HTML page and a client's POST reached
    whichever happened to be registered first. Routing that works by accident
    works until somebody reorders an include.

    The endpoint half runs under a context-managed `TestClient` because a mounted
    MCP app's session manager starts in a lifespan, and a `TestClient` used
    without `with` never runs one. That is not a test detail: it is the same
    reason `mount_mcp` has to chain the lifespan into the parent app, and
    without both halves the deployment serves a page saying the endpoint is live
    beside an endpoint that answers nothing.
    """
    from fastapi.testclient import TestClient

    from recon.api.app import app, mount_mcp

    assert mount_mcp()

    client, _user_id, _runs = signed_in_client(monkeypatch, tmp_path)
    page = client.get("/agent")
    assert page.status_code == 200
    assert "Agent access" in page.text
    assert page.headers["content-type"].startswith("text/html")

    # Read off the UI router rather than `app.routes`: this FastAPI keeps an
    # included router as a single opaque `_IncludedRouter` entry, so scanning the
    # app's own table finds no page paths at all — and an assertion over an empty
    # set is a test that cannot fail for the reason it was written.
    from recon.api.ui import router as ui_router

    ui_paths = {r.path for r in ui_router.routes}
    assert "/agent" in ui_paths and "/agent/check" in ui_paths
    assert mcphttp.MOUNT not in ui_paths, "the page and the endpoint share a path again"

    with TestClient(app) as live:
        endpoint = live.get(mcphttp.MOUNT)
        assert "Agent access" not in endpoint.text
        assert "<!doctype html>" not in endpoint.text.lower()


def test_the_mounted_endpoint_actually_answers_the_protocol(tmp_path):
    """The mount is the deployment shape — one container, one port, one
    certificate — so it has to serve MCP, not merely occupy the path.

    This is what caught the lifespan bug: mounting alone gave every request
    "task group is not initialized", and nothing else in the suite would have
    noticed until the endpoint was live and useless.
    """
    import json

    from fastapi.testclient import TestClient

    from recon.api.app import app, mount_mcp

    assert mount_mcp()

    with TestClient(app) as live:
        response = live.post(
            mcphttp.MOUNT,
            headers={
                "content-type": "application/json",
                "accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            },
        )

    assert response.status_code == 200, response.text[:400]
    body = response.text
    assert "task group is not initialized" not in body
    payload = json.loads(body.split("data:", 1)[1] if "data:" in body else body)
    assert payload["result"]["serverInfo"]["name"] == "recon"


@pytest.mark.parametrize("host", ["0.0.0.0", "10.0.1.5", "::", "fe80::1"])
def test_a_wildcard_bind_is_not_loopback(host, unconfigured):
    """`0.0.0.0` sat in the loopback set for one commit.

    It is the opposite of loopback — it is *every* interface — and the container
    inherits `FINCON_MCP_HOST=0.0.0.0`, so the first run of the built image
    served an unauthenticated MCP endpoint on all of them. The refusal that
    exists precisely to prevent that did not fire.

    Found by running the container and reading its own startup banner, which
    announced "NO AUTHORIZATION" while binding to the world. Nothing in the
    suite would have caught it, because every test until now passed the host
    `127.0.0.1`.
    """
    with pytest.raises(mcphttp.TransportError):
        mcphttp.build(mcphttp.Settings(host=host))


def test_the_container_cannot_serve_mcp_without_cognito():
    """The Dockerfile's own environment, checked against the rule.

    A deployment that has not been given a user pool must start the web app and
    decline the endpoint — not start both and hope the security group is right.
    """
    dockerfile = pathlib.Path(__file__).resolve().parents[2] / "Dockerfile"
    text = dockerfile.read_text()

    host = re.search(r"FINCON_MCP_HOST=(\S+)", text)
    assert host, "the image no longer sets a bind address, so this test is blind"
    assert host.group(1) not in mcphttp.LOOPBACK

    with pytest.raises(mcphttp.TransportError):
        mcphttp.build(mcphttp.Settings(host=host.group(1)))


def test_unset_and_broken_are_not_the_same_failure(configured, monkeypatch):
    """Two ways to have no endpoint, and they must not collapse into one.

    Unset means somebody has not deployed OAuth yet: decline it, serve the site,
    name what is missing. Set-and-broken means somebody typed a pool id wrong
    while intending an authenticated endpoint, and coming up healthy without it
    is how the page ends up reading "live" over nothing — `describe()` sees five
    variables and cannot see a 404 from the pool they name.
    """

    def explode(**_kwargs):
        raise RuntimeError("404 from cognito")

    monkeypatch.setattr("fastmcp.server.auth.providers.aws.AWSCognitoProvider", explode)

    with pytest.raises(mcphttp.AuthorityUnavailable) as caught:
        mcphttp.build(mcphttp.Settings.from_env())
    message = str(caught.value)
    assert CONFIGURED["COGNITO_USER_POOL_ID"] in message
    assert CONFIGURED["AWS_REGION"] in message
    assert not isinstance(caught.value, mcphttp.TransportError), (
        "a broken pool is catchable as a missing one, so the app will serve "
        "without the endpoint somebody explicitly asked for"
    )


def test_the_app_declines_an_unset_endpoint_and_refuses_a_broken_one(configured, monkeypatch):
    """The same distinction where it has an effect: `mount_mcp` catches one and
    not the other."""
    from recon.api.app import app, mount_mcp

    for name in CONFIGURED:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FINCON_MCP_HOST", "0.0.0.0")
    assert mount_mcp(app) is False, "an unset endpoint took the web app down with it"

    for name, value in CONFIGURED.items():
        monkeypatch.setenv(name, value)

    def explode(**_kwargs):
        raise RuntimeError("404 from cognito")

    monkeypatch.setattr("fastmcp.server.auth.providers.aws.AWSCognitoProvider", explode)
    with pytest.raises(mcphttp.AuthorityUnavailable):
        mount_mcp(app)
