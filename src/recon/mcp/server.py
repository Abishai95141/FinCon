"""MCP over the kernel — what an external agent may do, and what it may not.

The thesis is "open intake, verified commit": the model proposes, a
deterministic engine proves, a human decides. An MCP server is the one place
that sentence stops being prose, because it is where a model actually reaches
for a tool. So the boundary is drawn in the **tool schemas**, not in a
convention someone remembers to follow:

* No tool accepts a policy, a tolerance, a sign convention, a chart or a rule
  set. Every audit finding in `docs/04-CONTROL-PLANE-AUDIT.md` reduces to "the
  caller supplied its own permission", and a parameter is how a caller supplies
  anything. `tests/property/test_surface_authority.py` walks every registered
  tool's generated schema and fails on one that could carry authority — a
  structural check, because a convention would last exactly as long as the next
  person adding a tool.
* No tool posts to the ledger, promotes a rule, attests anything, or edits the
  taxonomy. `run_close` runs the deterministic pipeline, in which every posting
  descends from a proof the verifier re-derived; that is the product doing its
  job, not a model writing to the books.
* The one tool that takes a proposal — `propose_reclassification` — returns a
  verdict and persists nothing, and says so in its own output. A model can learn
  whether its idea would be admissible. It cannot make it so.

**`verify_proof` is the point of the whole surface.** It is stateless: hand it a
proof out of our decision log and records you ingested yourself from the source
files, and it re-derives the arithmetic under a policy you name. No account, no
database, no reason to trust us. Everything else here is convenience; that one
call is the argument.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastmcp import FastMCP

from .. import service
from ..contracts import Policy, Proof, Record

INSTRUCTIONS = """\
A reconciliation controller. It closes a three-way match, writes double-entry
journal entries for everything it can prove, and returns a ranked exception
worklist with a machine-checkable proof attached to every decision.

What you can do here: list loops and the periods whose source files have
arrived, run a close or just the matching stage, read the resulting worklist and
audit export, and verify any proof or decision log independently.

What you cannot do here, by construction: supply a policy or a tolerance,
promote a rule, attest a decision, or write to the ledger. Those need a named
human, and no tool on this server can name one for you. If a task seems to
require it, say so rather than looking for another route.

