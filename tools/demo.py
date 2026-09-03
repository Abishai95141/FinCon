"""Record the demo film's product footage — scripted, so it cannot fumble.

    make demo

A human driving a browser for four continuous minutes always produces a hunt
for a button or a scroll that overshoots, and ten takes later you are still
cutting around a stumble. So every click, scroll and dwell in shots 3-8 and 10
is written down here, a synthetic cursor is drawn into the page and tweened
between targets, and the whole film re-shoots in one command when the UI moves.

**It prints a cut list.** Each beat's wall-clock offset into the recording is
logged as it happens and written to `demo/cuts.json`, so the edit points are
generated rather than eyeballed. A beat that ran long is a number to change in
`BEATS`, not a re-shoot.

**What it refuses to ship.** The local server renders a development-credential
banner, true of this machine and false of the deployed product. It is removed
on every navigation and asserted gone — `tools/shots.py` shipped fourteen frames
with that banner because its selector was wrong and nothing checked.

Not used, deliberately: `?tour=`. The guided tour is the right thing for a
first-time user and would fight a voiceover for the same attention.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

OUT = Path("demo")
WIDTH, HEIGHT = 1600, 1000

#: Seconds each beat holds. This is the pacing dial: when the voiceover for a
#: shot comes in long, change the number and re-render. Nothing else moves.
#:
#: Sums to 142s of footage against 138s of scripted narration for shots 3-8 and
#: 10, which leaves a little air at each seam rather than a hard butt-cut.
BEATS: dict[str, float] = {
    "login": 4.0,
    "sources": 7.0,
    "load-sample": 4.0,
    "periods": 6.0,
    "close": 12.0,
    "scorecard": 14.0,
    "proof": 12.0,
    "worklist": 13.0,
    "ask-model": 15.0,
    "ledger-unmoved": 5.0,
    "dispose": 16.0,
    "signoff": 10.0,
    "pack": 14.0,
    "agent": 10.0,
}

#: Constant speed, not eased. Eased movement reads as an animation; constant
#: reads as a hand. The 400ms pause before a click is what stops scripted
#: footage looking robotic — an instant click on arrival is the tell.
CURSOR_SPEED = 1400.0
CLICK_PAUSE = 0.40

CURSOR_JS = """
(() => {
  if (document.getElementById('__demo_cursor')) return;
  const c = document.createElement('div');
  c.id = '__demo_cursor';
  c.style.cssText = [
    'position:fixed', 'left:0', 'top:0', 'width:20px', 'height:20px',
    'margin:-10px 0 0 -10px', 'border-radius:50%',
    'background:rgba(47,123,255,.92)',
    'box-shadow:0 0 0 6px rgba(47,123,255,.22), 0 2px 10px rgba(11,30,69,.35)',
    'pointer-events:none', 'z-index:2147483647',
    'transition:transform 120ms ease-out',
  ].join(';');
  document.body.appendChild(c);
  window.__demoMove = (x, y) => { c.style.transform = `translate(${x}px,${y}px)`; };
  window.__demoPress = (down) => {
    c.style.width = c.style.height = down ? '14px' : '20px';
    c.style.margin = down ? '-7px 0 0 -7px' : '-10px 0 0 -10px';
  };
  window.__demoMove(-50, -50);
})()
"""

#: The banner describes this machine's auth backend, not the product.
STRIP_BANNER = (
    "(() => { const g=[...document.querySelectorAll('.devbanner')]; "
    "g.forEach(e=>e.remove()); return g.length; })()"
)
BANNER_STILL_THERE = "(() => document.body.innerText.includes('Development credential store'))()"

SMOOTH_SCROLL = """
([targetY, ms]) => new Promise(done => {
  const start = window.scrollY, delta = targetY - start, t0 = performance.now();
  function step(now) {
    const p = Math.min(1, (now - t0) / ms);
    // ease-out cubic: fast away, settles rather than stops dead
    window.scrollTo(0, start + delta * (1 - Math.pow(1 - p, 3)));
    p < 1 ? requestAnimationFrame(step) : done(null);
  }
  requestAnimationFrame(step);
})
"""


class Stage:
    """The camera operator. Holds the page, the cursor and the cut list."""

    def __init__(self, page, base: str, scale: float):
        self.page = page
        self.base = base
        self.scale = scale
        self.t0 = time.monotonic()
        self.cuts: list[dict] = []
        self.x, self.y = -50.0, -50.0

    # -- timing -----------------------------------------------------------
    def mark(self, beat: str) -> None:
        """Record where this beat begins, in seconds into the capture."""
        at = time.monotonic() - self.t0
        self.cuts.append({"beat": beat, "at": round(at, 3), "hold": BEATS.get(beat, 0.0)})
        print(f"  {at:7.2f}s  {beat}", flush=True)

    def hold(self, beat: str) -> None:
        self.page.wait_for_timeout(BEATS[beat] * 1000 * self.scale)

    # -- movement ---------------------------------------------------------
    def cursor(self) -> None:
        self.page.evaluate(CURSOR_JS)
        self.page.evaluate("([x,y]) => window.__demoMove(x,y)", [self.x, self.y])

    def glide(self, selector: str) -> tuple[float, float]:
        """Move the dot to an element's centre at constant speed."""
        el = self.page.wait_for_selector(selector, state="visible", timeout=15000)
        el.scroll_into_view_if_needed()
        box = el.bounding_box()
        if box is None:
            raise RuntimeError(f"{selector} has no box — it is not on screen")
        tx, ty = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        dist = ((tx - self.x) ** 2 + (ty - self.y) ** 2) ** 0.5
        steps = max(2, int(dist / CURSOR_SPEED * 60))
        for i in range(1, steps + 1):
            p = i / steps
            self.page.evaluate(
                "([x,y]) => window.__demoMove(x,y)",
                [self.x + (tx - self.x) * p, self.y + (ty - self.y) * p],
            )
            self.page.wait_for_timeout(16)
        self.x, self.y = tx, ty
        return tx, ty

    def click(self, selector: str) -> None:
        self.glide(selector)
        self.page.wait_for_timeout(CLICK_PAUSE * 1000)
        self.page.evaluate("() => window.__demoPress(true)")
        self.page.wait_for_timeout(90)
        self.page.click(selector)
        self.page.evaluate("() => window.__demoPress && window.__demoPress(false)")

    def rest(self, selector: str, seconds: float) -> None:
        """Park the cursor on something while the narration talks about it."""
        self.glide(selector)
        self.page.wait_for_timeout(seconds * 1000 * self.scale)

    def scroll_to(self, selector: str, ms: int = 900) -> None:
        box = self.page.wait_for_selector(selector, state="attached").bounding_box()
        target = (box["y"] + window_offset(self.page)) - 140 if box else 0
        self.page.evaluate(SMOOTH_SCROLL, [max(0, target), ms])
        self.page.wait_for_timeout(ms + 120)

    def scroll_by(self, pixels: int, ms: int) -> None:
        y = self.page.evaluate("() => window.scrollY")
        self.page.evaluate(SMOOTH_SCROLL, [y + pixels, ms])
        self.page.wait_for_timeout(ms + 120)

    # -- navigation -------------------------------------------------------
    def go(self, path: str) -> None:
        self.page.goto(f"{self.base}{path}", wait_until="networkidle")
        self.clean()

    def clean(self) -> None:
        self.page.evaluate(STRIP_BANNER)
        if self.page.evaluate(BANNER_STILL_THERE):
            raise RuntimeError("the development banner is still on the page")
        self.cursor()


