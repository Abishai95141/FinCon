"""An exception that ends in an entry, and the bounds that stop it.

`docs/10-THE-USER-FLOW.md` §5.1 measured what this replaces: accepting a
classification left the journal at 23 entries and 4,994 bytes and changed
nothing about what blocked the close. The product could name a break, price it
and record who agreed with the naming, and the money never moved.

Two kinds of test here, and the second kind is the one that matters.

The first kind asserts a disposition *does* something — the journal grows, the
entry balances, the item stops blocking, beancount accepts it. Those catch a
feature that was never wired.

The second kind asserts the ceilings *refuse*. A write-off control that never
declines is a control nobody has seen work, and the two ways it is defeated are
different: one large item goes over the per-item ceiling, and ninety small ones
go under it and take the close apart between them. `F4` is the second one — a
reason makes a write-off legible, and only a budget makes it bounded.
"""

from __future__ import annotations

import csv
import io
import pathlib
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from recon import loop as looplib
from recon import review, service
from recon.disposition import (
    DEFAULT_SOURCE,
    DESTINATION,
    Decision,
    Disposition,
    DispositionError,
    budget_for,
    decide,
)
from recon.ledger.accounts import AccountRole
from tests.conftest import close_and_wait, signed_in_client

LOOP = "settlement_3way"
BATCH = "A"
ZERO = Decimal("0.00")


@pytest.fixture
def closed(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    client, _user_id, runs = signed_in_client(monkeypatch, tmp_path)
    page = close_and_wait(client, loop=LOOP, source_set=BATCH)
    return client, str(page.url).rsplit("/", 1)[-1], runs


def _tail(run_id, runs):
    return sorted(
        (e.exception for e in service.view(run_id, runs).exceptions),
        key=lambda e: abs(e.amount),
    )


def _rows(export) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(export.csv)))


# --------------------------------------------------------------- it moves money


def test_a_disposition_adds_a_balanced_entry_the_close_did_not_have(closed):
    """The whole point, stated as a diff. Before this existed the same sequence
    left every one of these numbers untouched."""
    _client, run_id, runs = closed
    before = service.journal(run_id, runs)
    smallest = _tail(run_id, runs)[0]

    result = service.dispose(
        run_id,
        smallest.exception_id,
        "write_off",
        decided_by="abishai",
        rationale="below materiality and aged out",
        runs_dir=runs,
    )
    after = service.journal(run_id, runs)

    assert after.entries == before.entries + 1
    assert after.decided == before.decided + 1
    assert len(after.csv) > len(before.csv)
    assert after.balanced

    mine = [r for r in _rows(after) if r["entry_id"] == result.entry_id]
    assert len(mine) == 2, "a disposition must be double entry, not a memo"
    assert sum(Decimal(r["amount"]) for r in mine) == ZERO
    assert {r["tier"] for r in mine} == {"P2"}
    assert {r["origin"] for r in mine} == {smallest.exception_id}


def test_each_of_the_four_endings_debits_a_different_real_account(closed):
    """Four endings that all booked to the same place would be one ending with
    four labels — which is what a status field is."""
    _client, run_id, runs = closed
    tail = _tail(run_id, runs)
    chart = looplib.get(LOOP).chart()

    made = {}
    for exception, kind, extra in (
        (tail[0], "write_off", {}),
        (tail[1], "carry_forward", {}),
        (tail[2], "chase", {"owner": "meera", "due_on": date(2026, 9, 15)}),
    ):
        made[kind] = service.dispose(
            run_id,
            exception.exception_id,
            kind,
            decided_by="abishai",
            rationale=f"{kind} because the evidence says so",
            runs_dir=runs,
            **extra,
        )

    debits = {kind: result.debit for kind, result in made.items()}
    assert len(set(debits.values())) == 3, f"endings collapsed onto one account: {debits}"
    assert debits["write_off"] == chart[AccountRole.WRITE_OFF]
    assert debits["carry_forward"] == chart[AccountRole.IN_TRANSIT]
    assert debits["chase"] == chart[AccountRole.RECEIVABLE]
    assert {r.credit for r in made.values()} == {chart[DEFAULT_SOURCE]}


