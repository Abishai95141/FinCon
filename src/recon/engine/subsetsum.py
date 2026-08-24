"""T2 subset-sum, with uniqueness treated as something to prove.

Finding one subset that sums to a payout is not evidence it is the only one.
This module enumerates solutions against a fixed target and reports what it
actually established:

    UNIQUE      exactly one subset, enumeration ran to completion
    AMBIGUOUS   two or more subsets — a data finding, no correct answer exists
    UNPROVEN    one subset found, but a bound stopped the enumeration
    TIMEOUT     the solver ran out of wall clock
    NONE        no subset sums to the target within tolerance

UNPROVEN and TIMEOUT are compute bounds, not data findings, and they map to
`E13` rather than `E09`. Reporting "unique" after a search that stopped early
would be a confident wrong answer on exactly the case this phase exists to
catch — see CLAUDE.md, and the honesty codes.

Amounts cross into the solver as **integer minor units**. CP-SAT is integer-only,
and rounding Decimals to floats on the way in would reintroduce the drift the
whole ledger is built to avoid.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from ortools.sat.python import cp_model

from ..contracts import Record

MINOR = Decimal("100")


class Outcome(StrEnum):
    UNIQUE = "unique"
    AMBIGUOUS = "ambiguous"
    UNPROVEN = "unproven"
    TIMEOUT = "timeout"
    NONE = "none"


@dataclass(frozen=True)
class SolverBounds:
    """Bounds are set before they are needed, not after a run hangs.

    Subset-sum is NP-hard: 40 candidate rows is ~10^12 subsets. Every bound here
    is a capacity limit, and hitting one is reported as such.
    """

    max_ms: int = 5000
    """Wall-clock budget in integer milliseconds. Seconds-as-float would trip
    the no-float rule in engine/ (CLAUDE.md rule 4) — and the rule is right to
    be blunt: durations at rest are integers here for the same reason money is.
    """
    max_solutions: int = 16
    """Enumeration cap. Hitting it means uniqueness was not established, which
    is why it is a distinct outcome rather than a silent truncation."""
    max_candidates: int = 40
    """Refuse rather than start a search that cannot finish honestly."""


@dataclass(frozen=True)
class SubsetResult:
    outcome: Outcome
    solutions: list[list[str]] = field(default_factory=list)
    """Record ids per solution, each sorted; solutions sorted among themselves
    so a rerun reports them in the same order."""

    bound_hit: str | None = None
    wall_ms: int = 0
    candidates: int = 0

    @property
    def proven_unique(self) -> bool:
        return self.outcome is Outcome.UNIQUE

    @property
    def is_capacity_limit(self) -> bool:
        """True where the answer is about our compute, not about the data."""
        return self.outcome in {Outcome.UNPROVEN, Outcome.TIMEOUT}

    def summary(self) -> str:
        text = (
            f"{self.outcome.value} ({len(self.solutions)} solution(s), {self.candidates} candidates"
        )
        if self.bound_hit:
            text += f", bound hit: {self.bound_hit}"
        return text + f", {self.wall_ms}ms)"


class _Collector(cp_model.CpSolverSolutionCallback):
    """Stops the search once `limit` solutions are seen, and records that it
    stopped — the difference between 'there are two' and 'we stopped at two'."""

    def __init__(self, flags: list[cp_model.IntVar], ids: list[str], limit: int) -> None:
        super().__init__()
        self._flags = flags
        self._ids = ids
        self._limit = limit
        self.solutions: list[list[str]] = []
        self.hit_limit = False

    def on_solution_callback(self) -> None:
        chosen = sorted(
            rid for flag, rid in zip(self._flags, self._ids, strict=True) if self.Value(flag)
        )
        if chosen:
            self.solutions.append(chosen)
        if len(self.solutions) >= self._limit:
            self.hit_limit = True
            self.StopSearch()


def solve(
    target: Decimal,
    candidates: list[Record],
    tolerance: Decimal = Decimal("0.00"),
    bounds: SolverBounds | None = None,
    cohesion_key: str | None = None,
) -> SubsetResult:
    """Which subset of `candidates` sums to `target`, and is it the only one?

    `target` is what the subset must sum to — the caller has already applied any
    sign convention, so this function is pure arithmetic over the records given.

    `cohesion_key` names a key whose equal values must move together: a fee and
    the charge it was levied on share a payment id, so a subset containing one
    without the other is not a payout any gateway ever made. Without this the
    solver reports subsets that mix a charge from one group with a fee from
    another — more ambiguity than the data actually contains, and a solution
    space that grows combinatorially with the number of fee rows. The key is
    named by the profile; the engine stays domain-agnostic.
    """
    bounds = bounds or SolverBounds()
    if not candidates:
        return SubsetResult(Outcome.NONE, candidates=0)

    if len(candidates) > bounds.max_candidates:
        # Refuse up front rather than start a search that cannot finish
        # honestly. A refusal names its bound; a hang does not.
        return SubsetResult(
            Outcome.TIMEOUT,
            bound_hit=f"max_candidates={bounds.max_candidates} (got {len(candidates)})",
            candidates=len(candidates),
        )

    amounts = [int((rec.amount * MINOR).to_integral_value()) for rec in candidates]
    ids = [rec.record_id for rec in candidates]
    goal = int((target * MINOR).to_integral_value())
    slack = int((tolerance * MINOR).to_integral_value())

    model = cp_model.CpModel()
    flags = [model.NewBoolVar(f"x{i}") for i in range(len(candidates))]
    total = sum(flag * amount for flag, amount in zip(flags, amounts, strict=True))
    model.Add(total >= goal - slack)
    model.Add(total <= goal + slack)
    model.Add(sum(flags) >= 1)  # the empty set is not an answer

    if cohesion_key is not None:
        cohorts: dict[str, list[cp_model.IntVar]] = {}
        for flag, rec in zip(flags, candidates, strict=True):
            value = rec.keys.get(cohesion_key)
            if value:
                cohorts.setdefault(value, []).append(flag)
        for members in cohorts.values():
            for other in members[1:]:
                model.Add(other == members[0])

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = bounds.max_ms / 1000
    solver.parameters.enumerate_all_solutions = True
    # Single worker: parallel search makes enumeration order nondeterministic,
    # and a rerun that reports its solutions in a different order is not
    # replayable evidence.
    solver.parameters.num_search_workers = 1

    collector = _Collector(flags, ids, bounds.max_solutions)
    started = time.monotonic_ns()
    status = solver.Solve(model, collector)
    elapsed = (time.monotonic_ns() - started) // 1_000_000

    found = sorted(collector.solutions)
    common = dict(solutions=found, wall_ms=elapsed, candidates=len(candidates))

    if collector.hit_limit:
        return SubsetResult(
            Outcome.UNPROVEN,
            bound_hit=f"max_solutions={bounds.max_solutions}",
            **common,
        )
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE) and not found:
        if status == cp_model.INFEASIBLE:
            return SubsetResult(Outcome.NONE, **common)
        return SubsetResult(Outcome.TIMEOUT, bound_hit=f"max_ms={bounds.max_ms}", **common)
    if not found:
        return SubsetResult(Outcome.NONE, **common)
    if len(found) == 1:
        return SubsetResult(Outcome.UNIQUE, **common)
    return SubsetResult(Outcome.AMBIGUOUS, **common)
