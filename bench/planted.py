"""Scoring the exception list against the defects P0 planted.

Three of the eight metrics live here, and they are the three that separate this
system from the baseline it ties on match rate:

    coverage        did the run notice the defect at all
    classification  did it name the defect correctly
    ambiguity       did it find exactly the ambiguity that exists

Two rules keep these from becoming self-congratulation.

**The denominator comes from the labels.** Not from what we surfaced, and not
from what the run decided to look at. Declaring a hard anchor out of scope is
the obvious way to flatter a coverage number, so scope for *measurement* is read
from the planted label's own `leg` — authored at P0, before the engine existed
and never edited to match it.

**Noticing and naming are scored apart.** `E14 UNEXPLAINED` is the engine
saying "something is wrong here and I cannot say what". That is a real and
useful thing to say, and it is not a classification. Counting it as one would
make the honesty code score like an answer, and the gap it leaves is exactly
what P12's triage has to close.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from recon.contracts import ExceptionCode, ReconException

from .rate import Rate


@dataclass(frozen=True)
class PlantedException:
    """A defect the generator planted, resolved into our record-id space."""

    code: str
    leg: str
    """"bank" or "orders". Decides whether the loop under measurement can see
    it at all — and it is the label's word, not the runner's."""

    subject: str
    record_ids: frozenset[str] = frozenset()
    amount: Decimal | None = None
    note: str = ""
    alternatives: tuple[frozenset[str], ...] | None = None
    """E09 only: the subsets the generator knows are both valid."""


@dataclass(frozen=True)
class ExceptionScore:
    planted_in_scope: int
    out_of_scope: list[PlantedException]
    raised: int
    surfaced: int
    classified: int
    missed: list[str]
    ambiguity_planted: int
    ambiguity_detected: int
    detail: list[str] = field(default_factory=list)

    @property
    def coverage(self) -> Rate:
        """Metric 5 — exceptions surfaced / exceptions planted."""
        return Rate(self.surfaced, self.planted_in_scope)

    @property
    def classification(self) -> Rate:
        """Metric 6 — of what was planted, how much came back with the right
        code. Denominated in *planted*, not in *surfaced*: naming one of two
        noticed defects correctly is not 50% accuracy on the problem."""
        return Rate(self.classified, self.planted_in_scope)

    @property
    def ambiguity(self) -> Rate:
        """Metric 7."""
        return Rate(self.ambiguity_detected, self.ambiguity_planted)


def subsets_agree(planted: Sequence[Iterable[str]], ours: Sequence[Iterable[str]] | None) -> bool:
    """Did we find exactly the ambiguity that exists — no fewer, no more.

    Over-reporting is a real failure, not a harmless surplus: P5 found the
    solver claiming four valid subsets where two exist, because it was free to
    pair a charge from one half with a fee from the other. A metric that counted
    that as a detection would have let it ship. So the count must match, and the
    subsets must match once projected onto the rows the labels name (ours carry
    the cohesive fees; the labels list the charges).
    """
    if not planted or not ours or len(planted) != len(ours):
        return False
    universe: set[str] = set().union(*(set(s) for s in planted))
    projected = {frozenset(set(s) & universe) for s in ours}
    return projected == {frozenset(s) for s in planted}


def load_planted(labels_path: Path, external_of: Mapping[str, str]) -> list[PlantedException]:
    """Read the planted defects and resolve each subject into record ids.

    `external_of` maps record id -> the source's own id. A planted subject is
    either a payout (resolve through its membership) or a row id (itself). A
    subject that resolves to nothing we ingested keeps an empty record set and
    is therefore unsurfaceable — which is the correct outcome to *measure*,
    not to hide.
    """
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    record_of = {ext: rid for rid, ext in external_of.items()}
    membership = labels["payout_membership"]

    def resolve(external_ids: Iterable[str]) -> frozenset[str]:
        return frozenset(record_of[e] for e in external_ids if e in record_of)

    def subject_rows(subject: str) -> list[str]:
        entry = membership.get(subject)
        if entry is None:
            return [subject]
        rows = [*entry["charges"], *entry["refunds"], *entry["fees"]]
        return [*rows, entry["bank_line"]] if entry["bank_line"] else rows

    planted: list[PlantedException] = []
    for raw in labels["expected_exceptions"]:
        subsets = raw.get("ambiguous_subsets")
        planted.append(
            PlantedException(
                code=raw["code"],
                leg=raw["leg"],
                subject=raw["subject"],
                record_ids=resolve(subject_rows(raw["subject"])),
                amount=Decimal(raw["unreconciled"]) if raw.get("unreconciled") else None,
                note=raw.get("note", ""),
                alternatives=tuple(resolve(s) for s in subsets) if subsets else None,
            )
        )
    return planted


def _touches(exc: ReconException, records: frozenset[str]) -> bool:
    named = set(exc.record_ids)
    for subset in exc.alternatives or []:
        named |= set(subset)
    return bool(named & records)


def score_planted(
    planted: Sequence[PlantedException],
    raised: Sequence[ReconException],
    *,
    in_scope_legs: set[str],
) -> ExceptionScore:
    """Score one arm's exception list.

    An arm that surfaces nothing scores zero rather than being excused — the
    baselines produce no exceptions at all, and that is the comparison this
    phase exists to put on the page.

    *Surfaced* is deliberately generous: the run named at least one record
    involved in the defect. It answers "did anyone have to look at this", which
    is what a controller cares about. *Classified* is the strict half.
    """
    in_scope = [p for p in planted if p.leg in in_scope_legs]
    out_of_scope = [p for p in planted if p.leg not in in_scope_legs]

    surfaced = classified = ambiguity_planted = ambiguity_detected = 0
    missed: list[str] = []
    detail: list[str] = []

    for item in in_scope:
        hits = [exc for exc in raised if _touches(exc, item.record_ids)]
        if item.alternatives:
            ambiguity_planted += 1

        if not hits:
            missed.append(item.code)
            # The label's own note, not ours. A miss with no context reads as a
            # bug; some are a stated limit of the loop as configured, and a
            # reader should be able to tell which from the page.
            detail.append(
                f"{item.code} {item.subject:<12} ₹{item.amount or 0:>11}  "
                f"NOT SURFACED — {item.note}"
            )
            continue

        surfaced += 1
        codes = {exc.code.value for exc in hits}
        named = item.code in codes
        classified += int(named)
        verdict = f"surfaced as {item.code}" if named else f"surfaced as {'/'.join(sorted(codes))}"

        if item.alternatives:
            agreed = any(
                exc.code is ExceptionCode.E09_NETTING_AMBIGUITY
                and subsets_agree(item.alternatives, exc.alternatives)
                for exc in hits
            )
            ambiguity_detected += int(agreed)
            verdict += ", subsets agree" if agreed else ", SUBSETS DISAGREE"

        detail.append(f"{item.code} {item.subject:<12} ₹{item.amount or 0:>11}  {verdict}")

    for item in out_of_scope:
        detail.append(
            f"{item.code} {item.subject:<12} ₹{item.amount or 0:>11}  "
            f"out of scope — {item.leg} leg is not part of this loop"
        )

    return ExceptionScore(
        planted_in_scope=len(in_scope),
        out_of_scope=out_of_scope,
        raised=len(raised),
        surfaced=surfaced,
        classified=classified,
        missed=missed,
        ambiguity_planted=ambiguity_planted,
        ambiguity_detected=ambiguity_detected,
        detail=detail,
    )
