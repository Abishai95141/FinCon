"""Capture the product screenshots the README and the landing page use.

Run against a **local** server with the dev credential store, because the shots
have to show a real close with a real tail and the hosted instance needs a
password nobody should type into a script:

    make shots

Two things this deliberately does *not* do.

**It does not mock a screen.** Every frame here is the running application
rendering its own state from `data/runs`. A composed screenshot of a page that
does not exist is the marketing version of a test asserting on data it made up,
and this repository's whole argument is that we do not do that.

**It hides exactly one thing**, and says so: the development-credential banner.
That banner is a true statement about *this machine's* auth backend — accounts
in a local JSON file rather than Cognito — and it is false of the deployed
product, which is what the screenshots are of. Hiding it makes the frame more
representative, not less. Nothing else is touched.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

OUT = Path("docs/media")
WIDTH, HEIGHT = 1440, 900

#: The banner is the only element suppressed, and only because it describes the
#: local credential store rather than the product.
HIDE = """
(() => {
  const gone = [...document.querySelectorAll('.devbanner')];
  gone.forEach(el => el.remove());
  return gone.length;
})()
"""

#: Belt and braces: the shot is wrong if the banner is still in it, and a silent
#: miss here puts a local-development notice on the front page of the repo.
ASSERT_CLEAN = """
(() => document.body.innerText.includes('Development credential store'))()
"""


def shots(run_id: str, item_id: str) -> list[tuple[str, str, str | None]]:
    """`(filename, path, selector-to-scroll-to)`.

    A selector rather than a pixel offset: the pages are server-rendered and
    their heights move with the data, so a hardcoded scroll would frame the
    wrong thing the next time the corpus changes.
    """
    return [
        ("periods", "/periods", None),
        ("close", f"/periods/{run_id}", None),
        ("worklist", "/worklist", None),
        ("item", f"/periods/{run_id}/items/{item_id}", None),
        ("pack", f"/periods/{run_id}/pack", None),
        ("verify", "/verify", None),
        ("sources", "/sources", None),
        ("agent", "/agent", None),
        ("settings", "/settings", None),
        ("log", f"/periods/{run_id}/log", None),
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://localhost:8142")
    ap.add_argument("--cookie", default=os.environ.get("FINCON_SHOT_COOKIE", ""))
    ap.add_argument("--run", default="")
    ap.add_argument("--item", default="")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--full", action="store_true", help="also capture full-page frames")
    args = ap.parse_args(argv)

    if not args.cookie:
        print(
            "no session cookie. Mint one against the same RECON_SESSION_SECRET the "
            "server is running with, and pass --cookie or set FINCON_SHOT_COOKIE.",
            file=sys.stderr,
        )
        return 2

    from playwright.sync_api import sync_playwright

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    host = args.base.split("//", 1)[-1].split(":")[0]

    written = []
    full = args.full
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=2
        )
        ctx.add_cookies(
            [{"name": "fincon_session", "value": args.cookie, "domain": host, "path": "/"}]
        )
        page = ctx.new_page()

        run_id, item_id = args.run, args.item
        if not run_id:
            page.goto(f"{args.base}/periods", wait_until="networkidle")
            link = page.query_selector("a[href^='/periods/'][href*='-']")
            if link is None:
                print("no close on this account — run one first", file=sys.stderr)
                return 3
            run_id = link.get_attribute("href").rsplit("/", 1)[-1]
        if not item_id:
            page.goto(f"{args.base}/worklist", wait_until="networkidle")
            link = page.query_selector("a[href*='/items/']")
            if link is None:
                print("no worklist item — the tail is empty", file=sys.stderr)
                return 3
            item_id = link.get_attribute("href").rsplit("/", 1)[-1]

        for name, path, _ in shots(run_id, item_id):
            page.goto(f"{args.base}{path}", wait_until="networkidle")
            page.evaluate(HIDE)
            if page.evaluate(ASSERT_CLEAN):
                # The first version of this matched on `children.length === 0`
                # and the banner holds a `<code>` tag, so every frame shipped
                # with it. Nothing checked, so nothing said.
                print(f"{name}: dev banner still on the page", file=sys.stderr)
                return 4
            target = out / f"{name}.png"
            page.screenshot(path=str(target), full_page=False)
            written.append((name, path, target.stat().st_size))
            # Full-page variants on request only. They are 3-4x the size, the
            # README links none of them, and `make shots FULL=1` regenerates
            # them in one command when the landing page wants them.
            if full and name in {"pack", "close", "agent", "verify"}:
                tall = out / f"{name}-full.png"
                page.screenshot(path=str(tall), full_page=True)
                written.append((f"{name}-full", path, tall.stat().st_size))
        browser.close()

    for name, path, size in written:
        print(f"  {name:16} {path:44} {size // 1024:>5} KB")
    print(f"{len(written)} frames -> {out}/  (run {run_id}, item {item_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
