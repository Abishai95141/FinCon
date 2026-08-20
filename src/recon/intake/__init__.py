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

from ..contracts import AdapterSpec, Record
from .proofs import IntakeProof, prove
from .readers import SourceDocument, read
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
    document = read(path, spec.reader, spec.source)
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
