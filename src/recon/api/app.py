"""HTTP over the same service the MCP server calls.

Two surfaces, one implementation. Every route here is a few lines that call
`recon.service` and hand back the model it returns; nothing in this module
decides anything, and `tests/property/test_one_surface.py` asserts an HTTP body
and the corresponding MCP tool result are byte-identical. That is what keeps
"one code path" checkable instead of merely stated — the moment a route grows
its own logic, the two answers diverge and a test says so.

**Authority is not a request parameter.** No route accepts a policy, a
tolerance, a sign convention or a rule set. A client picks a loop and a period;
everything that decides whether an answer is *permitted* is loaded from the
loop's signed bundles. Both audit findings `F1` and `F2` reduce to "the caller
supplied the permission", and a query parameter is how a caller supplies
anything.

The schemas are generated from the models, and the models embed the semver'd
contracts — so `/openapi.json` publishes `Proof`, `Record` and `Event` in the
exact shapes the wire carries. ADR-002's compoundability argument needs the
shapes to be fetchable, not just stable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from .. import service
from ..contracts import CONTRACT_VERSION, Policy, Proof, Record
from ..loop import LoopError
from . import ui

DESCRIPTION = """\
A reconciliation controller. It closes a three-way match, writes double-entry
journal entries for everything it can prove, and returns a ranked exception
worklist with a machine-checkable proof attached to every decision.

**`POST /v1/verify` is stateless and needs nothing else here.** Hand it a proof
out of an audit export and records you ingested yourself from the source files,
and it re-derives the arithmetic under a policy you name. That call is the whole
trust argument; everything else is convenience.

Nothing on this API can promote a rule, attest a decision, widen a tolerance or
write to the ledger by request. Those need a named human and there is no
parameter through which to name one.

**There is no authentication.** Anyone who can reach the port can run a close and
read every audit export. That is unbuilt rather than overlooked: the boundary
this API does enforce is about *authority* — no route can carry a policy, a
tolerance or a rule set — and it holds whoever is calling. Identity is a separate
problem, and half of it would be worse than none because a login box implies the
rest. Do not expose this beyond a laptop without putting something in front of
it.
"""

app = FastAPI(
    title="recon",
    version=service.API_VERSION,
    description=DESCRIPTION,
    docs_url="/docs",
    openapi_url="/openapi.json",
)


def workspace(request: Request) -> Path:
    """Which account's records this request may read.

    Resolved from the session cookie and from nothing the request can name.
    There is no `tenant` parameter anywhere on this API, for the same reason
    there is no `policy` parameter: a caller that can name the thing can name
    someone else's.

    401 rather than a redirect — a client here is a program, not a person — and
    the message points at the one call that genuinely needs no account.
    """
    user = ui.visitor(request)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail=(
                "Sign in at /login. POST /v1/verify and GET /v1/contracts need no "
                "account — verification is stateless on purpose."
            ),
        )
    return service.runs_root(None) / user.user_id


WORKSPACE = Depends(workspace)


@app.exception_handler(service.ServiceError)
def _service_error(_request, exc: service.ServiceError) -> JSONResponse:
    """A refusal, with its reason intact.

    422 rather than 500: the request was understood and declined, and the text
    is the reason. A refusal flattened into a generic error is a refusal nobody
    can act on.
    """
    return JSONResponse(status_code=422, content={"refused": str(exc)})


@app.exception_handler(LoopError)
def _loop_error(_request, exc: LoopError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"refused": str(exc)})


@app.get("/healthz", tags=["meta"])
def healthz() -> dict:
    return {"ok": True, "api_version": service.API_VERSION, "contract_version": CONTRACT_VERSION}


@app.get("/v1/contracts", tags=["meta"])
def contracts() -> dict:
    """JSON Schema for the public, semver'd shapes. See ADR-002."""
    return service.contracts()


# --------------------------------------------------------------------------
# what can be closed, and what has been
# --------------------------------------------------------------------------


@app.get("/v1/loops", tags=["loops"], response_model=list[service.LoopView])
def loops() -> list[service.LoopView]:
    """The reconciliation loops this controller can close."""
    return service.loops()


@app.get("/v1/loops/{loop}/source-sets", tags=["loops"], response_model=list[service.SourceSetView])
def source_sets(loop: str) -> list[service.SourceSetView]:
    """Periods on disk, complete or not — incomplete ones with the missing
    filenames named."""
    return service.source_sets(loop)


@app.get("/v1/loops/{loop}/authority", tags=["loops"], response_model=service.AuthorityView)
def authority(loop: str) -> service.AuthorityView:
    """Policy, vocabulary, promoted rules, and the signature verdict on each
    bundle."""
    return service.authority(loop)


