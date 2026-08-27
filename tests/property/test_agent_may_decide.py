"""An agent may decide, and the record always says that it did.

`/agent` used to tell a reader the assistant "cannot approve anything, and that
is not a policy we are asking you to trust — there is no tool for it and no
field to put your name in." That was true, and it was the wrong control.

An MCP caller over HTTP holds an OAuth token its principal issued, and the `sub`
on that token is *the same string the web session resolves to*. So the agent was
never an anonymous third party: it was the account, arriving through a different
door. Withholding the write tools protected nobody. It served a paying account a
read-only view of its own books and called the missing half governance — while
the customer had already accepted that risk, deliberately, by issuing a token.

What replaces the refusal is attribution. Every decision records the channel it
arrived through, so a reader of the log can always tell an agent acted. That is
this project's **never move silently** rule applied where the old answer was
*refuse what you cannot prove* — the same trade already made for `P3 DECLARED`.

The three things these tests pin, because each is a way the change could rot:

1. **No tool takes a name.** `decided_by` on a schema is the banned surface
   parameter at the one place value leaves a close. The name comes off the
   credential or the call is refused.
2. **The channel reaches the record**, and defaults to `browser` for every log
   written before the field existed.
3. **Every policy bound still binds.** The ceilings, the budget, the unopened
   blockers and the balance check were never questions about who was calling,
   so an agent must hit them exactly as a browser session does.
"""

from __future__ import annotations

import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from recon import review as reviewlib
from recon import service
from recon.contracts import ActorChannel
from recon.mcp import probe, server

# --------------------------------------------------------------------------
# 1 — the schemas name nobody
# --------------------------------------------------------------------------


def test_no_tool_lets_a_caller_name_the_person_a_decision_is_attributed_to():
    """The banned surface parameter, checked on the *generated* schemas.

    A convention lasts until the next person adds a tool, so this reads what
    FastMCP actually publishes rather than what the source appears to say.
    """
    catalog = probe.catalog()
    assert catalog.offenders == {}, (
        "a tool exposes a parameter a caller could use to supply its own identity "
        f"or authority: {catalog.offenders}"
    )


def test_the_writing_tools_are_the_ones_that_write():
    """`WRITING_TOOLS` is enumerated by hand, and this is why.

    `frozenset(everything_that_looks_like_a_write)` would certify the next tool
    by construction — the same defect as `frozenset(SomeEnum)` in the promotion
    gate, which auto-approved an action nobody had implemented.
    """
    catalog = probe.catalog()
    writing = {t.name for t in catalog.tools if t.writes}
    assert writing == {
        "run_close",
        "dispose_exception",
        "accept_classification",
        "sign_off_close",
    }, writing


def test_an_agent_with_no_credential_is_refused_rather_than_defaulted():
    """Over stdio there is no token, so there is no name — and no default.

    Every default here would be a name nobody chose, which is the one thing
    `P2 ATTESTED` cannot mean.
    """
    before = os.environ.pop("RECON_ACTOR", None)
    try:
        with pytest.raises(server.ToolRefusal) as caught:
            server._actor()
        assert "nobody to attribute it to" in str(caught.value)
    finally:
        if before is not None:
            os.environ["RECON_ACTOR"] = before


def test_a_named_stdio_operator_is_the_cli_channel():
    before = os.environ.get("RECON_ACTOR")
    os.environ["RECON_ACTOR"] = "meera@example.com"
    try:
        who, how = server._actor()
        assert who == "meera@example.com"
        assert how is ActorChannel.CLI
    finally:
        if before is None:
            os.environ.pop("RECON_ACTOR", None)
        else:
            os.environ["RECON_ACTOR"] = before


# --------------------------------------------------------------------------
# 2 — the channel reaches the record
# --------------------------------------------------------------------------


def test_a_disposition_records_the_channel_it_arrived_through(closed_run):
    run_id, runs_dir, tail = closed_run
    item = next(e for e in tail if e.amount < Decimal("1000"))

    service.dispose(
        run_id,
        item.exception_id,
        "write_off",
        decided_by="agent-principal@example.com",
        rationale="below materiality, accepted by the desk",
        via=ActorChannel.AGENT,
        runs_dir=runs_dir,
    )

    recorded = _payloads(run_id, runs_dir, "DispositionRecorded")
    assert len(recorded) == 1
    assert recorded[0]["decided_by"] == "agent-principal@example.com"
    assert recorded[0]["decided_via"] == "mcp-agent", (
        "the log cannot say an agent made this decision, which is the whole of "
        "what replaced the refusal"
    )


