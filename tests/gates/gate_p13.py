"""P13 — substrate.

**Gate:** an external process calls `run_match`, then re-derives the returned
proof without touching our database — and a forged proof is refused by that same
public call.

"External" is taken literally. `test_a_separate_os_process_...` spawns the MCP
server with `subprocess` and speaks the real protocol to it over stdio, and
`test_verification_needs_nothing_but_the_files_and_the_verifier` runs the
verification in a *third* process that imports no server, no close and no
benchmark — it reads the decision log off disk, ingests the source files with
the published adapter spec, and checks the arithmetic. An in-process client
would have proved that the code runs; it would have proved nothing about
whether verification needs our state, which is the only interesting question.

The two halves of the gate pull in opposite directions on purpose. Anything can
be verified if the verifier is lenient enough, so the forged-proof half is
larger than the honest half: seven forgeries, each attacking a different part of
the proof, and one of them — a caller supplying a policy generous enough to
launder the forgery — is the failure mode this surface most needed closing.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from recon import service
from recon.contracts import Policy, Proof, ProofTier, Record
from recon.mcp import serve_command
from recon.mcp.server import mcp

pytestmark = pytest.mark.gate

LOOP = "settlement_3way"
BATCH = "A"
ROOT = Path("data/batches")


def _call(tool: str, args: dict) -> dict:
    """One tool call against an in-process client, over the real MCP protocol.

    Used where the question is about the *tool*, not about externality — the
    subprocess tests below are the ones that carry that claim, and paying two
    seconds of process startup for every assertion would buy nothing.
    """

    async def go():
        async with Client(mcp) as client:
            return (await client.call_tool(tool, args)).data

    return asyncio.run(go())


@pytest.fixture(scope="module")
def staged() -> dict:
    return _call("run_match", {"loop": LOOP, "source_set": BATCH})


@pytest.fixture(scope="module")
def closed() -> dict:
    return _call("run_close", {"loop": LOOP, "source_set": BATCH})


# ---------------------------------------------------------------- externality


def test_a_separate_os_process_speaks_the_protocol_and_gets_proofs():
    """The gate's first clause, with a real process boundary in the middle."""
    command, args = serve_command()

    async def go():
        async with Client(StdioTransport(command=command, args=args)) as client:
            tools = {t.name for t in await client.list_tools()}
            result = await client.call_tool("run_match", {"loop": LOOP, "source_set": BATCH})
            return tools, result.data

    tools, staged = asyncio.run(go())
    assert "run_match" in tools and "verify_proof" in tools
    assert staged["matches"], "run_match returned no matches to check"
    for match in staged["matches"]:
        assert match["proof"], f"{match['match_id']} came back with no proof to re-derive"
        assert match["proof"]["legs"], "a proof with no legs proves nothing"


def test_verification_needs_nothing_but_the_files_and_the_verifier(tmp_path: Path):
    """Re-derive in a third process that imports no server and no close.

    The script below is the whole trust argument written out: read the decision
    log, take a proof, ingest the source files with the published adapter spec,
    recompute. If this passes, an auditor holding the same three things reaches
    the same answer, and nothing about our runtime is load-bearing.
    """
    view = service.close(LOOP, BATCH)
    log = service.runs_root() / view.run_id / "decisions.jsonl"

    script = f"""
import json
from pathlib import Path
from recon.contracts import Proof
from recon.intake import ingest, load_spec
from recon.engine.verifier import verify
from recon.contracts import Policy

# 1. the record. Nothing here ran a close.
proofs = []
for line in Path({str(log)!r}).read_text().splitlines():
    event = json.loads(line)
    if event["kind"] == "MatchProven":
        proofs.append(Proof.model_validate(event["payload"]["proof"]))

# 2. our own records, ingested from the source files with the published spec.
window = (__import__("datetime").date(2026, 7, 1), __import__("datetime").date(2026, 10, 31))
policy = Policy.model_validate_json(Path("data/policy/settlement_3way.json").read_text())
records = {{}}
for spec_id, filename in (
    ("icici-camt", "bank_icici_camt053.xml"),
    ("gateway-settlement", "settlement.csv"),
):
    result = ingest(load_spec(spec_id), Path("data/batches/{BATCH}") / filename, window, policy)
    records.update({{r.record_id: r for r in result.records}})

# 3. the arithmetic.
proven = sum(1 for p in proofs if verify(p, records, policy).proven)
print(json.dumps({{"proofs": len(proofs), "proven": proven}}))
"""
    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, cwd=Path.cwd()
    )
    assert done.returncode == 0, done.stderr[-2000:]
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["proofs"] > 0, "the decision log carried no proofs to re-derive"
    assert out["proven"] == out["proofs"], (
        f"only {out['proven']} of {out['proofs']} proofs re-derived from the source "
        f"files alone — the record does not stand on its own"
    )


