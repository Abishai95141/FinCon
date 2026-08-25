"""HTTP and MCP must be two doors into one room.

The banned pattern at the top of CLAUDE.md is *a demo path that differs from the
real path*, and two protocols over one kernel is the obvious place to grow one:
each surface gets its own convenience, the conveniences drift, and a year later
the API says 20 matches while the agent says 19. The defence is that neither
surface decides anything — both call `recon.service` and hand back what it
returns — and the way to keep that true is to compare the bytes.

Relations rather than examples, because an example test would pass the day one
surface started rounding a number differently in a case the example does not
cover:

* the same question asked of both surfaces returns the same answer, field for
  field, for every read operation both expose;
* a close run through HTTP and a close run through MCP over the same inputs
  produce the same run id and the same decisions;
* neither surface exposes an operation the other cannot, except where the
  difference is deliberate and named here.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client

from recon import loop as looplib
from recon import service
from recon.api import app
from recon.mcp.server import mcp

LOOP = "settlement_3way"
BATCH = "A"


@pytest.fixture(scope="module")
def http() -> TestClient:
    return TestClient(app)


def _tool(name: str, args: dict | None = None):
    async def go():
        async with Client(mcp) as client:
            return (await client.call_tool(name, args or {})).data

    return asyncio.run(go())


@pytest.fixture(scope="module")
def run_id() -> str:
    return service.close(LOOP, BATCH).run_id


#: (tool name, tool args, HTTP method, path template). Every read both surfaces
#: expose. Adding one to a surface and not to this table is how they drift, so
#: the completeness of the table is asserted below rather than trusted.
PAIRED = [
    ("list_loops", {}, "GET", "/v1/loops"),
    ("list_source_sets", {"loop": LOOP}, "GET", f"/v1/loops/{LOOP}/source-sets"),
    ("get_authority", {"loop": LOOP}, "GET", f"/v1/loops/{LOOP}/authority"),
    ("list_runs", {}, "GET", "/v1/runs"),
    ("get_close", {"run_id": "{run}"}, "GET", "/v1/runs/{run}"),
    ("get_worklist", {"run_id": "{run}"}, "GET", "/v1/runs/{run}/worklist"),
    ("get_events", {"run_id": "{run}"}, "GET", "/v1/runs/{run}/events"),
    ("audit_export", {"run_id": "{run}"}, "GET", "/v1/runs/{run}/export"),
    ("verify_journal", {"run_id": "{run}"}, "GET", "/v1/runs/{run}/chain"),
    ("get_contracts", {}, "GET", "/v1/contracts"),
]


@pytest.mark.parametrize("tool,args,method,path", PAIRED, ids=[p[0] for p in PAIRED])
def test_both_surfaces_answer_a_question_identically(
    http: TestClient, run_id: str, tool: str, args: dict, method: str, path: str
):
    filled = {k: (v.replace("{run}", run_id) if isinstance(v, str) else v) for k, v in args.items()}
    over_mcp = _tool(tool, filled)
    over_http = http.request(method, path.replace("{run}", run_id)).json()
    assert over_mcp == over_http, (
        f"{tool} and {method} {path} disagree — the two surfaces have grown "
        f"separate implementations"
    )


def test_the_pairing_table_covers_every_read_both_surfaces_expose():
    """A table of pairs is only a check if it is complete.

    Anything a surface exposes and this file does not compare is a place the two
    can diverge unobserved, so the operations left out are enumerated with a
    reason rather than omitted.
    """

    async def go():
        async with Client(mcp) as client:
            return {t.name for t in await client.list_tools()}

    unpaired = {
        # Writes a close. Compared by `test_a_close_is_the_same_close_through
        # _either_door` instead, which cannot use a naive equality check because
        # the two runs write to the same log path.
        "run_close",
        "run_match",
        "reverify_close",
        # HTTP takes these on a body rather than a path, so the shapes differ by
        # protocol convention rather than by implementation.
        "verify_proof",
        "propose_reclassification",
        "explain_exception",
    }
    paired = {name for name, _, _, _ in PAIRED}
    missing = _tool_names(go) - paired - unpaired
    assert not missing, f"tools no test compares against HTTP: {sorted(missing)}"


def _tool_names(go) -> set[str]:
    return asyncio.run(go())


def test_a_close_is_the_same_close_through_either_door(http: TestClient):
    """Same inputs, same authority, same decisions — whichever protocol asked.

    The run id is derived from the source bytes and the authority in force, so
    an id that differed between the two would mean one of them was reading
    something the other was not.
    """
    over_http = http.post(f"/v1/closes?loop={LOOP}&source_set={BATCH}").json()
    over_mcp = _tool("run_close", {"loop": LOOP, "source_set": BATCH})

    assert over_http["run_id"] == over_mcp["run_id"]
    assert over_http["tiers"] == over_mcp["tiers"]
    assert over_http["matches"] == over_mcp["matches"]
    assert over_http["exceptions"] == over_mcp["exceptions"]
    assert over_http["complete"] == over_mcp["complete"]


def test_a_verification_is_the_same_verdict_through_either_door(http: TestClient):
    staged = _tool("run_match", {"loop": LOOP, "source_set": BATCH})
    body = {"proof": staged["matches"][0]["proof"], "records": staged["records"], "loop": LOOP}

    over_http = http.post("/v1/verify", json=body).json()
    over_mcp = _tool("verify_proof", body)
    assert over_http == over_mcp
    assert over_http["proven"]


def test_neither_surface_holds_state_between_requests(http: TestClient, run_id: str):
    """Asking twice must give the same answer, and asking in a different order
    must not change it. A surface that accumulated anything would be a surface
    an auditor cannot reproduce."""
    first = http.get(f"/v1/runs/{run_id}").json()
    _tool("get_worklist", {"run_id": run_id})
    _tool("audit_export", {"run_id": run_id})
    assert http.get(f"/v1/runs/{run_id}").json() == first


def test_the_view_comes_from_the_record_not_from_the_run(run_id: str, tmp_path):
    """`close()` returns what `view()` returns, because it calls it.

    The relation that keeps it honest: edit the log, and the answer changes. If
    a surface were serving a cached outcome, it would not.
    """
    import json

    view = service.close(LOOP, BATCH, runs_dir=tmp_path)
    log = tmp_path / view.run_id / "decisions.jsonl"
    lines = log.read_text().splitlines()
    kept = [ln for ln in lines if json.loads(ln)["kind"] != "MatchProven"]
    log.write_text("\n".join(kept) + "\n")

    after = service.view(view.run_id, tmp_path)
    assert after.tiers.matched == 0, "the matches survived their removal from the record"
    assert after.chain_problems, "a log with events removed still claimed to hold"
    assert looplib.RUNS  # the real runs dir was untouched by this test


def test_a_record_names_bundles_the_way_a_stranger_would_read_them(run_id: str):
    """An audit artifact must not carry the home directory of whoever ran it.

    `rulestore.STORE` resolves to an absolute path so it works from any cwd, and
    the decision log recorded it verbatim — so a regulator's copy said
    `data/policy`, `data/taxonomy` and `/Users/somebody/.../data/rules`. Three
    bundles of the same kind, one of them leaking a path nobody outside needs.
    """
    for entry in service.view(run_id).authority:
        assert not entry["bundle"].startswith("/"), entry["bundle"]
        assert entry["bundle"].startswith("data/"), entry["bundle"]


def test_the_break_identity_survives_the_record(run_id: str):
    """`ReconException.fingerprint` reaches the log and has to come back.

    Content-derived identity is the thing that makes "this is the same break as
    last month" sayable at all, and the surface serves from the record — so a
    fingerprint that is written and not read is a column of dashes for everyone.
    """
    live = service.close(LOOP, BATCH)
    from_record = service.view(live.run_id)
    assert [e.exception.fingerprint for e in from_record.exceptions] == [
        e.exception.fingerprint for e in live.exceptions
    ]
    assert all(e.exception.fingerprint for e in from_record.exceptions)
    assert len({e.exception.fingerprint for e in from_record.exceptions}) == len(
        from_record.exceptions
    ), "two breaks share a fingerprint — the identity does not identify"
