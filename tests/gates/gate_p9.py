"""Gate P9 — the record.

Gate: replay a full close from the decision log alone and reconstruct the same
scorecard.

Written before the implementation. An event stream that cannot reproduce the
run is not an audit trail, it is a diary — and there are four specific ways to
write a diary and call it an audit trail:

* **Log the answer instead of the decisions.** If the log carries the scorecard,
  replay is a `json.load` and proves nothing. The log carries decisions; replay
  recomputes the scorecard from them, scored against the same labels.
* **Replay by re-running.** A replay that quietly calls the engine measures the
  engine, not the log. The engine is made to raise during replay.
* **Log the happy path.** A log written where someone remembered to call it
  misses exactly the refusals that matter. Events are derived by set arithmetic
  over the same structures the completeness audit walks, and every disposed
  input must be named by an event.
* **A log a writer can rewrite.** Events are hash-chained, so an edit, a
  deletion or a reorder is detectable. Its limit is stated in STATUS: a chain
  is no defence against an actor who rewrites the whole file.

P9 also closes two gaps left open by earlier phases: policy is loaded from disk
and trusted (P7), and nothing asserted that a proven match produced a journal
entry (P6).
"""

from __future__ import annotations

import json
from decimal import Decimal as D
from pathlib import Path

import pytest

pytestmark = pytest.mark.gate

BATCHES = Path("data/batches")


@pytest.fixture(scope="module", autouse=True)
def _batches_exist():
    if not (BATCHES / "A" / "labels.json").exists():
        pytest.skip("run `make gen` first — P9 logs a close over the P0 batches")


@pytest.fixture(scope="module")
def closed(tmp_path_factory):
    from bench.run import close

    return close("A", journal_dir=tmp_path_factory.mktemp("runs"))


@pytest.fixture(scope="module")
def events(closed):
    from recon.journal import read

    return read(closed.journal_path)


# --------------------------------------------------------------------------
# the gate proper
# --------------------------------------------------------------------------


def test_the_log_alone_reconstructs_the_same_scorecard(closed):
    """The gate sentence, executed. Nothing but the file on disk and the labels
    that were always ground truth."""
    from bench.replay import scorecard_from_log

    lived = {c.arm: c for c in closed.cards}["deterministic"]
    replayed = scorecard_from_log(closed.journal_path, BATCHES / "A" / "labels.json")

    assert replayed.produced == lived.produced
    assert replayed.correct == lived.correct
    assert replayed.false_matches == lived.false_matches
    assert replayed.missed == lived.missed
    assert replayed.tiers == lived.tiers
    assert replayed.auto_match_rate.value == lived.auto_match_rate.value
    assert replayed.exceptions.coverage.value == lived.exceptions.coverage.value
    assert replayed.exceptions.classification.value == lived.exceptions.classification.value
    assert replayed.exceptions.ambiguity_detected == lived.exceptions.ambiguity_detected


def test_replay_does_not_re_run_the_engine(closed, monkeypatch):
    """A replay that quietly re-matches is measuring the engine, not the log.
    The engine is made to explode; the scorecard must still come back."""
    import recon.engine.tiers as tiers_mod

    def detonate(*a, **k):
        raise AssertionError("replay called the matching engine")

    monkeypatch.setattr(tiers_mod, "run", detonate)
    from bench.replay import scorecard_from_log

    card = scorecard_from_log(closed.journal_path, BATCHES / "A" / "labels.json")
    assert card.produced > 0


def test_the_replay_path_imports_no_engine_module():
    """Structural, so the property survives a refactor that the monkeypatch
    above would miss."""
    import ast

    banned = {"recon.engine.tiers", "recon.engine.subsetsum", "recon.engine.blocking"}
    files = sorted(Path("src/recon/journal").rglob("*.py"))
    assert files, "no journal package — this test would pass over an empty set"
    for path in files:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module not in banned, f"{path}: imports {node.module}"