Start with `list_loops`, then `list_source_sets`. `verify_proof` is stateless
and needs nothing from a previous call.\
"""

mcp: FastMCP = FastMCP(name="recon", instructions=INSTRUCTIONS)


def _runs() -> Path | None:
    """Which account's records this server reads.

    An MCP server runs on someone's machine over stdio, so there is no session
    to resolve a tenant from — it acts as one account, named by `RECON_TENANT`.
    Unset means the shared workspace, which is what a single-operator laptop
    wants. Read per call rather than cached so a test can point it somewhere
    without reimporting the module.

    Deliberately *not* a tool parameter. A caller that could name a tenant could
    name someone else's, which is the identity version of the rule that keeps
    policy off these schemas.
    """
    return _tenant_root(_tenant_id())


def _tenant_id() -> str | None:
    """Whose account this call speaks for.

    Two transports, one rule: **identity is never a parameter.**

    Over HTTP the caller arrives with an OAuth access token that Cognito signed
    and FastMCP verified, and the `sub` claim is the tenant. That claim is the
    same string the web session resolves to — `CognitoIdentity` stores Cognito's
    `sub` as `user_id` — so an agent and the person whose account it acts for see
    exactly one set of records, which is the entire reason for hosting this.

    Over stdio there is no request and no token: the server is a process on
    somebody's laptop and acts as one account, named by `RECON_TENANT`. Unset
    means the shared workspace, which is what a single-operator machine wants.

    A tool parameter would be neither. A caller that could name an account could
    name someone else's, and an MCP caller may be a model.
    """
    try:
        from fastmcp.server.dependencies import get_access_token

        token = get_access_token()
    except Exception:
        token = None
    if token is not None and getattr(token, "subject", None):
        return str(token.subject)
    return os.environ.get("RECON_TENANT")


def _tenant_root(tenant: str | None) -> Path | None:
    if not tenant:
        return None
    # A `sub` is a UUID and a `RECON_TENANT` is whatever somebody typed. Neither
    # may walk out of the runs directory — a tenant id is data from outside.
    if "/" in tenant or "\\" in tenant or tenant in {"", ".", ".."}:
        raise ToolRefusal(f"{tenant!r} is not a usable account id")
    return service.runs_root(None) / tenant


class ToolRefusal(Exception):
    """A request this server will not serve, with the reason kept intact.

    Raised rather than returned as `{"error": ...}` so a caller cannot mistake a
    refusal for an answer. FastMCP renders it as a tool error; the text is the
    reason, and it is meant to be read.
    """


# --------------------------------------------------------------------------
# what can be closed
# --------------------------------------------------------------------------


@mcp.tool
def list_loops() -> list[dict]:
    """The reconciliation loops this controller can close.

    Each carries the policy and taxonomy governing it, the strategies it matches
    with in the order it tries them, the source files it expects, and any
    promoted rules in force. Read it before asking for a close: the loop decides
    what a "side", a "counterparty" and a "tolerance" mean, and nothing here is
    hardcoded in the engine.
    """
    return [lp.model_dump(mode="json") for lp in service.loops()]


@mcp.tool
def list_source_sets(loop: str) -> list[dict]:
    """Which periods' source files are on disk, complete or not.

    Incomplete ones are listed with the missing filenames named. A close over a
    half-arrived period would report a clean month over rows that never came, so
    it is refused — but the fact that October is short one file is the useful
    answer, not an empty list.
    """
    return [s.model_dump(mode="json") for s in service.source_sets(loop)]


@mcp.tool
def list_runs() -> list[str]:
    """Closes already recorded, by run id.

    A run id is derived from the source bytes and the authority in force, so
    re-closing identical inputs under an unchanged policy reuses the id rather
    than creating a second record of one event.
    """
    return service.stored_runs(_runs())


# --------------------------------------------------------------------------
# running one
# --------------------------------------------------------------------------


@mcp.tool
def run_close(loop: str, source_set: str) -> dict:
    """Close one period: match, verify, post, record.

    Note what this does not take. There is no policy argument, no tolerance, no
    rule set and no chart of accounts — a caller picks *which* loop and *which*
    period and nothing else, and everything that decides whether an answer is
    permitted is loaded from the loop's own signed bundles. You cannot widen a
    tolerance through this tool because there is no parameter through which to
    try.

    Every posting it writes descends from a proof that was re-derived from raw
    records before anyone saw it; a match that fails re-derivation is dropped and
    its refusal recorded. The return value is read back out of the decision log
    the close just wrote, so what you see is what an auditor holding that file
    would see.
    """
    try:
        return service.close(loop, source_set, runs_dir=_runs()).model_dump(mode="json")
    except (service.ServiceError, ValueError) as exc:
        raise ToolRefusal(str(exc)) from exc


@mcp.tool
def run_match(loop: str, source_set: str, offset: int = 0, limit: int | None = None) -> dict:
    """Match one period and return the proofs — no posting, no ledger, no log.

    The matching stage on its own, for a caller that wants to check our
    arithmetic rather than have us close the books. Returns proven matches with
    their full proofs, everything the verifier refused, and the exceptions
    raised.

    The records are **not** inlined — 543 rows of this toy corpus is ~342 KB,
    most of a context window. `fetch_records` pages them. But ignore them: ingest
    the same source files with the published adapter spec and verify against your
    own records. That is what `verify_proof` is for and it is the only version of
    this that proves anything about our honesty.

    Matches page too, proofs included, because a caller here is calling *for* the
    proofs. `match_page.next_offset` is the cursor; it is `null` when you have
    them all, and `total` is always the real total.
    """
    try:
        return service.match(loop, source_set, offset=offset, limit=limit).model_dump(mode="json")
    except (service.ServiceError, ValueError) as exc:
        raise ToolRefusal(str(exc)) from exc


# --------------------------------------------------------------------------
# reading one back
# --------------------------------------------------------------------------


@mcp.tool
def get_close(run_id: str, detail: str = "summary") -> dict:
    """A recorded close, rebuilt from its decision log.

    Match rate with its tier split and its proof-tier split, what is blocked,
    what is waiting on a human, which authority it ran under and whether that
    authority's signature held. Blocking recall is reported **absent** rather
    than zero: it is measured against labelled true pairs and production has no
    labels — a zero there would be a claim we did not earn.

    `detail="summary"` (the default) names each match and its `proof_id` without
    inlining twenty proofs; `get_proof` returns the one you want to read.
    `detail="full"` inlines them all and is ~59 KB. A projection, not a
    permission — it changes how much of the answer travels, never what it is.
    """
    try:
        return service.view(run_id, _runs(), detail=service.Detail(detail)).model_dump(mode="json")
    except ValueError as exc:
        raise ToolRefusal(f"detail must be 'summary' or 'full': {exc}") from exc


@mcp.tool
def get_proof(run_id: str, match_id: str) -> dict:
    """One match with its full proof — every leg, its record ids and its subtotal.

    What a verifier reads before calling `verify_proof`. The subtotals here are
    *claims* made by whatever produced the match; recomputing them from the
    records is the entire job, and `verify_proof` refuses a proof whose legs do
    not add up to what it says.
    """
    try:
        return service.proof_of(run_id, match_id, _runs()).model_dump(mode="json")
    except service.ServiceError as exc:
        raise ToolRefusal(str(exc)) from exc


@mcp.tool
def fetch_records(loop: str, source_set: str, offset: int = 0, limit: int | None = None) -> dict:
    """The records a loop reads, a budget at a time.

    Here for completeness, and worth skipping: verifying our arithmetic against
    records **we** handed you proves the sum and not the honesty. The source
    files, the adapter specs and the policy are all published — ingest them
    yourself and verify against those.
    """
    try:
        return service.record_page(loop, source_set, offset=offset, limit=limit).model_dump(
            mode="json"
        )
    except service.ServiceError as exc:
        raise ToolRefusal(str(exc)) from exc


@mcp.tool
def get_worklist(run_id: str) -> list[dict]:
    """The exception queue, ranked by cash impact x age and routed to an owner.

    This is the tail, and the tail is the product. An item whose code has not
    been ratified carries a note saying so — a proposed category rendered
    identically to a promoted one would hide the one thing you need in order to
    know how much to trust it.
    """
    return [e.model_dump(mode="json") for e in service.view(run_id, _runs()).exceptions]


@mcp.tool
def explain_exception(run_id: str, exception_id: str) -> dict:
    """One exception with its evidence, its records and what it is allowed to do.

    `E14 unexplained` means no strategy matched and the engine cannot say why.
    It carries the facts it has and leaves classification open on purpose:
    "I do not know" out loud beats a plausible guess routed to the wrong desk.
    """
    view = service.view(run_id, _runs())
    for item in view.exceptions:
        if item.exception.exception_id == exception_id:
            return item.model_dump(mode="json")
    raise ToolRefusal(
        f"no exception {exception_id!r} in run {run_id!r}; it holds "
        f"{[e.exception.exception_id for e in view.exceptions]}"
    )


@mcp.tool
def audit_export(run_id: str, offset: int = 0, limit: int | None = None) -> dict:
    """Everything needed to re-derive a close, and nothing that requires us.

    Every decision with its proof, the rule version that fired, the human who
    approved the authority, the source document hashes and the adapter spec ids
    that read them. `how_to_verify` spells out the four steps; none of them
    touch our database or our network.
    """
    return service.audit(run_id, _runs(), offset=offset, limit=limit).model_dump(mode="json")


@mcp.tool
def get_events(run_id: str, offset: int = 0, limit: int | None = None) -> dict:
    """The typed decision log, event by event, hash-chained.

    Append-only in the only sense a file can be: each event carries the hash of
    the one before it, so an edit, a deletion or a reorder breaks the chain and
    `verify_journal` says where. It does not prove custody — someone able to
    rewrite the whole file can recompute the chain over anything. What it closes
    is the partial edit and the truncated tail.

    Paged: 62 events for a 22-payout month is 114 KB. `total` is always the real
    total, so "here is the log" and "here is the start of the log" stay
    distinguishable — which a bare list could not manage.
    """
    page = service.event_page(run_id, offset=offset, limit=limit, runs_dir=_runs())
    return page.model_dump(mode="json")


# --------------------------------------------------------------------------
# the stateless public verification — the reason this server exists
# --------------------------------------------------------------------------


@mcp.tool
def verify_proof(
    proof: Proof,
    records: list[Record],
    loop: str | None = None,
    policy: Policy | None = None,
) -> dict:
    """Re-derive one proof from records you hold. Stateless, and it trusts nothing.

    The verifier fetches each record by id, recomputes every leg subtotal and the
    residual from those records, and compares against what the proof claims. It
    reads no stored residual, takes its sign convention from policy rather than
    from the proof, and refuses a proof whose claimed tolerance exceeds the
    policy ceiling. A proof that names a record you did not supply is refuted,
    not excused.

    Name a `loop` to verify under that loop's published policy, or hand in a
    `policy` of your own. Exactly one — there is no default, because a
    verification that silently chose a policy would be deciding your constraints
    for you. The verdict says which you used: a lenient policy you brought along
    yields a verdict about *your* constraints and is stamped `caller-supplied`
    so it cannot be quoted back as ours.

    This call is how you check our work without trusting us. Take a proof out of
    `audit_export`, ingest the source files yourself with the published adapter
    spec, and run it. If it disagrees with us, that is a finding about us.
    """
    try:
        return service.check(proof, records, policy=policy, loop_name=loop).model_dump(mode="json")
    except service.ServiceError as exc:
        raise ToolRefusal(str(exc)) from exc


@mcp.tool
def reverify_close(run_id: str, source_set: str) -> dict:
    """Re-derive a whole recorded close from the source files on disk.

    Re-ingests the sources with the published adapter specs, checks each
    document's sha256 against the hash the record pinned, and re-derives every
    proof in the log against those fresh records. Nothing is read from the
    memory of the process that ran the close, so this is the same thing an
    outside auditor does — done by us, on demand.

    Three failure modes, reported apart because they mean different things.
    `sources_match` false means you pointed it at different bytes than the close
    ran on: your mistake, not our finding. `refuted` means the arithmetic does
    not hold: our finding. `missing_proofs` means the record has no proof to
    check, which is a gap in the evidence and deliberately does not pass.
    """
    try:
        return service.reverify(run_id, source_set, runs_dir=_runs()).model_dump(mode="json")
    except (service.ServiceError, ValueError) as exc:
        raise ToolRefusal(str(exc)) from exc


@mcp.tool
def verify_journal(run_id: str) -> dict:
    """Check a decision log's hash chain and its terminator.

    The terminator states how many events precede it and what was decided; those
    are claims by the writer, and this checks them against the stream. A valid
    chain over a truncated log is still a valid chain, which is exactly why the
    terminator has to be there.
    """
    return service.check_chain(service.events(run_id, _runs())).model_dump(mode="json")


# --------------------------------------------------------------------------
# the one thing a proposer may do
# --------------------------------------------------------------------------


@mcp.tool
def propose_reclassification(
    run_id: str, exception_id: str, code: str, hypothesis: str, evidence: list[str]
) -> dict:
    """Ask whether a proposed code for an exception would be admissible.

    Nothing is written. The proposal goes through the same checker the live
    triage path uses: the code must resolve in the registry and be assignable,
    the hypothesis must exist, the evidence must cite a record the exception
    actually names, and the exception's own label must not already rest on
    stronger evidence than a proposal can carry. A derived `E09` — one the
    engine proved by enumerating two valid subsets — outranks any proposal and
    is refused here, which is the rule that stopped a model overwriting a proven
    answer with a guess.

    A verdict of `admissible: true` means the proposal is well-formed and
    permitted, not that it is right. Making it so needs a named human, and no
    tool on this server can name one.
    """
    return service.propose_reclassification(
        run_id, exception_id, code, hypothesis, evidence, runs_dir=_runs()
    ).model_dump(mode="json")


# --------------------------------------------------------------------------
# the authority, and the shapes everything travels in
# --------------------------------------------------------------------------


@mcp.tool
def get_authority(loop: str) -> dict:
    """The policy, vocabulary and promoted rules governing a loop — and who signed.

    Codes carry their lifecycle state: naming one grants nothing, and only a
    `promoted` code may direct a posting. Rules carry the human who approved
    them and the policy that approval was granted under; an approval is
    re-checked against the policy in force wherever the rule acts, so a rule
    approved under an old policy does not quietly keep its permissions.
    """
    return service.authority(loop).model_dump(mode="json")


@mcp.tool
def get_contracts() -> dict:
    """JSON Schema for the public, semver'd shapes — Record, Proof, Policy, Event.

    Published so another system can build on them. They are versioned under
    ADR-002: a field change is a version bump, not an edit, because an
    independently-written verifier that stops working is the one failure this
    design cannot survive.
    """
    return service.contracts()


def main(transport: str = "stdio") -> None:
    """Run the server. `stdio` for a local client, `http` for a remote one."""
    mcp.run(transport=transport)


def serve_command() -> tuple[str, list[str]]:
    """The command that starts this server in a process of its own.

    A module invocation rather than a path, because running the file directly
    breaks its relative imports — found by trying it. Returned as data so the
    P13 gate can spawn a genuinely separate OS process rather than assert
    externality against an in-process client, which would prove nothing about
    whether verification needs our state.
    """
    return sys.executable, ["-m", "recon.mcp.server"]


if __name__ == "__main__":
    main()
