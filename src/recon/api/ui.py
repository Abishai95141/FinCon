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

from html import escape
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import loop as looplib
from .. import service
from . import auth
from .auth import AuthError, User
from .theme import document, icon, money, wordmark

router = APIRouter(include_in_schema=False)

NAV = (
    ("periods", "/periods", "Periods"),
    ("worklist", "/periods", "Worklist"),
    ("verify", "/verify", "Verify"),
    ("sources", "/sources", "Data sources"),
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
        f"<main class='stage'><div class='crumb'>{crumb}</div>{body}</main></div>"
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


def _state_badge(view: service.CloseView) -> str:
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
        for source_set in service.source_sets(lp.name):
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
        run_rows = "".join(_run_row(rid, views[rid]) for rid in recorded)
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


def _run_row(run_id: str, view: service.CloseView | None) -> str:
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
        f"<td>{_state_badge(view)}</td></tr>"
    )


@router.post("/periods/close")
def do_close(
    request: Request,
    loop: str = Form(...),
    source_set: str = Form(...),
    csrf: str = Form(""),
    user: User = CURRENT_USER,
) -> Response:
    """Run the close, then send the controller to the record of it.

    A redirect rather than a rendered response: the page they land on is built
    from the decision log, and is the same page they get tomorrow. There is no
    "just after the run" view showing something the record does not contain.
    """
    _check_csrf(request, csrf)
    try:
        view = service.close(loop, source_set, runs_dir=tenant_runs(user, request))
    except (service.ServiceError, looplib.LoopError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RedirectResponse(f"/periods/{view.run_id}", status_code=303)


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

    metrics = (
        f"<div class='metrics'>"
        f"{_metric('Auto-matched', escape(tiers.rate), f'by tier {by_match}')}"
        f"{_metric('Proof tiers', by_proof, f'{tiers.declared} resting on a declared gap')}"
        f"{_metric('Every input disposed', 'yes' if view.complete else 'NO', 'matched, excepted, or out of scope with a reason', ok=view.complete)}"
        f"{_metric('Blocking recall', '<span style="color:var(--warning)">absent</span>', 'measured against labelled pairs; production has none')}"
        f"{_metric('Books', 'balanced' if not view.blocked else 'BLOCKED', '; '.join(view.blocked) or 'balance assertion held', ok=not view.blocked)}"
        f"{_metric('Awaiting sign-off', str(len(view.blocking_exceptions)), 'exceptions a human must clear')}"
        f"</div>"
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

    rows = []
    for item in view.exceptions:
        exc = item.exception
        note = (
            f" <span class='badge badge-declared'>{escape(item.authority_note)}</span>"
            if item.authority_note
            else ""
        )
        why = exc.hypothesis or "no hypothesis — the engine has facts, not an explanation"
        evidence = "".join(f"<li>{escape(line)}</li>" for line in exc.evidence) or (
            "<li class='cap'>no evidence lines</li>"
        )
        rows.append(
            f"<tr><td class='right num'>{item.rank}</td>"
            f"<td><b>{escape(exc.code)}</b> {escape(item.code_title)}{note}"
            f"<span class='sub'>{escape(why)}</span></td>"
            f"<td class='right num'>{money(exc.amount)}</td>"
            f"<td class='right num'>{item.age_days}d</td>"
            f"<td class='num'>{escape(exc.fingerprint[:8] or '—')}</td>"
            f"<td>{escape(item.owner)}</td>"
            f"<td><details><summary>evidence</summary>"
            f"<ul class='cap' style='margin:.2rem 0'>{evidence}</ul>"
            f"<p class='cap num'>{escape(', '.join(exc.record_ids[:6]))}</p></details></td></tr>"
        )
    worklist = (
        f"<div class='tbl'><table><tr><th class='right'>#</th><th>Exception</th>"
        f"<th class='right'>Amount</th><th class='right'>Age</th><th>Break</th>"
        f"<th>Owner</th><th>Detail</th></tr>{''.join(rows)}</table></div>"
        if rows
        else "<div class='panel' style='padding:1.2rem'><p class='cap' style='margin:0'>"
        "No exceptions. Every input was matched or declared out of scope.</p></div>"
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

    reverify = "".join(
        f"<form method='post' action='/periods/{escape(run_id)}/reverify' "
        f"style='display:inline'>{csrf}"
        f"<input type='hidden' name='source_set' value='{escape(s.name)}'>"
        f"<button class='btn btn-secondary' type='submit'>{icon('verify', 14)}"
        f"Re-derive against {escape(s.name)}</button></form> "
        for s in service.source_sets(view.loop)
        if s.complete
    )

    body = (
        f"<h1>{escape(view.run_id)}</h1>"
        f"<p class='cap' style='margin:0 0 1.3rem'>{escape(view.loop)} &middot; policy "
        f"<span class='num'>{escape(view.policy_ref or '—')}</span> &middot; {view.events} events "
        f"&middot; rebuilt from the decision log</p>"
        f"<div class='stages'>{stages}</div>{problems}{metrics}"
        f"<p class='sec'>Check this close</p>"
        f"<div class='panel' style='padding:1.2rem 1.3rem;margin-bottom:1.6rem'>"
        f"<p class='cap' style='margin:0 0 .8rem'>Re-ingests the source files, checks each "
        f"sha256 against the hash this record pinned, and re-derives every proof in the log. "
        f"Nothing is read from the process that ran the close.</p>"
        f"<div style='display:flex;gap:.5rem;flex-wrap:wrap;align-items:center'>{reverify}"
        f"<a class='btn btn-ghost' href='/v1/runs/{escape(run_id)}/export'>{icon('download', 14)}"
        f"Audit export</a>"
        f"<a class='btn btn-ghost' href='/v1/runs/{escape(run_id)}/events'>{icon('log', 14)}"
        f"Decision log</a></div></div>"
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
        f"<span>/</span>{_state_badge(view)}"
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


def _metric(key: str, value: str, note: str, *, ok: bool | None = None) -> str:
    colour = ""
    if ok is True:
        colour = "color:var(--success)"
    elif ok is False:
        colour = "color:var(--error)"
    return (
        f"<div class='panel solid metric'><div class='k'>{escape(key)}</div>"
        f"<div class='v' style='{colour}'>{value}</div>"
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
        report = service.reverify(run_id, source_set, runs_dir=tenant_runs(user, request))
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
    verdict = "holds" if report.holds else "DOES NOT HOLD"
    trailer = ""
    if refuted:
        trailer += f"<p class='sec' style='margin-top:1.6rem'>Refuted</p><div class='alert'><ul style='margin:0'>{refuted}</ul></div>"
    if report.missing_proofs:
        trailer += (
            f"<div class='alert alert-info'>{len(report.missing_proofs)} match(es) have no "
            f"proof in the record, so there was nothing to re-derive. This does not pass.</div>"
        )
    if not report.sources_match:
        trailer += (
            "<div class='alert alert-info'>The files on disk are not the bytes this close ran "
            "on, so a refutation here says nothing about the close. Point it at the right "
            "period.</div>"
        )

    body = (
        f"<h1>Re-derivation</h1>"
        f"<p class='cap' style='margin:0 0 1.3rem'>Against the files in "
        f"<span class='num'>{escape(source_set)}</span>, under "
        f"{escape(report.policy_ref)}. Nothing was read from the process that ran the close.</p>"
        f"<div class='metrics'>"
        f"{_metric('Verdict', verdict, 'sources, arithmetic and evidence must all pass', ok=report.holds)}"
        f"{_metric('Proofs re-derived', f'{report.proven}/{report.proofs_checked}', 'recomputed from freshly ingested records')}"
        f"{_metric('Records ingested', str(report.records_ingested), report.records_digest)}"
        f"</div>"
        f"<p class='sec'>Source documents</p>"
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


@router.get("/sources", response_class=HTMLResponse)
@router.get("/settings", response_class=HTMLResponse)
def not_built(request: Request, user: User = CURRENT_USER) -> Response:
    """Two rail destinations that lead nowhere yet, and say so.

    A nav item that silently does nothing is worse than one that explains what
    it is waiting for. Uploads need the S3 storage step; settings needs
    something to configure that is not authority — and authority is deliberately
    not configurable from here.
    """
    body = (
        "<h1>Not built yet</h1>"
        "<p class='body-lg' style='color:var(--n600);max-width:46rem'>This destination is "
        "in the plan and is not implemented. Source uploads arrive with tenant-scoped S3 "
        "storage; settings arrives when there is something to configure that is not "
        "authority &mdash; policy, tolerances and rules come from signed bundles and are "
        "deliberately not editable from a screen.</p>"
        "<p style='margin-top:1.4rem'><a class='btn btn-primary' href='/periods'>"
        "Back to periods</a></p>"
    )
    return shell(user, active="sources", crumb="<b>Not built</b>", body=body)
