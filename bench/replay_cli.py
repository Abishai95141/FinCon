"""Replay a close from its decision log and compare with the run.

    python -m bench.replay_cli A

Reads the log, rebuilds the scorecard from the events, and prints both it and
whatever disagrees. Deliberately a separate entry point from `bench.run`: an
auditor re-deriving our numbers should not have to run the thing that produced
them.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from recon.journal import verify_chain
from recon.journal.replay import disagreements

from .replay import replay_close, scorecard_from_log
from .run import BATCHES, RUNS


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bench.replay_cli")
    ap.add_argument("batch", default="A", nargs="?")
    ap.add_argument("--log", type=Path, default=None)
    args = ap.parse_args(argv)

    path = args.log or RUNS / args.batch / "decisions.jsonl"
    if not path.exists():
        print(f"no decision log at {path} — run `make eval` first")
        return 2

    replayed = replay_close(path, verify=False)
    problems = verify_chain(
        replayed and __import__("recon.journal", fromlist=["read"]).read(path, verify=False)
    )
    card = scorecard_from_log(path, BATCHES / args.batch / "labels.json", verify=False)

    print(f"replayed {path}")
    print(f"  batch {replayed.batch} · profile {replayed.profile} · policy {replayed.policy_ref}")
    print(
        f"  policy digest {replayed.policy_digest[:16]}  ({len(replayed.source_digests)} sources)"
    )
    print(f"  {card.headline()}")
    print(
        f"  exceptions: coverage {card.exceptions.coverage} · "
        f"classification {card.exceptions.classification} · "
        f"ambiguity {card.exceptions.ambiguity}"
    )
    print(f"  postings {len(replayed.postings)} · out of scope {len(replayed.out_of_scope)}")
    for source, gap in sorted(replayed.unverified.items()):
        print(f"  UNVERIFIED {source}: {gap[:90]}")

    problems += disagreements(replayed)
    for line in problems:
        print(f"  PROBLEM {line}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
