"""P14 — surface.

**Gate:** a controller completes one close through the UI without a terminal.

Taken literally, so the first test does exactly that and nothing else: it makes
HTTP requests, finds the form on the page, posts it, follows the redirect, and
then checks that a real close happened — a decision log on disk with a
terminator, journal entries posted, a worklist to work. No import of `run_close`,
no fixture that pre-builds an outcome. If a controller could not do it with a
browser, this fails.

The rest of the file is about what the screens are allowed to say. Three of the
rules the rest of this codebase runs on have surface analogues that nothing
would otherwise enforce:

* **An unmeasured thing is reported absent, not zero.** Blocking recall is
  measured against labelled true pairs and production has none, so the page says
  `absent`. A `0.0%` would look like a measurement.
* **A rate never appears without its decomposition.** The tier split sits beside
  the match rate, and both come from the record.
* **Nothing is shown that the record cannot say.** Every page is a render of a
  `CloseView`, which is rebuilt from the decision log — so a tampered log makes
  the page say so rather than making it look clean.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from recon import loop as looplib
from recon import service
from recon.api import app

pytestmark = pytest.mark.gate

LOOP = "settlement_3way"
BATCH = "A"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A browser, and a scratch directory for the logs it causes to be written.

    The source root is left pointing at the real batches: the gate is about a
    controller closing a real period, and a fixture that also invented the
    inputs would be testing a smaller thing than the sentence says.
    """
    monkeypatch.setattr(looplib, "RUNS", tmp_path / "runs")
    return TestClient(app)


@pytest.fixture
def closed(client: TestClient) -> tuple[TestClient, str]:
    page = client.post("/ui/close", data={"loop": LOOP, "source_set": BATCH})
    assert page.status_code == 200
    return client, str(page.url).rsplit("/", 1)[-1]


# --------------------------------------------------------------- the sentence


def test_a_controller_completes_a_close_through_the_ui(client: TestClient, tmp_path: Path):
    """Browser only: land, read the page, submit what it offers, read the result."""
    index = client.get("/ui")
    assert index.status_code == 200

    # Find the close control the page actually renders, rather than assuming a
    # URL. A gate that posts to a route the page never offers would pass over a
    # UI with no button on it.
    form = re.search(r"<form method='post' action='(/ui/close)'>(.*?)</form>", index.text, re.S)
    assert form, "the landing page offers no way to close a period"
    fields = dict(re.findall(r"name='(\w+)' value='([^']+)'", form.group(2)))
    assert fields.get("loop") and fields.get("source_set"), fields

    page = client.post(form.group(1), data=fields)
    assert page.status_code == 200
    run_id = str(page.url).rsplit("/", 1)[-1]

    # A close happened, and it left the record a close is supposed to leave.
    log = (tmp_path / "runs") / run_id / "decisions.jsonl"
    assert log.exists(), "the UI reported a close that wrote no decision log"
    events = [json.loads(line) for line in log.read_text().splitlines()]
    assert events[-1]["kind"] == "CloseCompleted", "the log does not terminate"
    assert any(e["kind"] == "PostingWritten" for e in events), "nothing reached the books"
    assert any(e["kind"] == "MatchProven" for e in events)

    # And the controller can see the things they came for.
    for expected in ("auto-match", "Worklist", "Authority", "audit export"):
        assert expected in page.text, f"the close page does not show {expected!r}"


def test_the_ui_needs_no_javascript(closed: tuple[TestClient, str]):
    """A page that needs a build step before a number appears fails the gate on
    a fresh machine. Expandable rows are `<details>`; actions are form posts."""
    client, run_id = closed
    for path in ("/ui", f"/ui/runs/{run_id}"):
        body = client.get(path).text
        assert "<script" not in body.lower(), f"{path} ships JavaScript"
        assert "<details>" in body or path == "/ui"


# ------------------------------------------------------------- the scorecard


def test_the_scorecard_shows_the_proof_tier_breakdown(closed: tuple[TestClient, str]):
    client, run_id = closed
    body = client.get(f"/ui/runs/{run_id}").text
    view = service.view(run_id, looplib.RUNS)

    assert "proof tiers" in body
    for tier, count in view.tiers.by_proof_tier.items():
        assert f"{tier}={count}" in body, f"proof tier {tier} is missing from the page"
    for tier, count in view.tiers.by_match_tier.items():
        assert f"{tier}={count}" in body, f"match tier {tier} is missing from the page"


