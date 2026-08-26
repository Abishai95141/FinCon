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

    # Mount MCP into the same process, so a deployment is one container, one
    # port and one certificate. It declines when nothing is configured and the
    # bind address is public — see `recon.mcp.http.build` — and the web app
    # starts either way, because refusing to serve a site over an MCP endpoint
    # nobody has set up yet would be the tail wagging the dog.
    from ..mcp import http as mcphttp
    from .app import app as fastapi_app
    from .app import mount_mcp

    mounted = mount_mcp(fastapi_app)
    state = mcphttp.describe()

    print(f"FinCon — screens at http://{args.host}:{args.port}/ui")
    print(f"        API docs at http://{args.host}:{args.port}/docs")
    if mounted and state["authenticated"]:
        print(f"        MCP       at {state['endpoint']} (Cognito OAuth)")
    elif mounted:
        print(
            f"        MCP       at http://{args.host}:{args.port}{mcphttp.MOUNT} "
            f"— NO AUTHORIZATION, loopback only"
        )
    else:
        print(f"        MCP       not served: {', '.join(state['missing'])} unset")
    # `proxy_headers` is not optional behind an ALB. TLS terminates at the load
    # balancer, so without it uvicorn believes every request is plain HTTP and
    # Starlette builds absolute redirects that say so — the MCP endpoint's own
    # trailing-slash redirect came back as `http://` on an https:// site, which
    # is a downgrade a client either follows or loops on.
    #
    # `forwarded_allow_ips="*"` is safe *only* because nothing but the load
    # balancer can reach this port: the task security group has one ingress rule
    # and it names the ALB's group. Trusting X-Forwarded-* from an address that
    # could be anybody is how a caller sets its own scheme and host.
    uvicorn.run(
        "recon.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FINCON_TRUSTED_PROXIES", "127.0.0.1"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
