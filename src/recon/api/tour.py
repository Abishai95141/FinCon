"""The guided tour — one question per screen, in the order a controller meets them.

`docs/13-THE-SCREENS.md` says each screen answers exactly one question, and that
a person who has never seen this should get from the first screen to the last
without asking anybody. That document is the design; this is the same thing said
to the person while they are standing on the screen.

**No JavaScript**, because `gate_p14.py::test_the_ui_needs_no_javascript` asserts
there is none and a tour is not the reason to start. So the step lives in the
URL: `?tour=<n>`. *Next* is a link to the next step's route, *Skip* is a link to
the route with no parameter, and the highlight is a CSS rule keyed on a class the
server puts on `<body>`. A page rendered with a step is a whole page the server
rendered — it survives a reload, it can be bookmarked, and the back button walks
the tour backwards for free.

**Highlights sit on stage content, never on the rail.** `.rail` is
`position: sticky`, which creates a stacking context its children cannot escape,
so a rail item cannot rise above the veil. The rail already says where you are
with `aria-current`; the veil dimming it is the correct reading.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape


@dataclass(frozen=True)
class Step:
    """One stop. `key` is the `data-tour` value on the element to light up."""

    key: str
    route: str
    title: str
    body: str
    place: str = "stage"


#: The journey, in `docs/13-THE-SCREENS.md`'s order. Deliberately confined to
#: routes that exist for an account with nothing in it: an item and a close pack
#: need a `run_id`, and a tour that dead-ends on "no period yet" teaches the
#: product is broken. The last step names them instead.
STEPS: tuple[Step, ...] = (
    Step(
        "sources-what",
        "/sources",
        "What this thing does",
        "A reconciliation takes two independent records of the same money and proves "
        "every match from the raw rows. What it cannot match becomes a ranked list "
        "with a named reason. That list is the work — matching is the part that was "
        "already solved.",
    ),
    Step(
        "sources-sample",
        "/sources",
        "Start with real files",
        "This loads a worked example for both reconciliations — real files whose "
        "answers are already known, so you can run a close end to end before "
        "bringing anything of your own.",
    ),
    Step(
        "sources-periods",
        "/sources",
        "A period is one month of one reconciliation",
        "Each needs its own pair of files. A period missing one stays on the list "
        "and says what it is waiting for, rather than disappearing — a month you "
        "cannot find is the same failure as a month closed over rows that never "
        "arrived.",
    ),
    Step(
        "periods-list",
        "/periods",
        "Close a period",
        "Pressing this reads the period's two files, matches what it can prove, "
        "writes the journal entries, and hands back everything it could not match. "
        "Six stages, a few seconds, and no model runs at any of them — the receipt "
        "says so, because a number you cannot re-derive is a number you cannot "
        "defend.",
    ),
    Step(
        "worklist-table",
        "/worklist",
        "What is on your desk",
        "Every open item across every close, ranked by how much cash is at stake "
        "times how long it has been waiting. Three states, because they need three "
        "different things from you: the arithmetic named it, the files cannot "
        "separate two causes, or nothing could read it at all. Each row opens an "
        "item, and each item ends in a journal entry under your name.",
    ),
    Step(
        "verify-how",
        "/verify",
        "Check it without trusting us",
        "The four steps an auditor takes: fetch the files, confirm each hash, post "
        "one proof to a public endpoint that needs no account, confirm the chain. "
        "Signed in, you get the same thing as a button. Same code path either way — "
        "a re-derivation that took an internal shortcut would be measuring the "
        "shortcut.",
    ),
    Step(
        "agent-what",
        "/agent",
        "Let an assistant help",
        "An assistant can read everything here and run a close, under your name and "
        "your credential. It cannot sign off, promote a rule or widen a tolerance — "
        "not by policy but by construction, and the page checks that against the "
        "tool definitions every time it renders.",
    ),
    Step(
        "settings-authority",
        "/settings",
        "What you are judged by",
        "Nothing on this screen is editable, and that is the point: a system where "
        "the person being judged can edit the judgement has no control at all. The "
        "tolerance, the promoted rules and the exception codes are shown with what "
        "each one is allowed to do.\n\nThat is the tour. What comes next only exists "
        "once you close a period — an item to resolve, a signature, and a close pack "
        "to hand to an auditor.",
    ),
)

TOTAL = len(STEPS)


def at(index: int | None) -> Step | None:
    """The step at `index`, or `None` for anything out of range."""
    if index is None or index < 0 or index >= TOTAL:
        return None
    return STEPS[index]


def parse(raw: str | None) -> int | None:
    """A tour index off the query string. Junk is not a tour, it is no tour."""
    if raw is None:
        return None
    try:
        index = int(raw)
    except ValueError:
        return None
    return index if 0 <= index < TOTAL else None


def body_class(index: int | None, route: str) -> str:
    """The class that arms the CSS, or empty when this page has no step."""
    step = at(index)
    return f"tour-on tour-at-{step.key}" if step and step.route == route else ""


def _dots(index: int) -> str:
    return "".join(f"<i class='tour-dot{' on' if n == index else ''}'></i>" for n in range(TOTAL))


def overlay(index: int, route: str) -> str:
    """The veil and the callout, or nothing when this page carries no step."""
    step = at(index)
    if step is None or step.route != route:
        return ""
    last = index == TOTAL - 1
    nxt = STEPS[index + 1] if not last else None
    forward = (
        f"<a class='btn btn-primary' href='{escape(route)}'>Finish</a>"
        if last
        else (
            f"<a class='btn btn-primary' href='{escape(nxt.route)}?tour={index + 1}"
            f"#{escape(nxt.key)}'>Next</a>"
        )
    )
    back = (
        f"<a class='tour-back' href='{escape(STEPS[index - 1].route)}?tour={index - 1}"
        f"#{escape(STEPS[index - 1].key)}'>Back</a>"
        if index
        else ""
    )
    paragraphs = "".join(
        f"<p class='tour-body'>{escape(chunk)}</p>" for chunk in step.body.split("\n\n")
    )
    return (
        f"<div class='tour-veil'></div>"
        f"<div class='tour-box tour-{escape(step.place)}' role='dialog' aria-modal='false' "
        f"aria-label='Product tour, step {index + 1} of {TOTAL}'>"
        f"<div class='tour-head'><span class='tour-step'>{index + 1} of {TOTAL}</span>"
        f"<a class='tour-skip' href='{escape(route)}'>Skip the tour</a></div>"
        f"<h2 class='tour-title'>{escape(step.title)}</h2>{paragraphs}"
        f"<div class='tour-foot'><span class='tour-dots'>{_dots(index)}</span>"
        f"<span class='tour-acts'>{back}{forward}</span></div></div>"
    )


def start_link(label: str = "Show me around") -> str:
    """The way in. Rendered on the landing screen, which is also step one."""
    return (
        f"<a class='btn btn-secondary tour-start' href='{escape(STEPS[0].route)}?tour=0"
        f"#{escape(STEPS[0].key)}'>"
        f"{escape(label)}</a>"
    )


def css() -> str:
    """One highlight rule per step, generated from `STEPS`.

    Generated rather than hand-written: a step whose key nobody styled would be a
    step that dims the page and lights nothing, and that failure is silent.
    """
    spots = ",".join(f".tour-at-{s.key} [data-tour='{s.key}']" for s in STEPS)
    return f"""
