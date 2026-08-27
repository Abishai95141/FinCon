"""No tool result may be too large to use.

The MCP surface passed its gate and an agent could not have used it. `run_match`
returned **397 KB** — roughly 100k tokens, most of a context window, for 543 rows
of a toy corpus. `get_events` 114 KB, `get_close` 58 KB. Every one of them was
tested, correct, and unusable, which is a distinction worth having a file about:
a tool result is not a payload, it is *context*, and a response that consumes the
caller's ability to think about the answer has not answered.

Two rules, both checked here rather than remembered.

**A budget, over every tool.** Not over the ones someone thought to measure —
the walk enumerates what the server actually registers, so a tool added next
month is in scope the day it appears.

**Nothing is capped silently.** CLAUDE.md bans a workflow that bounds coverage
without logging what it dropped, and a paged API is the same hazard with a nicer
name: `total` is the real total, `next_offset` exists exactly when more remains,
and `stopped_at_budget` says whether the page ended because the caller asked or
because the bytes ran out.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastmcp import Client

from recon import service
from recon.mcp.server import mcp

LOOP = "settlement_3way"
BATCH = "A"


@pytest.fixture(scope="module")
def run_id() -> str:
    return service.close(LOOP, BATCH).run_id


def _tools() -> list[str]:
    async def go():
        async with Client(mcp) as client:
            return sorted(t.name for t in await client.list_tools())

    return asyncio.run(go())


def _call(tool: str, args: dict):
    async def go():
        async with Client(mcp) as client:
            return (await client.call_tool(tool, args)).data

    return asyncio.run(go())


def _args(run_id: str) -> dict[str, dict]:
    """Realistic arguments for every tool that can be driven without a body.

    Deliberately the *largest* legitimate call for each — no `limit`, no offset,
    the batch with the most rows. A budget checked against a convenient small
    request is a budget checked against nothing.
    """
    view = service.view(run_id)
    return {
        "list_loops": {},
        "list_source_sets": {"loop": LOOP},
        "list_runs": {},
        "run_close": {"loop": LOOP, "source_set": BATCH},
        "run_match": {"loop": LOOP, "source_set": BATCH},
        "get_close": {"run_id": run_id},
        "get_proof": {"run_id": run_id, "match_id": view.matches[0].match_id},
        "get_worklist": {"run_id": run_id},
        "explain_exception": {
            "run_id": run_id,
            "exception_id": view.exceptions[0].exception.exception_id,
        },
        "audit_export": {"run_id": run_id},
        "get_events": {"run_id": run_id},
        "fetch_records": {"loop": LOOP, "source_set": BATCH},
        "verify_journal": {"run_id": run_id},
        "reverify_close": {"run_id": run_id, "source_set": BATCH},
        "get_authority": {"loop": LOOP},
        "get_contracts": {},
    }


def test_every_tool_is_covered_by_this_budget(run_id: str):
    """The guard the walk needs. A table that silently stops covering a tool is
    how the next 400 KB response ships."""
    unmeasured = (
        set(_tools())
        - set(_args(run_id))
        - {
            # Take a proof and a record list on the body. Their size is the caller's,
            # not ours — and refusing an honest 2 MB verification request would be
            # the wrong lesson from a 397 KB response.
            "verify_proof",
            # Returns a verdict of a dozen fields.
            "propose_reclassification",
            # The decision tools. Excluded because measuring them means *making*
            # a decision — booking an entry, or signing a close — and a budget
            # walk that mutates the record it is measuring would leave every
            # later case reading a different close than the one it was set up
            # for. Their results are a handful of fields by construction:
            # `DispositionView`, `AcceptedView` and a `CloseView` already
            # measured through `get_close`.
            "dispose_exception",
            "accept_classification",
            "sign_off_close",
        }
    )
    assert not unmeasured, f"tools with no budget case: {sorted(unmeasured)}"


def test_no_tool_result_exceeds_the_budget(run_id: str):
    """One test, every tool, all the failures named — a fix that shrinks one
    response and leaves three is worse than knowing."""
    over: list[str] = []
    for tool, args in sorted(_args(run_id).items()):
        size = len(json.dumps(_call(tool, args), default=str))
        if size > service.TOOL_BUDGET:
            over.append(f"{tool}: {size // 1024} KB > {service.TOOL_BUDGET // 1024} KB")
    assert not over, "results too large for a context window:\n  " + "\n  ".join(over)


def test_the_largest_results_are_the_ones_that_page(run_id: str):
    """A budget met by having nothing to say is not a budget met.

    `run_match` and `get_events` are the two that blew it, so they have to still
    be carrying their subject — a page of proofs and a page of events — rather
    than having been emptied to fit.
    """
    staged = _call("run_match", {"loop": LOOP, "source_set": BATCH})
    assert staged["matches"], "run_match fits the budget by returning no matches"
    assert all(m["proof"] for m in staged["matches"]), "the proofs were dropped, not paged"
    assert staged["match_page"]["total"] >= len(staged["matches"])

    events = _call("get_events", {"run_id": run_id})
    assert events["items"], "get_events fits the budget by returning no events"
    assert events["total"] > 0


def test_a_page_that_stops_early_says_so(run_id: str):
    """The whole difference between paging and truncating."""
    page = _call("get_events", {"run_id": run_id})
    assert page["returned"] <= page["total"]
    if page["returned"] < page["total"]:
        assert page["next_offset"] == page["returned"], page
        assert page["stopped_at_budget"] is True
    else:
        assert page["next_offset"] is None


def test_paging_through_a_collection_returns_all_of_it(run_id: str):
    """The relation a cursor has to satisfy, and the one a byte budget makes
    easy to get wrong: follow `next_offset` to the end and you must have every
    item exactly once, whatever sizes the rows happened to be."""
    seen: list[int] = []
    offset, guard = 0, 0
    while True:
        page = _call("get_events", {"run_id": run_id, "offset": offset})
        seen += [item["seq"] for item in page["items"]]
        guard += 1
        assert guard < 50, "the cursor is not advancing"
        if page["next_offset"] is None:
            total = page["total"]
            break
        offset = page["next_offset"]

    assert seen == sorted(seen), "paging reordered the log"
    assert len(seen) == total == len(set(seen)), f"{len(seen)} events over pages, {total} claimed"


def test_withheld_is_not_the_same_as_missing(run_id: str):
    """A proof this response chose not to inline and a proof the record does not
    contain must never render alike. One is a fetch away; the other is a
    finding."""
    summary = _call("get_close", {"run_id": run_id})
    assert summary["unproven_matches"] == [], "this run's record is missing a proof"
    for match in summary["matches"]:
        assert match["proof"] is None
        assert match["proof_id"], "a summary row with no id to fetch by"
        assert "get_proof" in match["proof_omitted"], match["proof_omitted"]

    full = _call("get_close", {"run_id": run_id, "detail": "full"})
    assert all(m["proof"] for m in full["matches"])
    assert all(m["proof_omitted"] == "" for m in full["matches"])


def test_records_are_withheld_with_their_count_and_their_digest(run_id: str):
    """Absent, named, and quantified — not quietly gone."""
    staged = _call("run_match", {"loop": LOOP, "source_set": BATCH})
    assert staged["records"] == []
    assert staged["records_available"] > 500
    assert staged["records_digest"], "no digest to say which records were meant"
    assert "fetch_records" in staged["records_note"]

    page = _call("fetch_records", {"loop": LOOP, "source_set": BATCH})
    assert page["total"] == staged["records_available"]
    assert page["items"]


def test_an_offset_past_the_end_is_refused_rather_than_returning_nothing(run_id: str):
    """An empty page and a page past the end look identical, and one of them is
    a caller bug that should not read as 'you have them all'."""
    with pytest.raises(Exception) as caught:
        _call("get_events", {"run_id": run_id, "offset": 10_000})
    assert "outside a collection" in str(caught.value)


def test_a_projection_never_changes_an_answer(run_id: str):
    """`detail` decides how much of a close travels. Not what it decided.

    This shipped broken for one commit and is the reason the rule is written
    down: with proofs withheld at `detail=summary`, the proof-tier split was
    counted off the withheld proofs and every match read as `unrecorded` — so a
    scorecard's headline decomposition, the thing that says how much of a close
    rests on arithmetic rather than on a declaration, silently became a column
    of nothing. The size of a response and the content of an answer have to be
    independent, and only a comparison can hold them so.
    """
    summary = service.view(run_id)
    full = service.view(run_id, detail=service.Detail.FULL)

    assert summary.tiers == full.tiers
    assert summary.complete == full.complete
    assert summary.ok == full.ok
    assert summary.blocked == full.blocked
    assert summary.blocking_exceptions == full.blocking_exceptions
    assert summary.exceptions == full.exceptions
    assert summary.unproven_matches == full.unproven_matches
    assert summary.chain_problems == full.chain_problems
    assert [m.match_id for m in summary.matches] == [m.match_id for m in full.matches]
    assert [m.tier for m in summary.matches] == [m.tier for m in full.matches]
    assert [m.group_size for m in summary.matches] == [m.group_size for m in full.matches]


def test_paging_never_changes_a_total(run_id: str):
    """The same relation for the cursor: a page's `total` is a fact about the
    collection, not about the slice — so it must not move as you walk it."""
    totals = [service.event_page(run_id, offset=off).total for off in (0, 5, 10)]
    assert len(set(totals)) == 1, f"the total moved while paging: {totals}"

    unlimited = service.match(LOOP, BATCH)
    limited = service.match(LOOP, BATCH, limit=2)
    assert unlimited.match_page["total"] == limited.match_page["total"]
    assert limited.match_page["returned"] == 2
    assert unlimited.records_available == limited.records_available