def test_a_disposed_item_stops_blocking_the_close(closed):
    """An ending that left the item blocking would be an ending in name only."""
    _client, run_id, runs = closed
    view = service.view(run_id, runs)
    blocking = view.blocking_exceptions
    assert blocking, "batch A stopped producing blockers; this test has no subject"

    target = next(e for e in _tail(run_id, runs) if e.exception_id in blocking)
    result = service.dispose(
        run_id,
        target.exception_id,
        "chase",
        decided_by="abishai",
        rationale="gateway says sent, bank never received",
        owner="meera",
        due_on=date(2026, 9, 15),
        runs_dir=runs,
    )
    assert target.exception_id not in result.blockers_left
    assert len(result.blockers_left) == len(blocking) - 1


def test_beancount_accepts_a_journal_with_dispositions_in_it(closed, tmp_path):
    """Our arithmetic checking our arithmetic proves nothing about syntax. This
    caught a real one: `decided_by: abishai` is a beancount lexer error, and the
    transaction was silently dropped from a file that otherwise looked fine."""
    loader = pytest.importorskip("beancount.loader")
    _client, run_id, runs = closed
    tail = _tail(run_id, runs)

    service.dispose(
        run_id,
        tail[0].exception_id,
        "write_off",
        decided_by="abishai kc",
        rationale="small, and four months old",
        runs_dir=runs,
    )
    export = service.journal(run_id, runs)
    ledger = tmp_path / "merged.beancount"
    ledger.write_text(export.beancount)

    entries, errors, _options = loader.load_file(str(ledger))
    assert not errors, f"beancount rejected our export: {errors[:3]}"

    txns = [e for e in entries if type(e).__name__ == "Transaction"]
    assert len(txns) == export.entries, (
        f"we claim {export.entries} entries and beancount found {len(txns)}"
    )
    for txn in txns:
        assert sum((p.units.number for p in txn.postings), start=0) == 0


# ------------------------------------------------------------------ it refuses


def test_a_large_item_cannot_be_written_off(closed):
    """The per-item ceiling, seen refusing *on its own*.

    The first version of this test asserted `"ceiling" in message` against the
    biggest item in the tail — and survived a mutant that disabled the ceiling
    entirely, because that item is also over the budget and the budget's own
    refusal says the word "ceiling" in passing. So the subject here is sized to
    sit over the ceiling and comfortably under the budget: nothing but the
    per-item check can decline it.
    """
    _client, run_id, runs = closed
    policy = looplib.get(LOOP).policy()
    tail = _tail(run_id, runs)
    budget = budget_for(tail, policy)

    over = policy.write_off_ceiling + Decimal("1.00")
    assert over < budget, "the corpus no longer separates the two bounds"
    item = tail[0].model_copy(update={"amount": over})

    with pytest.raises(DispositionError) as caught:
        decide(
            exception=item,
            disposition=Disposition.WRITE_OFF,
            chart=looplib.get(LOOP).chart(),
            policy=policy,
            decided_by="abishai",
            rationale="I would like this to go away",
            tail=tail,
        )
    assert "escalates" in str(caught.value), f"the refusal is not the ceiling's: {caught.value}"
    assert "budget" not in str(caught.value)

    biggest = tail[-1]
    with pytest.raises(service.ServiceError):
        service.dispose(
            run_id,
            biggest.exception_id,
            "write_off",
            decided_by="abishai",
            rationale="nor this",
            runs_dir=runs,
        )
    assert service.journal(run_id, runs).decided == 0, "a refusal still wrote an entry"


def test_many_small_write_offs_are_bounded_in_total(closed):
    """`F4`. Ninety items at ₹499 each pass the per-item ceiling one at a time.

    Constructed rather than drawn from the corpus, because batch A does not
    happen to contain enough small items to exhaust the budget — and a bound
    that is never approached is a bound nobody has watched hold.
    """
    _client, run_id, runs = closed
    policy = looplib.get(LOOP).policy()
    chart = looplib.get(LOOP).chart()
    tail = _tail(run_id, runs)
    template = tail[0]

    budget = budget_for(tail, policy)
    assert budget > ZERO

    spent = ZERO
    approved = 0
    refused = None
    for index in range(500):
        item = template.model_copy(
            update={
                "exception_id": f"EXC-SYNTH-{index:03d}",
                "amount": policy.write_off_ceiling,
            }
        )
        try:
            outcome = decide(
                exception=item,
                disposition=Disposition.WRITE_OFF,
                chart=chart,
                policy=policy,
                decided_by="abishai",
                rationale="under the ceiling",
                tail=tail,
                already_written_off=spent,
            )
        except DispositionError as exc:
            refused = str(exc)
            break
        spent += abs(item.amount)
        approved += 1
        assert outcome.budget_left is not None and outcome.budget_left >= ZERO

    assert refused is not None, (
        f"{approved} write-offs of {policy.write_off_ceiling} each were all approved — "
        f"the per-item ceiling is the only bound and the budget does nothing"
    )
    assert "budget" in refused
    assert spent <= budget


