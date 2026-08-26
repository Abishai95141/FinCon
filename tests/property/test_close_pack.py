"""The artifact a controller leaves with.

The approved journey ends here: *"Where are my results?"* — one page holding the
figures, the evidence, the journal, the tail, the authority, and how to check the
lot without us. Everything on it is rebuilt from the record, so a pack a
regulator reads is a pack an auditor can reproduce.

Two properties matter more than the rest, and both are about not overclaiming.
A pack must never present an unsigned close as approved, and it must say what it
is *missing* — the ledger is asserted in memory and never written to a file, and
a page listing journal entries without saying so would imply a durability this
build does not have.
"""

from __future__ import annotations

import csv
import io
import re
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from recon import review, service
from recon.api import auth
from recon.api.theme import money
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


def test_an_unsigned_close_says_so_at_the_top(closed):
    """The first thing a reader looks at must not imply an approval nobody gave."""
    client, run_id, _ = closed
    body = client.get(f"/periods/{run_id}/pack").text
    head = body[: body.index("What this close decided")]
    assert "Not signed off" in head
    assert "nobody has approved it" in head
    assert "Signed off by" not in head


def test_a_signed_pack_names_the_person_and_what_was_open(closed):
    client, run_id, runs_root = closed
    for exception_id in service.view(run_id, runs_root).blocking_exceptions:
        client.post(f"/periods/{run_id}/items/{exception_id}/acknowledge", data=_form(client))
    client.post(f"/periods/{run_id}/signoff", data=_form(client, note="October reconciled"))

    body = client.get(f"/periods/{run_id}/pack").text
    state = review.state(run_id, runs_root)
    assert f"Signed off by {state.signed_off_by}" in body
    assert "October reconciled" in body
    assert f"{state.still_open} item(s) still open at signature" in body
    assert "Not signed off" not in body


def test_the_pack_carries_the_evidence_chain(closed):
    """Hashes, and the spec that turns them back into records. Without both, "go
    and check" is an instruction nobody can follow."""
    client, run_id, runs_root = closed
    body = client.get(f"/periods/{run_id}/pack").text
    bundle = service.audit(run_id, runs_root, limit=10_000)

    assert bundle.sources, "the pack has no sources to cite"
    for source in bundle.sources:
        assert source["doc_hash"][:24] in body, f"{source['source']} has no hash on the pack"
        assert source["spec_id"] in body
    assert "re-ingesting the same files" in body.lower()


def test_the_pack_states_what_it_does_not_have(closed):
    """No ledger *file* is stored. The journal is re-derived from the decision
    log on request, which is stronger than a stored file — but the pack must not
    imply we keep a ledger, and it must still name what it never measured."""
    client, run_id, _ = closed
    body = client.get(f"/periods/{run_id}/pack").text
    assert "computed and thrown away" in body, "the pack hides that this was the gap"
    assert "absent" in body, "blocking recall is shown as a number rather than as absent"
    assert "not custody" in body, "the pack overclaims what a hash chain proves"


def test_every_posting_and_every_open_item_is_on_the_pack(closed):
    client, run_id, runs_root = closed
    body = client.get(f"/periods/{run_id}/pack").text
    view = service.view(run_id, runs_root)
    bundle = service.audit(run_id, runs_root, limit=10_000)

    assert f"{len(bundle.postings)} entries" in body
    for posting in bundle.postings:
        assert posting["narration"] in body
    for item in view.exceptions:
        assert item.exception.code in body
        assert money(item.exception.amount) in body
        assert item.owner in body


def test_the_pack_is_printable_and_reachable(closed):
    """A close pack is handed over, so it has to survive Ctrl+P — and it has to
    be findable from the close, or it is a page nobody opens."""
    client, run_id, _ = closed
    body = client.get(f"/periods/{run_id}/pack").text
    assert "@media print" in body
    assert ".rail,.crumb-row,.noprint{display:none" in body.replace(" ", "")

    close_page = client.get(f"/periods/{run_id}").text
    assert f"/periods/{run_id}/pack" in close_page, "the close does not link its own pack"


def test_the_pack_comes_from_the_record(closed):
    """Same rule as every other screen: edit the log and the pack changes. A
    pack served from the run that produced it would be a second copy of the
    truth, and the copy nobody reads is the one that rots."""
    client, run_id, runs_root = closed
    log = runs_root / run_id / "decisions.jsonl"
    before = client.get(f"/periods/{run_id}/pack").text
    assert re.search(r"\d+ entries", before)

    lines = [ln for ln in log.read_text().splitlines() if '"PostingWritten"' not in ln]
    log.write_text("\n".join(lines) + "\n")
    after = client.get(f"/periods/{run_id}/pack").text
    assert "0 entries" in after, "the pack still shows postings the record no longer holds"


def test_one_account_cannot_read_anothers_pack(tmp_path, monkeypatch):
    alice, _, _ = signed_in_client(monkeypatch, tmp_path, email="alice@acme.in")
    page = close_and_wait(alice, loop=LOOP, source_set=BATCH)
    run_id = str(page.url).rsplit("/", 1)[-1]
    assert alice.get(f"/periods/{run_id}/pack").status_code == 200

    bob, _, _ = signed_in_client(monkeypatch, tmp_path, email="bob@acme.in", sample=False)
    assert bob.get(f"/periods/{run_id}/pack").status_code == 404