/* `Next` links to `#<key>`, so the browser scrolls the spotlight into view with
   no script. `scroll-margin-top` keeps it off the very top edge. */
html{{scroll-behavior:smooth}}
@media(prefers-reduced-motion:reduce){{html{{scroll-behavior:auto}}}}
.tour-veil{{position:fixed;inset:0;z-index:60;background:rgba(11,30,69,.44);
  animation:tour-veil .3s ease both}}
@keyframes tour-veil{{from{{opacity:0}}to{{opacity:1}}}}
{spots}{{
  position:relative;z-index:61;background:var(--surface);
  border-radius:var(--r16);outline:2px solid var(--primary);outline-offset:4px;
  scroll-margin-top:1.6rem;
  animation:tour-spot .5s cubic-bezier(.2,.8,.2,1) both,tour-ring 2.6s ease-out .5s infinite;
}}
@keyframes tour-spot{{from{{transform:scale(.985)}}to{{transform:none}}}}
@keyframes tour-ring{{
  0%{{box-shadow:0 0 0 0 rgba(47,123,255,.42),var(--e4)}}
  70%{{box-shadow:0 0 0 18px rgba(47,123,255,0),var(--e4)}}
  100%{{box-shadow:0 0 0 0 rgba(47,123,255,0),var(--e4)}}}}
.tour-box{{
  position:fixed;z-index:62;width:min(30rem,calc(100vw - 2.4rem));
  background:var(--surface);border-radius:var(--r16);
  /* A border as well as a shadow: the spotlit element is often an opaque white
     panel, and white-on-white separated by a soft shadow alone reads as one
     surface. The top edge carries the accent so the eye finds the box first. */
  border:1px solid var(--n300);border-top:3px solid var(--primary);
  box-shadow:0 24px 48px -16px rgba(11,30,69,.34),0 6px 14px rgba(11,30,69,.10);
  padding:1.1rem 1.35rem 1.1rem;
  animation:tour-in .38s cubic-bezier(.2,.8,.2,1) both;
}}
.tour-stage{{right:1.5rem;bottom:1.5rem}}
.tour-rail{{left:1.5rem;bottom:1.5rem}}
@keyframes tour-in{{from{{opacity:0;transform:translateY(16px) scale(.97)}}
  to{{opacity:1;transform:none}}}}
.tour-head{{display:flex;align-items:center;justify-content:space-between;margin-bottom:.5rem}}
.tour-step{{font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
  color:var(--primary-deep)}}
.tour-skip{{font-size:12px;color:var(--n500);text-decoration:none}}
.tour-skip:hover{{color:var(--ink);text-decoration:underline}}
.tour-title{{margin:0 0 .45rem;font-size:17px;line-height:1.3;letter-spacing:-.015em;
  color:var(--ink-deep)}}
.tour-body{{margin:0 0 .7rem;font-size:13.5px;line-height:1.65;color:var(--n700)}}
.tour-foot{{display:flex;align-items:center;justify-content:space-between;gap:1rem;
  margin-top:.9rem;padding-top:.85rem;border-top:1px solid var(--n300)}}
.tour-dots{{display:flex;gap:.3rem}}
.tour-dot{{width:6px;height:6px;border-radius:999px;background:var(--n400);
  transition:background .2s,transform .2s}}
.tour-dot.on{{background:var(--primary);transform:scale(1.35)}}
.tour-acts{{display:flex;align-items:center;gap:.7rem}}
.tour-back{{font-size:12.5px;color:var(--n600);text-decoration:none}}
.tour-back:hover{{color:var(--ink);text-decoration:underline}}
.tour-start{{white-space:nowrap}}
@media(max-width:60rem){{
  .tour-box{{left:1.2rem;right:1.2rem;bottom:1.2rem;width:auto}}
}}
@media(prefers-reduced-motion:reduce){{
  .tour-veil,.tour-box{{animation:none}}
  {spots}{{animation:none}}
}}
"""