def test_dropping_one_proven_match_changes_the_replayed_scorecard(closed, tmp_path):
    """Proves the replay reads the log rather than recomputing. If deleting a
    decision leaves the answer unchanged, the answer did not come from the log."""
    from bench.replay import scorecard_from_log

    from recon.contracts import EventKind

    lines = closed.journal_path.read_text(encoding="utf-8").splitlines()
    proven = [line for line in lines if json.loads(line)["kind"] == EventKind.MATCH_PROVEN.value]
    kept = [line for line in lines if line != proven[0]]

    short = tmp_path / "short.jsonl"
    short.write_text("\n".join(kept) + "\n", encoding="utf-8")
    card = scorecard_from_log(short, BATCHES / "A" / "labels.json", verify=False)
    assert card.produced == len(proven) - 1


# --------------------------------------------------------------------------
# derived by set arithmetic, not by instrumenting the happy path
# --------------------------------------------------------------------------


def test_every_disposed_input_is_named_by_an_event(closed, events):
    """Invariant 8's shape, applied to the log. A log written where someone
    remembered to call it misses the refusals; this is checkable instead."""
    from recon.journal.derive import unlogged

    assert unlogged(closed.completeness, events) == []


def test_an_input_with_a_disposition_and_no_event_is_caught(closed, events):
    """The check has teeth: remove the events for one record and it fails."""
    from recon.journal.derive import unlogged

    victim = next(iter(closed.completeness.anchors))
    thinned = [e for e in events if victim not in json.dumps(e.payload.model_dump(mode="json"))]
    assert len(thinned) < len(events)
    assert victim in unlogged(closed.completeness, thinned)


def test_the_close_derivation_refuses_to_finish_with_an_unlogged_input(closed):
    """Not merely reportable — the close fails. A derivation that silently
    omits an input is the same class of bug as a filter upstream of the audit."""
    from dataclasses import replace

    from recon.journal.derive import DerivationError, derive

    # No fault-injection hook in production code: the inconsistency is real —
    # a decision set whose exceptions are gone while the audit still reports
    # those records as EXCEPTED.
    crippled = replace(closed.decisions, exceptions=[])
    with pytest.raises(DerivationError):
        derive(crippled)


# --------------------------------------------------------------------------
# refusals are first-class
# --------------------------------------------------------------------------


def test_a_refusal_by_the_verifier_is_recorded_as_a_decision(closed, tmp_path, monkeypatch):
    from bench.run import close

    import recon.close as close_mod
    from recon.contracts import EventKind
    from recon.engine.verifier import Verdict, VerdictKind
    from recon.journal import read

    monkeypatch.setattr(
        close_mod,
        "verify",
        lambda *a, **k: Verdict(VerdictKind.REFUTED, None, ["mutation"], "p@v1"),
    )
    result = close("A", journal_dir=tmp_path)
    kinds = [e.kind for e in read(result.journal_path)]
    assert EventKind.MATCH_REJECTED in kinds
    assert EventKind.MATCH_PROVEN not in kinds


def test_a_refused_promotion_is_recorded(tmp_path):
    """`R-EVIL` being turned away is the most interesting thing that happens in
    a governed system. A log containing only successes is a marketing document."""
    from recon.contracts import EventKind, PolicyViolation
    from recon.contracts.rule import ActionKind, RuleAction
    from recon.engine.promotion import promote
    from recon.journal import Journal, read
    from tests.gates.gate_p8 import _policy, _profile, _rule

    journal = Journal(tmp_path / "d.jsonl")
    evil = _rule("R-EVIL", RuleAction(kind=ActionKind.SET_TOLERANCE, amount="1000000.00"))
    from recon.engine.promotion import MatchHistory, regress

    history = MatchHistory(anchors=[], group_records=[], records={}, matches=[])
    outcome = regress(evil, history, _profile(), _policy())
    with pytest.raises(PolicyViolation):
        promote(evil, outcome, _policy(), actor="agent", journal=journal)

    events = read(tmp_path / "d.jsonl")
    assert [e.kind for e in events] == [EventKind.PROPOSAL_REFUSED]
    assert "ceiling" in json.dumps(events[0].payload.model_dump(mode="json"))
    assert events[0].actor == "agent"