def window_offset(page) -> float:
    return page.evaluate("() => window.scrollY")


# --------------------------------------------------------------------------
# the film
# --------------------------------------------------------------------------


def film(st: Stage, email: str, password: str) -> None:
    page = st.page

    # ---- shot 3: sign in, and what this is ------------------------------
    st.mark("login")
    st.go("/login")
    st.click("#email")
    page.type("#email", email, delay=55)
    st.click("#password")
    page.type("#password", password, delay=45)
    st.click("form[action='/login'] button[type=submit], button[type=submit]")
    page.wait_for_load_state("networkidle")
    st.clean()

    st.mark("sources")
    st.rest("#sources-what", BEATS["sources"])

    st.mark("load-sample")
    st.click("form[action='/sources/sample'] button[type=submit]")
    page.wait_for_load_state("networkidle")
    st.clean()
    st.hold("load-sample")

    # ---- shot 4: close a period -----------------------------------------
    st.mark("periods")
    st.go("/periods")
    st.rest("#periods-list", BEATS["periods"])

    st.mark("close")
    st.click("form[action='/periods/close'] button[type=submit]")

    # The processing page refreshes itself once a second and, when the job is
    # done, *stays where it is* — it drops the refresh and grows an "Open the
    # close" link. Waiting for the URL to change (the first version of this)
    # therefore waited for something that never happens, and burned 47 seconds
    # of footage on a close that takes 120 milliseconds.
    page.wait_for_selector("text=Open the close", timeout=60000)
    st.clean()

    # The receipt is the beat: six stages landed, and the page says in its own
    # words that no model was involved. Hold there rather than on the heading.
    st.rest("text=No model was involved", BEATS["close"])
    st.click("text=Open the close")
    page.wait_for_load_state("networkidle")
    st.clean()

    run_id = page.url.rstrip("/").rsplit("/", 1)[-1]

    # ---- shot 5: the scorecard, and a proof ------------------------------
    st.mark("scorecard")
    st.scroll_to("h1", 600)
    st.hold("scorecard")

    st.mark("proof")
    opened = False
    for sel in ("details summary", ".proofcard", "a[href*='/log']"):
        if page.query_selector(sel):
            st.click(sel)
            opened = True
            break
    if not opened:
        st.scroll_by(600, 900)
    page.wait_for_timeout(400)
    st.clean()
    st.hold("proof")

    # ---- shot 6: the tail, and the model ---------------------------------
    st.mark("worklist")
    st.go("/worklist")
    st.rest("#worklist-table", BEATS["worklist"])

    # Deliberately an E14, not simply the top row.
    #
    # The worklist ranks by cash impact x age, and the heaviest item here is an
    # `E06` the engine *derived* — so the model is correctly not offered on it
    # and the first take recorded a shot with nothing to show. E14 is where the
    # arithmetic ran out, which is the only place a model belongs, so the film
    # should be standing on one when it says so.
    e14 = "#worklist-table tr:has-text('E14') a[href*='/items/']"
    if page.query_selector(e14) is None:
        raise RuntimeError(
            "no E14 on the worklist — shot 6 has nothing to demonstrate. Every item "
            "carries a derived code, so the model would be refused on all of them."
        )
    st.click(e14)
    page.wait_for_load_state("networkidle")
    st.clean()

    st.mark("ask-model")
    ask = "form[action*='/classify'] button[type=submit]"
    if page.query_selector(ask) is None:
        raise RuntimeError(
            "this item offers no model call. It is an E14, so that is a product "
            "change rather than a bad pick — look at it before re-recording."
        )
    st.click(ask)
    page.wait_for_load_state("networkidle", timeout=90000)
    st.clean()
    st.hold("ask-model")

    # The beat the whole film turns on: a proposal arrived and the ledger did
    # not move. Park on the journal figure while the narration says so.
    st.mark("ledger-unmoved")
    for sel in (".metric", ".kv", "h1"):
        if page.query_selector(sel):
            st.rest(sel, BEATS["ledger-unmoved"])
            break

    # ---- shot 7: four endings --------------------------------------------
    st.mark("dispose")
    chase = "form:has(input[name=disposition][value=chase])"
    st.scroll_to(chase, 900)
    st.click(f"{chase} input[name=rationale]")
    page.type(
        f"{chase} input[name=rationale]", "gateway confirmed the remittance is late", delay=32
    )
    if page.query_selector(f"{chase} input[name=owner]"):
        st.click(f"{chase} input[name=owner]")
        page.type(f"{chase} input[name=owner]", "credit-control", delay=32)
    st.click(f"{chase} button[type=submit]")
    page.wait_for_load_state("networkidle")
    st.clean()
    st.hold("dispose")

    # ---- shot 8: sign off, and the pack ----------------------------------
    st.mark("signoff")
    st.go(f"/periods/{run_id}")
    if page.query_selector("#note"):
        st.click("#note")
        page.type("#note", "October reconciled", delay=38)
    st.hold("signoff")

    st.mark("pack")
    st.go(f"/periods/{run_id}/pack")
    height = page.evaluate("() => document.body.scrollHeight - window.innerHeight")
    st.page.evaluate(SMOOTH_SCROLL, [max(0, height), 9000])
    page.wait_for_timeout(9200)
    st.hold("pack")

    # ---- shot 10: the assistant -------------------------------------------
    st.mark("agent")
    st.go("/agent")
    st.rest("#agent-what", BEATS["agent"])
    st.mark("end")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://localhost:8142")
    ap.add_argument("--email", default=os.environ.get("FINCON_DEMO_EMAIL", ""))
    ap.add_argument("--password", default=os.environ.get("FINCON_DEMO_PASSWORD", ""))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="multiply every dwell — 0.25 for a fast rehearsal that still proves the path",
    )
    args = ap.parse_args(argv)

    if not args.email or not args.password:
        print(
            "set FINCON_DEMO_EMAIL and FINCON_DEMO_PASSWORD (a local dev account — "
            "`make demo-seed` makes one).",
            file=sys.stderr,
        )
        return 2

    from playwright.sync_api import sync_playwright

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--force-color-profile=srgb", "--font-render-hinting=none"]
        )
        ctx = browser.new_context(
            viewport={"width": WIDTH, "height": HEIGHT},
            device_scale_factor=1,
            record_video_dir=str(out),
            record_video_size={"width": WIDTH, "height": HEIGHT},
            reduced_motion="no-preference",
        )
        page = ctx.new_page()
        st = Stage(page, args.base.rstrip("/"), args.scale)
        try:
            film(st, args.email, args.password)
        finally:
            video = page.video
            ctx.close()
            browser.close()
            if video is not None:
                raw = out / "raw.webm"
                Path(video.path()).replace(raw)
                print(f"\n  video  {raw}  {raw.stat().st_size // 1024} KB")
        (out / "cuts.json").write_text(json.dumps(st.cuts, indent=2), encoding="utf-8")
        print(f"  cuts   {out / 'cuts.json'}  {len(st.cuts)} beats")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
