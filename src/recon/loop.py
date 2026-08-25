"""A named reconciliation loop the product can run on its own.

`bench/run.py:load_sides` was the only thing that knew which adapter reads which
file, which rows this loop declines to reconcile, and where the period starts.
`recon.close.run_close` took records that had *already* been read — so the
library could reconcile, and could not read. The one executable form of "close
the books" was a benchmark, and any surface built over it would either import
the harness that scores against ground truth or grow a second copy of intake.
That second copy is the banned pattern: a demo path that differs from the real
path.

So the loop definition moves here and the benchmark keeps a five-line delegate.
Everything a surface needs to run a close is now product configuration:

    loop = recon.loop.get("settlement_3way")
    outcome = recon.loop.run(loop, Path("data/batches/A"))

**Authority is not a parameter.** `run` takes no policy, no taxonomy and no rule
set. It loads each from the loop's own files and verifies their signatures, for
the reason `verifier.verify` takes policy separately: a caller that supplies the
authority is supplying its own permission (audit findings `F1`/`F2`). An HTTP
request and an MCP tool call are both callers, and the MCP caller may be a
model — so the boundary has to hold at the *type* level, not by convention.

**The run id is derived from the inputs and the authority, never from a clock.**
Two closes over the same bytes under the same policy get the same id, so a
re-close is idempotent (invariant 4) rather than a second record of one event;
change a source, the policy, the taxonomy or the rule bundle and the id moves.
A timestamped id would make every re-run look like new information.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .contracts import Policy, ProofTier, Record, TaxonomyRegistry
from .engine.tiers import MatchProfile
from .intake.proofs import IntakeProof
from .ledger.accounts import ChartOfAccounts

#: Where decision logs are written. Local scratch, not an archive: retention is
#: not built and STATUS.md says so rather than letting a gitignored directory
#: imply custody it does not have.
RUNS = Path(os.environ.get("RECON_RUNS_ROOT", "data/runs"))


class LoopError(ValueError):
    """A loop that does not exist, or a source set that cannot be closed.

    A configuration error, never an execution — the rule adapter specs and
    strategy names live under (ADR-001). A surface handing us an unknown loop
    name must not be able to reach code nobody wrote down.
    """


@dataclass(frozen=True)
class SourceBinding:
    """Which adapter reads which file into which side of the match.

    Data, not code. A surface can list what a loop *expects* before any file
    exists, which is how "your October bank statement has not arrived" is a
    thing the product can say rather than a stack trace.
    """

    spec_id: str
    """An adapter spec in `data/adapters/`. Declarative — see ADR-001."""

    filename: str
    side: str
    role: str
    """"anchor" — iterated one row at a time — or "group"."""

    external_key: str
    """Which normalized key names this row for a human. `""` means the source's
    own row id."""


@dataclass(frozen=True)
class LoadedSources:
    """Everything the sources produced, with nothing filtered out.

    `anchor_rows` and `group_rows` hold *every* row the adapters read. Rows this
    loop does not reconcile are in `scope` with a reason and still travel to the
    completeness audit — filtering before invariant 8 can see it is a silent
    drop with extra steps, which is how the planted `E08` once left a close with
    no disposition while the audit still read `complete`.
    """

    anchor_rows: list[tuple[str, Record]]
    group_rows: list[tuple[str, Record]]
    provenance: ProofTier
    """The weakest intake strength across the sources. A close is no better
    evidenced than the worst thing it read."""

    scope: dict[str, str]
    """record id -> why this loop does not reconcile it. Never a bare drop."""

    proofs: list[IntakeProof] = field(default_factory=list)
    digests: dict[str, str] = field(default_factory=dict)
    strengths: dict[str, str] = field(default_factory=dict)

    @property
    def anchors(self) -> list[tuple[str, Record]]:
        """The anchors the tiers are offered — everything not declared out of
        scope. `anchor_rows` stays whole so the audit still sees the rest."""
        return [(ext, rec) for ext, rec in self.anchor_rows if rec.record_id not in self.scope]

    def in_scope(self) -> tuple[list[tuple[str, Record]], list[tuple[str, Record]], ProofTier]:
        """Anchors, group rows, weakest provenance — what a caller that only
        wants to match needs."""
        return self.anchors, self.group_rows, self.provenance

    @property
    def ok(self) -> bool:
        """No source failed. Not the same as verified: a `declared` intake is
        usable and its records carry the lower proof tier."""
        return not any(p.failed for p in self.proofs)


@dataclass(frozen=True)
class Loop:
    """One reconciliation loop, as configuration.

    Everything domain-specific is here or in the profile; `engine/` reads none
    of it (invariant 7). A second loop is a second entry in `REGISTRY`, not an
    engine edit.
    """

    name: str
    profile: MatchProfile
    period: tuple[date, date]
    opened_on: date
    sources: tuple[SourceBinding, ...]
    policy_file: Path
    taxonomy_file: Path
    load: Callable[[Path], LoadedSources]
    """Read a source set into records. Loop-specific because *which* adapter
    reads *which* file is domain knowledge."""

    policy: Callable[[], Policy]
    taxonomy: Callable[[], TaxonomyRegistry]
    chart: Callable[[], ChartOfAccounts]
    description: str = ""

    @property
    def filenames(self) -> tuple[str, ...]:
        return tuple(b.filename for b in self.sources)

    def bundles(self) -> list[Path]:
        """The directories whose signatures a close checks before trusting what
        it loaded from them. The rule store is included even when empty — an
        unsigned empty store is a state worth recording, not an absence."""
        from .engine import rulestore

        return [self.policy_file.parent, self.taxonomy_file.parent, rulestore.STORE]

    def missing(self, root: Path) -> list[str]:
        """Which of this loop's sources are not on disk. Named rather than
        counted: "settlement.csv has not arrived" is actionable and "1 source
        missing" is not."""
        return [b.filename for b in self.sources if not (root / b.filename).exists()]


