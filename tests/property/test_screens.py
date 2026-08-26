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
    """The structural half. *Which* kind of empty is
    `test_the_worklist_says_which_kind_of_empty_it_is`; this one only asks that
    an empty state is a message and not a table with no rows in it."""
    client, _, _ = session
    page = client.get("/worklist").text
    assert "class='empty'" in page, "an empty worklist renders no empty state at all"
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
    from recon import service

    authority = service.authority("settlement_3way")
    assert authority.policy.ref in body, "the page does not name the policy in force"

    # The *number*, not the label above it. Pinning "Tolerance ceiling" made this
    # test fail for a rewrite rather than for a regression, and the thing that
    # must never disappear is the figure a person is being held to.
    from recon.api.theme import money

    assert money(authority.policy.tolerance_ceiling) in body, (
        "the tolerance a close absorbs silently is not shown anywhere"
    )
    assert authority.policy.approved_by in body, "the ceiling is shown and nobody owns it"

    # And it must say, in some words, that this is not the place to change it.
    assert "cannot be changed" in body or "read only" in body.lower(), (
        "the page shows the authority without saying it is not editable here"
    )

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
    # One button, and only one. The page carried a "Load sample data" per loop
    # plus a third at the bottom, so a person had to guess which one gave them a
    # working example — the answer being all of them, separately.
    assert body.count("action='/sources/sample'") == 1, (
        f"{body.count(chr(39).join(['action=', '/sources/sample', '']))} sample buttons on one page"
    )
    # Bring your own is still on the page, collapsed rather than removed: it is
    # the second thing a person does, not the first, and four file pickers open
    # by default were most of why this screen read as a form to fill in.
    assert "Add a period of your own" in body
    assert "<details>" in body, "the upload form is open by default again"
    assert "enctype='multipart/form-data'" in body, "the upload form cannot carry a file"

    # And each picker says what to go and find, not just what we save it as.
    assert "Bank statement" in body and "Gateway settlement report" in body, (
        "the upload boxes are labelled by filename only, so a person cannot tell "
        "which of their files goes where"
    )


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


def test_the_worklist_tells_a_solved_break_from_an_unsolved_one(tmp_path, monkeypatch):
    """Three states that need three different things from a person.

    Before this they all rendered as bold text and a paragraph, so a break the
    engine had *solved* looked exactly like one it had given up on — and the
    ambiguity's four-sentence explanation, which is correct because it has to say
    how to resolve it, filled the cell and buried the twenty rows that were named.
    """
    from tests.conftest import close_and_wait, signed_in_client

    client, _user_id, _runs = signed_in_client(monkeypatch, tmp_path)
    close_and_wait(client, loop="tds_26as", source_set="FY2627")
    body = client.get("/worklist").text

    assert "badge-ok'>derived" in body, "a code the arithmetic named is not marked as derived"
    assert "either / or" in body, "a derived ambiguity is not marked as one"
    assert "these files cannot separate them" in body

    # The long explanation belongs on the item page, not in a table cell.
    assert "ask the deductor for the challan" not in body, (
        "the full ambiguity reason is in the worklist row again"
    )


def test_every_worklist_row_opens_the_item_it_describes(tmp_path, monkeypatch):
    """The page a controller starts the day on had no way to open anything on
    it — every row described work with no door into it."""
    import re

    from tests.conftest import close_and_wait, signed_in_client

    client, _user_id, _runs = signed_in_client(monkeypatch, tmp_path)
    page = close_and_wait(client, loop="tds_26as", source_set="FY2627")
    run_id = str(page.url).rsplit("/", 1)[-1]

    body = client.get("/worklist").text
    links = set(re.findall(r"/periods/[^/']+/items/(EXC-\d+)", body))
    # Eleven derived breaks plus seven ambiguities. Fewer than the number of
    # unmatched rows, because the two sides of one break are one item.
    assert len(links) >= 18, f"only {len(links)} of the worklist rows link to an item"

    opened = client.get(f"/periods/{run_id}/items/{sorted(links)[0]}")
    assert opened.status_code == 200
    assert "near miss" in opened.text, (
        "the item page does not show the near-miss evidence the code was derived from"
    )


def test_verify_lets_a_signed_in_person_re_check_their_own_close(tmp_path, monkeypatch):
    """The page had two readers and served one.

    An auditor with a terminal got four correct steps of curl. A controller who
    had just run a close got the same four steps, when their version of the
    question is "re-check the one I just ran" and the answer is a button.
    """
    from tests.conftest import close_and_wait, signed_in_client

    client, _user_id, _runs = signed_in_client(monkeypatch, tmp_path)
    page = close_and_wait(client, loop="settlement_3way", source_set="A")
    run_id = str(page.url).rsplit("/", 1)[-1]

    body = client.get("/verify").text
    assert run_id in body, "the page does not offer the close this account just ran"
    assert f"/periods/{run_id}/reverify" in body, "there is no way to re-check it"

    # And the stranger's route is still there — losing it would undercut the
    # claim the page exists to make.
    assert "/v1/verify" in body
    assert "sha256" in body


