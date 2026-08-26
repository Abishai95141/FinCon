"""`recon-api` — start the HTTP surface and the screens.

A one-line entry point on purpose. Everything it could plausibly configure is
either a deployment concern (host, port, reload) or authority, and authority is
not configurable from a command line: policy, the taxonomy and the promoted
rules come from the loop's signed bundles, so there is no flag here that could
widen a tolerance or add a rule.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

#: Read before the app imports, so a laptop can hold a model key without it
#: reaching a commit. Deliberately not a package dependency and deliberately not
#: clever: `KEY=value` lines, `#` comments, first definition wins so a real
#: environment variable always beats the file.
DEV_ENV = Path("data/dev/.env")


def load_dev_env(path: Path | None = None) -> list[str]:
    """Load `data/dev/.env` into the environment. Returns the names it set.

    Names, never values — a loader that logged what it loaded would put the
    secret in the terminal, which is the thing the file exists to avoid.
    """
    target = path or DEV_ENV
    if not target.exists():
        return []
    loaded = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name, value = name.strip(), value.strip().strip("\"'")
        if name and name not in os.environ:
            os.environ[name] = value
            loaded.append(name)
    return loaded


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    ap = argparse.ArgumentParser(prog="recon-api")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true")
    args = ap.parse_args(argv)

    loaded = load_dev_env()
    if loaded:
        print(f"loaded {len(loaded)} setting(s) from {DEV_ENV}: {', '.join(sorted(loaded))}")

    print(f"FinCon — screens at http://{args.host}:{args.port}/ui")
    print(f"        API docs at http://{args.host}:{args.port}/docs")
    uvicorn.run("recon.api:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