def test_the_real_close_records_refusals_and_exceptions_not_only_matches(events):
    from recon.contracts import EventKind

    kinds = {e.kind for e in events}
    assert EventKind.EXCEPTION_RAISED in kinds
    assert EventKind.OUT_OF_SCOPE in kinds, "P10 found a silent filter; it must be on the record"
    assert EventKind.CLOSE_BLOCKED in kinds, "blocking exceptions were raised and nothing said so"


# --------------------------------------------------------------------------
# append-only: an edit, a deletion or a reorder is detectable
# --------------------------------------------------------------------------


def _tamper(src: Path, dst: Path, fn):
    lines = src.read_text(encoding="utf-8").splitlines()
    dst.write_text("\n".join(fn(lines)) + "\n", encoding="utf-8")
    return dst


def test_editing_an_event_breaks_the_chain(closed, tmp_path):
    from recon.journal import read, verify_chain

    def edit(lines):
        out = list(lines)
        row = json.loads(out[3])
        row["actor"] = "someone-else"
        out[3] = json.dumps(row)
        return out

    path = _tamper(closed.journal_path, tmp_path / "e.jsonl", edit)
    assert verify_chain(read(path, verify=False))


def test_deleting_an_event_breaks_the_chain(closed, tmp_path):
    from recon.journal import read, verify_chain

    path = _tamper(closed.journal_path, tmp_path / "d.jsonl", lambda ls: ls[:3] + ls[4:])
    assert verify_chain(read(path, verify=False))


def test_reordering_events_breaks_the_chain(closed, tmp_path):
    from recon.journal import read, verify_chain

    def swap(lines):
        out = list(lines)
        out[3], out[4] = out[4], out[3]
        return out

    path = _tamper(closed.journal_path, tmp_path / "s.jsonl", swap)
    assert verify_chain(read(path, verify=False))


def test_an_untampered_log_verifies(closed, events):
    from recon.journal import verify_chain

    assert verify_chain(events) == []


def test_reading_a_tampered_log_raises_by_default(closed, tmp_path):
    from recon.journal import JournalTampered, read

    path = _tamper(closed.journal_path, tmp_path / "d.jsonl", lambda ls: ls[:3] + ls[4:])
    with pytest.raises(JournalTampered):
        read(path)


def test_appending_to_a_tampered_log_is_refused(closed, tmp_path):
    """The chain is checked on write too. Otherwise an edit is repaired by the
    next legitimate append."""
    from recon.journal import Journal, JournalTampered

    def edit(lines):
        out = list(lines)
        row = json.loads(out[2])
        row["actor"] = "ghost"
        out[2] = json.dumps(row)
        return out

    path = _tamper(closed.journal_path, tmp_path / "t.jsonl", edit)
    with pytest.raises(JournalTampered):
        Journal(path)


def test_a_log_with_no_terminator_is_reported_as_incomplete(closed, tmp_path):
    """Truncating the tail leaves a valid chain — the honest limit of a chain
    without an external anchor. The terminating event is how a short log is
    still detectable."""
    from recon.journal import read, verify_chain

    path = _tamper(closed.journal_path, tmp_path / "c.jsonl", lambda ls: ls[:-1])
    problems = verify_chain(read(path, verify=False))
    assert any("terminat" in p for p in problems), problems


# --------------------------------------------------------------------------
# policy provenance — the gap P7 left open
# --------------------------------------------------------------------------


def test_every_decision_names_the_policy_that_judged_it(events):
    from recon.contracts import EventKind

    judged = {
        EventKind.MATCH_PROVEN,
        EventKind.MATCH_REJECTED,
        EventKind.EXCEPTION_RAISED,
        EventKind.CLOSE_STARTED,
    }
    for event in events:
        if event.kind in judged:
            assert event.policy_ref, f"{event.kind} carries no policy ref"


