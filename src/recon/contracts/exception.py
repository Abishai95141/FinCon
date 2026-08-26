"""ReconException — one unresolved item, labelled from an open vocabulary.

Named ReconException rather than Exception to avoid shadowing the builtin: a
model named `Exception` in a package that also raises would be a trap for every
future reader.

**The code set was closed until P11 and is now open, with the authority moved
rather than removed.** The old argument was that a model which can invent a
category can drift. True — but a closed enum leaves an agent meeting something
genuinely new with two options, pick the nearest wrong code or crash, and a
wrong code routes work to the wrong desk and may fire the wrong rule. That is a
confident wrong answer, which is the failure this project exists to prevent.

So the split is: this contract validates the *shape* of a code, and
`TaxonomyRegistry` says what one *means* and what it may do. Minting a code
grants nothing; the lifecycle hands power back a step at a time. A well-formed
id that resolves in no registry entry fails the close — open is not "anything
goes".
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import CONTRACT_VERSION, Money
from .proof import ProofTier
from .taxonomy import CodeId


class ExceptionCode(StrEnum):
    """The ids that ship seeded, as named constants.

    **Not the vocabulary.** Since P11 `ReconException.code` is a pattern-validated
    string and the registry is the authority; this enum exists so code that means
    `E09` can say so instead of writing a string literal. A member here is just an
    id that happens to be seeded — it carries no more weight than any other entry
    in the registry, and `X-...` codes are equally real.
    """

    E01_TIMING = "E01"
    E02_FEE_VARIANCE = "E02"
    E03_FX_ROUNDING = "E03"
    E04_PARTIAL_PAYMENT = "E04"
    E05_OVERPAYMENT = "E05"
    E06_DUPLICATE = "E06"
    E07_CHARGEBACK_POST_PERIOD = "E07"
    E08_MISSING_REMITTANCE = "E08"
    E09_NETTING_AMBIGUITY = "E09"
    E10_REFERENCE_CORRUPTION = "E10"
    E11_COUNTERPARTY_ALIAS = "E11"
    E12_WRONG_ENTITY = "E12"
    E13_SOLVER_TIMEOUT = "E13"
    E14_UNEXPLAINED = "E14"
    """No strategy applied and the engine cannot say why. Added in 1.4.0 because
    invariant 8 requires a disposition for every input, and force-fitting an
    unmatched item into `E02` or `E01` would put a guess where the engine has
    only facts. Carries what it does know — the amount, the best residual, the
    row count — and leaves classification to triage."""


class Resolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolved_by: str
    resolved_at: datetime
    action: str
    """What was done, in the resolver's words. Feeds rule induction (P7)."""
    posting_hint: str | None = None
    """Account the difference was booked to, where one was chosen."""


class ReconException(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str = CONTRACT_VERSION
    exception_id: str
    code: CodeId
    """A pattern-validated id, not an enum member. What it *means* — who owns it,
    whether a rule may key on it, where it books — comes from the registry, which
    is a separate versioned input the proposer cannot supply."""

    as_of: date

    fingerprint: str = ""
    """Content-derived identity for the *break*, stable across closes.

    `exception_id` is positional — `EXC-00001` names a different finding in
    every batch — which is the defect P12 fixed for records
    (`source:natural-key-hash:occurrence`) and never fixed one layer up. So the
    same unresolved break appearing in two consecutive closes had no linkage, no
    first-seen, and no occurrence count, and the worklist's "age" was the age of
    the *transaction* rather than of the break.

    Borrowed from Open Policy Agent-adjacent practice by way of Formance's
    reconciliation service, which dedups alerts on `(rule_id, fingerprint,
    period_id)` and carries `first_seen_at` / `occurrence_count` — a break that
    persists is one case that keeps recurring, not N unrelated findings.
    """

    code_provenance: ProofTier = ProofTier.P3_DECLARED
    """How this exception came by its code — not how confident we are in it.

    `P0` means the engine *derived* the label: `E09` from an enumeration that
    found two valid subsets, `E13` from a bound it measured. `P3` is the default
    and means nobody vouched for it — `E14` is exactly that, the absence of a
    derivation.

    It exists so `reclassifiable` can ask about *evidence* instead of consulting
    a hardcoded list of code ids. A proposal is `P2` at best, so it may overwrite
    `P3` and never `P0`."""

    amount: Money
    """Cash impact. Drives ranking and must tie to the balance-assertion gap
    for bank-leg exceptions (CLAUDE.md invariant 1)."""

    leg: str = "bank"
    """"bank" moves the balance-assertion gap; "orders" is a linkage failure
    that leaves the bank balance untouched. Summing the two would make the
    invariant unfalsifiable."""

    record_ids: list[str] = Field(default_factory=list)
    """The records this is about."""

    ambiguous_codes: list[str] = Field(default_factory=list)
    """Codes the engine *derived* are equally supported, when it could not pick.

    Structured rather than left in the hypothesis, because a checker that had to
    parse "either X or Y" out of prose would be the engine reading text it wrote
    — and because this is what stops a model proposal overturning a derived
    ambiguity. The engine did not fail to decide here; it decided that these
    files cannot decide, which is a `P0` finding like any other."""

    hypothesis: str | None = None
    """Model-authored, one sentence. Never authoritative — a human reads it."""

    evidence: list[str] = Field(default_factory=list)
    """Citations a human can follow: record lineage, contract clause, prior rule."""

    rank: int | None = None
    """1 = work this first. Assigned by triage on cash impact x age."""

    alternatives: list[list[str]] | None = None
    """E09 only: the competing record subsets. Present so a reviewer can confirm
    the ambiguity rather than take the classifier's word for it.

    They must be **distinct**, not disjoint. Contract 1.1.0 required
    disjointness, which was wrong: {A,B} and {B,C} both summing to the target is
    genuine ambiguity — two valid answers that happen to share a record. The
    solver produces overlapping alternatives whenever a row can belong to more
    than one viable subset, and rejecting those would have forced the engine to
    hide real ambiguity to satisfy a validator."""

    blocks_close: bool = False
    resolution: Resolution | None = None

    @model_validator(mode="after")
    def _ambiguity_shows_its_alternatives(self) -> ReconException:
        if self.code == ExceptionCode.E09_NETTING_AMBIGUITY:
            if not self.alternatives or len(self.alternatives) < 2:
                raise ValueError("E09 must carry at least two competing subsets")
            if any(not subset for subset in self.alternatives):
                raise ValueError("an empty subset is not an alternative")
            shapes = {frozenset(subset) for subset in self.alternatives}
            if len(shapes) < 2:
                raise ValueError(
                    "E09 alternatives must be distinct — the same subset listed "
                    "twice is one answer, not an ambiguity"
                )
        if self.leg not in {"bank", "orders"}:
            raise ValueError(f"leg must be 'bank' or 'orders', got {self.leg!r}")
        return self