def test_the_record_carries_the_proof_not_a_pointer_to_one(closed: dict):
    """Until contract 7.4.0 the log named a `proof_id` and stored no proof, so
    the artifact we hand an auditor cited evidence nobody could fetch."""
    assert closed["unproven_matches"] == [], closed["unproven_matches"]
    events = _call("get_events", {"run_id": closed["run_id"]})
    proven = [e for e in events if e["kind"] == "MatchProven"]
    assert proven, "no MatchProven events"
    assert all(e["payload"].get("proof") for e in proven)


def test_a_log_without_proofs_reports_absent_rather_than_clean(tmp_path: Path):
    """The failure this must never have: a record with no evidence in it
    re-deriving to `0 checked, 0 refuted` and reading as a pass."""
    view = service.close(LOOP, BATCH, runs_dir=tmp_path)
    log = tmp_path / view.run_id / "decisions.jsonl"
    stripped = []
    for line in log.read_text().splitlines():
        event = json.loads(line)
        if event["kind"] == "MatchProven":
            event["payload"]["proof"] = None
        stripped.append(json.dumps(event))
    log.write_text("\n".join(stripped) + "\n")

    older = service.view(view.run_id, tmp_path)
    assert older.unproven_matches, "a log with its proofs removed claimed nothing was missing"
    report = service.reverify(view.run_id, BATCH, runs_dir=tmp_path)
    assert report.proofs_checked == 0
    assert not report.holds, "0 proofs checked, 0 refuted, and it called that a pass"


# ------------------------------------------------------------ the honest half


def test_the_returned_proof_re_derives_against_independently_read_records(staged: dict):
    """Ignore the records the server handed back; use our own."""
    lp = service.looplib.get(LOOP)
    loaded = lp.load(ROOT / BATCH)
    ours = [rec for _, rec in [*loaded.anchor_rows, *loaded.group_rows]]
    for match in staged["matches"]:
        verdict = _call(
            "verify_proof",
            {
                "proof": match["proof"],
                "records": [r.model_dump(mode="json") for r in ours],
                "loop": LOOP,
            },
        )
        assert verdict["proven"], (match["match_id"], verdict["reasons"])
        assert verdict["policy_source"] == "in-force"
        assert verdict["policy_ref"] == "settlement-in@v1"


def test_verify_proof_is_stateless_across_processes(staged: dict, tmp_path: Path):
    """Two processes, no shared memory, same verdict.

    A verification that consulted anything accumulated in the server would
    differ between a warm process and a cold one, and would be worthless to an
    auditor who has neither.
    """
    command, args = serve_command()
    proof = staged["matches"][0]["proof"]
    records = staged["records"]

    async def once():
        async with Client(StdioTransport(command=command, args=args)) as client:
            result = await client.call_tool(
                "verify_proof", {"proof": proof, "records": records, "loop": LOOP}
            )
            return result.data

    first, second = asyncio.run(once()), asyncio.run(once())
    assert first == second, "the same verification gave two answers in two processes"
    assert first["proven"]


# ------------------------------------------------------------ the forged half


def _proof_of(staged: dict, tier: str = "T0") -> Proof:
    for match in staged["matches"]:
        if match["tier"] == tier:
            return Proof.model_validate(match["proof"])
    pytest.skip(f"no {tier} match in this batch to forge")


def _records_of(staged: dict) -> list[Record]:
    return [Record.model_validate(r) for r in staged["records"]]


def _verify(proof: Proof, records: list[Record]) -> dict:
    return _call(
        "verify_proof",
        {
            "proof": proof.model_dump(mode="json"),
            "records": [r.model_dump(mode="json") for r in records],
            "loop": LOOP,
        },
    )


def test_a_forged_residual_is_refused(staged: dict):
    proof = _proof_of(staged)
    forged = proof.model_copy(update={"residual": proof.residual + Decimal("500.00")})
    verdict = _verify(forged, _records_of(staged))
    assert not verdict["proven"]
    assert any("claimed residual" in r for r in verdict["reasons"]), verdict["reasons"]


def test_a_forged_leg_subtotal_is_refused(staged: dict):
    proof = _proof_of(staged)
    legs = list(proof.legs)
    legs[0] = legs[0].model_copy(update={"subtotal": legs[0].subtotal + Decimal("1.00")})
    verdict = _verify(proof.model_copy(update={"legs": legs}), _records_of(staged))
    assert not verdict["proven"]
    assert any("claimed subtotal" in r for r in verdict["reasons"]), verdict["reasons"]


