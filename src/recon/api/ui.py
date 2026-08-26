# ruff: noqa: E501 — HTML fragments. Wrapping one mid-attribute makes the markup
# harder to read and easier to break than the long line it replaces.
"""The screens. Server-rendered, no JavaScript, no build step.

A page that needs `npm install` before a controller can see a number is a page
that fails on a fresh machine, so there is none here: expandable rows are
`<details>`, every action is a form post, and the whole product is HTML and CSS.

Three things hold across every screen, and they come from the approved flow
rather than from taste:

**One primary action per screen.** If a screen wants two, it is two screens.

**A rate never appears without its decomposition.** `20/23 (87.0%)` with the
tier split beside it. `87%` alone is the gameable number this whole project
exists to stop quoting.

**Nothing is shown that the record cannot say.** Every page renders a
`CloseView`, rebuilt from the decision log — including when the log has been
edited, where the page says so rather than rendering something clean.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from decimal import Decimal
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import loop as looplib
from .. import progress, review, service
from ..triage import classify as classify_mod
from . import auth
from .auth import AuthError, User
from .theme import document, icon, money, wordmark

router = APIRouter(include_in_schema=False)

#: Order is the order of work. Data sources comes first because a new account
#: has nothing to close and the rail should say so by its shape, not only by an
#: empty state three clicks in.
NAV = (
    ("sources", "/sources", "Data sources"),
    ("periods", "/periods", "Periods"),
    ("worklist", "/worklist", "Worklist"),
    ("verify", "/verify", "Verify"),
    ("settings", "/settings", "Settings"),
)


# --------------------------------------------------------------------------
# session plumbing
# --------------------------------------------------------------------------


def visitor(request: Request) -> User | None:
    token = request.cookies.get(auth.SESSION_COOKIE)
    return auth.read(token, auth.session_secret()) if token else None


def signed_in(request: Request) -> User:
    """The account for this request, or a redirect to the door.

    Raised as a 303 rather than a 401 because these routes are for a browser: a
    controller who followed a stale bookmark should land on the login, not on a
    JSON error. `/v1` answers the same question with a 401, which is right for
    a client that is not a person.
    """
    user = visitor(request)
    if user is None:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


#: `Depends` in a default is FastAPI's idiom and ruff's B008; a module-level
#: singleton is the same wiring, written the way the linter can read.
CURRENT_USER = Depends(signed_in)


#: The most one uploaded source may weigh. A statement is a text file; anything
#: past this is a mistake or an attack, and both deserve the same answer.
MAX_UPLOAD = 25 * 1024 * 1024

#: Where the shipped example periods live. Copied into an account rather than
#: read in place, so a new user's first close is over *their* files and behaves
#: exactly like one over their own bank statement.
SAMPLE_ROOT = Path("data/batches")


def tenant_sources(user: User) -> Path:
    """This account's source files. Same rule as its records: derived from the
    session, never from the request."""
    return service.TENANT_SOURCES / user.user_id


def tenant_runs(user: User, request: Request) -> Path:
    """Where this account's closes live. Resolved from the session and from
    nothing the request can influence — the same rule this surface applies to
    authority, applied to identity."""
    return service.runs_root(None) / user.user_id


def _check_csrf(request: Request, token: str | None) -> None:
    if not auth.csrf_ok(request.cookies.get(auth.CSRF_COOKIE), token):
        raise HTTPException(status_code=403, detail="This form expired. Reload and try again.")


def _with_session(response: Response, user: User) -> Response:
    secure = not auth.is_dev()
    response.set_cookie(
        auth.SESSION_COOKIE,
        auth.issue(user, auth.session_secret()),
        max_age=auth.SESSION_TTL,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        auth.CSRF_COOKIE,
        auth.new_csrf(),
        max_age=auth.SESSION_TTL,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )
    return response


def _csrf_field(request: Request) -> str:
    token = request.cookies.get(auth.CSRF_COOKIE) or ""
    return f"<input type='hidden' name='csrf' value='{escape(token)}'>"


# --------------------------------------------------------------------------
# the shell
# --------------------------------------------------------------------------


def _rail(user: User, active: str, worklist_count: int) -> str:
    items = []
    for key, href, label in NAV:
        count = (
            f"<span class='count'>{worklist_count}</span>"
            if key == "worklist" and worklist_count
            else ""
        )
        current = " aria-current='page'" if key == active else ""
        items.append(
            f"<a href='{href}'{current}>{icon(key)}<span>{escape(label)}</span>{count}</a>"
        )
    return (
        f"<aside class='rail'><div>{wordmark(24, '16px')}</div>"
        f"<nav class='nav'>{''.join(items)}</nav>"
        f"<div class='rail-foot'><div class='who'>"
        f"<span class='avatar'>{escape(user.initials)}</span>"
        f"<span style='line-height:1.25;min-width:0'>"
        f"<span style='display:block;font-size:12.5px;font-weight:500;overflow:hidden;"
        f"text-overflow:ellipsis'>{escape(user.email)}</span>"
        f"<span class='cap'>Controller</span></span></div>"
        f"<form method='post' action='/logout' style='margin-top:.7rem'>"
        f"<button class='btn btn-ghost' style='padding:.35rem .5rem;font-size:12px'>"
        f"{icon('signout', 14)}Sign out</button></form></div></aside>"
    )


def _crumb_row(crumb: str, worklist: int) -> str:
    """Breadcrumb on the left, the two things a controller reaches for on the
    right. The bell carries the open count rather than being decorative — a
    notification icon with nothing behind it is furniture."""
    bell = (
        f"<a class='iconbtn' href='/worklist' aria-label='{worklist} items need review'>"
        f"{icon('bell', 16)}<span class='dot'>{worklist}</span></a>"
        if worklist
        else f"<a class='iconbtn' href='/worklist' aria-label='Worklist'>{icon('bell', 16)}</a>"
    )
    return (
        f"<div class='crumb-row'><div class='crumb'>{crumb}</div>"
        f"<div class='crumb-tools'>{bell}"
        f"<a class='iconbtn' href='/verify' aria-label='How verification works'>"
        f"{icon('help', 16)}</a></div></div>"
    )


def shell(user: User, *, active: str, crumb: str, body: str, worklist: int = 0) -> HTMLResponse:
    banner = ""
    if not auth.is_dev():
        banner = ""
    elif auth.build_identity().name == "local":
        banner = (
            "<div class='devbanner'>Development credential store &mdash; accounts live "
            "in a local file, not in Cognito. <code>RECON_ENV=dev</code>.</div>"
        )
    inner = (
        f"{banner}<div class='shell'>{_rail(user, active, worklist)}"
        f"<main class='stage'>{_crumb_row(crumb, worklist)}{body}</main></div>"
    )
    return HTMLResponse(document("FinCon", inner))


# --------------------------------------------------------------------------
# the door
# --------------------------------------------------------------------------


PROOF_CARD = (
    "<div class='proofcard frost'>"
    "<div style='display:flex;justify-content:space-between;align-items:center;"
    "margin-bottom:.6rem'>"
    "<b style='font-size:12px'>PRF&#8209;M&#8209;00001</b>"
    "<span style='display:flex;gap:.3rem'>"
    "<span class='badge badge-ok' style='font-size:10.5px'>T0 exact</span>"
    "<span class='badge badge-info' style='font-size:10.5px'>P0</span></span></div>"
    "<div class='row'><span>bank &middot; 1 record</span><b>&#8377;&nbsp;90,259.47</b></div>"
    "<div class='row'><span>settlement &middot; 22 records</span>"
    "<b>&#8377;&nbsp;&minus;90,259.47</b></div>"
    "<div class='row' style='border-top:1px solid rgba(47,123,255,.12);margin-top:.3rem;"
    "padding-top:.45rem'><span>residual</span><b>&#8377;&nbsp;0.00</b></div>"
    "<div style='margin-top:.6rem;padding-top:.6rem;border-top:1px solid rgba(47,123,255,.12);"
    "font-size:11.5px;color:#15803D;display:flex;align-items:center;gap:.35rem'>"
    "&#10003; Re-derived from the source files</div></div>"
)


def _login_page(*, email: str = "", error: str = "", notice: str = "", csrf: str = "") -> str:
    """The split. Asymmetric on purpose — an even split is what a template does.

    The form pane is opaque: blur behind a password field is decoration at the
    exact moment a person needs certainty. The identity pane is the one place in
    the product where a gradient is permitted, and it carries a real proof
    rather than an illustration, because that costs nothing and is true.
    """
    alert = f"<div class='alert'>{escape(error)}</div>" if error else ""
    if notice:
        alert += f"<div class='alert alert-info'>{escape(notice)}</div>"
    return document(
        "Sign in · FinCon",
        f"""