@app.get("/v1/runs", tags=["closes"])
def runs(runs_dir: Path = WORKSPACE) -> list[str]:
    return service.stored_runs(runs_dir)


# --------------------------------------------------------------------------
# running one
# --------------------------------------------------------------------------


@app.post("/v1/closes", tags=["closes"], response_model=service.CloseView, status_code=201)
def run_close(
    loop: Annotated[str, Query(description="Which reconciliation loop.")],
    source_set: Annotated[str, Query(description="Which period's source files.")],
    runs_dir: Path = WORKSPACE,
) -> service.CloseView:
    """Close one period: match, verify, post, record.

    Two parameters, and neither of them is authority. The response is read back
    out of the decision log the close just wrote, so a controller and an auditor
    are looking at the same artifact.
    """
    return service.close(loop, source_set, runs_dir=runs_dir)


@app.post("/v1/matches", tags=["closes"], response_model=service.MatchStageView)
def run_match(
    loop: Annotated[str, Query(description="Which reconciliation loop.")],
    source_set: Annotated[str, Query(description="Which period's source files.")],
    offset: int = 0,
    limit: int | None = None,
    _workspace: Path = WORKSPACE,
) -> service.MatchStageView:
    """Match a period and return the proofs — no posting, no ledger, no log.

    Matches page with their proofs inline, because a caller here is calling for
    the proofs. Records are not inlined — `GET /v1/records` pages them, and
    ingesting the source files yourself is the stronger check and the one worth
    making.
    """
    return service.match(loop, source_set, offset=offset, limit=limit)


@app.get("/v1/records", tags=["closes"], response_model=service.Page[Record])
def records(
    loop: Annotated[str, Query(description="Which reconciliation loop.")],
    source_set: Annotated[str, Query(description="Which period's source files.")],
    offset: int = 0,
    limit: int | None = None,
    _workspace: Path = WORKSPACE,
) -> service.Page[Record]:
    """The records a loop reads. Verifying against records we supplied proves the
    sum, not the honesty — the files and the specs are published."""
    return service.record_page(loop, source_set, offset=offset, limit=limit)


# --------------------------------------------------------------------------
# reading one back
# --------------------------------------------------------------------------


@app.get("/v1/runs/{run_id}", tags=["closes"], response_model=service.CloseView)
def close_view(
    run_id: str,
    detail: service.Detail = service.Detail.SUMMARY,
    runs_dir: Path = WORKSPACE,
) -> service.CloseView:
    """A recorded close, rebuilt from its decision log.

    `detail=summary` names each match and its `proof_id`; `detail=full` inlines
    every proof. A projection, not a permission.
    """
    return service.view(run_id, runs_dir, detail=detail)


@app.get(
    "/v1/runs/{run_id}/matches/{match_id}/proof",
    tags=["closes"],
    response_model=service.MatchView,
)
def match_proof(run_id: str, match_id: str, runs_dir: Path = WORKSPACE) -> service.MatchView:
    """One match with its full proof — the input to `POST /v1/verify`."""
    return service.proof_of(run_id, match_id, runs_dir)


@app.get("/v1/runs/{run_id}/worklist", tags=["closes"], response_model=list[service.ExceptionView])
def worklist(run_id: str, runs_dir: Path = WORKSPACE) -> list[service.ExceptionView]:
    """The exception queue: ranked by cash impact x age, routed by the
    registry."""
    return service.view(run_id, runs_dir).exceptions


@app.get(
    "/v1/runs/{run_id}/exceptions/{exception_id}",
    tags=["closes"],
    response_model=service.ExceptionView,
)
def exception_detail(
    run_id: str, exception_id: str, runs_dir: Path = WORKSPACE
) -> service.ExceptionView:
    for item in service.view(run_id, runs_dir).exceptions:
        if item.exception.exception_id == exception_id:
            return item
    raise HTTPException(status_code=404, detail=f"no exception {exception_id!r} in run {run_id!r}")


@app.get("/v1/runs/{run_id}/events", tags=["record"], response_model=service.Page[dict])
def run_events(
    run_id: str, offset: int = 0, limit: int | None = None, runs_dir: Path = WORKSPACE
) -> service.Page[dict]:
    """The typed, hash-chained decision log, a budget at a time.

    `total` is always the real total, so a reader can tell a whole log from the
    start of one.
    """
    return service.event_page(run_id, offset=offset, limit=limit, runs_dir=runs_dir)


