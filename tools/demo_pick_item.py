"""Which item does the model actually help on? Ask, before the camera rolls.

    make demo-pick

The film's AI moment is the shot the whole product argument turns on, and the
first cut landed on an item where the model returned `E14` — it agreed with the
engine that it could not say why. Honest, and useless as a demonstration: the
one shot about what the AI *does* showed it doing nothing.

The recorder was picking the first `E14` on the worklist. That is the right
*class* of item — the model is only offered exceptions the arithmetic could not
name — but not the right instance, and which instance helps is not something a
selector can know.

So this asks. It runs the real classifier over every offered item and writes the
one whose proposed code differs from the engine's to `demo/ai-item.json`.

**This is choosing a demonstration, not manufacturing one.** The call on camera
is a fresh call whose answer is whatever the model says at the time — nothing
here is replayed into the film. What it prevents is spending the film's most
important thirty seconds on an item that happens to produce nothing.

It also prints what the model said about *every* offered item, including the
ones it could not name, because that ratio is what the narration has to be
honest about — on batch A it varies run to run, and the narration must not
quote a ratio that will not hold.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

OUT = Path("demo/ai-item.json")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", default="A")
    ap.add_argument("--runs", default="data/runs")
    ap.add_argument("--batches", default="data/batches")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)

    os.environ.setdefault("RECON_ENV", "dev")

    from recon import loop as looplib
    from recon import service
    from recon.triage import classify as classify_mod
    from recon.triage.client import ModelEdge

    runs = Path(args.runs)
    view = service.view(args.run, runs)
    lp = looplib.get(view.loop)
    sources = lp.load(Path(args.batches) / args.run)
    records = {r.record_id: r for _, r in [*sources.anchor_rows, *sources.group_rows]}

    try:
        edge = ModelEdge()
    except Exception as exc:
        print(f"no model configured: {exc}", file=sys.stderr)
        return 2

    offered = [e.exception for e in view.exceptions if classify_mod.reclassifiable(e.exception)]
    if not offered:
        print(
            "every item carries a code the engine derived, so the model is offered "
            "none of them and shot 6 has nothing to show.",
            file=sys.stderr,
        )
        return 3

    print(f"  model {edge.model} · {len(offered)} of {len(view.exceptions)} items offered\n")
    moved: list[dict] = []
    for exc in offered:
        result = classify_mod.classify(
            exceptions=[exc], taxonomy=lp.taxonomy(), records=records, edge=edge
        )[0]
        said = "; ".join(result.refusals) if result.refusals else (result.hypothesis or "")
        changed = result.code != exc.code
        print(f"  {exc.exception_id}  {exc.code} -> {result.code}  {'NAMED' if changed else '—'}")
        print(f"     {said[:150]}")
        if changed:
            moved.append(
                {
                    "exception_id": exc.exception_id,
                    "from_code": exc.code,
                    "to_code": result.code,
                    "amount": str(exc.amount),
                    "said": said,
                }
            )

    print(f"\n  {len(moved)} of {len(offered)} named. That ratio belongs in the narration.")
    if not moved:
        print(
            "\nthe model named none of them, so there is no honest AI demonstration "
            "in this close. That is a finding about the corpus or the prompt, not a "
            "reason to film the shot anyway.",
            file=sys.stderr,
        )
        return 4

    # The largest one it named: the film should stand on real money, and a
    # viewer discounts a demonstration on rounding.
    pick = max(moved, key=lambda m: float(m["amount"]))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"offered": len(offered), "named": len(moved), "pick": pick}, indent=2),
        encoding="utf-8",
    )
    print(f"\n  filming {pick['exception_id']}: {pick['from_code']} -> {pick['to_code']}  -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