# ---------------------------------------------------------------------------
# The journal export
#
# Until 2026-08-26 `post_and_assert` rendered a complete beancount ledger into
# `CloseResult.text` and *nothing read it*. The books tied, the assertion held,
# and the one artifact a controller actually needs — the entries to post — was
# computed and dropped. A close that proves twenty matches and hands back no
# journal has done the hard half of the work and none of the useful half.
#
# These assert the export exists, balances, and is rebuilt from the decision
# log rather than from the live close — because the log is the thing we ask a
# third party to trust, and an export the log cannot produce is an export only
# we can vouch for.
# ---------------------------------------------------------------------------


def _rows(export: service.JournalExport) -> list[dict[str, str]]:
    """Parsed as a CSV reader would, not split on commas — the file ships CRLF
    per RFC 4180 because a controller opens it in Excel or feeds it to Tally."""
    return list(csv.DictReader(io.StringIO(export.csv)))


def test_the_journal_is_double_entry_and_every_entry_balances(closed):
    _client, run_id, runs_root = closed
    export = service.journal(run_id, runs_root)

    assert export.entries > 0, "a close that posted nothing is not the corpus we ship"
    assert export.balanced

    by_entry: dict[str, list[Decimal]] = {}
    for row in _rows(export):
        by_entry.setdefault(row["entry_id"], []).append(Decimal(row["amount"]))

    assert len(by_entry) == export.entries
    for entry_id, amounts in by_entry.items():
        assert len(amounts) >= 2, f"{entry_id} is a single-sided posting"
        assert sum(amounts) == 0, f"{entry_id} does not balance: {amounts}"


def test_every_journal_line_names_the_decision_it_came_from(closed):
    """A line with no origin is a number a controller cannot defend to an auditor."""
    _client, run_id, runs_root = closed
    export = service.journal(run_id, runs_root)
    view = service.view(run_id, runs_root)
    known = {m.proof_id for m in view.matches} | {e.exception.exception_id for e in view.exceptions}

    origins = {row["origin"] for row in _rows(export)}
    assert origins
    assert origins <= known, f"journal cites decisions not in the record: {origins - known}"


def test_an_exception_that_raised_no_entry_is_named_not_omitted(closed):
    """Silence about an unposted break is how value leaves a close unnoticed."""
    _client, run_id, runs_root = closed
    export = service.journal(run_id, runs_root)
    view = service.view(run_id, runs_root)

    posted = {row["origin"] for row in _rows(export)}
    silent = {
        e.exception.exception_id for e in view.exceptions if e.exception.exception_id not in posted
    }
    named = {line.split(" ")[0] for line in export.unposted}
    assert named == silent, f"unposted exceptions unaccounted for: {silent - named}"


def test_the_journal_downloads_as_a_file_a_controller_can_import(closed):
    client, run_id, _ = closed
    csv = client.get(f"/v1/runs/{run_id}/journal.csv")
    assert csv.status_code == 200
    assert csv.headers["content-type"].startswith("text/csv")
    assert run_id in csv.headers["content-disposition"]
    assert csv.text.startswith("entry_id,date,narration,account,amount,currency,origin")

    bean = client.get(f"/v1/runs/{run_id}/journal.beancount")
    assert bean.status_code == 200
    assert "Assets:Bank" in bean.text
    assert "origin:" in bean.text, "a beancount line with no provenance is unauditable"


def test_the_pack_hands_over_the_journal_rather_than_only_displaying_it(closed):
    client, run_id, _ = closed
    body = client.get(f"/periods/{run_id}/pack").text
    assert f"/v1/runs/{run_id}/journal.csv" in body
    assert f"/v1/runs/{run_id}/journal.beancount" in body


def test_the_journal_belongs_to_the_account_that_closed_it(closed, tmp_path, monkeypatch):
    """The export is a new route, and a new route is a new chance to leak."""
    _client, run_id, _ = closed
    other, _, _ = signed_in_client(monkeypatch, tmp_path / "other", email="rival@other.in")
    response = other.get(f"/v1/runs/{run_id}/journal.csv")
    assert response.status_code != 200
    assert "Assets:Bank" not in response.text, "the journal crossed an account boundary"


def test_beancount_itself_parses_what_we_export(closed, tmp_path):
    """The strongest check available on an export: hand it to the parser we do
    not control and see whether it objects.

    Our own assertion that the books balance is our arithmetic checking our
    arithmetic. `beancount.loader` is a third party, it knows nothing about this
    project, and if the account names, dates, syntax or amounts are wrong it says
    so. Zero errors here is the difference between "we think this imports" and
    "this imports".
    """
    loader = pytest.importorskip("beancount.loader")
    _client, run_id, runs_root = closed

    ledger = tmp_path / f"{run_id}.beancount"
    ledger.write_text(service.journal(run_id, runs_root).beancount)
    entries, errors, _options = loader.load_file(str(ledger))

    assert not errors, f"beancount rejected our own export: {errors[:3]}"
    txns = [e for e in entries if type(e).__name__ == "Transaction"]
    assert txns, "the export parsed but contains no transactions"
    for txn in txns:
        assert sum((p.units.number for p in txn.postings), start=0) == 0