def test_the_log_pins_the_bytes_of_the_policy_it_ran_under(closed, events, tmp_path):
    """P7 shipped with policy loaded from disk and trusted — nothing checked
    provenance. A run judged under a version nobody approved is now visible: the
    header event carries a digest of the policy file itself."""
    import hashlib

    from recon.contracts import EventKind

    header = next(e for e in events if e.kind is EventKind.CLOSE_STARTED)
    on_disk = hashlib.sha256(
        (Path("data/policy") / "settlement_3way.json").read_bytes()
    ).hexdigest()
    assert header.payload.policy_digest == on_disk

    tampered = json.loads((Path("data/policy") / "settlement_3way.json").read_text())
    tampered["tolerance_ceiling"] = "999999.00"
    (tmp_path / "p.json").write_text(json.dumps(tampered))
    assert (
        hashlib.sha256((tmp_path / "p.json").read_bytes()).hexdigest()
        != header.payload.policy_digest
    )


def test_the_log_pins_the_inputs_it_ran_over(events):
    from recon.contracts import EventKind

    header = next(e for e in events if e.kind is EventKind.CLOSE_STARTED)
    assert header.payload.source_digests
    assert all(len(d) == 64 for d in header.payload.source_digests.values())


# --------------------------------------------------------------------------
# a kind with no producer is declared, not silently missing
# --------------------------------------------------------------------------


def test_every_event_kind_declares_who_produces_it():
    from recon.contracts import PRODUCERS, EventKind

    assert set(PRODUCERS) == set(EventKind), (
        f"kinds with no declared producer: {sorted(set(EventKind) - set(PRODUCERS))}"
    )


def test_no_event_kind_is_left_without_a_producer():
    """The list this asserted has emptied, one phase at a time.

    `CodeProposed` left it at P11, `RuleInduced` at P12 part 2, and
    `AdapterAuthored` with adapter synthesis. The property was always the point
    and the membership never was: a kind either names the thing that writes it
    or names the phase that will, and a kind that quietly did neither would be a
    hole in the vocabulary nobody could see.

    Now that every kind has a producer, the discipline is inverted: adding a kind
    without one fails here rather than being noticed later.
    """
    from recon.contracts import PRODUCERS, EventKind

    unbuilt = {k.value: v for k, v in PRODUCERS.items() if v.startswith("P")}
    assert unbuilt == {}, f"kinds still naming a phase rather than a producer: {unbuilt}"
    assert set(PRODUCERS) == set(EventKind)
    for kind, producer in PRODUCERS.items():
        assert producer.strip(), f"{kind} names no producer at all"


def test_the_close_reports_which_kinds_it_could_not_produce(closed):
    # Empty now, and that is the assertion: the close reports which kinds it
    # could not produce, and there are none left. It stays because a kind added
    # without a producer must show up here on the page, not only in a test.
    assert closed.unproduced_kinds == {}


# --------------------------------------------------------------------------
# postings — the gap P6 left open
# --------------------------------------------------------------------------


def test_every_proven_match_produced_exactly_one_journal_entry(closed):
    """P6's audit covered anchors, records and sources. Nothing asserted that a
    match this system calls proven ever reached the books, which is the thing
    the product claims to do."""
    proof_ids = {m.proof.proof_id for m in closed.matches}
    posted = [e.proof_id for e in closed.entries if e.proof_id]
    assert sorted(posted) == sorted(proof_ids)
    assert len(posted) == len(set(posted)), "a proof posted twice"


def test_no_journal_entry_exists_without_a_proof_or_a_named_exception(closed):
    proofs = {m.proof.proof_id for m in closed.matches}
    exceptions = {e.exception_id for e in closed.exceptions}
    for entry in closed.entries:
        origin = entry.proof_id or entry.meta.get("exception_id")
        assert origin in proofs or origin in exceptions, f"orphan entry {entry.entry_id}"