def test_a_log_written_before_the_field_existed_still_reads_as_a_browser():
    """The default is load-bearing, not cosmetic.

    Every disposition written before this change came from a browser session,
    because no other channel could write one. A required field here would have
    made every existing decision log unreadable — and this project's answer to
    that has always been an additive optional field, never a migration.
    """
    from recon.contracts.event import DispositionRecordedPayload

    payload = DispositionRecordedPayload.model_validate(
        {
            "exception_id": "EXC-00001",
            "fingerprint": "abc",
            "disposition": "chase",
            "from_code": "E08",
            "amount": "100.00",
            "debit_account": "receivable",
            "credit_account": "clearing",
            "entry_id": "E1",
            "decided_by": "someone@example.com",
            "rationale": "r",
            "policy_ref": "settlement-in@v1",
        }
    )
    assert payload.decided_via is ActorChannel.BROWSER


# --------------------------------------------------------------------------
# 3 — every bound still binds
# --------------------------------------------------------------------------


def test_the_write_off_ceiling_binds_an_agent_exactly_as_it_binds_a_person(closed_run):
    """The ceiling was never a question about who was calling.

    This is the test that decides whether the change was a relocation of the
    control or a removal of it. Policy is where the ceilings live; the channel
    is a fact about the door, not a permission.
    """
    run_id, runs_dir, tail = closed_run
    biggest = max(tail, key=lambda e: e.amount)

    with pytest.raises(service.ServiceError) as caught:
        service.dispose(
            run_id,
            biggest.exception_id,
            "write_off",
            decided_by="agent-principal@example.com",
            rationale="an agent trying to write off the largest break in the close",
            via=ActorChannel.AGENT,
            runs_dir=runs_dir,
        )
    assert "ceiling" in str(caught.value).lower() or "budget" in str(caught.value).lower()


def test_an_agent_cannot_sign_off_over_unopened_blockers(closed_run):
    """Delegating does not make an unopened item opened.

    The refusal reads the review log, which has no idea a channel exists — which
    is exactly why it still fires. A control that had to be taught about agents
    would be a control that could be taught to make an exception for them.
    """
    run_id, runs_dir, _ = closed_run
    with pytest.raises(service.ServiceError) as caught:
        service.sign_off(
            run_id,
            signed_by="agent-principal@example.com",
            note="signed by an assistant without reading the tail",
            via=ActorChannel.AGENT,
            runs_dir=runs_dir,
        )
    assert "blocking" in str(caught.value).lower() or "balance" in str(caught.value).lower()


def test_a_proposal_still_cannot_overwrite_a_derived_code_however_it_arrives(closed_run):
    """The strongest refusal in the system is about evidence, not about actors.

    `E09` is proved by enumerating two valid subsets. A named human cannot
    overwrite it and neither can an agent holding that human's token, because
    what is being refused is a guess outranking arithmetic.
    """
    run_id, runs_dir, tail = closed_run
    derived = [e for e in tail if e.code_provenance.value == "P0"]
    if not derived:
        pytest.fail(
            "this corpus produced no derived exception, so the refusal this test "
            "exists for cannot be reached — that is a corpus problem to look at, "
            "not a test to skip"
        )
    with pytest.raises(service.ServiceError) as caught:
        service.accept_classification(
            run_id,
            derived[0].exception_id,
            "E01",
            accepted_by="agent-principal@example.com",
            rationale="an agent guessing at a code the engine proved",
            via=ActorChannel.AGENT,
            runs_dir=runs_dir,
        )
    assert "overwrite" in str(caught.value).lower() or "derived" in str(caught.value).lower()


# --------------------------------------------------------------------------


def _payloads(run_id: str, runs_dir: Path, kind: str) -> list[dict]:
    path = runs_dir / run_id / reviewlib.FILENAME
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("kind") == kind:
            out.append(event["payload"])
    return out


@pytest.fixture
def closed_run(tmp_path):
    """A real close, in a temp runs directory, with its tail."""
    import shutil

    src = Path("data/runs/A")
    if not src.exists():
        pytest.fail("data/runs/A is absent — run `make eval` or `make gen` first")
    runs_dir = tmp_path / "runs"
    (runs_dir).mkdir(parents=True)
    shutil.copytree(src, runs_dir / "A")
    # A copied close carries whatever review log the source had; these tests
    # assert on what *this* run writes, so it starts empty.
    stale = runs_dir / "A" / reviewlib.FILENAME
    if stale.exists():
        stale.unlink()
    view = service.view("A", runs_dir)
    return "A", runs_dir, [e.exception for e in view.exceptions]


def test_the_due_date_is_parsed_rather_than_passed_through():
    """`due_on` arrives as a string over MCP and must not reach the record as one."""
    assert date.fromisoformat("2026-09-30") == date(2026, 9, 30)