def test_verify_works_with_no_account_at_all(tmp_path):
    """Requiring a login to check our arithmetic would undercut the exact claim
    this page makes. It renders signed out, and says how, without a session."""
    from fastapi.testclient import TestClient

    from recon.api.app import app

    with TestClient(app, follow_redirects=False) as anon:
        response = anon.get("/verify")

    assert response.status_code == 200
    assert "/v1/verify" in response.text
    assert "Sign in" in response.text, "no way back to the product from the public page"
    assert "Your closes" not in response.text, "a signed-out visitor is shown somebody's runs"


def test_settings_explains_why_it_is_read_only_rather_than_looking_unfinished(session):
    """A screen full of values and no controls reads as half-built unless it says
    why. The reason is the whole control plane: a system where the person being
    judged can edit the judgement has no control at all."""
    client, _, _ = session
    body = client.get("/settings").text

    assert "signed bundles" in body
    assert "re-signed" in body or "untrusted" in body, (
        "the page does not say what happens if somebody edits a bundle anyway"
    )
    # Each table says what it is *for*, not just what is in it.
    for phrase in ("Naming grants nothing", "regression"):
        assert phrase in body, f"a table on settings is unexplained: {phrase!r} missing"


def test_resolving_an_item_takes_it_off_the_worklist(tmp_path, monkeypatch):
    """The disposition panel promises exactly this and the worklist did not do it.

    An exception is *raised* in the close's record and *ended* in the review log.
    The worklist read the first and never the second, so a person could book,
    chase and write off every item in a close and watch the count stay where it
    was — which makes resolving pointless and the good ending unreachable.
    """
    from recon import service
    from recon.api import auth
    from tests.conftest import close_and_wait, signed_in_client

    client, _user_id, runs = signed_in_client(monkeypatch, tmp_path)
    page = close_and_wait(client, loop="settlement_3way", source_set="A")
    run_id = str(page.url).rsplit("/", 1)[-1]

    before = service.view(run_id, runs).exceptions
    assert before, "batch A raised nothing, so this test has no subject"
    assert str(len(before)) in client.get("/worklist").text

    token = client.cookies.get(auth.CSRF_COOKIE, "")
    first = before[0].exception
    client.post(
        f"/periods/{run_id}/items/{first.exception_id}/dispose",
        data={
            "disposition": "chase",
            "rationale": "gateway says sent, bank never received",
            "owner": "meera",
            "due_on": "2026-09-30",
            "csrf": token,
        },
    )

    body = client.get("/worklist").text
    assert f"items/{first.exception_id}" not in body, "a resolved item is still on the worklist"
    # And the record still holds it — resolving ends an item, it does not erase it.
    assert len(service.view(run_id, runs).exceptions) == len(before)


def test_the_worklist_says_which_kind_of_empty_it_is(tmp_path, monkeypatch):
    """Three opposite situations shared one sentence: "either no close has been
    run yet, or every item has been cleared". That is a screen shrugging — and
    one of the three is somebody having just finished a month's work, which is
    the moment the product should be clearest and was instead at its vaguest."""
    from recon import service
    from recon.api import auth
    from tests.conftest import close_and_wait, signed_in_client

    client, _user_id, runs = signed_in_client(monkeypatch, tmp_path)

    fresh = client.get("/worklist").text
    assert "Nothing here yet" in fresh
    assert "Close a period" in fresh, "a new account is not told what to do next"

    page = close_and_wait(client, loop="settlement_3way", source_set="A")
    run_id = str(page.url).rsplit("/", 1)[-1]
    token = client.cookies.get(auth.CSRF_COOKIE, "")
    for item in service.view(run_id, runs).exceptions:
        client.post(
            f"/periods/{run_id}/items/{item.exception.exception_id}/dispose",
            data={
                "disposition": "chase",
                "rationale": "chasing the gateway",
                "owner": "meera",
                "due_on": "2026-09-30",
                "csrf": token,
            },
        )

    worked = client.get("/worklist").text
    assert "Nothing left to work" in worked
    assert "matches proven" in worked, "the good ending does not say what was achieved"
    assert "your signature" in worked, "it does not say what is left to do"
    assert "&amp;mdash;" not in worked, "an html entity is rendering as literal text"

    client.post(f"/periods/{run_id}/signoff", data={"csrf": token, "note": "October"})
    done = client.get("/worklist").text
    assert "This month is done" in done
    assert f"/periods/{run_id}/pack" in done, "the finished state does not offer the pack"


def test_an_empty_desk_is_not_the_same_as_an_empty_worklist(tmp_path, monkeypatch):
    """A filter with nothing behind it is a filter, not an achievement — and the
    items are somebody else's, so it must not congratulate anybody."""
    from tests.conftest import close_and_wait, signed_in_client

    client, _user_id, _runs = signed_in_client(monkeypatch, tmp_path)
    close_and_wait(client, loop="settlement_3way", source_set="A")

    body = client.get("/worklist?owner=nobody-at-all").text
    assert "Nothing on the nobody-at-all desk" in body
    assert "open on other desks" in body
    assert "done" not in body.lower().split("nothing on the")[1][:200]