def test_an_unattributable_credit_parks_in_suspense_not_in_income(closed):
    """The planted E08: ₹1,160 arrived and nobody knows from whom. The money is
    in the bank and the balance must say so; guessing it into revenue is the
    error the suspense account exists to prevent."""
    from recon.ledger.accounts import AccountRole

    entry = next(e for e in closed.entries if e.meta.get("amount") == "1160.00")
    roles = {p.role for p in entry.postings}
    assert roles == {AccountRole.BANK, AccountRole.SUSPENSE}

    # Widened at P11. Once the code registry started directing bookings, this
    # test passed because the *registry* says suspense rather than because the
    # rule refuses revenue — so flipping the fallback to income survived it. No
    # exception entry may credit revenue, whichever layer decided.
    revenue = {AccountRole.INCOME, AccountRole.REFUNDS}
    booked = [e for e in closed.entries if e.meta.get("exception_id")]
    assert booked
    for candidate in booked:
        assert not (revenue & {p.role for p in candidate.postings}), candidate.entry_id


def test_a_settlement_group_that_never_reached_the_bank_is_not_posted(closed):
    """Money the gateway says it sent but the bank never received is a
    receivable, not cash. Posting it would put money in the books that is not
    in the account."""
    group_side = [
        e
        for e in closed.exceptions
        if e.leg == "bank" and "was not claimed" in (e.hypothesis or "")
    ]
    assert group_side
    posted = {e.meta.get("exception_id") for e in closed.entries}
    for exc in group_side:
        assert exc.exception_id not in posted


def test_the_journal_balances_and_the_close_is_not_blocked(closed):
    assert closed.ledger is not None
    assert closed.ledger.entries_loaded == len(closed.entries)
    assert not closed.ledger.blocked, closed.ledger.errors


def test_invariant_1_the_unattributed_bank_value_equals_the_suspense_balance(closed):
    """CLAUDE.md invariant 1, checkable for the first time because until this
    phase nothing posted. If they diverge the system is wrong and must say so
    rather than post."""
    from recon.ledger.accounts import AccountRole

    # Deliberately derived from two different places: one side from the
    # postings, the other from the exception list. Reading both off the entries
    # would make this agree with itself.
    suspense = sum(
        (p.amount for e in closed.entries for p in e.postings if p.role is AccountRole.SUSPENSE),
        D("0.00"),
    )
    anchor_ids = {r for r, rec in closed.records.items() if rec.side == "bank"}
    unattributed = sum(
        (exc.amount for exc in closed.exceptions if set(exc.record_ids) & anchor_ids),
        D("0.00"),
    )
    assert -suspense == unattributed
    assert unattributed > 0


def test_the_completeness_audit_now_covers_postings(closed):
    assert closed.completeness.postings
    assert closed.completeness.complete
    assert "undisposed_postings" in dir(closed.completeness)


def test_a_proven_match_with_no_posting_makes_the_audit_fail(closed):
    """The audit is not decorative: withhold one entry and it must go red."""
    from recon.engine.completeness import audit

    report = audit(
        anchors=[],
        group_records=[],
        matched_anchor_ids=[],
        matched_record_ids=[],
        exceptions=[],
        proof_ids=[m.proof.proof_id for m in closed.matches],
        posted_proof_ids=[m.proof.proof_id for m in closed.matches][:-1],
    )
    assert not report.complete
    assert report.undisposed_postings


# --------------------------------------------------------------------------
# determinism
# --------------------------------------------------------------------------


def test_the_decisions_are_deterministic_even_though_the_timestamps_are_not(tmp_path):
    """Two runs over the same inputs record the same decisions. The event hashes
    differ because they cover the wall-clock time, which is content an auditor
    needs — so determinism is asserted where it exists, on the decisions."""
    from bench.run import close

    from recon.journal import read

    def decisions(dirname):
        result = close("A", journal_dir=tmp_path / dirname)
        return [
            (e.kind, e.actor, e.outcome, e.input_hash, e.payload.model_dump(mode="json"))
            for e in read(result.journal_path)
        ]

    first, second = decisions("one"), decisions("two")
    assert first == second
    assert len(first) > 20