<div class='auth'>
  <section class='split-form'>
    <div style='margin-bottom:2.2rem'>{wordmark(28, "18px")}</div>
    <h3 style='font-size:24px'>Sign in</h3>
    <p class='cap' style='margin:.2rem 0 1.5rem'>
      New here? Enter your email and we will create the account.</p>
    {alert}
    <form method='post' action='/login'>
      <input type='hidden' name='csrf' value='{escape(csrf)}'>
      <div class='field'><label for='email'>Email</label>
        <input class='input' id='email' name='email' type='email' required
               autocomplete='email' autofocus value='{escape(email)}'
               placeholder='you@company.com'></div>
      <div class='field'><label for='password'>Password</label>
        <div class='input-icon'>{icon("lock", 14)}
        <input class='input' id='password' name='password' type='password' required
               autocomplete='current-password' minlength='{auth.MIN_PASSWORD}'></div></div>
      <button class='btn btn-primary btn-wide' type='submit'>
        Continue {icon("arrow", 15)}</button>
    </form>
    <div class='rule-line'>auditing a close?</div>
    <a class='btn btn-secondary btn-wide' href='/verify'>
      {icon("verify", 15)} Verify a proof &mdash; no account needed</a>
    <p class='cap' style='margin-top:1.6rem'>
      At least {auth.MIN_PASSWORD} characters. We never store your password.</p>
  </section>
  <section class='split-art'>
    <div class='orb' style='width:200px;height:200px;top:-40px;right:-30px;
      background:radial-gradient(circle at 35% 30%,#8FBAFF,#2F7BFF);opacity:.34'></div>
    <div class='orb' style='width:120px;height:120px;bottom:34px;left:-32px;
      background:radial-gradient(circle at 40% 35%,#BFD9FF,#6FA3FF);opacity:.42'></div>
    <div class='art-inner'>
      <div>
        <p class='sec' style='color:#3E7BD6;margin-bottom:.7rem'>Open intake &middot; verified commit</p>
        <p class='quote'>Every match carries a proof a stranger can re-derive.</p>
      </div>
      {PROOF_CARD}
    </div>
  </section>
</div>""",
    )


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request) -> Response:
    if visitor(request) is not None:
        return RedirectResponse("/periods", status_code=303)
    token = request.cookies.get(auth.CSRF_COOKIE) or auth.new_csrf()
    page = HTMLResponse(_login_page(csrf=token))
    page.set_cookie(
        auth.CSRF_COOKIE,
        token,
        max_age=auth.SESSION_TTL,
        httponly=False,
        secure=not auth.is_dev(),
        samesite="lax",
        path="/",
    )
    return page


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    csrf: str = Form(""),
) -> Response:
    """One field decides sign-in or sign-up.

    No tabs and no toggle: an address we do not know is an account we offer to
    create, in place. The failure text is identical for an unknown address and a
    wrong password — the two must be indistinguishable, or this form becomes an
    account-enumeration oracle.
    """
    _check_csrf(request, csrf)
    identity = auth.build_identity()
    try:
        user = (
            identity.sign_in(email, password)
            if identity.exists(email)
            else identity.sign_up(email, password)
        )
    except AuthError as exc:
        return HTMLResponse(
            _login_page(
                email=email, error=str(exc), csrf=request.cookies.get(auth.CSRF_COOKIE, "")
            ),
            status_code=400,
        )
    return _with_session(RedirectResponse("/periods", status_code=303), user)


@router.post("/logout")
def logout(request: Request, csrf: str = Form("")) -> Response:
    _check_csrf(request, csrf)
    out = RedirectResponse("/login", status_code=303)
    out.delete_cookie(auth.SESSION_COOKIE, path="/")
    return out


@router.get("/", response_class=HTMLResponse)
def root(request: Request) -> Response:
    return RedirectResponse("/periods" if visitor(request) else "/login", status_code=303)


# --------------------------------------------------------------------------
# periods — the home
# --------------------------------------------------------------------------


def _state_badge(view: service.CloseView, signed: str = "") -> str:
    if signed:
        return f"<span class='badge badge-ok'>Signed off by {escape(signed)}</span>"
    if view.blocked:
        return "<span class='badge badge-bad'>Blocked</span>"
    if view.blocking_exceptions:
        return "<span class='badge badge-declared'>Needs review</span>"
    return "<span class='badge badge-ok'>Clear</span>"


@router.get("/periods", response_class=HTMLResponse)
def periods(request: Request, user: User = CURRENT_USER) -> Response:
    runs_dir = tenant_runs(user, request)
    recorded = service.stored_runs(runs_dir)
    views = {}
    for run_id in recorded:
        try:
            views[run_id] = service.view(run_id, runs_dir)
        except Exception:  # a log we cannot read is still a row worth showing
            views[run_id] = None

    open_items = sum(len(v.blocking_exceptions) for v in views.values() if v)
    csrf = _csrf_field(request)

    cards = []
    for lp in service.loops():
        rows = []
        for source_set in service.source_sets(lp.name, tenant_sources(user)):
            if source_set.complete:
                action = (
                    f"<form method='post' action='/periods/close'>{csrf}"
                    f"<input type='hidden' name='loop' value='{escape(lp.name)}'>"
                    f"<input type='hidden' name='source_set' value='{escape(source_set.name)}'>"
                    f"<button class='btn btn-primary' type='submit'>Close "
                    f"{escape(source_set.name)}</button></form>"
                )
                state = "<span class='badge badge-ok'>All sources present</span>"
            else:
                # Named, not counted, and the button is disabled rather than
                # missing: "October is short the settlement file" is the answer
                # a controller needs, and a period that quietly vanished from the
                # list would answer "where is October?" with nothing.
                action = "<span class='btn btn-secondary' aria-disabled='true'>Cannot close</span>"
                missing = escape(", ".join(source_set.missing))
                state = f"<span class='badge badge-declared'>Missing {missing}</span>"
            rows.append(
                f"<tr><td><b>{escape(source_set.name)}</b></td><td>{state}</td>"
                f"<td class='right'>{action}</td></tr>"
            )
        cards.append(
            f"<div class='panel' style='padding:1.3rem 1.4rem;margin-bottom:1rem'>"
            f"<div style='display:flex;gap:.5rem;align-items:baseline;flex-wrap:wrap'>"
            f"<h3 style='margin:0'>{escape(lp.name)}</h3>"
            f"<span class='badge badge-mute'>{escape(lp.policy_ref)}</span>"
            f"<span class='badge badge-mute'>{escape(lp.taxonomy_ref)}</span></div>"
            f"<p class='cap' style='margin:.4rem 0 1rem'>{escape(lp.description)}<br>"
            f"{lp.period_start}&ndash;{lp.period_end} &middot; "
            f"{escape(' → '.join(lp.strategies))} &middot; "
            f"rules in force: {escape(', '.join(lp.promoted_rules) or 'none')}</p>"
            f"<div class='tbl'><table><tr><th>Period</th><th>Sources</th>"
            f"<th class='right'>Action</th></tr>{''.join(rows)}</table></div></div>"
        )

    if recorded:
        run_rows = "".join(
            _run_row(rid, views[rid], review.state(rid, runs_dir).signed_off_by) for rid in recorded
        )
        closes = (
            f"<div class='tbl'><table><tr><th>Run</th><th>Loop</th>"
            f"<th class='right'>Matched</th><th class='right'>Worklist</th>"
            f"<th>State</th></tr>{run_rows}</table></div>"
        )
    else:
        closes = (
            "<div class='panel' style='padding:1.3rem 1.4rem'><p class='cap' style='margin:0'>"
            "No closes yet. Pick a period above &mdash; a close takes a few seconds and "
            "writes a record you can hand to an auditor.</p></div>"
        )

    body = (
        f"<h1>Close the books</h1>"
        f"<p class='cap' style='margin:0 0 1.6rem'>Pick a period whose source files have "
        f"arrived. Everything here is read from disk &mdash; nothing has been run yet.</p>"
        f"{''.join(cards)}"
        f"<p class='sec' style='margin-top:2rem'>Recorded closes</p>{closes}"
    )
    return shell(user, active="periods", crumb="<b>Periods</b>", body=body, worklist=open_items)


def _run_row(run_id: str, view: service.CloseView | None, signed: str = "") -> str:
    if view is None:
        return (
            f"<tr><td><a href='/periods/{escape(run_id)}'>{escape(run_id)}</a></td>"
            f"<td colspan='4'><span class='badge badge-bad'>Unreadable record</span></td></tr>"
        )
    return (
        f"<tr><td><a href='/periods/{escape(run_id)}'>{escape(run_id)}</a></td>"
        f"<td>{escape(view.loop)}</td>"
        f"<td class='right num'>{escape(view.tiers.rate)}</td>"
        f"<td class='right num'>{len(view.exceptions)}</td>"
        f"<td>{_state_badge(view, signed)}</td></tr>"
    )


def tenant_jobs(user: User, request: Request) -> Path:
    return tenant_runs(user, request) / ".jobs"


@router.post("/periods/close")
def do_close(
    request: Request,
    loop: str = Form(...),
    source_set: str = Form(...),
    csrf: str = Form(""),
    user: User = CURRENT_USER,
) -> Response:
    """Start the close, then send the controller somewhere they can watch it.

    A close takes a couple of seconds, and for those seconds the old surface
    showed nothing: the request hung and a finished page appeared. That is the
    moment a controller most wants to know what the machine is doing with their
    books, so it runs on a thread and the browser is redirected to a page that
    reports the pipeline's real stages as they complete.
    """
    _check_csrf(request, csrf)
    try:
        service.loops_for(loop)
    except looplib.LoopError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    sources, runs, jobs = (
        tenant_sources(user),
        tenant_runs(user, request),
        tenant_jobs(user, request),
    )
    period = sources / source_set
    if not period.exists():
        raise HTTPException(422, f"no source set {source_set!r} for this account")
    # Checked here, before a thread starts. `loop.run` refuses a half-arrived
    # period too, but that refusal would arrive as a *failed job* — a controller
    # who has not uploaded the bank statement should be told so, not shown a
    # processing page that spends two seconds reaching the same answer.
    missing = looplib.get(loop).missing(period)
    if missing:
        raise HTTPException(
            422,
            f"{source_set} is missing {', '.join(missing)}. A close over a "
            f"half-arrived period would report a clean month over rows that never came.",
        )

    tracker = progress.Tracker(jobs, loop, source_set)

    def work() -> None:
        try:
            outcome = looplib.run(
                looplib.get(loop),
                sources / source_set,
                runs_dir=runs,
                label=source_set,
                track=tracker,
            )
            events = len(service.events(outcome.run_id, runs))
            tracker.finish(outcome.run_id, rows=len(outcome.records), events=events)
        except Exception as exc:  # every failure is a state the page must show
            tracker.fail(f"{type(exc).__name__}: {exc}")

    threading.Thread(target=work, daemon=True).start()
    return RedirectResponse(f"/periods/closing/{tracker.job.job_id}", status_code=303)


@router.get("/periods/closing/{job_id}", response_class=HTMLResponse)
def closing_page(request: Request, job_id: str, user: User = CURRENT_USER) -> Response:
    """The pipeline, as it happens. Refreshed by the browser, not by a script.

    `<meta http-equiv="refresh">` rather than JavaScript, for the same reason
    nothing else here ships any: the page has to work on a fresh machine with no
    build step. It costs a full render per second, which for six stages and two
    seconds is a trade worth making.

    The stages and their descriptions are rendered from `progress.STAGES` before
    anything has happened, so a reader sees the whole shape of the work up front
    rather than watching steps appear from nowhere.
    """
    job = progress.read(tenant_jobs(user, request), job_id)
    if job is None:
        raise HTTPException(404, "That close is not one of yours, or has been cleaned up.")

    # Deliberately *not* redirecting the moment it finishes. On this corpus a
    # close takes tens of milliseconds, so an automatic redirect meant the work
    # flashed past and a reader was left asking whether it had run at all. The
    # completed pipeline, with what each stage did and how long it took, is the
    # receipt — and the honest answer to that question is a number with the work
    # beside it, not a delay added to make the work look harder.
    describe = dict(progress.STAGES)
    steps = []
    for stage in job.stages:
        if stage.state == "done":
            glyph, cls = icon("check", 12, 3), "done"
        elif stage.state == "running":
            glyph, cls = "<span class='pulse'><i></i><i></i></span>", "running"
        elif stage.state == "failed":
            glyph, cls = icon("x", 12, 3), "failed"
        else:
            glyph, cls = "", "waiting"
        fact = f"<div class='fact'>{escape(stage.detail)}</div>" if stage.detail else ""
        took = (
            f"<div class='ms'>{stage.elapsed_ms} ms</div>"
            if stage.state in {"done", "failed"}
            else ""
        )
        steps.append(
            f"<div class='step {cls}'><span class='mark'>{glyph}</span>"
            f"<span class='what'><div class='name'>{escape(stage.name)}</div>"
            f"<div class='why'>{escape(describe.get(stage.name, ''))}</div>"
            f"{fact}</span>{took}</div>"
        )

    if job.state == "failed":
        head = (
            f"<h1>The close stopped</h1>"
            f"<p class='sub'>{escape(job.loop)} &middot; {escape(job.source_set)}</p>"
            f"<div class='alert' style='margin-top:1rem'>{escape(job.error)}</div>"
            f"<p class='cap'>The stages below show how far it got. The ones still "
            f"waiting were not run &mdash; marking them done would be the worst thing "
            f"this product could tell you.</p>"
        )
        refresh = ""
        tail = (
            "<p style='margin-top:1.4rem'>"
            "<a class='btn btn-primary' href='/periods'>Back to periods</a></p>"
        )
    elif job.state == "complete":
        head = (
            f"<h1>Closed {escape(job.source_set)}</h1>"
            f"<p class='sub'>{escape(job.loop)} &middot; "
            f"<b>{job.rows} records</b> read, matched, verified, posted and chained into "
            f"<b>{job.events} decisions</b> &mdash; in <b>{job.total_ms} ms</b>.</p>"
        )
        refresh = ""
        tail = (
            f"<p style='margin-top:1.4rem'>"
            f"<a class='btn btn-primary' href='/periods/{escape(job.run_id)}'>"
            f"Open the close {icon('arrow', 15)}</a>"
            f"<a class='btn btn-ghost' href='/periods/{escape(job.run_id)}/log'>"
            f"{icon('log', 14)}Decision log</a></p>"
            f"<div class='note' style='margin-top:1.4rem'><b>No model was involved.</b> "
            f"Every stage above is deterministic &mdash; the same files produce the same "
            f"answer, and a third party holding them re-derives it without us. A model is "
            f"only ever asked to <i>read</i> an exception a human is already looking at, on "
            f"that item's own page, and what it says is inert until somebody accepts it.</div>"
            f"<p class='cap' style='margin-top:1rem'>Every stage above ran on this request "
            f"&mdash; the decision log was deleted and rewritten, and its timestamps are from "
            f"a moment ago. It is fast because the period is {job.rows} rows, not because "
            f"anything was skipped: a delay added to make the work look harder would be the "
            f"one thing this product must never do.</p>"
        )
    else:
        head = (
            f"<h1>Closing {escape(job.source_set)}</h1>"
            f"<p class='sub'>{escape(job.loop)} &middot; every stage below is a real "
            f"boundary in the pipeline, reporting the fact it produced.</p>"
        )
        refresh = "<meta http-equiv='refresh' content='1'>"
        tail = (
            "<p class='cap' style='margin-top:1.4rem'>This page refreshes itself. Nothing "
            "is posted until every match has been re-derived from the raw records, and a "
            "match that fails re-derivation is dropped rather than reported.</p>"
        )

    body = f"<div class='run'>{head}<div class='steps'>{''.join(steps)}</div>{tail}</div>"
    page = shell(
        user,
        active="periods",
        crumb="<a href='/periods'>Periods</a><span>/</span><b>Closing</b>",
        body=body,
    )
    return HTMLResponse(page.body.decode().replace("<title>", f"{refresh}<title>", 1))


# --------------------------------------------------------------------------
# one close
# --------------------------------------------------------------------------


def _proof_block(match: service.MatchView) -> str:
    proof = match.proof
    if proof is None:
        return (
            "<p class='note note-bad'>The record does not contain this proof &mdash; a log "
            "written before contract 7.4.0. Absent evidence, not weak evidence.</p>"
        )
    legs = "".join(
        f"<tr><td>{escape(leg.side)}</td><td class='right num'>{money(leg.subtotal)}</td>"
        f"<td class='cap'>{escape(', '.join(leg.record_ids[:5]))}"
        f"{'&hellip;' if len(leg.record_ids) > 5 else ''}</td></tr>"
        for leg in proof.legs
    )
    extra = []
    if proof.rule_id:
        extra.append(f"rule {escape(proof.rule_id)}@v{proof.rule_version}")
    if proof.attested_by:
        extra.append(f"attested by {escape(proof.attested_by)}")
    if proof.declared_amount is not None:
        extra.append(
            f"declared gap {proof.declared_amount} &mdash; {escape(proof.declared_gap or '')}"
        )
    return (
        f"<p class='cap'>{escape(proof.proof_id)} &middot; match tier "
        f"<b>{escape(match.tier)}</b> &middot; proof tier <b>{escape(proof.provenance.value)}</b>"
        f" &middot; residual {money(proof.residual)} &middot; tolerance "
        f"{proof.tolerance_used}/{proof.tolerance_allowed}"
        + (" &middot; " + " &middot; ".join(extra) if extra else "")
        + f"</p><div class='tbl'><table><tr><th>Side</th><th class='right'>Claimed subtotal</th>"
        f"<th>Records</th></tr>{legs}</table></div>"
        "<p class='cap' style='margin-top:.5rem'>Claimed subtotals. A verifier recomputes "
        "them from the records and refuses the match if they disagree.</p>"
    )


@router.get("/periods/{run_id}", response_class=HTMLResponse)
def close_page(request: Request, run_id: str, user: User = CURRENT_USER) -> Response:
    runs_dir = tenant_runs(user, request)
    try:
        # The page renders every proof inline behind `<details>`, so it asks for
        # them. A browser is not a context window; the budget exists for the
        # surface where a response is charged by the token.
        view = service.view(run_id, runs_dir, detail=service.Detail.FULL)
    except service.ServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    csrf = _csrf_field(request)
    tiers = view.tiers
    by_match = " ".join(f"{k}={v}" for k, v in sorted(tiers.by_match_tier.items())) or "&mdash;"
    by_proof = " ".join(f"{k}={v}" for k, v in sorted(tiers.by_proof_tier.items())) or "&mdash;"

    matched, offered = tiers.matched, tiers.anchors_in_scope
    pct = f"{(matched * 100 / offered):.1f}%" if offered else "&mdash;"
    metrics = (
        "<div class='metrics'>"
        + _metric(
            "Auto-matched",
            f"{matched}<small> / {offered}</small>",
            f"by tier {by_match}",
            ico="trend",
            bar=round(matched * 100 / offered) if offered else 0,
            sub=f"<span style='color:var(--primary);font-weight:600;font-size:15px'>{pct}</span>",
        )
        + _metric(
            "Proof tiers",
            by_proof,
            f"{tiers.declared} resting on a declared gap",
            ico="layers",
        )
        + _metric(
            "Every input disposed",
            "Yes" if view.complete else "<span class='v bad'>No</span>",
            "matched, excepted, or out of scope with a reason",
            ico="verify",
            tone="" if view.complete else "bad",
        )
        + _metric(
            "Blocking recall",
            "Absent",
            "measured against labelled pairs; production has none",
            ico="alert",
        )
        + _metric(
            "Books",
            "Balanced" if not view.blocked else "<span class='v bad'>Blocked</span>",
            "; ".join(view.blocked) or "balance assertion held",
            ico="scale",
            tone="" if not view.blocked else "bad",
        )
        + _metric(
            "Awaiting sign-off",
            str(len(view.blocking_exceptions)),
            "exceptions a human must clear",
            ico="user",
        )
        + "</div>"
    )

    problems = ""
    if view.chain_problems:
        items = "".join(f"<li>{escape(p)}</li>" for p in view.chain_problems)
        problems += (
            f"<div class='alert'><b>The decision log does not vouch for itself.</b>"
            f"<ul style='margin:.4rem 0 0'>{items}</ul></div>"
        )
    if view.unproven_matches:
        problems += (
            f"<div class='alert alert-info'>{len(view.unproven_matches)} match(es) have no "
            f"proof in the record. Absent evidence, named rather than passed over.</div>"
        )

    stages = "".join(
        f"<span class='st st-ok'>{icon('check', 11, 3)}{escape(label)}</span>"
        for label in _stage_labels(view)
    )

    state = review.state(run_id, runs_dir)
    rows = []
    for item in view.exceptions:
        exc = item.exception
        note = (
            f" <span class='badge badge-declared'>{escape(item.authority_note)}</span>"
            if item.authority_note
            else ""
        )
        why = exc.hypothesis or "no hypothesis — the engine has facts, not an explanation"
        taken = state.acknowledged.get(exc.exception_id)
        status = (
            f"<span class='badge badge-ok'>{escape(taken.split('@')[0])}</span>"
            if taken
            else f"<span class='badge {'badge-declared' if exc.blocks_close else 'badge-mute'}'>"
            f"{'blocks sign-off' if exc.blocks_close else 'open'}</span>"
        )
        rows.append(
            f"<tr><td class='right num'>{item.rank}</td>"
            f"<td><a href='/periods/{escape(run_id)}/items/{escape(exc.exception_id)}'>"
            f"<b>{escape(exc.code)}</b></a> {escape(item.code_title)}{note}"
            f"<span class='sub'>{escape(why)}</span></td>"
            f"<td class='right num'>{money(exc.amount)}</td>"
            f"<td class='right num'>{item.age_days}d</td>"
            f"<td class='num'>{escape(exc.fingerprint[:8] or '—')}</td>"
            f"<td>{escape(item.owner)}</td>"
            f"<td>{status}</td></tr>"
        )
    worklist = (
        f"<div class='tbl'><table><tr><th class='right'>#</th><th>Exception</th>"
        f"<th class='right'>Amount</th><th class='right'>Age</th><th>Break</th>"
        f"<th>Owner</th><th>Status</th></tr>{''.join(rows)}</table></div>"
        if rows
        else "<div class='panel' style='padding:1.2rem'><p class='cap' style='margin:0'>"
        "No exceptions. Every input was matched or declared out of scope.</p></div>"
    )

    # --- sign-off: the terminal human decision -----------------------------
    open_blockers = review.blockers([e.exception for e in view.exceptions], state)
    if state.signed_off:
        signoff = (
            f"<div class='panel' style='padding:1.3rem 1.4rem;margin-bottom:1.6rem'>"
            f"<p class='sec' style='margin-bottom:.5rem'>Signed off</p>"
            f"<p style='margin:0'><b>{escape(state.signed_off_by)}</b> accepted this close"
            + (f" &mdash; &ldquo;{escape(state.note)}&rdquo;" if state.note else "")
            + ".</p><p class='cap' style='margin:.6rem 0 0'>Recorded in "
            "<code>review.jsonl</code>, chained separately from the decision log. The "
            "close record itself is sealed and unchanged &mdash; what the engine decided "
            "and what a person decided are two records.</p></div>"
        )
    elif view.blocked:
        signoff = (
            "<div class='panel' style='padding:1.3rem 1.4rem;margin-bottom:1.6rem'>"
            "<p class='sec' style='margin-bottom:.5rem'>Sign-off</p>"
            "<p class='note note-bad' style='margin:0'>The books do not balance, so this "
            "close cannot be signed off. Putting a name to a number the system itself says "
            "is wrong is the one thing a sign-off must never allow.</p></div>"
        )
    elif open_blockers:
        signoff = (
            f"<div class='panel' style='padding:1.3rem 1.4rem;margin-bottom:1.6rem'>"
            f"<p class='sec' style='margin-bottom:.5rem'>Sign-off</p>"
            f"<p style='margin:0 0 .6rem'><b>{len(open_blockers)} item(s) still need a human.</b> "
            f"Open each one and take it &mdash; signing off on items nobody has looked at is "
            f"exactly what this control exists to stop.</p>"
            f"<p class='cap' style='margin:0'>"
            + " ".join(
                f"<a href='/periods/{escape(run_id)}/items/{escape(i)}'>{escape(i)}</a>"
                for i in open_blockers
            )
            + "</p><p style='margin-top:.9rem'><button class='btn btn-primary' disabled>"
            "Sign off</button></p></div>"
        )
    else:
        signoff = (
            f"<div class='panel' style='padding:1.3rem 1.4rem;margin-bottom:1.6rem'>"
            f"<p class='sec' style='margin-bottom:.5rem'>Sign-off</p>"
            f"<p style='margin:0 0 .9rem'>Every blocking item has been taken and the books "
            f"balance. Signing off records <b>your name</b> against this close.</p>"
            f"<form method='post' action='/periods/{escape(run_id)}/signoff'>{csrf}"
            f"<div class='field'><label for='note'>Note (optional)</label>"
            f"<input class='input' id='note' name='note' placeholder='October reconciled'></div>"
            f"<button class='btn btn-primary' type='submit'>{icon('check', 15)}"
            f"Sign off as {escape(user.email)}</button></form></div>"
        )

    matches = "".join(
        f"<details style='padding:.35rem 0;border-bottom:1px solid var(--n200)'>"
        f"<summary>{escape(m.anchor_external)} &rarr; {escape(m.group_ref)} "
        f"({escape(m.tier)}, {m.group_size} rows)</summary>{_proof_block(m)}</details>"
        for m in view.matches
    )

    authority = "".join(
        f"<tr><td class='num'>{escape(a['bundle'])}</td><td>{escape(a['signed_by'] or '—')}</td>"
        f"<td>{'<span class="badge badge-ok">trusted</span>' if a['trusted'] else '<span class="badge badge-mute">unverified</span>'}</td>"
        f"<td class='cap'>{escape('; '.join(a['reasons']) or '—')}</td></tr>"
        for a in view.authority
    )

    # The record pins a sha256 per source, so the page knows which files this
    # close ran on. Offering the others as equals invited the mistake that
    # produced twenty meaningless refutations — they are still reachable, behind
    # a disclosure that says what they are for.
    ran_on = service.source_set_of(run_id, tenant_runs(user, request), root=tenant_sources(user))
    others = [
        s.name
        for s in service.source_sets(view.loop, tenant_sources(user))
        if s.complete and s.name != ran_on
    ]

    def _rebutton(name: str, primary: bool) -> str:
        cls = "btn-secondary" if primary else "btn-ghost"
        label = "Re-derive this close" if primary else f"against {escape(name)}"
        return (
            f"<form method='post' action='/periods/{escape(run_id)}/reverify' style='display:inline'>"
            f"{csrf}<input type='hidden' name='source_set' value='{escape(name)}'>"
            f"<button class='btn {cls}' type='submit'>{icon('verify', 14) if primary else ''}"
            f"{label}</button></form> "
        )

    reverify = _rebutton(ran_on, True) if ran_on else ""
    if others:
        reverify += (
            "<details style='display:inline-block;margin-left:.4rem'>"
            "<summary>check against other files</summary>"
            "<div style='margin-top:.6rem;display:flex;gap:.4rem;flex-wrap:wrap'>"
            + "".join(_rebutton(name, False) for name in others)
            + "<p class='cap' style='margin:.4rem 0 0;max-width:38ch'>These are different bytes. "
            "Record ids are content-derived, so every proof will cite rows that are not there &mdash; "
            "that is a fact about the files, not a finding about this close.</p></div></details>"
        )
    if not ran_on:
        reverify = (
            "<span class='badge badge-declared'>The files this close ran on are not on disk</span> "
            + "".join(_rebutton(n, False) for n in others)
        )

    # Escape the dates, then join with the entity — `escape()` over the whole
    # string turns `&ndash;` into visible `&amp;ndash;`, which is how an entity
    # ends up printed on a page.
    period = " &ndash; ".join(escape(d) for d in view.period) if view.period else "&mdash;"
    body = (
        f"<div class='pagehead'><div class='lhs'>"
        f"<h1>{escape(view.run_id)}</h1>"
        f"<p class='sub'>{escape(view.loop)} &middot; policy "
        f"<span class='num'>{escape(view.policy_ref or '—')}</span> &middot; {view.events} events "
        f"&middot; rebuilt from the decision log</p></div>"
        f"<div class='rhs'><span class='chip-select'>{icon('calendar', 16)}"
        f"<span><span class='k'>Period</span><br><span class='v num'>{period}</span></span>"
        f"</span>"
        f"<a class='btn btn-primary' href='/periods/{escape(run_id)}/pack'>"
        f"Close pack {icon('arrow', 14)}</a></div></div>"
        f"<div class='stages'>{stages}</div>{problems}{metrics}"
        f"<p class='sec'>Check this close</p>"
        f"<div class='panel' style='padding:1.2rem 1.3rem;margin-bottom:1.6rem'>"
        f"<p class='cap' style='margin:0 0 .8rem'>Re-ingests the source files, checks each "
        f"sha256 against the hash this record pinned, and re-derives every proof in the log. "
        f"Nothing is read from the process that ran the close.</p>"
        f"<div style='display:flex;gap:.5rem;flex-wrap:wrap;align-items:center'>{reverify}"
        f"<a class='btn btn-ghost' href='/v1/runs/{escape(run_id)}/export'>{icon('download', 14)}"
        f"Audit export</a>"
        f"<a class='btn btn-ghost' href='/periods/{escape(run_id)}/log'>{icon('log', 14)}"
        f"Decision log</a>"
        f"<a class='btn btn-ghost' href='/periods/{escape(run_id)}/pack'>{icon('file', 14)}"
        f"Close pack</a></div></div>"
        f"{signoff}"
        f"<p class='sec'>Worklist &mdash; {len(view.exceptions)} items, ranked by cash impact "
        f"&times; age</p>{worklist}"
        f"<p class='sec' style='margin-top:2rem'>Matches &mdash; {len(view.matches)}</p>"
        f"<div class='panel' style='padding:.5rem 1.2rem'>{matches}</div>"
        f"<p class='sec' style='margin-top:2rem'>Authority</p>"
        f"<div class='tbl'><table><tr><th>Bundle</th><th>Signed by</th><th>Trusted</th>"
        f"<th>Why not</th></tr>{authority}</table></div>"
    )
    crumb = (
        f"<a href='/periods'>Periods</a><span>/</span><b>{escape(view.run_id)}</b>"
        f"<span>/</span>{_state_badge(view, state.signed_off_by)}"
    )
    return shell(
        user,
        active="periods",
        crumb=crumb,
        body=body,
        worklist=len(view.blocking_exceptions),
    )


def _stage_labels(view: service.CloseView) -> list[str]:
    return [
        f"Ingest · {len(view.sources)} sources",
        "Block",
        f"Match · {view.tiers.matched}",
        f"Verify · {view.tiers.matched}/{view.tiers.matched}",
        "Post · balanced" if not view.blocked else "Post · blocked",
        f"Record · {view.events} events",
    ]


def _metric(
    key: str,
    value: str,
    note: str,
    *,
    ico: str = "layers",
    tone: str = "",
    bar: int | None = None,
    sub: str = "",
) -> str:
    """One figure, its icon, its note — and never a rate without its parts.

    `sub` is where the decomposition goes, so a card physically cannot show a
    percentage on its own: the caller has to supply both or neither.
    """
    progress = (
        f"<div class='bar'><i style='width:{max(0, min(bar, 100))}%'></i></div>"
        if bar is not None
        else ""
    )
    return (
        f"<div class='panel solid metric'><div class='head'><div>"
        f"<div class='k'>{escape(key)}</div><div class='v'>{value}</div></div>"
        f"<span class='metric-ico {tone}'>{icon(ico, 17)}</span></div>"
        f"{progress}"
        f"{f"<div class='d'>{sub}</div>" if sub else ''}"
        f"<div class='d'>{escape(note)}</div></div>"
    )


@router.post("/periods/{run_id}/reverify", response_class=HTMLResponse)
def do_reverify(
    request: Request,
    run_id: str,
    source_set: str = Form(...),
    csrf: str = Form(""),
    user: User = CURRENT_USER,
) -> Response:
    """Re-derive, and print what came back &mdash; including when it disagrees."""
    _check_csrf(request, csrf)
    try:
        report = service.reverify(
            run_id, source_set, root=tenant_sources(user), runs_dir=tenant_runs(user, request)
        )
    except service.ServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    sources = "".join(
        f"<tr><td class='num'>{escape(s.source)}</td><td class='num'>{escape(s.spec_id)}</td>"
        f"<td class='num'>{escape(s.recorded_hash[:16])}</td>"
        f"<td class='num'>{escape(s.actual_hash[:16])}</td>"
        f"<td>{'<span class="badge badge-ok">same file</span>' if s.same_file else '<span class="badge badge-bad">different file</span>'}</td></tr>"
        for s in report.sources
    )
    refuted = "".join(
        f"<li><span class='num'>{escape(r['proof_id'])}</span>: "
        f"{escape('; '.join(r['reasons']))}</li>"
        for r in report.refuted
    )
    # When the files are not the ones this close ran on, the refutations mean
    # nothing — record ids are content-derived, so different bytes cite rows that
    # are not there. Leading with twenty walls of red was the page telling a
    # reader they had found a problem with the close when they had pointed it at
    # the wrong period. That reads as an accusation and it is a navigation error.
    trailer = ""
    if not report.sources_match:
        trailer += (
            "<div class='alert alert-info'><b>These are not the files this close ran on.</b><br>"
            "Record ids are derived from content, so a different period's files cite rows that "
            "do not exist here. Every refutation below follows from that and says nothing about "
            "the close &mdash; re-derive against the period whose hashes match.</div>"
        )
    if refuted:
        label = (
            "Refuted &mdash; expected, given the files above"
            if not report.sources_match
            else "Refuted"
        )
        trailer += (
            f"<details style='margin-top:1.4rem'>"
            f"<summary>{label} ({len(report.refuted)})</summary>"
            f"<div class='alert' style='margin-top:.6rem'><ul style='margin:0'>{refuted}</ul></div>"
            f"</details>"
        )
    if report.missing_proofs:
        trailer += (
            f"<div class='alert alert-info' style='margin-top:1rem'>{len(report.missing_proofs)} "
            f"match(es) have no proof in the record, so there was nothing to re-derive. "
            f"This does not pass.</div>"
        )

    body = (
        f"<h1>Re-derivation</h1>"
        f"<p class='cap' style='margin:0 0 1.3rem'>Against the files in "
        f"<span class='num'>{escape(source_set)}</span>, under "
        f"{escape(report.policy_ref)}. Nothing was read from the process that ran the close.</p>"
        "<div class='metrics'>"
        + _metric(
            "Verdict",
            "<span style='color:var(--success)'>holds</span>"
            if report.holds
            else "<span style='color:var(--error)'>does not hold</span>",
            "sources, arithmetic and evidence must all pass",
            ico="verify",
            tone="" if report.holds else "bad",
        )
        + _metric(
            "Proofs re-derived",
            f"{report.proven}/{report.proofs_checked}",
            "recomputed from freshly ingested records",
            ico="layers",
        )
        + _metric(
            "Records ingested",
            str(report.records_ingested),
            report.records_digest,
            ico="sources",
        )
        + "</div>"
        + f"<p class='sec'>Source documents</p>"
        f"<div class='tbl'><table><tr><th>Source</th><th>Spec</th>"
        f"<th>Hash in the record</th><th>Hash on disk</th><th></th></tr>{sources}</table></div>"
        f"{trailer}"
        f"<p style='margin-top:1.6rem'><a href='/periods/{escape(run_id)}'>&larr; back to the close</a></p>"
    )
    crumb = (
        f"<a href='/periods'>Periods</a><span>/</span>"
        f"<a href='/periods/{escape(run_id)}'>{escape(run_id)}</a><span>/</span>"
        f"<b>Re-derivation</b>"
    )
    return shell(user, active="verify", crumb=crumb, body=body)


# --------------------------------------------------------------------------
# the public door — an auditor needs no account
# --------------------------------------------------------------------------


@router.get("/verify", response_class=HTMLResponse)
def verify_page(request: Request) -> Response:
    """Public and stateless. An auditor checking our arithmetic should not need
    an account with us; requiring one would undercut the exact claim this page
    exists to make."""
    loops = "".join(
        f"<li><b>{escape(lp.name)}</b> &mdash; policy <span class='num'>"
        f"{escape(lp.policy_ref)}</span></li>"
        for lp in service.loops()
    )
    body = f"""
<div style='max-width:46rem;margin:0 auto;padding:3rem 1.5rem'>
  <div style='margin-bottom:2rem'>{wordmark(26, "17px")}</div>
  <h1>Verify a proof</h1>
  <p class='body-lg' style='color:var(--n600);margin-bottom:1.6rem'>
    Stateless, public, and it trusts nothing. Hand it a proof from an audit export
    and records you ingested yourself from the source files, and it re-derives the
    arithmetic under a policy you name.</p>

  <div class='panel' style='padding:1.4rem 1.5rem;margin-bottom:1.2rem'>
    <p class='sec' style='margin-bottom:.7rem'>How it works</p>
    <ol style='margin:0;padding-left:1.1rem;color:var(--n700)'>
      <li>Fetch the source files named in the export and confirm each sha256.</li>
      <li>Ingest them with the published adapter spec in <code>data/adapters/</code>.</li>
      <li><code>POST /v1/verify</code> with the proof, your records, and a loop name.</li>
      <li>Confirm the decision log's chain with <code>GET /v1/runs/{{id}}/chain</code>.</li>
    </ol>
    <p class='cap' style='margin:.9rem 0 0'>None of this needs our database, our network
    or our goodwill. A step that disagrees is a finding about us.</p>
  </div>

  <div class='panel' style='padding:1.4rem 1.5rem'>
    <p class='sec' style='margin-bottom:.7rem'>Published loops</p>
    <ul style='margin:0;padding-left:1.1rem;color:var(--n700)'>{loops}</ul>
    <p class='cap' style='margin:.9rem 0 0'>The verdict names the policy that judged it and
    whether you supplied it. A lenient policy you bring along yields a verdict about
    <i>your</i> constraints, stamped <code>caller-supplied</code> so it cannot be quoted
    back as ours.</p>
  </div>

  <p style='margin-top:1.6rem'>
    <a class='btn btn-secondary' href='/docs'>Open the API reference</a>
    <a class='btn btn-ghost' href='/login'>Sign in {icon("arrow", 14)}</a></p>
</div>"""
    return HTMLResponse(document("Verify a proof · FinCon", body))


def _empty(ico: str, title: str, body: str, action: str = "") -> str:
    return (
        f"<div class='empty'><div class='ring'>{icon(ico, 22)}</div>"
        f"<h3>{escape(title)}</h3><p>{escape(body)}</p>"
        f"{f"<p style='margin-top:1.1rem'>{action}</p>" if action else ''}</div>"
    )


@router.get("/worklist", response_class=HTMLResponse)
def worklist_page(request: Request, owner: str = "", user: User = CURRENT_USER) -> Response:
    """Every open item across every close, ranked and routed.

    The per-close worklist answers "what is wrong with October". This answers
    "what is on my desk", which is the question a controller actually starts the
    day with — and it is the reason the tail is the product rather than the match
    rate.
    """
    runs_dir = tenant_runs(user, request)
    rows, owners, total_paise = [], {}, 0
    for run_id in service.stored_runs(runs_dir):
        try:
            view = service.view(run_id, runs_dir)
        except Exception:
            continue
        for item in view.exceptions:
            owners[item.owner] = owners.get(item.owner, 0) + 1
            if owner and item.owner != owner:
                continue
            total_paise += item.cash_impact_paise
            exc = item.exception
            note = (
                f" <span class='badge badge-declared'>{escape(item.authority_note)}</span>"
                if item.authority_note
                else ""
            )
            rows.append(
                (
                    item.cash_impact_paise * max(item.age_days, 1),
                    f"<tr><td><a href='/periods/{escape(run_id)}'>{escape(run_id)}</a></td>"
                    f"<td><b>{escape(exc.code)}</b> {escape(item.code_title)}{note}"
                    f"<span class='sub'>{escape(exc.hypothesis or 'the engine has facts, not an explanation')}</span></td>"
                    f"<td class='right num'>{money(exc.amount)}</td>"
                    f"<td class='right num'>{item.age_days}d</td>"
                    f"<td class='num'>{escape(exc.fingerprint[:8] or '&mdash;')}</td>"
                    f"<td>{escape(item.owner)}</td></tr>",
                )
            )
    rows.sort(key=lambda pair: -pair[0])

    filters = "".join(
        f"<a href='/worklist{'' if not name else '?owner=' + name}' "
        f"aria-current='{str(owner == name).lower()}'>{escape(label)} "
        f"<span class='num'>{count}</span></a>"
        for name, label, count in [("", "All desks", sum(owners.values()))]
        + [(o, o, n) for o, n in sorted(owners.items())]
    )

    table = (
        f"<div class='tbl'><table><tr><th>Run</th><th>Exception</th>"
        f"<th class='right'>Amount</th><th class='right'>Age</th><th>Break</th>"
        f"<th>Owner</th></tr>{''.join(html for _, html in rows)}</table></div>"
        if rows
        else _empty(
            "inbox",
            "Nothing on this desk",
            "Either no close has been run yet, or every item has been cleared. "
            "The worklist only ever shows what a close actually raised.",
            "<a class='btn btn-primary' href='/periods'>Go to periods</a>",
        )
    )
    body = (
        f"<div class='pagehead'><div class='lhs'><h1>Worklist</h1>"
        f"<p class='sub'>Ranked by cash impact &times; age, routed by the taxonomy. "
        f"{len(rows)} item(s), {money(Decimal(total_paise) / 100)} at stake.</p></div></div>"
        f"<div class='toolbar'><div class='pillnav'>{filters}</div></div>{table}"
    )
    return shell(
        user,
        active="worklist",
        crumb="<b>Worklist</b>",
        body=body,
        worklist=sum(owners.values()),
    )


@router.get("/periods/{run_id}/log", response_class=HTMLResponse)
def log_page(request: Request, run_id: str, offset: int = 0, user: User = CURRENT_USER) -> Response:
    """The decision log as a timeline rather than a wall of JSON.

    This is the artifact an auditor is handed, so it is worth rendering as
    something a person can read: one row per decision, in order, with the
    payload behind a disclosure. The counts at the top are the shape of the
    close — 20 matches, 7 exceptions, 23 postings — which is the first thing
    anyone wants and the last thing raw JSON gives them.
    """
    runs_dir = tenant_runs(user, request)
    try:
        page = service.event_page(run_id, offset=offset, runs_dir=runs_dir)
        chain = service.check_chain(service.events(run_id, runs_dir))
    except service.ServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    tone = {
        "MatchProven": "k-ok",
        "PostingWritten": "k-ok",
        "SourceIngested": "k-ok",
        "CloseCompleted": "k-ok",
        "AuthorityVerified": "k-info",
        "RuleApplied": "k-info",
        "CloseStarted": "k-info",
        "OutOfScope": "k-info",
        "ExceptionRaised": "k-warn",
        "IntakeUnverified": "k-warn",
        "MatchRejected": "k-bad",
        "CloseBlocked": "k-bad",
        "ProposalRefused": "k-bad",
    }
    glyph = {"k-ok": "check", "k-bad": "x", "k-warn": "alert", "k-info": "layers"}

    events_html = []
    for event in page.items:
        klass = tone.get(event["kind"], "k-info")
        payload = json.dumps(event["payload"], indent=2, sort_keys=True)
        events_html.append(
            f"<div class='ev {klass}'><span class='node'>{icon(glyph[klass], 11, 3)}</span>"
            f"<div class='line'><span class='kind'>{escape(event['kind'])}</span>"
            f"<span class='badge badge-mute'>{escape(event['outcome'])}</span>"
            f"<span class='meta'>#{event['seq']} &middot; {escape(event['actor'])} &middot; "
            f"{escape(event['at'][11:19])}Z</span></div>"
            f"<details><summary>payload &amp; hash</summary>"
            f"<pre>{escape(payload)}</pre>"
            f"<p class='cap num' style='margin:.4rem 0 0'>hash {escape(event['event_hash'][:32])}&hellip;<br>"
            f"prev {escape(event['prev_hash'][:32])}&hellip;</p></details></div>"
        )

    kinds: dict[str, int] = {}
    for event in service.events(run_id, runs_dir):
        kinds[event.kind.value] = kinds.get(event.kind.value, 0) + 1
    summary = "".join(
        f"<span class='badge {'badge-ok' if tone.get(k) == 'k-ok' else 'badge-bad' if tone.get(k) == 'k-bad' else 'badge-declared' if tone.get(k) == 'k-warn' else 'badge-info'}'>"
        f"{escape(k)} <span class='num'>{n}</span></span> "
        for k, n in sorted(kinds.items(), key=lambda kv: -kv[1])
    )

    nav = ""
    if page.next_offset is not None:
        nav = (
            f"<p style='margin-top:1.2rem'><a class='btn btn-secondary' "
            f"href='/periods/{escape(run_id)}/log?offset={page.next_offset}'>"
            f"Next {page.total - page.next_offset} events {icon('arrow', 14)}</a></p>"
        )
    if offset:
        nav += (
            f"<p style='margin-top:.6rem'><a href='/periods/{escape(run_id)}/log'>"
            f"&larr; back to the start</a></p>"
        )

    verdict = (
        "<span class='badge badge-ok'>chain holds</span>"
        if chain.holds
        else "<span class='badge badge-bad'>chain does not hold</span>"
    )
    problems = (
        ""
        if chain.holds
        else "<div class='alert'><b>The log does not vouch for itself.</b><ul style='margin:.4rem 0 0'>"
        + "".join(f"<li>{escape(p)}</li>" for p in chain.problems)
        + "</ul></div>"
    )

    body = (
        f"<div class='pagehead'><div class='lhs'><h1>Decision log</h1>"
        f"<p class='sub'>Every decision this close made, in order, hash-chained. "
        f"Showing {page.returned} of {page.total}.</p></div>"
        f"<div class='rhs'>{verdict}"
        f"<a class='btn btn-secondary' href='/v1/runs/{escape(run_id)}/events'>"
        f"{icon('download', 14)}Raw JSON</a></div></div>"
        f"{problems}"
        f"<div class='panel' style='padding:1rem 1.2rem;margin-bottom:1.4rem'>{summary}"
        f"<p class='cap' style='margin:.7rem 0 0'>A hash chain proves internal consistency, "
        f"not custody &mdash; an actor able to rewrite the whole file can recompute it over "
        f"anything. What it closes is the partial edit and the truncated tail.</p></div>"
        f"<div class='panel' style='padding:1.2rem 1.4rem'><div class='log'>"
        f"{''.join(events_html)}</div>{nav}</div>"
    )
    crumb = (
        f"<a href='/periods'>Periods</a><span>/</span>"
        f"<a href='/periods/{escape(run_id)}'>{escape(run_id)}</a><span>/</span><b>Decision log</b>"
    )
    return shell(user, active="periods", crumb=crumb, body=body)


@router.post("/sources/sample")
def load_sample(request: Request, csrf: str = Form(""), user: User = CURRENT_USER) -> Response:
    """Copy the shipped example periods into this account.

    Copied rather than read in place, so a new account's first close runs over
    *its own* files and behaves exactly like one over a real bank statement —
    same ingest, same hashes, same re-derivation. A demo mode that read a shared
    directory would be a second code path, which is the thing this codebase most
    consistently refuses.
    """
    _check_csrf(request, csrf)
    destination = tenant_sources(user)
    destination.mkdir(parents=True, exist_ok=True)
    copied = []
    for period in (
        sorted(d for d in SAMPLE_ROOT.iterdir() if d.is_dir()) if SAMPLE_ROOT.exists() else []
    ):
        target = destination / period.name
        if target.exists():
            continue
        target.mkdir(parents=True)
        for source in period.iterdir():
            if source.is_file() and not source.name.startswith("labels"):
                shutil.copy2(source, target / source.name)
        copied.append(period.name)
    return RedirectResponse(
        f"/sources?loaded={','.join(copied)}" if copied else "/sources?loaded=none",
        status_code=303,
    )


@router.post("/sources/upload")
async def upload_period(
    request: Request,
    period: str = Form(...),
    csrf: str = Form(""),
    user: User = CURRENT_USER,
) -> Response:
    """Take one period's files.

    Filenames come from the loop, not from the upload: a source is accepted
    under the name the adapter expects, so a caller cannot write anywhere it
    likes by naming a file `../../something`. The period name is checked for the
    same reason.
    """
    _check_csrf(request, csrf)
    name = period.strip()
    if not name or not all(c.isalnum() or c in "-_ " for c in name):
        raise HTTPException(422, "A period name may hold letters, digits, spaces, - and _.")

    loop = service.loops()[0]
    expected = {src.filename for src in loop.sources}
    form = await request.form()
    target = tenant_sources(user) / name
    target.mkdir(parents=True, exist_ok=True)

    written = []
    for field, upload in form.multi_items():
        if field not in expected or not hasattr(upload, "filename") or not upload.filename:
            continue
        body = await upload.read()
        if len(body) > MAX_UPLOAD:
            raise HTTPException(
                422,
                f"{field} is {len(body) // 1024 // 1024} MB. The cap is "
                f"{MAX_UPLOAD // 1024 // 1024} MB — a statement is a text file, and "
                f"anything past this is a mistake or an attack.",
            )
        (target / field).write_bytes(body)
        written.append(field)

    if not written:
        target.rmdir() if not any(target.iterdir()) else None
        raise HTTPException(422, "No files were attached.")
    return RedirectResponse(f"/sources?uploaded={name}", status_code=303)


@router.get("/sources", response_class=HTMLResponse)
def sources_page(
    request: Request, loaded: str = "", uploaded: str = "", user: User = CURRENT_USER
) -> Response:
    """What this account has, and the two ways to get more.

    Adapters are declarative specs interpreted by a closed vocabulary of parse
    verbs — no generated code is executed (ADR-001) — so listing them is listing
    data, and a reader can see what a file is allowed to become before uploading
    one.
    """
    csrf = _csrf_field(request)
    root = tenant_sources(user)
    banner = ""
    if loaded == "none":
        banner = "<div class='alert alert-info'>Those periods are already loaded.</div>"
    elif loaded:
        banner = (
            f"<div class='alert alert-info'>Loaded {escape(loaded)}. Close one from Periods.</div>"
        )
    elif uploaded:
        banner = f"<div class='alert alert-info'>Uploaded {escape(uploaded)}.</div>"

    cards = []
    for lp in service.loops():
        sets = service.source_sets(lp.name, root)
        rows = "".join(
            f"<tr><td><b>{escape(s.name)}</b></td>"
            f"<td>{"<span class='badge badge-ok'>ready to close</span>" if s.complete else f"<span class='badge badge-declared'>missing {escape(chr(44).join(s.missing))}</span>"}</td>"
            f"<td class='cap'>{escape(', '.join(s.present)) or '&mdash;'}</td>"
            f"<td class='right'>{"<a class='btn btn-secondary' href='/periods'>Close it</a>" if s.complete else ''}</td></tr>"
            for s in sets
        )
        adapters = "".join(
            f"<tr><td><b>{escape(src.filename)}</b><span class='sub'>side "
            f"{escape(src.side)} &middot; {escape(src.role)}</span></td>"
            f"<td class='num'>{escape(src.spec_id)}</td></tr>"
            for src in lp.sources
        )
        inputs = "".join(
            f"<div class='field'><label for='{escape(src.filename)}'>{escape(src.filename)}"
            f" <span class='cap'>&mdash; {escape(src.side)}</span></label>"
            f"<input class='input' type='file' id='{escape(src.filename)}' "
            f"name='{escape(src.filename)}'></div>"
            for src in lp.sources
        )
        cards.append(
            f"<div class='panel' style='padding:1.4rem 1.5rem;margin-bottom:1.2rem'>"
            f"<h3 style='margin:0 0 .2rem'>{escape(lp.name)}</h3>"
            f"<p class='cap' style='margin:0 0 1.2rem'>{escape(lp.description)}</p>"
            f"<p class='sec' style='margin-bottom:.5rem'>Your periods</p>"
            + (
                f"<div class='tbl' style='margin-bottom:1.4rem'><table><tr><th>Period</th>"
                f"<th>State</th><th>Files</th><th></th></tr>{rows}</table></div>"
                if sets
                else _empty(
                    "inbox",
                    "No source files yet",
                    "Load the shipped example periods to see a close end to end, or "
                    "upload a bank statement and a gateway settlement of your own.",
                    f"<form method='post' action='/sources/sample' style='display:inline'>{csrf}"
                    f"<button class='btn btn-primary' type='submit'>{icon('download', 15)}"
                    f"Load sample data</button></form>",
                )
                + "<div style='height:1.4rem'></div>"
            )
            + f"<div class='grid' style='display:grid;gap:1.4rem;grid-template-columns:1fr'>"
            f"<div><p class='sec' style='margin-bottom:.5rem'>Upload a period</p>"
            f"<form method='post' action='/sources/upload' enctype='multipart/form-data'>{csrf}"
            f"<div class='field'><label for='period'>Period name</label>"
            f"<input class='input' id='period' name='period' placeholder='October 2026' required>"
            f"</div>{inputs}"
            f"<button class='btn btn-primary' type='submit'>{icon('arrow', 15)}Upload</button>"
            f"</form>"
            f"<p class='cap' style='margin-top:.8rem'>Files are stored under your account "
            f"only. A period is closeable once every file the loop expects has arrived &mdash; "
            f"a close over a half-arrived month would report a clean period over rows that "
            f"never came.</p></div>"
            f"<div><p class='sec' style='margin-bottom:.5rem'>Adapters</p>"
            f"<div class='tbl'><table><tr><th>File</th><th>Spec</th></tr>{adapters}</table></div>"
            f"<p class='cap' style='margin-top:.8rem'>Specs are data, not code. An unknown "
            f"parse verb is a spec error before anything runs, never an execution "
            f"(ADR-001).</p>"
            f"<form method='post' action='/sources/sample' style='margin-top:1rem'>{csrf}"
            f"<button class='btn btn-secondary' type='submit'>{icon('download', 15)}"
            f"Load sample data</button></form></div></div></div>"
        )

    body = (
        f"<div class='pagehead'><div class='lhs'><h1>Data sources</h1>"
        f"<p class='sub'>Two records of the same money, per period. Bring your own, or "
        f"load the shipped examples to see a close end to end.</p></div></div>"
        f"{banner}{''.join(cards)}"
    )
    return shell(user, active="sources", crumb="<b>Data sources</b>", body=body)


@router.get("/periods/{run_id}/pack", response_class=HTMLResponse)
def close_pack(request: Request, run_id: str, user: User = CURRENT_USER) -> Response:
    """The close pack — what a controller hands to an auditor.

    Everything in one place and everything from the record: the figures, who
    signed it and what was still open when they did, the source documents with
    the hashes that pin them, the journal that was written, the tail that was
    not closed, the authority it all ran under, and four steps to check the lot
    without us.

    Two things it is careful about.

    **It states what is missing.** The ledger is asserted in memory and never
    written as a beancount file, and `data/runs/` has no retention. A pack that
    listed its journal entries without saying that would imply a durability this
    build does not have.

    **It does not claim approval it does not have.** An unsigned close says so at
    the top, in the place a reader looks first.
    """
    runs_dir = tenant_runs(user, request)
    try:
        view = service.view(run_id, runs_dir, detail=service.Detail.FULL)
        bundle = service.audit(run_id, runs_dir, limit=10_000)
    except service.ServiceError as exc:
        raise HTTPException(404, str(exc)) from exc
    state = review.state(run_id, runs_dir)
    tiers = view.tiers

    # ---- the seal -------------------------------------------------------
    if state.signed_off:
        seal = (
            f"<div class='seal'><span class='ico'>{icon('check', 20, 2.6)}</span><div>"
            f"<b>Signed off by {escape(state.signed_off_by)}</b>"
            f"<span>{escape(state.signed_off_at[:19].replace('T', ' '))} UTC &middot; "
            f"{state.still_open} item(s) still open at signature"
            + (f" &middot; &ldquo;{escape(state.note)}&rdquo;" if state.note else "")
            + "</span></div></div>"
        )
    else:
        seal = (
            f"<div class='seal unsealed'><span class='ico'>{icon('alert', 20, 2.4)}</span><div>"
            f"<b>Not signed off</b><span>The engine finished this close; nobody has "
            f"approved it. {len(view.blocking_exceptions)} item(s) still need a human. "
            f"<a href='/periods/{escape(run_id)}'>Review it</a>.</span></div></div>"
        )

    # ---- figures --------------------------------------------------------
    figs = "".join(
        f"<div class='fig'><div class='k'>{escape(k)}</div><div class='v'>{v}</div>"
        f"<div class='n'>{escape(n)}</div></div>"
        for k, v, n in [
            (
                "Auto-matched",
                escape(tiers.rate),
                " ".join(f"{a}={b}" for a, b in sorted(tiers.by_match_tier.items())),
            ),
            (
                "Proof tiers",
                " ".join(f"{a}={b}" for a, b in sorted(tiers.by_proof_tier.items())),
                f"{tiers.declared} on a declared gap",
            ),
            (
                "Open items",
                str(len(view.exceptions)),
                f"{len(view.blocking_exceptions)} block sign-off",
            ),
            ("Postings", str(view.postings), "balanced" if not view.blocked else "BLOCKED"),
            ("Decisions", str(view.events), "hash-chained"),
        ]
    )

    # ---- sources: the evidence chain ------------------------------------
    def _strength(src: dict) -> str:
        if src["strength"] == "verified":
            return "<span class='badge badge-ok'>verified</span>"
        return f"<span class='badge badge-declared'>{escape(src['strength'])}</span>"

    sources = "".join(
        f"<tr><td><b>{escape(src['source'])}</b>"
        f"<span class='sub'>read by {escape(src['spec_id'])}</span></td>"
        f"<td class='num'>{escape(src['doc_hash'][:24])}&hellip;</td>"
        f"<td class='right num'>{src['rows_parsed']}/{src['rows_in_file']}</td>"
        f"<td>{_strength(src)}</td></tr>"
        for src in bundle.sources
    )
    gaps = "".join(
        f"<li>{escape(src['source'])}: {escape(src['gap'])}</li>"
        for src in bundle.sources
        if src.get("gap")
    )

    # ---- the journal ----------------------------------------------------
    entries = []
    for posting in bundle.postings:
        lines = "".join(
            f"<tr><td>{escape(line['role'])}</td>"
            f"<td class='right num'>{money(Decimal(line['amount']))}</td></tr>"
            for line in posting["postings"]
        )
        origin = posting.get("proof_id") or posting.get("exception_id") or "—"
        entries.append(
            f"<div class='entry'><div class='top'><b>{escape(posting['entry_date'])} "
            f"{escape(posting['narration'])}</b>"
            f"<span class='num'>{escape(origin)}</span></div>"
            f"<table>{lines}</table></div>"
        )

    export = service.journal(run_id, runs_dir)
    unposted_note = (
        f"<p class='lede' style='margin-top:1rem'><b>{len(export.unposted)} exception(s) "
        f"raised no entry</b> and are listed in the tail below. Money that never reached "
        f"the account is a receivable, not cash &mdash; booking it would put a figure in the "
        f"books the bank does not have.</p>"
        if export.unposted
        else ""
    )

    # ---- the tail -------------------------------------------------------
    def _taken(item) -> str:
        who = state.acknowledged.get(item.exception.exception_id)
        if not who:
            return "<span class='badge badge-mute'>open</span>"
        return f"<span class='badge badge-ok'>taken by {escape(who.split('@')[0])}</span>"

    tail_rows = "".join(
        f"<tr><td><b>{escape(item.exception.code)}</b> {escape(item.code_title)}</td>"
        f"<td class='right num'>{money(item.exception.amount)}</td>"
        f"<td>{escape(item.owner)}</td>"
        f"<td>{_taken(item)}</td></tr>"
        for item in view.exceptions
    )

    # ---- authority ------------------------------------------------------
    def _trusted(entry: dict) -> str:
        if entry["trusted"]:
            return "<span class='badge badge-ok'>trusted</span>"
        return "<span class='badge badge-mute'>unverified</span>"

    authority = "".join(
        f"<tr><td class='num'>{escape(a['bundle'])}</td>"
        f"<td>{escape(a['signed_by'] or '&mdash;')}</td>"
        f"<td class='num'>{escape((a['digest'] or '')[:16])}</td>"
        f"<td>{"<span class='badge badge-ok'>trusted</span>" if a['trusted'] else "<span class='badge badge-mute'>unverified</span>"}</td></tr>"
        for a in bundle.authority
    )

    how = "".join(f"<li>{escape(step)}</li>" for step in bundle.how_to_verify)

    body = f"""
<div class='pack'>
  <div class='pagehead noprint'><div class='lhs'>
    <h1>Close pack</h1>
    <p class='sub'>{escape(run_id)} &middot; {escape(view.loop)} &middot;
      {escape(" to ".join(bundle.period))}</p></div>
    <div class='rhs'>
      <a class='btn btn-secondary' href='/v1/runs/{escape(run_id)}/export'>
        {icon("download", 14)}Audit export (JSON)</a>
      <a class='btn btn-ghost' href='/periods/{escape(run_id)}/log'>
        {icon("log", 14)}Decision log</a></div></div>

  <div style='display:none' class='printonly'></div>
  {seal}

  <section style='margin-top:2rem'>
    <h2>What this close decided</h2>
    <div class='figs'>{figs}</div>
    <p class='lede'>Policy <span class='num'>{escape(bundle.policy_ref or "&mdash;")}</span>,
      approved by <b>{escape(bundle.policy_approved_by)}</b>. Vocabulary
      <span class='num'>{escape(bundle.taxonomy_ref)}</span>.
      Blocking recall is <b>absent</b> rather than zero &mdash; it is measured against
      labelled true pairs, and production has none.</p>
  </section>

  <section>
    <h2>Source documents</h2>
    <p class='lede'>The evidence this close rests on. Each hash pins the exact bytes;
      re-ingesting the same files with the named spec reproduces every record id.</p>
    <div class='tbl'><table><tr><th>Source</th><th>sha256</th>
      <th class='right'>Rows</th><th>Intake</th></tr>{sources}</table></div>
    {f"<p class='lede' style='margin-top:.7rem'><b>Declared gaps:</b></p><ul class='cap'>{gaps}</ul>" if gaps else ""}
  </section>

  <section>
    <h2>Journal &mdash; {len(bundle.postings)} entries</h2>
    <p class='lede'>Double-entry, and the balance assertion held against the bank's own
      closing figure. <b>This is the file you post into your books</b> &mdash; it was
      computed and thrown away until 2026-08-26, which meant a controller could see the
      books tie and still had to hand-type every line.</p>
    <p class='noprint' style='margin:0 0 1rem'>
      <a class='btn btn-secondary' href='/v1/runs/{escape(run_id)}/journal.csv'>
        {icon("download", 14)}journal.csv</a>
      <a class='btn btn-ghost' href='/v1/runs/{escape(run_id)}/journal.beancount'>
        {icon("download", 14)}beancount</a></p>
    {"".join(entries)}
    {unposted_note}
  </section>

  <section>
    <h2>The tail &mdash; {len(view.exceptions)} items</h2>
    <p class='lede'>What this close could not prove, each named, priced and routed.
      An item taken by a person is accounted for; it is not resolved.</p>
    <div class='tbl'><table><tr><th>Exception</th><th class='right'>Amount</th>
      <th>Owner</th><th>Status</th></tr>{tail_rows}</table></div>
  </section>

  <section>
    <h2>Authority</h2>
    <p class='lede'>Which policy, vocabulary and rules governed this close, and who put
      their name to them. A digest proves what ran; a signature proves who approved it.</p>
    <div class='tbl'><table><tr><th>Bundle</th><th>Signed by</th><th>Digest</th>
      <th>State</th></tr>{authority}</table></div>
  </section>

  <section>
    <h2>Check this without us</h2>
    <ol class='steps-num'>{how}</ol>
    <p class='lede' style='margin-top:1rem'>The decision log's own chain
      {"<b>holds</b>" if bundle.chain.holds else "<b>DOES NOT HOLD</b>"}
      over {bundle.chain.events} events. {escape(bundle.chain.caveat)}</p>
  </section>

  <p class='cap noprint'>Contract {escape(bundle.contract_version)} &middot;
    generated from the record, not from the run that produced it.</p>
</div>"""
    crumb = (
        f"<a href='/periods'>Periods</a><span>/</span>"
        f"<a href='/periods/{escape(run_id)}'>{escape(run_id)}</a><span>/</span><b>Close pack</b>"
    )
    return shell(user, active="periods", crumb=crumb, body=body)


# --------------------------------------------------------------------------
# one item — where the model proposes, the checker checks, and a human decides
# --------------------------------------------------------------------------


def _item_or_404(run_id: str, exception_id: str, runs_dir: Path):
    for item in service.view(run_id, runs_dir).exceptions:
        if item.exception.exception_id == exception_id:
            return item
    raise HTTPException(404, f"no item {exception_id!r} in {run_id!r}")


@router.get("/periods/{run_id}/items/{exception_id}", response_class=HTMLResponse)
def item_page(
    request: Request, run_id: str, exception_id: str, user: User = CURRENT_USER
) -> Response:
    """One exception, everything known about it, and the three things a human
    can do: read the evidence, ask the model for a reading, and take the item.

    This is the screen the thesis lives on. The model proposes, a deterministic
    checker says whether the proposal is even admissible, and nothing moves
    until a named person accepts it — so all three are on one page, in that
    order, with the model's output visibly inert until the last step.
    """
    runs_dir = tenant_runs(user, request)
    item = _item_or_404(run_id, exception_id, runs_dir)
    exc = item.exception
    state = review.state(run_id, runs_dir)
    csrf = _csrf_field(request)

    taken = state.acknowledged.get(exception_id)
    accepted = state.accepted.get(exception_id)
    derived = not classify_mod.reclassifiable(exc)

    evidence = "".join(f"<li>{escape(line)}</li>" for line in exc.evidence) or (
        "<li class='cap'>no evidence lines</li>"
    )
    alternatives = ""
    if exc.alternatives:
        alternatives = (
            "<p class='sec' style='margin:1.4rem 0 .5rem'>Competing subsets</p>"
            "<div class='tbl'><table><tr><th>Subset</th><th class='right'>Rows</th></tr>"
            + "".join(
                f"<tr><td class='num'>{escape(', '.join(sorted(sub)[:3]))}&hellip;</td>"
                f"<td class='right num'>{len(sub)}</td></tr>"
                for sub in exc.alternatives
            )
            + "</table></div><p class='cap'>Two valid answers exist. Picking either "
            "would be a confident wrong answer, which is why the engine picked "
            "neither.</p>"
        )

    # --- the model panel ---------------------------------------------------
    proposal = request.query_params.get("proposal", "")
    verdict_text = request.query_params.get("verdict", "")
    model_name = request.query_params.get("model", "")
    if derived:
        ai = (
            f"<div class='note'>The engine <b>derived</b> this label &mdash; "
            f"<code>{escape(exc.code)}</code> at "
            f"<code>{escape(exc.code_provenance.value)}</code>. A model proposal is "
            f"<code>P2</code> at best and may not overwrite a higher proof tier, so "
            f"this item is never sent to a model at all. Refusing after the call "
            f"would still have spent it, and would invite the argument that the "
            f"model would have been right.</div>"
        )
    elif proposal:
        ai = (
            f"<div class='panel' style='padding:1.1rem 1.2rem'>"
            f"<div style='display:flex;justify-content:space-between;gap:1rem;align-items:baseline'>"
            f"<b>Proposed: <code>{escape(proposal)}</code></b>"
            f"<span class='badge badge-mute'>{escape(model_name or 'model')}</span></div>"
            f"<p class='cap' style='margin:.5rem 0 0'>{escape(verdict_text)}</p>"
            f"<form method='post' action='/periods/{escape(run_id)}/items/{escape(exception_id)}/accept' "
            f"style='margin-top:.9rem'>{csrf}"
            f"<input type='hidden' name='code' value='{escape(proposal)}'>"
            f"<input type='hidden' name='model' value='{escape(model_name)}'>"
            f"<input type='hidden' name='hypothesis' value='{escape(verdict_text)}'>"
            f"<button class='btn btn-primary' type='submit'>Accept as "
            f"{escape(proposal)}</button>"
            f"<a class='btn btn-ghost' href='/periods/{escape(run_id)}/items/{escape(exception_id)}'>"
            f"Discard</a></form>"
            f"<p class='cap' style='margin:.8rem 0 0'>Nothing has changed yet. A proposal "
            f"is inert until a named human accepts it, and accepting records who did.</p>"
            f"</div>"
        )
    else:
        configured = bool(os.environ.get("DEEPSEEK_API_KEY"))
        ai = (
            f"<form method='post' action='/periods/{escape(run_id)}/items/{escape(exception_id)}/classify'>"
            f"{csrf}<button class='btn btn-secondary' type='submit'>{icon('layers', 15)}"
            f"Ask the model for a reading</button></form>"
            f"<p class='cap' style='margin-top:.7rem'>One call, one exception. The model sees "
            f"the amounts, dates and keys of the records this item names and the code menu &mdash; "
            f"nothing else, and it cannot write anything. Its answer goes through the same "
            f"checker the live triage path uses before you are shown it.</p>"
            if configured
            else "<div class='note note-warn'><b>No model is configured.</b> Set "
            "<code>DEEPSEEK_API_KEY</code> to enable classification. Reported absent "
            "rather than as a zero &mdash; an unmeasured thing shown as a number is a "
            "claim nobody earned.</div>"
        )

    ack = (
        f"<div class='note'><b>Taken by {escape(taken)}.</b>"
        + (
            f" &ldquo;{escape(state.notes[exception_id])}&rdquo;"
            if exception_id in state.notes
            else ""
        )
        + "</div>"
        if taken
        else (
            f"<form method='post' action='/periods/{escape(run_id)}/items/{escape(exception_id)}/acknowledge'>"
            f"{csrf}<div class='field'><label for='note'>Note (optional)</label>"
            f"<input class='input' id='note' name='note' placeholder='what you found, or what you are waiting on'></div>"
            f"<button class='btn btn-primary' type='submit'>{icon('check', 15)}"
            f"Take this item</button></form>"
            f"<p class='cap' style='margin-top:.7rem'>Taking an item does not resolve it. "
            f"No posting moves and the money is still unreconciled &mdash; what changes is that "
            f"you are accountable for it, which is the whole content of <code>P2 ATTESTED</code> "
            f"and the most this build can honestly offer. Sign-off refuses while any blocking "
            f"item is untaken.</p>"
        )
    )

    accepted_note = (
        f"<div class='note'><b>{escape(state.accepted_by.get(exception_id, 'someone'))}</b> "
        f"moved this from <code>{escape(state.accepted_from.get(exception_id, '?'))}</code> "
        f"to <code>{escape(accepted)}</code>. The engine's own label is unchanged in the "
        f"decision log &mdash; a reclassification is a second record, not an edit.</div>"
        if accepted
        else ""
    )

    body = (
        f"<div class='pagehead'><div class='lhs'>"
        f"<h1>{escape(exc.code)} &middot; {escape(item.code_title)}</h1>"
        f"<p class='sub'>{money(exc.amount)} &middot; {item.age_days}d old &middot; "
        f"break <span class='num'>{escape(exc.fingerprint[:12] or '&mdash;')}</span> &middot; "
        f"owner {escape(item.owner)}</p></div>"
        f"<div class='rhs'><span class='badge {'badge-ok' if taken else 'badge-declared'}'>"
        f"{'taken' if taken else 'needs a human'}</span></div></div>"
        f"{accepted_note}"
        f"<div class='panel' style='padding:1.3rem 1.4rem;margin-bottom:1.2rem'>"
        f"<p class='sec' style='margin-bottom:.5rem'>What the engine says</p>"
        f"<p style='margin:0 0 .8rem'>{escape(exc.hypothesis or 'No hypothesis. The engine has facts here, not an explanation — that is what E14 means.')}</p>"
        f"<ul class='cap' style='margin:0'>{evidence}</ul>"
        f"{alternatives}"
        f"<p class='sec' style='margin:1.4rem 0 .5rem'>Records</p>"
        f"<p class='cap num' style='margin:0'>{escape(', '.join(exc.record_ids[:10]))}"
        f"{'&hellip;' if len(exc.record_ids) > 10 else ''}</p></div>"
        f"<div class='panel' style='padding:1.3rem 1.4rem;margin-bottom:1.2rem'>"
        f"<p class='sec' style='margin-bottom:.5rem'>Ask the model</p>{ai}</div>"
        f"<div class='panel' style='padding:1.3rem 1.4rem'>"
        f"<p class='sec' style='margin-bottom:.5rem'>Your decision</p>{ack}</div>"
    )
    crumb = (
        f"<a href='/periods'>Periods</a><span>/</span>"
        f"<a href='/periods/{escape(run_id)}'>{escape(run_id)}</a><span>/</span>"
        f"<b>{escape(exception_id)}</b>"
    )
    return shell(user, active="worklist", crumb=crumb, body=body)


@router.post("/periods/{run_id}/items/{exception_id}/classify")
def classify_item(
    request: Request,
    run_id: str,
    exception_id: str,
    csrf: str = Form(""),
    user: User = CURRENT_USER,
) -> Response:
    """One model call, then the checker, then back to the page.

    The proposal is carried in the URL rather than stored: it has not been
    accepted, so there is nothing to persist. A proposal saved somewhere would
    start looking like a decision.
    """
    _check_csrf(request, csrf)
    runs_dir = tenant_runs(user, request)
    item = _item_or_404(run_id, exception_id, runs_dir)
    view = service.view(run_id, runs_dir)
    loop = looplib.get(view.loop)

    try:
        from ..triage.client import ModelEdge

        edge = ModelEdge()
    except Exception as exc:
        raise HTTPException(422, f"No model is configured: {exc}") from exc

    sources = loop.load(
        tenant_sources(user)
        / (service.source_set_of(run_id, runs_dir, root=tenant_sources(user)) or "")
    )
    records = {rec.record_id: rec for _, rec in [*sources.anchor_rows, *sources.group_rows]}
    results = classify_mod.classify(
        exceptions=[item.exception], taxonomy=loop.taxonomy(), records=records, edge=edge
    )
    result = results[0]
    verdict = "; ".join(result.refusals) if result.refusals else (result.hypothesis or "")
    query = urlencode({"proposal": result.code, "verdict": verdict[:400], "model": edge.model})
    return RedirectResponse(f"/periods/{run_id}/items/{exception_id}?{query}", status_code=303)


@router.post("/periods/{run_id}/items/{exception_id}/accept")
def accept_item(
    request: Request,
    run_id: str,
    exception_id: str,
    code: str = Form(...),
    hypothesis: str = Form(""),
    model: str = Form(""),
    csrf: str = Form(""),
    user: User = CURRENT_USER,
) -> Response:
    _check_csrf(request, csrf)
    runs_dir = tenant_runs(user, request)
    item = _item_or_404(run_id, exception_id, runs_dir)
    try:
        review.accept_classification(
            run_id,
            runs_dir,
            exception=item.exception,
            to_code=code,
            by=user.email,
            hypothesis=hypothesis,
            model=model,
        )
    except review.ReviewError as exc:
        raise HTTPException(422, str(exc)) from exc
    return RedirectResponse(f"/periods/{run_id}/items/{exception_id}", status_code=303)


@router.post("/periods/{run_id}/items/{exception_id}/acknowledge")
def acknowledge_item(
    request: Request,
    run_id: str,
    exception_id: str,
    note: str = Form(""),
    csrf: str = Form(""),
    user: User = CURRENT_USER,
) -> Response:
    _check_csrf(request, csrf)
    runs_dir = tenant_runs(user, request)
    item = _item_or_404(run_id, exception_id, runs_dir)
    try:
        review.acknowledge(run_id, runs_dir, exception=item.exception, by=user.email, note=note)
    except review.ReviewError as exc:
        raise HTTPException(422, str(exc)) from exc
    return RedirectResponse(f"/periods/{run_id}", status_code=303)


@router.post("/periods/{run_id}/signoff")
def sign_off_close(
    request: Request,
    run_id: str,
    note: str = Form(""),
    csrf: str = Form(""),
    user: User = CURRENT_USER,
) -> Response:
    """The terminal human decision, or a refusal with the reason."""
    _check_csrf(request, csrf)
    runs_dir = tenant_runs(user, request)
    view = service.view(run_id, runs_dir)
    try:
        review.sign_off(
            run_id,
            runs_dir,
            exceptions=[e.exception for e in view.exceptions],
            outcome_digest=run_id,
            by=user.email,
            note=note,
            books_blocked=list(view.blocked),
        )
    except review.ReviewError as exc:
        raise HTTPException(422, str(exc)) from exc
    return RedirectResponse(f"/periods/{run_id}", status_code=303)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, user: User = CURRENT_USER) -> Response:
    """The account, and the authority in force — which is not editable here.

    Deliberately: policy, tolerances, the taxonomy and the rule store come from
    signed bundles, and a screen that could change them would be the caller
    supplying its own permission. So this page *shows* the authority and names
    who signed it, and offers no way to alter it.
    """
    identity = auth.build_identity()
    authority = service.authority("settlement_3way")
    codes = "".join(
        f"<tr><td><b>{escape(c['code'])}</b> {escape(c['title'])}</td>"
        f"<td><span class='badge {'badge-ok' if c['status'] == 'promoted' else 'badge-declared'}'>"
        f"{escape(c['status'])}</span></td><td>{escape(c['owner'])}</td>"
        f"<td>{'yes' if c['may_direct_a_posting'] else 'no'}</td></tr>"
        for c in authority.codes
    )
    bundles = "".join(
        f"<tr><td class='num'>{escape(b['bundle'])}</td><td>{escape(b['signed_by'] or '&mdash;')}</td>"
        f"<td class='num'>{escape((b['digest'] or '')[:16])}</td>"
        f"<td>{"<span class='badge badge-ok'>trusted</span>" if b['trusted'] else "<span class='badge badge-mute'>unverified</span>"}</td></tr>"
        for b in authority.bundles
    )
    rules = (
        "".join(
            f"<tr><td class='num'>{escape(r['ref'])}</td><td>{escape(', '.join(r['then']))}</td>"
            f"<td>{escape(r['approved_by'] or '&mdash;')}</td>"
            f"<td class='num'>{escape(r['policy_ref'] or '&mdash;')}</td></tr>"
            for r in authority.rules
        )
        or "<tr><td colspan='4' class='cap'>No promoted rules.</td></tr>"
    )

    body = (
        f"<div class='pagehead'><div class='lhs'><h1>Settings</h1>"
        f"<p class='sub'>Your account, and the authority every close runs under.</p></div></div>"
        f"<div class='grid' style='display:grid;gap:1.2rem;grid-template-columns:1fr'>"
        f"<div class='panel' style='padding:1.3rem 1.4rem'>"
        f"<p class='sec'>Account</p><div class='kv'>"
        f"<div class='row'><span class='k'>Email</span><span class='v'>{escape(user.email)}</span></div>"
        f"<div class='row'><span class='k'>Account id</span><span class='v'>{escape(user.user_id)}</span></div>"
        f"<div class='row'><span class='k'>Credential store</span><span class='v'>"
        f"{escape(identity.name)}{' (managed)' if identity.managed else ' — development only'}</span></div>"
        f"<div class='row'><span class='k'>Records</span><span class='v num'>"
        f"{len(service.stored_runs(tenant_runs(user, request)))} close(s), visible only to this account</span></div>"
        f"</div></div>"
        f"<div class='panel' style='padding:1.3rem 1.4rem'>"
        f"<p class='sec'>Authority &mdash; read only</p>"
        f"<p class='cap' style='margin:0 0 1rem'>Policy, the taxonomy and the promoted rules come "
        f"from signed bundles supplied out of band. There is no control here that could widen a "
        f"tolerance or add a rule, and that is the point.</p>"
        f"<div class='kv' style='margin-bottom:1.2rem'>"
        f"<div class='row'><span class='k'>Policy</span><span class='v num'>{escape(authority.policy.ref)}</span></div>"
        f"<div class='row'><span class='k'>Approved by</span><span class='v'>{escape(authority.policy.approved_by)}</span></div>"
        f"<div class='row'><span class='k'>Tolerance ceiling</span><span class='v num'>{money(authority.policy.tolerance_ceiling)}</span></div>"
        f"<div class='row'><span class='k'>Taxonomy</span><span class='v num'>{escape(authority.taxonomy_ref)}</span></div>"
        f"</div>"
        f"<p class='sec' style='margin-bottom:.5rem'>Signed bundles</p>"
        f"<div class='tbl' style='margin-bottom:1.2rem'><table><tr><th>Bundle</th><th>Signed by</th>"
        f"<th>Digest</th><th>State</th></tr>{bundles}</table></div>"
        f"<p class='sec' style='margin-bottom:.5rem'>Promoted rules</p>"
        f"<div class='tbl' style='margin-bottom:1.2rem'><table><tr><th>Rule</th><th>Actions</th>"
        f"<th>Approved by</th><th>Under policy</th></tr>{rules}</table></div>"
        f"<p class='sec' style='margin-bottom:.5rem'>Exception vocabulary</p>"
        f"<div class='tbl'><table><tr><th>Code</th><th>Status</th><th>Owner</th>"
        f"<th>May direct a posting</th></tr>{codes}</table></div></div></div>"
    )
    return shell(user, active="settings", crumb="<b>Settings</b>", body=body)
