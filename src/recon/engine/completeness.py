"""Invariant 8 — every input has a disposition.

This module exists because every other check in the system answers its own
question correctly and nobody asks whether everything that came in got an
answer. Three failure cases shipped green because of that: a header-only file
read as a clean month, a partial payment vanished into `unmatched_anchors`, and
a 1:N settlement did the same. None was a bug in a check. All three were the
absence of this one.

**It must not ask the engine whether it handled everything.** The audit is set
arithmetic over inputs and outputs: given what went in, and given the matches,
exceptions, rejections and out-of-scope declarations that came out, is anything
unaccounted for? Asking the producer to self-report would make this the same
class of check as the ones the audit at P5 walked straight through.

A list of anticipated failures ages badly — the next novel input is by
definition not on it. This catches cases nobody enumerated.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from ..contracts import ReconException, Record


class Disposition(StrEnum):
    MATCHED = "matched"
    EXCEPTED = "excepted"
    """Named in an exception — the item is unresolved but it is not unexplained."""
    OUT_OF_SCOPE = "out_of_scope"
    """Deliberately excluded, with a stated reason. Never a bare exclusion."""
    REJECTED = "rejected"
    """Refused at intake, with a reason. Counted by row conservation."""
    UNDISPOSED = "undisposed"
    """The bug. An input the run neither handled nor mentioned."""


class CompletenessError(AssertionError):
    """Raised by `CompletenessReport.raise_if_incomplete`. A run that finishes
    with an undisposed input is a bug in the system, not a finding about the
    data, so this is an assertion rather than a domain exception."""


@dataclass(frozen=True)
class CompletenessReport:
    anchors: dict[str, Disposition]
    records: dict[str, Disposition]
    sources: dict[str, str]
    """source name -> intake strength (verified / declared / failed)."""

    notes: list[str] = field(default_factory=list)

    @property
    def undisposed_anchors(self) -> list[str]:
        return sorted(k for k, v in self.anchors.items() if v is Disposition.UNDISPOSED)

    @property
    def undisposed_records(self) -> list[str]:
        return sorted(k for k, v in self.records.items() if v is Disposition.UNDISPOSED)

    @property
    def failed_sources(self) -> list[str]:
        return sorted(k for k, v in self.sources.items() if v == "failed")

    @property
    def complete(self) -> bool:
        return not (self.undisposed_anchors or self.undisposed_records or self.failed_sources)

    def tally(self, side: str = "anchors") -> dict[str, int]:
        pool = self.anchors if side == "anchors" else self.records
        counts: dict[str, int] = {}
        for disposition in pool.values():
            counts[disposition.value] = counts.get(disposition.value, 0) + 1
        return dict(sorted(counts.items()))

    def render(self) -> str:
        head = "complete" if self.complete else "INCOMPLETE"
        lines = [
            f"disposition [{head}]  anchors={self.tally('anchors')}  "
            f"records={self.tally('records')}"
        ]
        if self.failed_sources:
            lines.append(f"  sources that failed intake: {self.failed_sources}")
        if self.undisposed_anchors:
            lines.append(
                f"  UNDISPOSED anchors ({len(self.undisposed_anchors)}): "
                f"{self.undisposed_anchors[:5]}"
            )
        if self.undisposed_records:
            lines.append(
                f"  UNDISPOSED records ({len(self.undisposed_records)}): "
                f"{self.undisposed_records[:5]}"
            )
        return "\n".join(lines + [f"  {n}" for n in self.notes])

    def raise_if_incomplete(self) -> None:
        if not self.complete:
            raise CompletenessError(self.render())


def audit(
    *,
    anchors: Iterable[Record],
    group_records: Iterable[Record],
    matched_anchor_ids: Iterable[str],
    matched_record_ids: Iterable[str],
    exceptions: Iterable[ReconException],
    out_of_scope: Mapping[str, str] | None = None,
    rejected_ids: Iterable[str] = (),
    source_strengths: Mapping[str, str] | None = None,
) -> CompletenessReport:
    """Set arithmetic over what went in and what came out.

    `out_of_scope` maps id -> reason. A bare set of excluded ids is not
    acceptable input: an exclusion without a reason is indistinguishable from a
    silent drop, which is the thing this module exists to catch.
    """
    scope = dict(out_of_scope or {})
    unreasoned = sorted(k for k, v in scope.items() if not (v or "").strip())
    matched_a, matched_r = set(matched_anchor_ids), set(matched_record_ids)
    rejected = set(rejected_ids)
    # A record listed in an exception's `alternatives` is explained by that
    # exception just as much as one in `record_ids` — E09 names its competing
    # subsets there, and those rows are anything but unmentioned.
    exception_list = list(exceptions)
    explained = {rid for exc in exception_list for rid in exc.record_ids}
    explained |= {
        rid for exc in exception_list for subset in (exc.alternatives or []) for rid in subset
    }

    def classify(record_id: str) -> Disposition:
        if record_id in matched_a or record_id in matched_r:
            return Disposition.MATCHED
        if record_id in explained:
            return Disposition.EXCEPTED
        if record_id in rejected:
            return Disposition.REJECTED
        # An exclusion only counts when it carries a reason.
        if record_id in scope and record_id not in unreasoned:
            return Disposition.OUT_OF_SCOPE
        return Disposition.UNDISPOSED

    notes: list[str] = []
    if unreasoned:
        notes.append(
            f"{len(unreasoned)} out-of-scope declaration(s) carry no reason and do "
            f"not count as disposed: {unreasoned[:5]}"
        )

    return CompletenessReport(
        anchors={rec.record_id: classify(rec.record_id) for rec in anchors},
        records={rec.record_id: classify(rec.record_id) for rec in group_records},
        sources=dict(source_strengths or {}),
        notes=notes,
    )