def test_the_budget_cannot_be_enlarged_by_padding_the_tail(closed):
    """A metamorphic relation, and the reason this denominator is fixed.

    `max_reference_selectivity` had exactly this defect: the same rule went from
    refused to allowed when unrelated rows were added, because it was measuring
    corpus composition. Here the denominator must be the tail the close
    produced — so a bigger tail is a bigger budget, which is *correct* and
    monotone, but disposing of items must never move it.
    """
    _client, run_id, runs = closed
    policy = looplib.get(LOOP).policy()
    tail = _tail(run_id, runs)
    before = budget_for(tail, policy)

    service.dispose(
        run_id,
        tail[0].exception_id,
        "write_off",
        decided_by="abishai",
        rationale="small",
        runs_dir=runs,
    )
    after = budget_for(_tail(run_id, runs), policy)
    assert after == before, (
        "the write-off budget moved after a write-off — the next one is being "
        "measured against a denominator the last one changed"
    )


def test_an_item_cannot_end_twice(closed):
    """Two endings take the value out twice, and both entries balance."""
    _client, run_id, runs = closed
    target = _tail(run_id, runs)[0]
    common = dict(decided_by="abishai", rationale="first", runs_dir=runs)

    service.dispose(run_id, target.exception_id, "write_off", **common)
    with pytest.raises(service.ServiceError) as caught:
        service.dispose(run_id, target.exception_id, "carry_forward", **common)

    assert "already" in str(caught.value)
    assert service.journal(run_id, runs).decided == 1


def test_a_disposition_needs_a_person_and_a_reason(closed):
    """`P2 ATTESTED` means somebody is accountable, and a number in the books
    with no reason beside it is one nobody can defend."""
    _client, run_id, runs = closed
    target = _tail(run_id, runs)[0]

    with pytest.raises(service.ServiceError, match="named human"):
        service.dispose(
            run_id, target.exception_id, "write_off", decided_by="  ", rationale="x", runs_dir=runs
        )
    with pytest.raises(service.ServiceError, match="rationale"):
        service.dispose(
            run_id,
            target.exception_id,
            "write_off",
            decided_by="abishai",
            rationale="",
            runs_dir=runs,
        )


def test_a_receivable_needs_an_owner_and_a_date(closed):
    """An item that is never late is never chased."""
    _client, run_id, runs = closed
    target = _tail(run_id, runs)[0]

    with pytest.raises(service.ServiceError, match="owner"):
        service.dispose(
            run_id,
            target.exception_id,
            "chase",
            decided_by="abishai",
            rationale="owed",
            runs_dir=runs,
        )
    with pytest.raises(service.ServiceError, match="date"):
        service.dispose(
            run_id,
            target.exception_id,
            "chase",
            decided_by="abishai",
            rationale="owed",
            owner="meera",
            runs_dir=runs,
        )


def test_an_unpromoted_code_cannot_be_booked(closed):
    """Naming grants nothing. A code minted this morning must not reach an
    expense account by being clicked, the same way `posting_rules` will not
    consult a `PROPOSED` code's `books_to`."""
    _client, run_id, runs = closed
    unnamed = next(
        (e for e in _tail(run_id, runs) if e.code == "E14"),
        None,
    )
    assert unnamed is not None, "batch A stopped producing E14; this test has no subject"

    with pytest.raises(service.ServiceError) as caught:
        service.dispose(
            run_id,
            unnamed.exception_id,
            "book",
            decided_by="abishai",
            rationale="looks like a fee",
            runs_dir=runs,
        )
    assert "no account" in str(caught.value) or "promoted" in str(caught.value)


# ------------------------------------------------------------ the shape itself