#: The loops this build can close. A name that is not here is a configuration
#: error before anything runs — never a lookup that falls through to a default.
REGISTRY: dict[str, Loop] = {}


def register(loop: Loop) -> Loop:
    if loop.name in REGISTRY:
        raise LoopError(f"loop {loop.name!r} is already registered")
    REGISTRY[loop.name] = loop
    return loop


def names() -> list[str]:
    return sorted(REGISTRY)


def get(name: str) -> Loop:
    """Resolve a loop name. Raises rather than defaulting — a surface that could
    be handed an unknown loop and quietly close the wrong one is worse than one
    that refuses."""
    _install()
    if name not in REGISTRY:
        raise LoopError(f"no loop named {name!r}; known: {names()}")
    return REGISTRY[name]


def all_loops() -> list[Loop]:
    _install()
    return [REGISTRY[n] for n in names()]


def _install() -> None:
    """Import the shipped profiles once, on first use.

    At import time instead would make `recon.loop` unimportable whenever a
    profile is malformed, which is the failure that most needs a legible error.
    """
    if not REGISTRY:
        from .profiles import settlement  # noqa: F401


def source_sets(loop: Loop, root: Path) -> list[str]:
    """Directories under `root` that hold every file this loop reads.

    A surface lists these so a controller picks a period rather than typing a
    path. A directory holding *some* of the files is deliberately absent from
    this list and legible through `Loop.missing` — a close over a half-arrived
    month is the failure this exists to prevent.
    """
    if not root.exists():
        return []
    return sorted(d.name for d in root.iterdir() if d.is_dir() and not loop.missing(d))


def run_id_for(loop: Loop, sources: LoadedSources, *, label: str, rules: Sequence = ()) -> str:
    """An id derived from what this close reads and what governs it.

    Content-derived for the same reason `ReconException.fingerprint` is: an id
    that is a position in a sequence names a different thing every time, and an
    id that is a timestamp makes a re-run of identical inputs look like new
    information. Everything that can change the answer is in the digest —
    source bytes, policy, taxonomy, rule bundle — so two runs sharing an id
    decided the same thing, and a changed input gets its own record instead of
    overwriting the old one.
    """
    from .engine import rulestore

    body = "|".join(
        [
            loop.name,
            label,
            *(f"{s}={h}" for s, h in sorted(sources.digests.items())),
            file_digest(loop.policy_file),
            file_digest(loop.taxonomy_file),
            rulestore.bundle_digest(list(rules)),
        ]
    )
    return f"{label}-{hashlib.sha256(body.encode()).hexdigest()[:8]}"


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def run(loop: Loop, root: Path, *, runs_dir: Path | None = None, label: str | None = None):
    """Close one source set. The product's one path, with the files on it.

    Deliberately parameterless where authority is concerned. Policy, the
    taxonomy and the promoted rules are read from the loop's own files and their
    bundles are verified inside `run_close`; there is no argument through which
    a caller could widen a tolerance, re-route a posting or add a rule. That is
    what makes an MCP tool over this safe to hand a model: the tool schema
    cannot express the thing that would need refusing.
    """
    from .close import CloseRequest, run_close
    from .engine import rulestore

    label = label or root.name
    missing = loop.missing(root)
    if missing:
        raise LoopError(
            f"{root} is not a complete source set for {loop.name}: {missing} "
            f"absent. A close over a half-arrived period would report a clean "
            f"month over rows that never came."
        )

    sources = loop.load(root)
    rules = rulestore.load(loop.profile.name)
    run_id = run_id_for(loop, sources, label=label, rules=rules)

    return run_close(
        CloseRequest(
            run_id=run_id,
            anchors=sources.anchor_rows,
            groups=sources.group_rows,
            profile=loop.profile,
            policy=loop.policy(),
            taxonomy=loop.taxonomy(),
            chart=loop.chart(),
            period=loop.period,
            opened_on=loop.opened_on,
            journal_path=(runs_dir or RUNS) / run_id / "decisions.jsonl",
            source_proofs=sources.proofs,
            provenance=sources.provenance,
            out_of_scope=sources.scope,
            rules=rules,
            bundles=loop.bundles(),
            policy_digest=file_digest(loop.policy_file),
            taxonomy_digest=file_digest(loop.taxonomy_file),
        )
    )
