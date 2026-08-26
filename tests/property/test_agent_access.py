"""The MCP configuration screen, and the claims it makes.

A config page is unusual among screens: almost everything on it is a claim about
a *different process*. "18 tools", "no tool takes a policy", "this command
works" — each is either measured against the real server or it is decoration.

So the tests here are mostly about agreement between two views that could
silently drift apart: the catalogue rendered in-process (fast, for the table)
and the server a client actually spawns (slow, over stdio). If those two ever
disagree, the page is telling the user about a server that is not the one they
will connect to, which is worse than saying nothing.
"""

from __future__ import annotations

import json
import pathlib
import re
import shlex

import pytest

from recon.api import auth
from recon.api.ui import _mcp_config
from recon.mcp import probe as mcpprobe
from tests.conftest import signed_in_client


@pytest.fixture
def signed_in(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    return signed_in_client(monkeypatch, tmp_path)


# ---------------------------------------------------------------- the config


def test_the_config_names_this_account_and_nobody_else(signed_in, tmp_path, monkeypatch):
    """Two accounts, two configs. `RECON_TENANT` is the only thing standing
    between an agent and somebody else's closes, so it must not be a constant."""
    client, user_id, _ = signed_in
    body = client.get("/mcp").text
    assert user_id in body

    other, other_id, _ = signed_in_client(monkeypatch, tmp_path / "other", email="rival@other.in")
    assert other_id != user_id
    assert other_id not in body
    assert user_id not in other.get("/mcp").text


def test_the_json_block_is_valid_json_a_client_can_paste(signed_in):
    """A config block that does not parse is a support ticket with extra steps."""
    _client, user_id, _ = signed_in
    from recon.api.auth import User

    _cli, block, _raw = _mcp_config(User(user_id=user_id, email="controller@acme.in"))
    parsed = json.loads(block)

    server = parsed["mcpServers"]["fincon"]
    assert server["env"]["RECON_TENANT"] == user_id
    assert server["args"] == ["-m", "recon.mcp.server"]
    assert pathlib.Path(server["cwd"]).is_dir()


def test_the_command_is_an_interpreter_that_can_actually_import_recon(signed_in):
    """A bare `python3` in the config is the most common way this fails: the
    client starts *a* python, and it is not the one holding our dependencies."""
    from recon.api.auth import User

    _cli, block, _raw = _mcp_config(User(user_id="abc", email="x@y.in"))
    command = json.loads(block)["mcpServers"]["fincon"]["command"]

    assert pathlib.Path(command).is_absolute(), f"{command} is not an absolute path"
    assert pathlib.Path(command).exists()


def test_the_cli_form_survives_a_shell(signed_in):
    """`claude mcp add-json` takes the JSON as one argv element. Unquoted, the
    shell eats the braces and the user gets an error about nothing."""
    from recon.api.auth import User

    cli, _block, _raw = _mcp_config(User(user_id="abc", email="x@y.in"))
    argv = shlex.split(cli)
    assert argv[:4] == ["claude", "mcp", "add-json", "fincon"]
    assert json.loads(argv[4])["args"] == ["-m", "recon.mcp.server"]


# ------------------------------------------------------------- the catalogue


def test_the_catalogue_matches_the_server_a_client_will_actually_spawn():
    """The one test that keeps this page honest.

    The table is built in-process for speed. The user connects to a subprocess.
    Nothing in the code makes those the same, so assert it — a page describing a
    server that is not the one on the other end of the config is a page that
    misleads precisely when it matters.
    """
    catalog = mcpprobe.catalog()
    result = mcpprobe.probe()

    assert result.ok, f"the server did not start: {result.error}"
    assert tuple(t.name for t in catalog.tools) == result.tools


def test_the_boundary_check_is_computed_rather_than_asserted():
    """`boundary_holds` must be capable of going false.

    A green badge means nothing unless the code behind it can go red. The
    carve-out proves the machinery works: `verify_proof` genuinely does take a
    `policy`, and it is excluded by name — so the intersection is doing real work
    on a real schema, not returning empty because it never looks.
    """
    catalog = mcpprobe.catalog()
    assert catalog.boundary_holds
    assert not catalog.offenders

    stateless = next(t for t in catalog.tools if t.name == mcpprobe.STATELESS_TOOL)
    assert mcpprobe.AUTHORITY_PARAMS & set(stateless.params), (
        "the deliberate exception no longer takes a policy, so the exclusion is "
        "hiding nothing and the boundary check is unexercised"
    )


def test_only_one_tool_writes_and_the_page_names_it(signed_in):
    client, _user_id, _ = signed_in
    catalog = mcpprobe.catalog()
    assert catalog.writes == ("run_close",)

    body = client.get("/mcp").text
    for tool in catalog.tools:
        assert tool.name in body, f"{tool.name} is exposed and not shown on the page"


# ------------------------------------------------------------------ the check


def test_the_check_starts_a_real_process_and_reports_what_happened(signed_in):
    client, _user_id, _ = signed_in
    token = client.cookies.get(auth.CSRF_COOKIE, "")
    body = client.post("/mcp/check", data={"csrf": token}).text

    assert "server answered" in body
    assert re.search(r"handshake \d+ ms", body)
    assert "7." in body, "the contract version read off the wire is not shown"


def test_a_probe_that_cannot_connect_reports_the_reason_not_a_crash(monkeypatch):
    """The page exists to diagnose a broken connection. If it 500s when the
    connection is broken, it has inverted its own purpose."""
    monkeypatch.setattr(
        mcpprobe, "serve_command", lambda: ("/nonexistent/python", ["-m", "recon.mcp.server"])
    )
    result = mcpprobe.probe(timeout=10)

    assert not result.ok
    assert result.error, "a failure with no reason is not a diagnosis"
    assert result.hint, "a failure with no remedy is a dead end"


def test_the_check_needs_a_session_and_a_token(signed_in, tmp_path, monkeypatch):
    """It spawns a process. Anything that spawns a process needs both."""
    client, _user_id, _ = signed_in
    assert client.post("/mcp/check", data={"csrf": "wrong"}).status_code == 403

    from fastapi.testclient import TestClient

    from recon.api.app import app

    with TestClient(app, follow_redirects=False) as anon:
        assert anon.post("/mcp/check", data={"csrf": "x"}).status_code in (303, 401, 403)
        assert anon.get("/mcp").status_code in (303, 401)
