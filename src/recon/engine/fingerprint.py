"""Content-derived identity for a break, so the same one is recognisable twice.

`exception_id` is `EXC-00001` — a position in a list. It names a different
finding in every batch, so nothing links an unresolved break across two closes:
no first-seen, no occurrence count, and a worklist "age" that is the age of the
transaction rather than of the problem. That is precisely the defect P12 fixed
for records, one layer up and left in place.

The shape is Formance's: their reconciliation service dedups alerts on
`(rule_id, fingerprint, period_id)` and carries `first_seen_at` and
`occurrence_count`, so a break that persists is one case that keeps recurring
rather than N unrelated findings. Same reasoning, same fix.

Built from the natural keys of the records involved, not from their record ids:
a record id already carries the source and an occurrence number, and a break
should stay the same break when a source is re-exported with different row
numbering.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

from ..contracts import ReconException, Record


def of(exception: ReconException, records: Mapping[str, Record]) -> str:
    """What this break *is*, independent of when it was found.

    Deliberately excludes the amount. A partial payment that grows between two
    closes is the same unresolved break with a bigger number, and a fingerprint
    that moved with the amount would report it as a new case every period —
    which is how a recurring problem hides as a stream of one-offs.
    """
    keys = sorted(records[rid].natural_key or rid for rid in exception.record_ids if rid in records)
    body = "|".join([exception.code, *keys])
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def stamp(
    exceptions: Sequence[ReconException], records: Mapping[str, Record]
) -> list[ReconException]:
    """Give every exception its fingerprint. One place, so the three engine
    sites that construct exceptions cannot drift on how identity is computed."""
    return [e.model_copy(update={"fingerprint": of(e, records)}) for e in exceptions]