def test_a_proof_with_a_record_removed_from_a_leg_is_refused(staged: dict):
    """Dropping an inconvenient row is the forgery that would matter most —
    the legs then sum honestly and the residual is genuinely zero."""
    proof = _proof_of(staged)
    legs = list(proof.legs)
    fat = max(range(len(legs)), key=lambda i: len(legs[i].record_ids))
    if len(legs[fat].record_ids) < 2:
        pytest.skip("no multi-record leg in this batch")
    legs[fat] = legs[fat].model_copy(update={"record_ids": legs[fat].record_ids[:-1]})
    verdict = _verify(proof.model_copy(update={"legs": legs}), _records_of(staged))
    assert not verdict["proven"], "a row was deleted from the evidence and it still verified"


def test_a_proof_citing_a_record_nobody_can_fetch_is_refused(staged: dict):
    proof = _proof_of(staged)
    legs = list(proof.legs)
    legs[0] = legs[0].model_copy(update={"record_ids": ["no-such-record"]})
    verdict = _verify(proof.model_copy(update={"legs": legs}), _records_of(staged))
    assert not verdict["proven"]
    assert any("not found" in r for r in verdict["reasons"]), verdict["reasons"]


def test_a_proof_claiming_more_tolerance_than_policy_allows_is_refused(staged: dict):
    """Audit finding `F1` at the public boundary: the ceiling comes from policy,
    never from the artifact being checked."""
    proof = _proof_of(staged)
    forged = proof.model_copy(update={"tolerance_allowed": Decimal("1000000.00")})
    verdict = _verify(forged, _records_of(staged))
    assert not verdict["proven"]
    assert any("ceiling" in r for r in verdict["reasons"]), verdict["reasons"]


def test_a_declared_gap_relabelled_as_arithmetic_is_refused(staged: dict):
    """`P3 DECLARED` is a match resting on a stated gap. Relabelled `P0`, it
    would read as re-derivable from raw records, which it is not."""
    proof = _proof_of(staged, tier="T4")
    forged = proof.model_copy(update={"provenance": ProofTier.P0_ARITHMETIC})
    verdict = _verify(forged, _records_of(staged))
    assert not verdict["proven"]
    assert any("only P3" in r or "P0" in r for r in verdict["reasons"]), verdict["reasons"]


def test_a_declared_amount_of_the_proofs_own_choosing_is_refused(staged: dict):
    proof = _proof_of(staged, tier="T4")
    forged = proof.model_copy(update={"declared_amount": Decimal("1.00")})
    verdict = _verify(forged, _records_of(staged))
    assert not verdict["proven"]
    assert any("declares a gap" in r for r in verdict["reasons"]), verdict["reasons"]


def test_a_lenient_policy_a_caller_brought_along_cannot_be_quoted_as_ours(staged: dict):
    """The laundering channel, closed.

    A caller may verify under their own policy — that is the point of a stateless
    public call, and an auditor with stricter constraints than ours should be
    able to apply them. What must never happen is a verdict produced under a
    policy *someone brought with them* coming back indistinguishable from one
    produced under the policy in force. So the response names the policy and
    where it came from, and the two are not the same object.
    """
    proof = _proof_of(staged)
    forged = proof.model_copy(update={"residual": proof.residual + Decimal("500.00")})
    records = [r.model_dump(mode="json") for r in _records_of(staged)]

    strict = _call(
        "verify_proof", {"proof": forged.model_dump(mode="json"), "records": records, "loop": LOOP}
    )
    assert not strict["proven"]
    assert strict["policy_source"] == "in-force"

    generous = Policy.model_validate_json(Path("data/policy/settlement_3way.json").read_text())
    generous = generous.model_copy(
        update={"policy_id": "brought-my-own", "tolerance_ceiling": Decimal("9999999.00")}
    )
    verdict = _call(
        "verify_proof",
        {
            "proof": forged.model_dump(mode="json"),
            "records": records,
            "policy": generous.model_dump(mode="json"),
        },
    )
    # Whether it proves under a ceiling that wide is the caller's business. That
    # it is *labelled* as the caller's business is ours.
    assert verdict["policy_source"] == "caller-supplied"
    assert verdict["policy_ref"] == "brought-my-own@v1"
    assert verdict["policy_ref"] != strict["policy_ref"]