def test_the_scorecard_digest_in_the_terminator_matches_the_lived_scorecard(closed):
    """The terminator carries a digest of the scorecard the run produced. It is
    not what replay reads — replay recomputes — it is what makes a replay
    disagreeing with the run detectable rather than a matter of opinion."""
    from bench.replay import scorecard_digest, scorecard_from_log

    from recon.contracts import EventKind
    from recon.journal import read

    terminator = next(e for e in read(closed.journal_path) if e.kind is EventKind.CLOSE_COMPLETED)
    replayed = scorecard_from_log(closed.journal_path, BATCHES / "A" / "labels.json")
    assert terminator.payload.scorecard_digest == scorecard_digest(replayed)


def test_a_finished_log_cannot_be_quietly_extended(closed):
    """The terminator means "this close ended here". A later append would make
    it mean "this close ended here, until someone added more"."""
    from recon.contracts import CloseBlockedPayload, EventKind
    from recon.journal import Journal, JournalSealed

    journal = Journal(closed.journal_path)
    with pytest.raises(JournalSealed):
        journal.append(
            EventKind.CLOSE_BLOCKED,
            actor="ghost",
            outcome="blocked",
            input_hash="x",
            payload=CloseBlockedPayload(reasons=["added after the fact"]),
        )


def test_re_running_a_close_writes_a_new_log_rather_than_appending(tmp_path):
    from bench.run import close

    from recon.contracts import EventKind
    from recon.journal import read

    first = close("A", journal_dir=tmp_path)
    length = len(read(first.journal_path))
    second = close("A", journal_dir=tmp_path)
    events = read(second.journal_path)
    assert len(events) == length, "the second close appended to the first"
    assert [e.kind for e in events].count(EventKind.CLOSE_STARTED) == 1


# --------------------------------------------------------------------------
# holes mutation found in the gate above, and the tests that close them
# --------------------------------------------------------------------------


def test_an_event_spliced_from_another_log_is_caught(closed, tmp_path):
    """Found by mutation: deleting the `prev_hash` link left every test green,
    because deletions and reorders are also caught by the seq and content
    checks. A splice is the case only the link can see — the event is internally
    consistent, its seq is right for the position, and it simply belongs to a
    different run."""
    from bench.run import close

    from recon.journal import read, verify_chain

    other = close("B", journal_dir=tmp_path / "b")
    mine = closed.journal_path.read_text(encoding="utf-8").splitlines()
    theirs = other.journal_path.read_text(encoding="utf-8").splitlines()

    spliced = list(mine)
    spliced[3] = theirs[3]
    assert json.loads(spliced[3])["seq"] == 3, "the splice must keep the position honest"

    path = tmp_path / "spliced.jsonl"
    path.write_text("\n".join(spliced) + "\n", encoding="utf-8")
    problems = verify_chain(read(path, verify=False))
    assert any("does not follow" in p for p in problems), problems


def test_a_skipped_sequence_number_is_caught(tmp_path):
    """Also found by mutation. A writer that skips a number produces a log whose
    chain links hold and whose hashes are all correct — the count is the only
    thing that says an event is missing."""
    from recon.contracts import CloseBlockedPayload, EventKind
    from recon.journal import Journal, digest_of, read, verify_chain

    journal = Journal(tmp_path / "gap.jsonl")
    for _ in range(3):
        journal.append(
            EventKind.CLOSE_BLOCKED,
            actor="engine",
            outcome="blocked",
            input_hash="x",
            payload=CloseBlockedPayload(reasons=["r"]),
        )
    events = read(tmp_path / "gap.jsonl", verify=False)

    # Rewrite the last event with seq 5 and re-seal it: internally consistent,
    # correctly linked, and lying about its position.
    bumped = events[-1].model_copy(update={"seq": 5, "event_hash": ""})
    sealed = bumped.model_copy(update={"event_hash": digest_of(bumped, bumped.prev_hash)})
    forged = tmp_path / "forged.jsonl"
    forged.write_text(
        "\n".join([e.model_dump_json() for e in events[:-1]] + [sealed.model_dump_json()]) + "\n",
        encoding="utf-8",
    )

    problems = verify_chain(read(forged, verify=False))
    assert any("missing or moved" in p for p in problems), problems
    assert not any("does not match its hash" in p for p in problems), (
        "the forgery is self-consistent — only the sequence gives it away"
    )


