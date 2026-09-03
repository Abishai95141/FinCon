"""One screen must not print two answers to one question.

The close page carries the blocking count twice: a metric card reading
*"Awaiting sign-off — N exceptions a human must clear"*, and the sign-off panel
reading *"N item(s) still need a human"*. They were computed from different
sources — the card from `view.blocking_exceptions`, which is what the close
**raised**, and the panel from `review.blockers`, which is what a human has
since **taken**.

So a signed close rendered *"Signed off by controller@fincon.demo"* in the
breadcrumb, beside a card insisting five exceptions still needed clearing. Both
numbers were correct answers to different questions and the page asked only one.

Found while filming: the demo's hero screen contradicted itself for the length
of a shot, which is exactly the kind of thing a still screenshot never catches
and thirty continuous seconds of footage does.

It is also the same defect this project has now fixed three times — an exception
is *raised* in the close's record and *ended* in the review log, and reading only
the first makes resolving invisible. The worklist had it; the disposition count
had it; this had it.
"""

from __future__ import annotations

import re

import pytest

from recon import review, service

RUN = "A"


@pytest.fixture
def closed(tmp_path, monkeypatch):
    """A signed-in client whose account holds a real close, taken from batch A.

    Copied into the tenant rather than pointed at `data/runs/` so the test can
    acknowledge items without writing into the repository.
    """
    import shutil
    from pathlib import Path

    from tests.conftest import signed_in_client

    client, _user_id, runs_root = signed_in_client(monkeypatch, tmp_path)
    src = Path("data/runs") / RUN
    if not src.exists():
        pytest.fail(f"{src} is absent — run `make eval` first")
    runs_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, runs_root / RUN)
    stale = runs_root / RUN / review.FILENAME
    if stale.exists():
        stale.unlink()
    return client, runs_root


def _card(body: str) -> int:
    """The metric card's number, off the rendered page."""
    m = re.search(r"Awaiting sign-off.*?<div class='v[^']*'>(\d+)</div>", body, re.S) or re.search(
        r"Awaiting sign-off.*?>(\d+)<", body, re.S
    )
    assert m, "the close page no longer renders an 'Awaiting sign-off' metric"
    return int(m.group(1))


def _panel(body: str) -> int:
    """The sign-off panel's number. Zero when it says the close is signed."""
    m = re.search(r"<b>(\d+) item\(s\) still need a human", body)
    return int(m.group(1)) if m else 0


def test_the_two_blocking_counts_on_one_page_agree(closed):
    """Before anybody has touched it, and after each item is taken."""
    client, runs = closed

    body = client.get(f"/periods/{RUN}").text
    assert _card(body) == _panel(body), (
        "the metric card and the sign-off panel disagree on how many items need "
        "a human, which means one of them is reading the close record and the "
        "other the review log"
    )

    view = service.view(RUN, runs)
    blocking = review.blockers([e.exception for e in view.exceptions], review.state(RUN, runs))
    if not blocking:
        pytest.fail(
            "this close has no blocking exception, so the disagreement cannot be "
            "reached — a corpus problem to look at, not a test to skip"
        )

    # Take them one at a time. The card must fall in step with the panel; before
    # the fix it stayed frozen at whatever the close raised.
    for taken, exception_id in enumerate(blocking, start=1):
        client.post(
            f"/periods/{RUN}/items/{exception_id}/acknowledge",
            data={"note": "", "csrf": _token(client, f"/periods/{RUN}/items/{exception_id}")},
            follow_redirects=True,
        )
        body = client.get(f"/periods/{RUN}").text
        assert _card(body) == _panel(body), (
            f"after taking {taken} of {len(blocking)}, the card says {_card(body)} "
            f"and the panel says {_panel(body)}"
        )

    body = client.get(f"/periods/{RUN}").text
    assert _card(body) == 0, (
        "every blocking item has been taken and the card still reports work "
        "outstanding — it is reading what the close raised, not what a human did"
    )


def _token(client, path: str) -> str:
    m = re.search(r"name='csrf' value='([^']+)'", client.get(path).text)
    assert m, f"no csrf token on {path}"
    return m.group(1)
