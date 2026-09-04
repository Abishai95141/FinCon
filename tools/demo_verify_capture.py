"""Shot 9 — run the real verification, keep exactly what came back.

    make demo-verify

Hits the **deployed** endpoint twice with a real proof: once honest, once with a
single leg subtotal bent by a rupee. Writes `demo/verify-session.json` — the
commands as typed and the responses as received — which `motion/src/Verify.tsx`
renders as a terminal.

**Why this exists rather than a screen recording.** The first plan had a human
record a terminal with a screen recorder, and that is why shot 9 was still
missing after everything else was cut: it was the one shot the pipeline could
not re-make, so it never got made. Now it re-shoots with the other three
Remotion comps.

**What makes it honest.** Nothing here is typed by hand. The commands are the
ones executed and the JSON is the bytes the server returned — a transcript, not
a mock-up. If the endpoint went down or the proof stopped verifying, this fails
rather than rendering a green `"proven": true` nobody earned. That matters more
here than anywhere else in the film: shot 9 *is* the claim that a stranger can
check our arithmetic, and faking it would be the one lie the product cannot
survive.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

OUT = Path("demo/verify-session.json")
PROOF = Path("docs/sample-proof.json")
BASE = "https://fincon.astutecomputer.com"

#: Shown on screen instead of the full command, which is 180 characters and
#: unreadable at 1080p. The URL is the load-bearing part — it is somebody else's
#: hostname, which is the entire point of the shot.
TYPED_HONEST = "curl -s -X POST {base}/v1/verify -d @proof.json | jq"
TYPED_BENT = "curl -s -X POST {base}/v1/verify -d @bent.json | jq"

#: The fields the shot shows. The full response is a dozen keys and the three
#: that carry the argument are these: did it re-derive, to what, and under whose
#: policy.
KEEP_OK = ("proven", "recomputed_residual", "policy_ref", "policy_source")
KEEP_BENT = ("proven", "reasons")


def post(base: str, payload: dict) -> dict:
    """One real request. `curl` rather than a client library, because the shot
    shows a curl command and the two should not be different things."""
    done = subprocess.run(
        [
            "curl",
            "-s",
            "-X",
            "POST",
            f"{base}/v1/verify",
            "-H",
            "content-type: application/json",
            "--max-time",
            "30",
            "-d",
            "@-",
        ],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
    )
    if not done.stdout.strip():
        raise RuntimeError(f"{base}/v1/verify returned nothing")
    return json.loads(done.stdout)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--proof", default=str(PROOF))
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)

    proof_file = Path(args.proof)
    if not proof_file.exists():
        print(f"{proof_file} is absent", file=sys.stderr)
        return 2
    payload = json.loads(proof_file.read_text(encoding="utf-8"))

    honest = post(args.base, payload)
    if not honest.get("proven"):
        print(
            f"the shipped proof does not verify against {args.base}: "
            f"{honest.get('reasons')}. Shot 9 asserts that it does, so this is a "
            f"finding rather than a rendering problem.",
            file=sys.stderr,
        )
        return 3

    # Bend one leg subtotal by a rupee. Small enough that the document still
    # looks well-formed, large enough that the sum stops closing — the refusal
    # has to be the arithmetic failing, not a parser rejecting a malformed file.
    bent = json.loads(json.dumps(payload))
    leg = bent["proof"]["legs"][0]
    before = leg["subtotal"]
    leg["subtotal"] = f"{float(before) + 1:.2f}"

    refused = post(args.base, bent)
    if refused.get("proven"):
        print(
            "a proof with a bent subtotal still verified. That is the control "
            "this shot exists to demonstrate, and it did not fire.",
            file=sys.stderr,
        )
        return 3

    session = {
        "base": args.base,
        "leg": leg.get("side", "?"),
        "bent_from": before,
        "bent_to": leg["subtotal"],
        "steps": [
            {
                "typed": TYPED_HONEST.format(base=args.base),
                "response": {k: honest[k] for k in KEEP_OK if k in honest},
            },
            {
                "typed": TYPED_BENT.format(base=args.base),
                "response": {k: refused[k] for k in KEEP_BENT if k in refused},
            },
        ],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(session, indent=2), encoding="utf-8")

    print(
        f"  proven     residual {honest.get('recomputed_residual')}  "
        f"policy {honest.get('policy_source')}"
    )
    print(f"  refused    {refused['reasons'][0][:88]}")
    print(f"  -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