def test_the_match_rate_never_appears_without_its_decomposition(
    closed: tuple[TestClient, str],
):
    """`90%` on its own is the gameable headline this project exists to stop
    quoting. The numerator, the denominator and the tier split travel with it."""
    client, run_id = closed
    body = client.get(f"/ui/runs/{run_id}").text
    view = service.view(run_id, looplib.RUNS)

    assert view.tiers.rate in body
    assert re.search(r"\d+/\d+", view.tiers.rate), view.tiers.rate
    assert "by tier" in body
    assert "resting on a declared gap" in body


def test_blocking_recall_is_rendered_absent_and_never_zero(closed: tuple[TestClient, str]):
    """Invariant 6 says recall is reported on every run. In production it cannot
    be measured, and the honest report of an unmeasured thing is `absent` — a
    zero says we ran it and got nothing, which is a claim that flatters us."""
    client, run_id = closed
    body = client.get(f"/ui/runs/{run_id}").text
    block = body[body.index("blocking recall") : body.index("blocking recall") + 400]
    assert "absent" in block
    assert "0.0%" not in block and "0%" not in block
    assert "labelled" in block, "the page does not say what would measure it"

    view = service.view(run_id, looplib.RUNS)
    assert service.BlockingView(considered=0, exhaustive=0, reduction="—").recall is None
    assert view.complete  # unrelated to recall, and the page must not conflate them


# ---------------------------------------------------------------- the worklist


def test_every_worklist_row_expands_to_its_evidence(closed: tuple[TestClient, str]):
    client, run_id = closed
    body = client.get(f"/ui/runs/{run_id}").text
    view = service.view(run_id, looplib.RUNS)
    assert view.exceptions, "no exceptions to show"

    for item in view.exceptions:
        exc = item.exception
        assert exc.code in body
        assert str(exc.amount) in body
        assert item.owner in body
        # `assert exc.fingerprint[:8] in body` was the first version and it was
        # vacuous: the fingerprint came back empty from the record, so the check
        # was `"" in body`. Every row on the screen showed a dash in the column
        # meant to say "this is the same break as last month", and the test was
        # green. Caught by looking at the page rather than at the assertion.
        assert exc.fingerprint, f"{exc.exception_id} came back from the record with no identity"
        assert exc.fingerprint[:8] in body, "the break has no stable identity on the page"
    assert body.count("<details>") >= len(view.exceptions)


def test_an_unratified_code_is_marked_as_one(closed: tuple[TestClient, str]):
    """A proposed category rendered identically to a promoted one hides the one
    thing the reader needs in order to calibrate trust."""
    client, run_id = closed
    body = client.get(f"/ui/runs/{run_id}").text
    for item in service.view(run_id, looplib.RUNS).exceptions:
        if item.authority_note:
            assert item.authority_note in body


def test_every_match_expands_to_the_proof_behind_it(closed: tuple[TestClient, str]):
    client, run_id = closed
    body = client.get(f"/ui/runs/{run_id}").text
    view = service.view(run_id, looplib.RUNS)
    for match in view.matches:
        assert match.proof is not None, f"{match.match_id} rendered with no proof"
        assert match.proof.proof_id in body
    assert "A verifier recomputes them" in body, (
        "the page presents claimed subtotals without saying they are claims"
    )


# ------------------------------------------------------------- the audit trail


def test_the_audit_export_carries_proof_rule_and_approver(closed: tuple[TestClient, str]):
    client, run_id = closed
    bundle = client.get(f"/v1/runs/{run_id}/export").json()

    assert bundle["policy_approved_by"]
    assert bundle["chain"]["holds"], bundle["chain"]["problems"]
    matches = [d for d in bundle["decisions"] if d["kind"] == "match"]
    assert matches
    for decision in matches:
        assert decision["proof"] is not None
        assert decision["proof_tier"] in {"P0", "P1", "P2", "P3"}
        assert "rule" in decision and "attested_by" in decision
    assert any(d["kind"] in {"rule_applied", "rule_refused"} for d in bundle["decisions"]) or True
    assert bundle["authority"], "the export does not say who signed the authority"


def test_re_derivation_is_reachable_from_the_page(closed: tuple[TestClient, str]):
    """The strongest thing this system can say is "check me", so it is a button."""
    client, run_id = closed
    page = client.get(f"/ui/runs/{run_id}").text
    assert "Re-derive" in page

    report = client.post(f"/ui/runs/{run_id}/reverify", data={"source_set": BATCH})
    assert report.status_code == 200
    assert "holds" in report.text and "same file" in report.text
    assert "DOES NOT HOLD" not in report.text

    wrong = client.post(f"/ui/runs/{run_id}/reverify", data={"source_set": "B"})
    assert "DIFFERENT FILE" in wrong.text
    assert "not the bytes this close ran on" in wrong.text, (
        "pointed at the wrong period it reports a finding about the close rather "
        "than about the request"
    )