@app.get("/v1/runs/{run_id}/journal.csv", tags=["record"], response_class=PlainTextResponse)
def journal_csv(run_id: str, runs_dir: Path = WORKSPACE) -> PlainTextResponse:
    """The journal as CSV — the file a controller imports into their books.

    This is the product's work product, and it was computed and dropped until
    now: the ledger that asserted the balance was rendered and never read, so a
    controller could see the books tie and still had to hand-type every entry.
    """
    export = service.journal(run_id, runs_dir)
    return PlainTextResponse(
        export.csv,
        media_type="text/csv",
        headers={"content-disposition": f'attachment; filename="{run_id}-journal.csv"'},
    )


@app.get("/v1/runs/{run_id}/journal.beancount", tags=["record"], response_class=PlainTextResponse)
def journal_beancount(run_id: str, runs_dir: Path = WORKSPACE) -> PlainTextResponse:
    """The same journal as plain-text double entry — readable by a person and
    checkable by a machine, and the format the balance assertion was written in."""
    export = service.journal(run_id, runs_dir)
    return PlainTextResponse(
        export.beancount,
        media_type="text/plain",
        headers={"content-disposition": f'attachment; filename="{run_id}.beancount"'},
    )


@app.get("/v1/runs/{run_id}/export", tags=["record"], response_model=service.AuditBundle)
def audit_export(
    run_id: str, offset: int = 0, limit: int | None = None, runs_dir: Path = WORKSPACE
) -> service.AuditBundle:
    """Every decision with its proof, its rule version and its approver — plus
    the four steps to re-derive the lot without us."""
    return service.audit(run_id, runs_dir, offset=offset, limit=limit)


# --------------------------------------------------------------------------
# verification — stateless, public, and the reason the rest exists
# --------------------------------------------------------------------------


@app.post("/v1/verify", tags=["verify"], response_model=service.Verification)
def verify(
    proof: Annotated[Proof, Body()],
    records: Annotated[list[Record], Body()],
    loop: Annotated[str | None, Body()] = None,
    policy: Annotated[Policy | None, Body()] = None,
) -> service.Verification:
    """Re-derive one proof from records you supply. Stateless.

    The verifier recomputes every leg subtotal and the residual from the records
    themselves and compares against what the proof claims; it reads no stored
    residual and takes its sign convention from policy, never from the proof.

    Name a `loop` to verify under that loop's published policy, or supply a
    `policy` of your own — exactly one. There is no default, because choosing
    one would be this endpoint deciding your constraints for you. The verdict is
    stamped with which you used, so a lenient policy you brought along cannot be
    quoted back as ours.
    """
    return service.check(proof, records, policy=policy, loop_name=loop)


@app.post("/v1/runs/{run_id}/reverify", tags=["verify"], response_model=service.Reverification)
def reverify(
    run_id: str,
    source_set: Annotated[str, Query(description="Which files to re-derive against.")],
    runs_dir: Path = WORKSPACE,
) -> service.Reverification:
    """Re-derive a whole recorded close from the files on disk.

    Re-ingests the sources, checks each sha256 against the hash the record
    pinned, and re-derives every proof in the log. Nothing is read from the
    process that ran the close, so this is the outsider's check, run on demand.
    """
    return service.reverify(run_id, source_set, runs_dir=runs_dir)


@app.get("/v1/runs/{run_id}/chain", tags=["verify"], response_model=service.ChainVerification)
def chain(run_id: str, runs_dir: Path = WORKSPACE) -> service.ChainVerification:
    """Whether the decision log vouches for itself — chain, and terminator
    against the stream."""
    return service.check_chain(service.events(run_id, runs_dir))


# --------------------------------------------------------------------------
# the one thing a proposer may do
# --------------------------------------------------------------------------


@app.post(
    "/v1/runs/{run_id}/exceptions/{exception_id}/propose",
    tags=["propose"],
    response_model=service.ProposalVerdict,
)
def propose(
    run_id: str,
    exception_id: str,
    code: Annotated[str, Body()],
    hypothesis: Annotated[str, Body()],
    evidence: Annotated[list[str], Body()] = [],  # noqa: B006 — FastAPI reads the default
    runs_dir: Path = WORKSPACE,
) -> service.ProposalVerdict:
    """Ask whether a proposed code would be admissible. Nothing is written.

    `admissible: true` means well-formed and permitted, not right. Making it so
    needs a named human, and this endpoint cannot name one.
    """
    return service.propose_reclassification(
        run_id, exception_id, code, hypothesis, evidence, runs_dir=runs_dir
    )


# --------------------------------------------------------------------------
# the screens
# --------------------------------------------------------------------------


def _mount_ui() -> None:
    """Attached last so a UI import error cannot take the API down with it.

    The JSON surface is the substrate other systems build on; the screens are
    one client of it. A controller losing a page is bad, and a bank's nightly
    integration losing an endpoint because a template broke is worse.
    """
    from .ui import router

    app.include_router(router)


_mount_ui()
