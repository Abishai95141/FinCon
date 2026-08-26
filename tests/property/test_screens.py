"""Every destination the rail offers must lead somewhere real.

A nav item that 404s or renders an empty shell is worse than one that is not
there, and the way it happens is exactly what happened here: the routes were
built one at a time and the rail listed all of them from the start. So this
walks what the rail actually renders and follows every link, rather than
checking a list somebody remembered to update.

The rest is about presenting data honestly under pressure — an empty worklist
that says so, a decision log that is readable rather than a JSON dump, and a
settings page that shows the authority without offering a way to change it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from recon import service
from tests.conftest import close_and_wait, signed_in_client

LOOP = "settlement_3way"
BATCH = "A"


@pytest.fixture
def session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    return signed_in_client(monkeypatch, tmp_path)


@pytest.fixture
def closed(session):
    client, _, runs_root = session

    page = close_and_wait(client, loop=LOOP, source_set=BATCH)
    return client, str(page.url).rsplit("/", 1)[-1], runs_root


def test_every_rail_destination_loads(session):
    """Followed from the markup, not from a list. A rail that grew a fifth item
    would otherwise be checked by four assertions."""
    client, _, _ = session
    rail = client.get("/periods").text
    nav = re.search(r"<nav class='nav'>(.*?)</nav>", rail, re.S)
    assert nav, "the shell renders no navigation at all"
    links = re.findall(r"href='(/[^']*)'", nav.group(1))
    assert len(links) >= 5, f"the rail offers only {links}"
    for href in links:
        page = client.get(href)
        assert page.status_code == 200, f"{href} -> {page.status_code}"
        assert "<h1>" in page.text, f"{href} renders no page heading"
        assert "Not built" not in page.text, f"{href} is still a dead end"


def test_the_worklist_gathers_every_close(closed):
    client, run_id, _ = closed
    page = client.get("/worklist")
    assert page.status_code == 200
    view = service.view(run_id, _runs(client))
    for item in view.exceptions:
        assert item.exception.code in page.text
    assert "at stake" in page.text, "the worklist does not total the money on the desk"
    assert "All desks" in page.text


def test_an_empty_worklist_says_so_rather_than_rendering_a_blank_table(session):
    client, _, _ = session
    page = client.get("/worklist").text
    assert "Nothing on this desk" in page
    assert "<table>" not in page, "an empty state that is still a table is not an empty state"


def test_the_decision_log_is_readable_not_a_json_dump(closed):
    client, run_id, _ = closed
    page = client.get(f"/periods/{run_id}/log")
    assert page.status_code == 200
    body = page.text

    assert "class='log'" in body, "the log is not rendered as a timeline"
    assert "CloseStarted" in body and "MatchProven" in body
    assert "chain holds" in body
    assert "not custody" in body, "the page overclaims what a hash chain proves"
    # The counts at the top are the shape of the close, which is the first thing
    # a reader wants and the last thing raw JSON gives them.
    assert re.search(r"MatchProven <span class='num'>\d+</span>", body)
    assert "Raw JSON" in body, "no escape hatch to the machine-readable form"


def test_the_decision_log_pages_without_losing_events(closed):
    client, run_id, _ = closed
    total = service.event_page(run_id, runs_dir=_runs(client)).total
    seen, offset, guard = 0, 0, 0
    while True:
        page = client.get(f"/periods/{run_id}/log?offset={offset}").text
        seen += page.count("class='ev ")
        guard += 1
        assert guard < 20, "the log pager is not advancing"
        nxt = re.search(r"log\?offset=(\d+)'>\s*Next", page)
        if not nxt:
            break
        offset = int(nxt.group(1))
    assert seen == total, f"walked {seen} events over pages, the log holds {total}"


def test_settings_shows_the_authority_and_offers_no_way_to_change_it(session):
    """The rule the whole control plane rests on, at the one screen most likely
    to break it: a settings page is where a tolerance would end up."""
    client, _, _ = session
    body = client.get("/settings").text
    assert "settlement-in@v1" in body
    assert "Tolerance ceiling" in body
    assert "read only" in body.lower()

    forms = re.findall(r"<form[^>]*>", body)
    assert all("logout" in f for f in forms), f"settings offers a mutating form: {forms}"
    assert "<input class='input'" not in body, "settings offers an editable field"


def test_data_sources_lists_the_adapters_and_what_has_arrived(session):
    client, _, _ = session
    body = client.get("/sources").text
    assert "bank_icici_camt053.xml" in body
    assert "settlement.csv" in body
    assert "icici-camt" in body
    assert "ready to close" in body, "no period is shown as closeable"
    # The two ways in, both on the page: bring your own, or load the shipped
    # examples. A product whose first screen offers neither is a product nobody
    # can start.
    assert "Load sample data" in body
    assert "Upload a period" in body
    assert "enctype='multipart/form-data'" in body, "the upload form cannot carry a file"


def test_the_close_page_leads_with_the_period_it_ran_on(closed):
    """The re-derive control defaults to the files whose hashes match the record.
    Offering the others as equals is what produced twenty meaningless
    refutations and a page that read like an accusation."""
    client, run_id, runs_root = closed
    body = client.get(f"/periods/{run_id}").text
    assert "Re-derive this close" in body
    assert "check against other files" in body
    from recon.api import auth as auth_mod
    from recon.api.ui import tenant_sources

    user = auth_mod.read(client.cookies[auth_mod.SESSION_COOKIE], auth_mod.session_secret())
    assert service.source_set_of(run_id, runs_root, root=tenant_sources(user)) == BATCH


def _runs(client: TestClient) -> Path:
    from recon.api import auth

    user = auth.read(client.cookies[auth.SESSION_COOKIE], auth.session_secret())
    return service.runs_root(None) / user.user_id


def test_no_grid_lets_a_code_block_widen_the_page():
    """`1fr` is `minmax(auto, 1fr)`, and the auto minimum is the width of the
    widest thing inside the track.

    A `<pre>` with `white-space:pre` is therefore free to push its own column
    past the viewport, taking the whole page with it — which is what the MCP
    config blocks did on 2026-08-26: the screenshot showed the JSON running off
    the right edge with no scrollbar anywhere.

    `overflow-x:auto` on the block cannot fix it. The block scrolls only if
    something above it refuses to grow, and every ancestor grid has to say so.
    """
    import importlib
    import re

    theme = importlib.import_module("recon.api.theme")
    css = next(
        v
        for _k, v in vars(theme).items()
        if isinstance(v, str) and ".panel{" in v and len(v) > 5000
    )

    bare = re.findall(r"grid-template-columns:\s*1fr\b[^;}]*", css)
    assert not bare, f"grids that can be widened from inside: {bare}"

    assert "min-width:0" in css, "no flex/grid child declares a zero minimum"
    for selector in (".snip", ".tbl"):
        assert f"{selector}{{" in css or f"{selector} " in css
    assert "overflow-x:auto" in css
