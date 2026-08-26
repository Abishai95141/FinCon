"""A close that finished is not a close somebody approved.

Until this landed the product showed one as the other: the scorecard said
`complete`, the badge said "Needs review", and there was nothing to review with.
That is a product claiming an approval nobody gave, which is the same class of
defect as an unmeasured thing reported as zero — a claim that flatters us for
free.

So the properties here are about the signature meaning something: it names a
person, it refuses while the books do not balance, it refuses while blocking
items are unopened, and it cannot be quietly revised afterwards. And it lives in
its *own* chained record, because `decisions.jsonl` seals at its terminator and
that is correct — what the engine decided and what a human decided are two
different statements.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from recon import review, service
from recon.api import auth
from tests.conftest import close_and_wait, signed_in_client

LOOP = "settlement_3way"
BATCH = "A"


@pytest.fixture
def closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    client, _, runs_root = signed_in_client(monkeypatch, tmp_path)
    page = close_and_wait(client, loop=LOOP, source_set=BATCH)
    return client, str(page.url).rsplit("/", 1)[-1], runs_root


def _form(client: TestClient, **fields) -> dict:
    return {**fields, "csrf": client.cookies.get(auth.CSRF_COOKIE, "")}


def test_a_finished_close_is_not_an_approved_one(closed):
    """The distinction the whole module exists for."""
    client, run_id, runs_root = closed
    view = service.view(run_id, runs_root)
    assert view.complete, "this close did not finish, so the test proves nothing"

    assert not review.state(run_id, runs_root).signed_off
    body = client.get(f"/periods/{run_id}").text
    assert "Needs review" in body
    assert "Signed off" not in body
    assert "still need a human" in body


def test_sign_off_refuses_while_blocking_items_are_unopened(closed):
    client, run_id, runs_root = closed
    view = service.view(run_id, runs_root)
    assert view.blocking_exceptions, "nothing blocks this close, so there is no gate to test"

    refused = client.post(f"/periods/{run_id}/signoff", data=_form(client, note="ship it"))
    assert refused.status_code == 422
    assert "nobody has taken" in refused.text
    assert not review.state(run_id, runs_root).signed_off


def test_taking_every_blocking_item_opens_the_gate(closed):
    client, run_id, runs_root = closed
    view = service.view(run_id, runs_root)

    for exception_id in view.blocking_exceptions:
        taken = client.post(
            f"/periods/{run_id}/items/{exception_id}/acknowledge",
            data=_form(client, note="checked against the gateway export"),
        )
        assert taken.status_code == 200, taken.text[:200]

    page = client.get(f"/periods/{run_id}").text
    assert "Sign off as" in page, "every blocker is taken and the gate is still shut"

    done = client.post(f"/periods/{run_id}/signoff", data=_form(client, note="October reconciled"))
    assert done.status_code == 200

    state = review.state(run_id, runs_root)
    assert state.signed_off
    assert "@" in state.signed_off_by, "the signature does not name a person"
    assert state.note == "October reconciled"
    assert review.problems(run_id, runs_root) == [], "the review record does not vouch for itself"

    # And every surface that shows a state has to show *this* one. A panel that
    # says signed beside a badge that says "Needs review" is the product
    # disagreeing with itself, which is worse than either answer alone.
    page = client.get(f"/periods/{run_id}").text
    assert "Needs review" not in page, "the close page still calls a signed close unreviewed"
    assert "Signed off by" in page
    assert "Needs review" not in client.get("/periods").text


def test_a_signed_close_cannot_be_quietly_revised(closed):
    client, run_id, runs_root = closed
    view = service.view(run_id, runs_root)
    for exception_id in view.blocking_exceptions:
        client.post(f"/periods/{run_id}/items/{exception_id}/acknowledge", data=_form(client))
    client.post(f"/periods/{run_id}/signoff", data=_form(client))

    later = client.post(
        f"/periods/{run_id}/items/{view.exceptions[0].exception.exception_id}/acknowledge",
        data=_form(client, note="second thoughts"),
    )
    assert later.status_code == 422
    assert "signed off" in later.text


def test_the_review_record_is_separate_from_the_decision_log(closed):
    """The close record seals at its terminator, and must stay sealed. A human
    decision appended to it would make the engine's record say something the
    engine never decided."""
    client, run_id, runs_root = closed
    exception_id = service.view(run_id, runs_root).blocking_exceptions[0]
    client.post(f"/periods/{run_id}/items/{exception_id}/acknowledge", data=_form(client))

    decisions = (runs_root / run_id / "decisions.jsonl").read_text()
    assert "ExceptionAcknowledged" not in decisions
    assert decisions.strip().splitlines()[-1].count("CloseCompleted") == 1

    assert (runs_root / run_id / "review.jsonl").exists()
    kinds = [e.kind.value for e in review.events(run_id, runs_root)]
    assert kinds == ["ExceptionAcknowledged"]


def test_the_signature_records_what_was_still_open(closed):
    """A signature on an unstated position says nothing. How much was still
    outstanding at the moment somebody put their name to it is part of the
    statement."""
    client, run_id, runs_root = closed
    view = service.view(run_id, runs_root)
    for exception_id in view.blocking_exceptions:
        client.post(f"/periods/{run_id}/items/{exception_id}/acknowledge", data=_form(client))
    client.post(f"/periods/{run_id}/signoff", data=_form(client))

    state = review.state(run_id, runs_root)
    assert state.still_open == len(view.exceptions) - len(view.blocking_exceptions)
    assert str(state.still_open) in client.get(f"/periods/{run_id}").text


def test_a_derived_label_cannot_be_reclassified_by_anyone(closed):
    """`E09` proved by enumerating two valid subsets is `P0`. A proposal is `P2`
    at best, and a *human accepting* one does not change that — the ordering is
    about evidence, not about who is asking."""
    client, run_id, runs_root = closed
    derived = [
        e
        for e in service.view(run_id, runs_root).exceptions
        if e.exception.code_provenance.value == "P0"
    ]
    assert derived, "this batch derived no label, so the guard is untested"
    target = derived[0].exception

    refused = client.post(
        f"/periods/{run_id}/items/{target.exception_id}/accept",
        data=_form(client, code="E01", hypothesis="a guess", model="test"),
    )
    assert refused.status_code == 422
    assert "higher proof tier" in refused.text
    assert target.exception_id not in review.state(run_id, runs_root).accepted


def test_the_item_page_says_a_derived_label_is_never_sent_to_a_model(closed):
    """Refusing after the call would still have spent it, and would invite the
    argument that the model would have been right."""
    client, run_id, runs_root = closed
    derived = [
        e
        for e in service.view(run_id, runs_root).exceptions
        if e.exception.code_provenance.value == "P0"
    ]
    body = client.get(f"/periods/{run_id}/items/{derived[0].exception.exception_id}").text
    assert "never sent to a model" in body
    assert "Ask the model for a reading" not in body


def test_an_unconfigured_model_is_reported_absent_not_missing(closed, monkeypatch):
    """Absent, named, and pointing at what would fix it — not a silent nothing."""
    from recon.triage.classify import reclassifiable

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    client, run_id, runs_root = closed
    # `!= "P0"` is not the same question: `P1 RULE` outranks a proposal too, so
    # an E06 a rule labelled is never offered to a model either. Ask the
    # ordering, not the label.
    open_item = next(
        e for e in service.view(run_id, runs_root).exceptions if reclassifiable(e.exception)
    )
    body = client.get(f"/periods/{run_id}/items/{open_item.exception.exception_id}").text
    assert "No model is configured" in body
    assert "absent" in body, "an unmeasured thing is being shown as a zero"
    assert "DEEPSEEK_API_KEY" in body, "the page does not say what would enable it"


def test_taking_an_item_resolves_nothing(closed):
    """Acknowledging is accountability, not resolution. If it started moving
    postings it would need the attestation path into the ledger, which is its
    own phase — and a button that implied otherwise would be the shallow proxy."""
    client, run_id, runs_root = closed
    before = service.view(run_id, runs_root)
    exception_id = before.blocking_exceptions[0]
    client.post(f"/periods/{run_id}/items/{exception_id}/acknowledge", data=_form(client))
    after = service.view(run_id, runs_root)

    assert after.tiers == before.tiers
    assert after.postings == before.postings
    assert [e.exception.amount for e in after.exceptions] == [
        e.exception.amount for e in before.exceptions
    ]
    assert after.exceptions[0].exception.code == before.exceptions[0].exception.code


def test_a_close_over_uploaded_files_is_the_same_close(tmp_path, monkeypatch):
    """Sample data is *copied* into the account, not read in place — so a first
    close runs over the account's own files and behaves exactly like one over a
    real bank statement. A demo mode reading a shared directory would be the
    second code path this codebase keeps refusing."""
    client, user_id, runs_root = signed_in_client(monkeypatch, tmp_path)
    sources = service.TENANT_SOURCES / user_id
    assert (sources / BATCH / "settlement.csv").exists(), "sample data was not copied in"
    assert not (sources / BATCH / "labels.json").exists(), "ground-truth labels were copied too"

    page = close_and_wait(client, loop=LOOP, source_set=BATCH)
    run_id = str(page.url).rsplit("/", 1)[-1]
    view = service.view(run_id, runs_root)
    assert view.tiers.matched == 20
    assert view.complete

    report = service.reverify(run_id, BATCH, root=sources, runs_dir=runs_root)
    assert report.holds, "a close over the account's own copy does not re-derive"


def test_an_upload_cannot_write_outside_its_period(tmp_path, monkeypatch):
    """Filenames come from the loop, never from the upload."""
    client, user_id, _ = signed_in_client(monkeypatch, tmp_path, sample=False)
    reply = client.post(
        "/sources/upload",
        data={"period": "../escape", "csrf": client.cookies[auth.CSRF_COOKIE]},
        files={"settlement.csv": ("settlement.csv", b"row_id\n", "text/csv")},
    )
    assert reply.status_code == 422
    assert "letters, digits" in reply.text
    assert not (service.TENANT_SOURCES / user_id).parent.joinpath("escape").exists()


def test_an_upload_lands_under_the_expected_name(tmp_path, monkeypatch):
    client, user_id, _ = signed_in_client(monkeypatch, tmp_path, sample=False)
    reply = client.post(
        "/sources/upload",
        data={"period": "OCT 2026", "csrf": client.cookies[auth.CSRF_COOKIE]},
        files={"settlement.csv": ("whatever-they-called-it.csv", b"row_id\n", "text/csv")},
    )
    assert reply.status_code == 200
    landed = service.TENANT_SOURCES / user_id / "OCT 2026"
    assert (landed / "settlement.csv").exists(), "the file did not land under the adapter's name"
    assert not (landed / "whatever-they-called-it.csv").exists()

    page = client.get("/sources").text
    # The *filename*, not the word around it. A half-arrived period has to name
    # what it is short of — "1 source missing" is not something anybody can act
    # on — but the sentence it sits in is copy and pinning that made this test
    # fail for a rewrite rather than for a regression.
    assert "bank_icici_camt053.xml" in page, "a half-arrived period does not name what it lacks"
    assert "ready to close" not in page.split("bank_icici_camt053.xml")[0][-400:], (
        "a period short of a file is offered as closeable"
    )


def test_one_account_cannot_reach_anothers_sources(tmp_path, monkeypatch):
    """One root, two accounts. Separate roots would prove nothing — isolation is
    only interesting when both tenants live in the same directory tree."""
    alice, alice_id, _ = signed_in_client(monkeypatch, tmp_path, email="alice@acme.in")
    bob, bob_id, _ = signed_in_client(monkeypatch, tmp_path, email="bob@acme.in", sample=False)
    assert alice_id != bob_id

    assert "ready to close" in alice.get("/sources").text
    assert "Nothing here yet" in bob.get("/sources").text
    refused = bob.post("/periods/close", data=_form(bob, loop=LOOP, source_set=BATCH))
    assert refused.status_code == 422
