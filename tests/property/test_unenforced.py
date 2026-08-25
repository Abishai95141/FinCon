"""A ratchet over things that are declared and not enforced.

This project has now fixed the same disease five times in five costumes: a proof
that named a rule nobody checked, actions promoted that did nothing, authority
pinned but unsigned, approvals granted but never re-examined, a vocabulary the
model was judged on but never told. Each fix was structural for its instance.
None of them stopped the *next* instance, which is why it kept recurring.

This is the thing that does. It counts declarations nothing downstream reads and
refuses to let that number grow. It does not demand zero — many of these are
payload fields written for an auditor to read later, which is a real purpose that
no amount of grepping can see. What it forbids is *adding* to the pile without
noticing, which is exactly how every one of the five arrived.

The number is a budget, not a target. Lower it when you close some; never raise
it to make a commit green.
"""

from __future__ import annotations

import ast
import pathlib
import re

from recon.contracts import PRODUCERS

ROOT = pathlib.Path(__file__).resolve().parents[2]
#: Measured 2026-08-25 at 57, then 52 the same day. Ratchet: may fall, never rise.
#:
#: The audit quoted 40 for the same idea. The difference is not drift — that
#: scan searched `contracts/` as well, so a validator reading its own field
#: counted as a consumer. Excluding the package is the stricter and more useful
#: question: does anything *outside* the contract ever read this? 57 was the
#: honest answer to it, and the smaller number was the flattering one.
#:
#: 57 -> 52 at P13/P14, and the *cause* is worth more than the number. Nothing
#: was written to close these five; a surface was built, and it turned out that
#: an API and an MCP server read fields nobody had had a reason to read before —
#: the intake proof's row counts, the promotion event's approver, the code
#: definition's owner. "Unread" was never a property of the contract. It was a
#: property of having no consumer, and the honest way to fall further is to
#: build things that need them rather than to wire readers on purpose.
UNREAD_FIELD_BUDGET = 52

_SKIP = {"contract_version", "model_config"}


def _production_source() -> str:
    return "\n".join(
        p.read_text()
        for p in [*ROOT.glob("src/recon/**/*.py"), *ROOT.glob("bench/**/*.py")]
        if "contracts/" not in p.as_posix()
    )


def unread_contract_fields() -> list[str]:
    """Contract fields nothing outside `contracts/` ever reads.

    Deliberately crude — an attribute-name grep. A field named the same as an
    unrelated attribute elsewhere counts as read, so this *under*-reports. That
    is the right direction for a ratchet: it will not manufacture work, and a
    number that only moves when something real changes is a number people trust.
    """
    prod = _production_source()
    unread: list[str] = []
    for path in sorted(ROOT.glob("src/recon/contracts/*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                if not (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)):
                    continue
                name = stmt.target.id
                if name.startswith("_") or name in _SKIP:
                    continue
                if not re.search(rf"\.{re.escape(name)}\b", prod):
                    unread.append(f"{node.name}.{name}")
    return sorted(unread)


def test_every_event_kind_has_real_code_that_emits_it():
    """The one sub-class of this that *is* closed, and stays closed.

    `PRODUCERS` maps each event kind to what produces it, and a phase number
    there means 'nothing does, yet'. That was 3 at P9 and is 0 now — the only
    part of this disease that has been measurably eliminated rather than
    treated instance by instance.
    """
    pending = {k.value: v for k, v in PRODUCERS.items() if v.startswith("P")}
    assert not pending, (
        f"{len(pending)} event kind(s) are declared with no producer: {pending}. "
        "A typed event nothing emits is a promise in the contract and a hole in the log"
    )


def test_the_unread_contract_field_count_does_not_grow():
    """The ratchet itself."""
    unread = unread_contract_fields()
    assert len(unread) <= UNREAD_FIELD_BUDGET, (
        f"{len(unread)} contract fields nothing outside contracts/ reads, over the "
        f"budget of {UNREAD_FIELD_BUDGET}. New ones: this is how every declared-"
        f"but-unenforced defect in this codebase arrived. All of them:\n  " + "\n  ".join(unread)
    )


def test_the_budget_is_not_slack():
    """A budget far above the real number ratchets nothing. If the count has
    fallen, this fails and makes you tighten it — the direction a ratchet is
    supposed to move."""
    unread = unread_contract_fields()
    assert len(unread) >= UNREAD_FIELD_BUDGET - 2, (
        f"only {len(unread)} unread fields against a budget of {UNREAD_FIELD_BUDGET}. "
        f"Lower UNREAD_FIELD_BUDGET to {len(unread)} and keep the ratchet tight"
    )


def test_the_scan_finds_something_it_is_supposed_to_find():
    """A ratchet counting zero things would pass forever. `scorecard_digest` is
    a known member of this population: it exists so a caller that *can* score
    may attach a digest, and nothing in the product reads it back."""
    assert "CloseCompletedPayload.scorecard_digest" in unread_contract_fields()
