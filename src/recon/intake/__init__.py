"""Intake — read a source, interpret a spec, prove what came out.

    result = ingest(spec, Path("data/batches/A/bank_icici.csv"))
    result.proof.strength   # "verified" | "declared" | "failed"

Specs are loaded from JSON on disk (`data/adapters/`). They are data, not code —
see ADR-001 — so loading one is `AdapterSpec.model_validate_json`, and a spec
that names a verb outside the closed enum fails validation before anything runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ..contracts import AdapterSpec, ParseVerb, Record
from .proofs import Check, CheckStatus, IntakeProof, prove
from .readers import ReaderError, SourceDocument, read
from .spec import Interpreted, Rejection, interpret

ADAPTER_DIR = Path("data/adapters")


@dataclass(frozen=True)
class IngestResult:
    spec: AdapterSpec
    document: SourceDocument
    records: list[Record]
    rejections: list[Rejection]
    proof: IntakeProof

    @property
    def ok(self) -> bool:
        """No check failed. Not the same as verified — a 'declared' intake is ok
        but weakly evidenced, and its records carry the lower proof tier."""
        return not self.proof.failed


def _unreadable(spec: AdapterSpec, path: Path, exc: Exception) -> IngestResult:
    """A source that cannot be opened is a failed source, not a failed run."""
    empty = SourceDocument(source=spec.source, doc_hash="", rows=[], rows_in_file=0)
    proof = IntakeProof(
        source=spec.source,
        spec_ref=spec.ref,
        doc_hash="",
        rows_in_file=0,
        rows_parsed=0,
        rows_rejected=0,
        checks=[
            Check(
                "readable",
                CheckStatus.FAIL,
                f"{path.name} could not be read: {exc}",
            )
        ],
    )
    return IngestResult(spec=spec, document=empty, records=[], rejections=[], proof=proof)


def _incomplete_spec(spec: AdapterSpec, columns: list[str]) -> IngestResult:
    """A spec that admits it cannot express a column is not ready to run."""
    empty = SourceDocument(source=spec.source, doc_hash="", rows=[], rows_in_file=0)
    proof = IntakeProof(
        source=spec.source,
        spec_ref=spec.ref,
        doc_hash="",
        rows_in_file=0,
        rows_parsed=0,
        rows_rejected=0,
        checks=[
            Check(
                "spec_complete",
                CheckStatus.FAIL,
                f"spec declares {len(columns)} column(s) UNMAPPABLE — no verb in "
                f"this vocabulary expresses them: {sorted(columns)}. Escalate for a "
                f"verb or a mapping rather than running a partial ingest.",
            )
        ],
    )
    return IngestResult(spec=spec, document=empty, records=[], rejections=[], proof=proof)


def load_spec(spec_id: str, directory: Path = ADAPTER_DIR) -> AdapterSpec:
    path = directory / f"{spec_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"no adapter spec at {path}")
    return AdapterSpec.model_validate_json(path.read_text(encoding="utf-8"))


def ingest(
    spec: AdapterSpec,
    path: Path,
    window: tuple[date, date] | None = None,
) -> IngestResult:
    """Read, interpret, prove. Never raises on a bad document — a failure is
    reported in the proof so a scorecard can show it, rather than crashing the
    close and losing the diagnosis."""
    unmappable = [
        f.source or f.as_key or "?" for f in spec.fields if f.parse is ParseVerb.UNMAPPABLE
    ]
    if unmappable:
        # Declaring a column UNMAPPABLE is a statement about the SPEC, not about
        # individual rows. Letting the run proceed on the fields that do parse
        # would report a partial ingest as merely "declared" — which is how a
        # whole class of rows goes missing quietly. Escalate instead.
        return _incomplete_spec(spec, unmappable)

    try:
        document = read(path, spec.reader, spec.source)
    except ReaderError as exc:
        # The docstring above promised this. Before P6 the reader raised straight
        # through, so one unopenable file in a batch killed the whole close and
        # left no proof object to show anyone.
        return _unreadable(spec, path, exc)
    out: Interpreted = interpret(spec, document)
    return IngestResult(
        spec=spec,
        document=document,
        records=out.records,
        rejections=out.rejections,
        proof=prove(spec, document, out, window),
    )


__all__ = [
    "ADAPTER_DIR",
    "IngestResult",
    "IntakeProof",
    "Rejection",
    "ingest",
    "load_spec",
]