def test_every_disposition_has_a_destination_and_none_share_one():
    """`raise_advisory` was in the enum, the tool schema and `MODELLED_ACTIONS`
    and implemented nowhere, and it outscored every real rule by doing nothing.
    A member of this enum that reached no account would be the same thing."""
    routed = {d: DESTINATION.get(d) for d in Disposition if d is not Disposition.BOOK}
    assert all(routed.values()), f"a disposition routes nowhere: {routed}"
    assert len(set(routed.values())) == len(routed), "two endings share an account"
    assert DEFAULT_SOURCE not in routed.values(), "an ending debits what it credits"
    assert Disposition.BOOK not in DESTINATION, (
        "BOOK gained a default destination — an unratified code now reaches an account by omission"
    )


def test_a_refused_decision_is_not_constructible(closed):
    """`Decision` has no `ok` field on purpose. A caller cannot hold a rejected
    disposition and use half of it."""
    _client, run_id, runs = closed
    assert not hasattr(Decision, "ok")
    assert "applied" not in Decision.__slots__

    biggest = _tail(run_id, runs)[-1]
    with pytest.raises(DispositionError):
        decide(
            exception=biggest,
            disposition=Disposition.WRITE_OFF,
            chart=looplib.get(LOOP).chart(),
            policy=looplib.get(LOOP).policy(),
            decided_by="abishai",
            rationale="no",
            tail=_tail(run_id, runs),
        )


def test_the_record_carries_the_bounds_it_was_checked_against(closed):
    """A ceiling that only shows up when it refuses is a control an auditor
    cannot see was in force."""
    _client, run_id, runs = closed
    target = _tail(run_id, runs)[0]
    service.dispose(
        run_id,
        target.exception_id,
        "write_off",
        decided_by="abishai",
        rationale="small",
        runs_dir=runs,
    )

    events = review.dispositions(run_id, runs)
    assert len(events) == 1
    payload = events[0].payload
    assert payload.ceiling_applied == looplib.get(LOOP).policy().write_off_ceiling
    assert payload.budget_remaining is not None
    assert payload.policy_ref
    assert payload.fingerprint, "the ending does not name the break it ended"


# --------------------------------------------------------------------- the UI


def test_the_screen_offers_four_endings_and_disables_what_policy_forbids(closed):
    _client, run_id, runs = closed
    client = _client
    tail = _tail(run_id, runs)
    biggest, smallest = tail[-1], tail[0]

    body = client.get(f"/periods/{run_id}/items/{biggest.exception_id}").text
    for kind in Disposition:
        assert f'value="{kind.value}"' in body or f"value='{kind.value}'" in body

    assert "over the" in body and "ceiling" in body, (
        "the write-off control on an item above the ceiling gives no reason"
    )
    small_body = client.get(f"/periods/{run_id}/items/{smallest.exception_id}").text
    assert "escalates" not in small_body


def test_the_route_takes_no_ceiling_no_account_and_no_signer(closed):
    """Every finding in the control-plane audit reduces to the caller supplying
    its own permission, and a form field is how a caller supplies one."""
    import inspect

    from recon.api.ui import dispose_item

    taken = set(inspect.signature(dispose_item).parameters)
    forbidden = {
        "policy",
        "ceiling",
        "write_off_ceiling",
        "budget",
        "account",
        "debit",
        "credit",
        "chart",
        "decided_by",
        "tier",
    }
    assert not (taken & forbidden), f"the route accepts authority: {sorted(taken & forbidden)}"


def test_the_pack_names_who_decided_what_and_under_which_policy(closed):
    _client, run_id, runs = closed
    client = _client
    target = _tail(run_id, runs)[0]
    service.dispose(
        run_id,
        target.exception_id,
        "write_off",
        decided_by="abishai@acme.in",
        rationale="four months old and under materiality",
        runs_dir=runs,
    )

    body = client.get(f"/periods/{run_id}/pack").text
    assert "Decided by a person" in body
    assert "abishai@acme.in" in body
    assert "four months old and under materiality" in body
    assert looplib.get(LOOP).policy().ref in body


def test_the_budget_is_the_stated_share_of_the_tail(closed):
    """Pinned to its definition, not only to its stability.

    A relation that compares the budget before and against after cannot see a
    budget that is uniformly wrong — a mutant doubling the denominator passed
    it, because doubled-then and doubled-now are still equal. The share is
    policy, so assert the arithmetic.
    """
    _client, run_id, runs = closed
    policy = looplib.get(LOOP).policy()
    tail = _tail(run_id, runs)

    expected = (
        sum((abs(e.amount) for e in tail), start=ZERO) * policy.write_off_budget_ratio
    ).quantize(Decimal("0.01"))
    assert budget_for(tail, policy) == expected
    assert budget_for([], policy) == ZERO, "an empty tail affords a write-off budget"