def test_verification_refuses_to_pick_a_policy_for_you():
    """No default. A verification that chose the constraints would be the whole
    control-plane audit reintroduced at the one endpoint that must not have it."""
    staged = _call("run_match", {"loop": LOOP, "source_set": BATCH})
    proof = staged["matches"][0]["proof"]
    own = json.loads(Path("data/policy/settlement_3way.json").read_text())
    for args in ({}, {"loop": LOOP, "policy": own}):
        with pytest.raises(Exception) as caught:
            _call("verify_proof", {"proof": proof, "records": staged["records"], **args})
        assert "policy" in str(caught.value)


# ------------------------------------------------- what the surface may not do


def test_no_tool_can_supply_authority():
    """The boundary, checked against the generated schemas rather than promised.

    Every finding in `docs/04-CONTROL-PLANE-AUDIT.md` reduces to "the caller
    supplied its own permission". A parameter is how a caller supplies anything,
    so the check is: no tool that *acts* may take one that carries authority.
    `verify_proof` is the deliberate exception and is safe for the opposite
    reason — a caller verifying under their own policy learns about their own
    constraints, and the verdict says so.
    """

    async def go():
        async with Client(mcp) as client:
            return {t.name: t.inputSchema for t in await client.list_tools()}

    banned = {"policy", "tolerance", "tolerance_ceiling", "side_signs", "rules", "chart", "profile"}
    for name, schema in asyncio.run(go()).items():
        if name == "verify_proof":
            continue
        offending = banned & set((schema or {}).get("properties", {}))
        assert not offending, f"{name} accepts authority as a parameter: {sorted(offending)}"


def test_a_proposal_changes_nothing(closed: dict):
    """CLAUDE.md rule 2 at the one interface a model actually drives."""
    run_id = closed["run_id"]
    before = _call("get_close", {"run_id": run_id})
    target = before["exceptions"][0]["exception"]["exception_id"]

    verdict = _call(
        "propose_reclassification",
        {
            "run_id": run_id,
            "exception_id": target,
            "code": "E01",
            "hypothesis": "in transit across the period boundary",
            "evidence": before["exceptions"][0]["exception"]["record_ids"][:1],
        },
    )
    assert verdict["persisted"] is False
    assert _call("get_close", {"run_id": run_id}) == before, (
        "a proposal moved something in the close"
    )


def test_a_proposal_cannot_overwrite_a_derived_label(closed: dict):
    """`E09` proved by enumerating two valid subsets outranks any proposal.

    This is the rule that stopped a model destroying a `P0` answer with a guess —
    net lift zero, one gained and one destroyed — and it has to hold at the
    surface, not only in the triage module.
    """
    derived = [e for e in closed["exceptions"] if e["exception"]["code_provenance"] == "P0"]
    if not derived:
        pytest.skip("this batch raised no derived exception to protect")
    subject = derived[0]["exception"]
    verdict = _call(
        "propose_reclassification",
        {
            "run_id": closed["run_id"],
            "exception_id": subject["exception_id"],
            "code": "E01",
            "hypothesis": "a guess",
            "evidence": subject["record_ids"][:1],
        },
    )
    assert not verdict["admissible"]
    assert any("proof tier" in r for r in verdict["reasons"]), verdict["reasons"]


def test_the_audit_export_stands_on_its_own(closed: dict):
    """Every decision with its proof, its rule version and its approver — plus
    what an auditor needs to fetch and re-run, named rather than implied."""
    bundle = _call("audit_export", {"run_id": closed["run_id"]})
    assert bundle["chain"]["holds"], bundle["chain"]["problems"]
    assert bundle["policy_approved_by"], "the export does not name who approved the policy"

    matches = [d for d in bundle["decisions"] if d["kind"] == "match"]
    assert matches, "an export with no decisions in it"
    for decision in matches:
        assert decision["proof"], f"{decision['match_id']} exported without its proof"
        assert decision["proof_tier"] in {"P0", "P1", "P2", "P3"}
    for source in bundle["sources"]:
        assert source["doc_hash"] and source["spec_id"], source
    assert len(bundle["how_to_verify"]) >= 4


def test_re_derivation_refuses_the_wrong_files(closed: dict):
    """Pointed at another period, it must say *that*, not report a finding about
    the close. Three failure modes, kept apart because they mean different
    things to whoever is reading."""
    wrong = _call("reverify_close", {"run_id": closed["run_id"], "source_set": "B"})
    assert not wrong["sources_match"]
    assert not wrong["holds"]

    right = _call("reverify_close", {"run_id": closed["run_id"], "source_set": BATCH})
    assert right["sources_match"] and right["holds"]
    assert right["proven"] == right["proofs_checked"] > 0