def test_a_stream_that_disagrees_with_its_own_terminator_is_reported(closed, tmp_path):
    """The terminator's counts are a claim by the writer. Replay never reads
    them for its answer, which is exactly why something has to check them —
    otherwise they are decoration that could say anything."""
    from bench.replay import replay_close

    from recon.journal.replay import disagreements

    assert disagreements(replay_close(closed.journal_path)) == []

    lines = closed.journal_path.read_text(encoding="utf-8").splitlines()
    proven = [line for line in lines if json.loads(line)["kind"] == "MatchProven"]
    path = tmp_path / "short.jsonl"
    path.write_text("\n".join(line for line in lines if line != proven[0]) + "\n", encoding="utf-8")

    problems = disagreements(replay_close(path, verify=False))
    assert any("matches" in p for p in problems), problems


def test_the_close_feeds_its_posting_audit_from_the_entries_it_wrote(tmp_path, monkeypatch):
    """Found by mutation, and it is the shallow-proxy shape this project keeps
    finding: feed the audit the proof ids it is checking and the check passes by
    construction. Withhold one real entry and the close must go incomplete."""
    from bench.run import close

    import recon.ledger.posting_rules as rules

    real = rules.entries_for

    def one_short(**kwargs):
        entries, declined = real(**kwargs)
        return [e for e in entries if not e.proof_id or e is not entries[0]], declined

    # Posting moved into `recon.close.run_close` with A1; the patch follows it.
    import recon.close as close_mod

    monkeypatch.setattr(close_mod, "entries_for", one_short)
    result = close("A", journal_dir=tmp_path)
    assert not result.completeness.complete
    assert result.completeness.undisposed_postings
    assert not result.ok


# --------------------------------------------------------------------------
# the event contract refuses, rather than merely constructs
# --------------------------------------------------------------------------


def test_an_event_cannot_carry_a_payload_of_the_wrong_kind():
    """A `MatchProven` carrying an exception's payload would deserialise, route
    to the wrong branch on replay, and produce a scorecard nobody could explain.
    P1's rule applies here too: a validator that is never tested for refusal is
    documentation."""
    from datetime import UTC, datetime

    from pydantic import ValidationError

    from recon.contracts import CloseBlockedPayload, Event, EventKind

    with pytest.raises(ValidationError):
        Event(
            seq=0,
            kind=EventKind.MATCH_PROVEN,
            at=datetime.now(UTC),
            actor="engine",
            outcome="proven",
            input_hash="x",
            payload=CloseBlockedPayload(reasons=["wrong shape"]),
        )


def test_an_event_must_name_who_decided():
    from datetime import UTC, datetime

    from pydantic import ValidationError

    from recon.contracts import CloseBlockedPayload, Event, EventKind

    for blank in ("", "   "):
        with pytest.raises(ValidationError):
            Event(
                seq=0,
                kind=EventKind.CLOSE_BLOCKED,
                at=datetime.now(UTC),
                actor=blank,
                outcome="blocked",
                input_hash="x",
                payload=CloseBlockedPayload(reasons=["r"]),
            )


