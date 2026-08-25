"""`recon-api` — start the HTTP surface and the screens.

A one-line entry point on purpose. Everything it could plausibly configure is
either a deployment concern (host, port, reload) or authority, and authority is
not configurable from a command line: policy, the taxonomy and the promoted
rules come from the loop's signed bundles, so there is no flag here that could
widen a tolerance or add a rule.
"""

from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    ap = argparse.ArgumentParser(prog="recon-api")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true")
    args = ap.parse_args(argv)

    print(f"recon — screens at http://{args.host}:{args.port}/ui")
    print(f"        API docs at http://{args.host}:{args.port}/docs")
    uvicorn.run("recon.api:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