def test_the_running_write_off_total_comes_off_the_log(closed):
    """The bound is only a bound if the total behind it accumulates.

    `test_many_small_write_offs_are_bounded_in_total` passes
    `already_written_off` itself, so it never touches
    `review.state().written_off` — and a mutant that reset the running total on
    every fold survived it, leaving every item a full budget.

    Batch A holds exactly one item under the ceiling, so this asserts on one
    write-off rather than pretending otherwise: a total that resets reads as
    ₹0.00 after it, which is the mutant.
    """
    _client, run_id, runs = closed
    policy = looplib.get(LOOP).policy()
    tail = _tail(run_id, runs)

    assert review.state(run_id, runs).written_off == ZERO
    small = next(e for e in tail if abs(e.amount) <= policy.write_off_ceiling)
    service.dispose(
        run_id,
        small.exception_id,
        "write_off",
        decided_by="abishai",
        rationale="under materiality",
        runs_dir=runs,
    )

    after = review.state(run_id, runs).written_off
    assert after == abs(small.amount) > ZERO, (
        f"the close's running write-off total reads {after} after writing off "
        f"{abs(small.amount)} — the next item would see an untouched budget"
    )

    # A different ending must not touch the write-off total, or the budget would
    # be consumed by decisions that take nothing out of the books.
    other = next(e for e in tail if e.exception_id != small.exception_id)
    service.dispose(
        run_id,
        other.exception_id,
        "carry_forward",
        decided_by="abishai",
        rationale="T+2 lag",
        runs_dir=runs,
    )
    assert review.state(run_id, runs).written_off == after


def test_the_fold_sums_many_write_offs_rather_than_keeping_the_last(closed):
    """The accumulation itself, over more items than the corpus supplies.

    Folded from constructed events rather than driven through the service,
    because batch A holds one item under the ceiling and a bound tested against
    a single item has not been seen to add.
    """
    from recon.contracts import DispositionRecordedPayload, EventKind
    from recon.contracts.event import Event
    from recon.review import fold

    def written(amount: str, index: int) -> Event:
        return Event(
            seq=index,
            kind=EventKind.DISPOSITION_RECORDED,
            at=datetime(2026, 8, 26, 12, index, tzinfo=UTC),
            actor="abishai",
            outcome="write_off",
            input_hash=f"h{index}",
            prev_hash="",
            event_hash="",
            payload=DispositionRecordedPayload(
                exception_id=f"EXC-{index:05d}",
                fingerprint=f"f{index}",
                disposition="write_off",
                from_code="E02",
                amount=Decimal(amount),
                debit_account="write_off",
                credit_account="clearing",
                entry_id=f"JE-D-EXC-{index:05d}",
                decided_by="abishai",
                rationale="small",
                policy_ref="settlement-in@v1",
            ),
        )

    stream = [written("100.00", i) for i in range(1, 6)]
    state = fold(stream)
    assert state.written_off == Decimal("500.00"), (
        f"five ₹100 write-offs folded to {state.written_off}"
    )
    assert len(state.disposed) == 5


def test_the_signer_is_the_session_and_no_form_field_can_change_it(closed):
    """Checked through the route, not by reading its signature.

    The signature check survived a mutant that fed the `owner` field into
    `decided_by` — the parameter list was still clean, and the value was coming
    from the request anyway. `P2 ATTESTED` names a person; a person able to name
    a different one has attested in somebody else's name.
    """
    client, run_id, runs = closed
    target = _tail(run_id, runs)[0]
    token = client.cookies.get("fincon_csrf", "")

    response = client.post(
        f"/periods/{run_id}/items/{target.exception_id}/dispose",
        data={
            "disposition": "chase",
            "rationale": "owed to us",
            "owner": "somebody-else@evil.in",
            "due_on": "2026-09-15",
            "csrf": token,
        },
    )
    assert response.status_code in (200, 303)

    events = review.dispositions(run_id, runs)
    assert len(events) == 1
    assert events[0].payload.decided_by == "controller@acme.in", (
        f"the form chose the signer: {events[0].payload.decided_by}"
    )
    assert events[0].payload.owner == "somebody-else@evil.in", (
        "the owner field stopped being carried, so this test proves nothing"
    )