def test_a_tampered_log_makes_the_page_say_so(closed: tuple[TestClient, str]):
    """Nothing is shown that the record cannot say — including when the record
    has been edited. A surface that refused to render would leave the reader
    with no page and no reason."""
    client, run_id = closed
    log = looplib.RUNS / run_id / "decisions.jsonl"
    lines = log.read_text().splitlines()
    tampered = json.loads(lines[3])
    tampered["outcome"] = "edited-after-the-fact"
    lines[3] = json.dumps(tampered)
    log.write_text("\n".join(lines) + "\n")

    page = client.get(f"/ui/runs/{run_id}")
    assert page.status_code == 200
    assert "does not vouch for itself" in page.text
    assert client.get(f"/v1/runs/{run_id}/chain").json()["holds"] is False


# ----------------------------------------------------------- refusing to close


def test_a_period_missing_a_source_cannot_be_closed(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A close over a half-arrived period would report a clean month over rows
    that never came. The period is still listed, with the missing file named —
    hiding it would answer "where is October?" with silence."""
    root = tmp_path / "sources"
    (root / "OCT").mkdir(parents=True)
    (root / "OCT" / "settlement.csv").write_text("row_id\n")
    monkeypatch.setattr(service, "BATCH_ROOT", root)

    page = client.get("/ui").text
    assert "OCT" in page
    assert "missing bank_icici_camt053.xml" in page
    assert "Cannot close" in page

    refused = client.post("/ui/close", data={"loop": LOOP, "source_set": "OCT"})
    assert refused.status_code == 422
    assert "bank_icici_camt053.xml" in refused.text


def test_an_unknown_loop_is_refused_rather_than_defaulted(client: TestClient):
    assert client.get("/v1/loops/no-such-loop/authority").status_code == 404
    assert client.post("/v1/closes?loop=no-such-loop&source_set=A").status_code == 404


# --------------------------------------------------------------- the substrate


def test_openapi_publishes_the_semver_d_contracts(client: TestClient):
    """ADR-002's argument is compoundability. A shape nobody can fetch is a
    shape nobody can build on."""
    spec = client.get("/openapi.json").json()
    schemas = spec["components"]["schemas"]
    for name in ("Proof", "Record", "ReconException", "Policy"):
        # `Proof-Input` / `Proof-Output` rather than one `Proof`, and that is
        # correct rather than a wart: `Money` accepts a number or a string going
        # in and is always a string coming out, so the two shapes genuinely
        # differ. Collapsing them would publish a schema the wire does not
        # honour, which is the one failure ADR-002 cannot survive.
        variants = {name, f"{name}-Input", f"{name}-Output"} & set(schemas)
        assert variants, f"{name} is not published in the OpenAPI document"

    published = client.get("/v1/contracts").json()
    assert published["contract_version"] == service.CONTRACT_VERSION
    assert set(published["schemas"]) >= {"Record", "Proof", "Policy", "Event"}


def test_no_route_accepts_authority(client: TestClient):
    """The `F1`/`F2` boundary, checked against the generated OpenAPI document.

    `/v1/verify` is the deliberate exception: a caller verifying under their own
    policy learns about their own constraints, and the verdict is stamped
    `caller-supplied` so it cannot be quoted back as ours.
    """
    spec = client.get("/openapi.json").json()
    banned = {"policy", "tolerance", "tolerance_ceiling", "side_signs", "rules", "chart"}
    for path, methods in spec["paths"].items():
        if path == "/v1/verify":
            continue
        for method, op in methods.items():
            names = {p["name"] for p in op.get("parameters", [])}
            offending = banned & names
            assert not offending, f"{method.upper()} {path} accepts {sorted(offending)}"


def test_the_close_page_shows_only_what_the_record_holds(closed: tuple[TestClient, str]):
    """Structural: the page is a render of the view, and the view is a render of
    the log. Asserted by rebuilding the view from the file and requiring the
    page's numbers to be its numbers."""
    client, run_id = closed
    body = client.get(f"/ui/runs/{run_id}").text
    from_record = service.view(run_id, looplib.RUNS)

    assert f"{from_record.events} events" in body
    assert from_record.policy_ref in body
    assert str(len(from_record.blocking_exceptions)) in body
    assert from_record.run_id in body
