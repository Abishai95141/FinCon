"""The guided tour — every step must find its own page and its own anchor.

A tour step is two halves that live in different files: an entry in
`tour.STEPS`, and a `data-tour` attribute somewhere in `ui.py`. When they drift
the failure is silent in the worst way — the veil goes up, the page dims, and
nothing lights, so the product looks broken to the person the tour exists to
reassure. Nothing about rendering a page notices.

So this walks the real steps against the real routes, and it is the reason the
highlight CSS is generated from `STEPS` rather than hand-written.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from recon.api import tour
from tests.conftest import signed_in_client


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    made, _user, _root = signed_in_client(monkeypatch, tmp_path)
    return made


@pytest.mark.parametrize("index", range(tour.TOTAL), ids=[s.key for s in tour.STEPS])
def test_every_step_arms_its_own_highlight(client: TestClient, index: int):
    """The page renders, the body class matches, and the anchor is on it."""
    step = tour.STEPS[index]
    page = client.get(f"{step.route}?tour={index}")
    assert page.status_code == 200, f"{step.route} did not render"
    body = page.text
    assert f"tour-at-{step.key}" in body, "the body class that arms the CSS is absent"
    assert f"data-tour='{step.key}'" in body, (
        f"step {index} dims {step.route} and lights nothing — no element carries "
        f"data-tour='{step.key}'"
    )
    assert f".tour-at-{step.key} [data-tour='{step.key}']" in body, (
        "the generated highlight rule for this step is not in the stylesheet"
    )


@pytest.mark.parametrize("index", range(tour.TOTAL), ids=[s.key for s in tour.STEPS])
def test_every_step_can_be_left(client: TestClient, index: int):
    """Skip goes to the plain route; the last step offers Finish, not Next.

    A tour with no exit is a modal nobody asked for.
    """
    step = tour.STEPS[index]
    body = client.get(f"{step.route}?tour={index}").text
    assert f"href='{step.route}'" in body, "no way out of this step"
    if index == tour.TOTAL - 1:
        assert ">Finish</a>" in body and ">Next</a>" not in body
    else:
        nxt = tour.STEPS[index + 1]
        assert f"href='{nxt.route}?tour={index + 1}#{nxt.key}'" in body, (
            "Next must carry the fragment — it is what scrolls the spotlight into "
            "view, and it is the whole reason this needs no JavaScript"
        )


def test_the_tour_ships_no_javascript(client: TestClient):
    """`gate_p14` asserts the product needs none. A tour is not the exception."""
    for index, step in enumerate(tour.STEPS):
        body = client.get(f"{step.route}?tour={index}").text.lower()
        assert "<script" not in body, f"step {index} ships JavaScript"
        assert "onclick" not in body, f"step {index} carries an inline handler"


def test_a_page_with_no_step_is_untouched(client: TestClient):
    """The tour costs nothing when it is not running — including its stylesheet.

    Rendered unconditionally it would be dead weight on every page, and the
    `tour-` classes would sit in markup nobody was touring.
    """
    plain = client.get("/sources").text
    assert "tour-veil" not in plain and "tour-at-" not in plain
    assert ".tour-box{" not in plain, "the tour stylesheet rides along on every page"
    # Junk is not a tour. It must not arm one, and must not 500.
    for junk in ("banana", "-1", "99", ""):
        page = client.get(f"/sources?tour={junk}")
        assert page.status_code == 200
        assert "tour-veil" not in page.text, f"?tour={junk!r} armed a step"


def test_the_landing_screen_offers_the_tour(client: TestClient):
    """Where a person lands after signing in is where the tour starts."""
    from recon.api.ui import LANDING

    assert tour.STEPS[0].route == LANDING, (
        "the tour starts somewhere other than where a new account lands"
    )
    assert "tour-start" in client.get(LANDING).text, "no way in"


def test_signing_in_lands_on_the_first_screen_of_the_tour(client: TestClient):
    """Data sources, not Periods: it is the only screen that opens by saying
    what a reconciliation is, and a new account has no periods to look at."""
    landed = client.get("/")
    assert landed.url.path == tour.STEPS[0].route == "/sources"