def test_an_unknown_kind_is_rejected_before_anything_reads_it():
    from pydantic import ValidationError

    from recon.contracts import Event

    with pytest.raises((ValidationError, ValueError, KeyError)):
        Event.model_validate_json(
            '{"seq":0,"kind":"WhateverIWant","at":"2026-08-01T00:00:00Z",'
            '"actor":"a","outcome":"o","input_hash":"h","payload":{}}'
        )


def test_a_log_of_refusals_replays_to_an_empty_scorecard(tmp_path, monkeypatch):
    from bench.replay import replay_close, scorecard_from_log
    from bench.run import close

    import recon.close as close_mod
    from recon.engine.verifier import Verdict, VerdictKind

    monkeypatch.setattr(
        close_mod,
        "verify",
        lambda *a, **k: Verdict(VerdictKind.REFUTED, None, ["mutation"], "p@v1"),
    )
    result = close("A", journal_dir=tmp_path)
    replayed = replay_close(result.journal_path)
    assert replayed.rejected, "the refusals did not survive the round trip"
    assert replayed.pairs == {}
    card = scorecard_from_log(result.journal_path, BATCHES / "A" / "labels.json")
    assert card.produced == 0


def test_disagreements_on_an_unterminated_log_says_so(closed, tmp_path):
    from bench.replay import replay_close

    from recon.journal.replay import disagreements

    lines = closed.journal_path.read_text(encoding="utf-8").splitlines()[:-1]
    path = tmp_path / "open.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert any("does not terminate" in p for p in disagreements(replay_close(path)))


def test_the_replay_command_runs_and_reports_agreement(closed, capsys):
    """`make replay` is a claim in the Makefile. An entry point nothing runs is
    how `tests/gates/` came to collect zero tests at P1."""
    from bench.replay_cli import main

    assert main(["A", "--log", str(closed.journal_path)]) == 0
    out = capsys.readouterr().out
    assert "auto-match" in out and "coverage" in out
    assert "PROBLEM" not in out


def test_the_replay_command_reports_a_tampered_log_rather_than_scoring_it(closed, tmp_path, capsys):
    from bench.replay_cli import main

    lines = closed.journal_path.read_text(encoding="utf-8").splitlines()
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(lines[:3] + lines[4:]) + "\n", encoding="utf-8")
    assert main(["A", "--log", str(path)]) == 1
    assert "PROBLEM" in capsys.readouterr().out


def test_the_replay_command_says_so_when_there_is_no_log(tmp_path, capsys):
    from bench.replay_cli import main

    assert main(["A", "--log", str(tmp_path / "absent.jsonl")]) == 2
    assert "no decision log" in capsys.readouterr().out


def test_no_decision_carries_a_wall_clock_measurement(closed):
    """Found by this file's own determinism test, intermittently.

    The subset-sum solver appended its elapsed time to the summary that becomes
    an exception's `evidence`, so the same close produced a different decision
    on every run — `4ms` one time, `1ms` the next — and could not be replayed.
    The determinism test only failed when the timings happened to differ, which
    is a test that catches a bug some of the time.

    Timing is not a decision. It is a fact about our machine, the same
    distinction this codebase already draws for `E13`, and it belongs in metrics
    rather than in the record.
    """
    import re

    clock = re.compile(r"\b\d+\s?(ms|s|sec|seconds|ns)\b")
    for exception in closed.exceptions:
        for line in exception.evidence:
            assert not clock.search(line), f"{exception.exception_id} evidence: {line!r}"
        assert not clock.search(exception.hypothesis or "")


def test_a_stated_bound_is_still_evidence(closed):
    """The other half: a bound that was *hit* is a policy limit and part of the
    finding, so removing the clock must not remove that too."""
    from recon.engine.subsetsum import Outcome, SubsetResult

    hit = SubsetResult(
        outcome=Outcome.TIMEOUT,
        solutions=[],
        candidates=40,
        wall_ms=5000,
        bound_hit="wall clock 5000ms",
    )
    assert "bound hit: wall clock 5000ms" in hit.summary()
    assert "5000ms)" not in hit.summary().replace("bound hit: wall clock 5000ms", "")
