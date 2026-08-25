"""The screens — server-rendered, so a controller needs a browser and nothing else.

P14's gate is one sentence: *a controller completes one close through the UI
without a terminal.* Three pages meet it — pick a period, run it, work the
result — and each is a thin render over `recon.service`. No template engine, no
build step, no JavaScript: a page that needs `npm install` before a controller
can see a number is a page that fails the gate on a fresh machine.

The design decisions that are not cosmetic:

**Nothing is shown that the record cannot say.** Every page renders a
`CloseView`, which is rebuilt from the decision log. If a fact is on screen, it
is in the file an auditor gets.

**Blocking recall is rendered absent, not zero.** It is measured against
labelled true pairs and production has none. A `0.0%` there would look like a
measurement, and looking like a measurement is worse than admitting there is
none.

**A rate never appears without its decomposition**, and the tier split sits
beside it. `90%` alone is the gameable number this whole project exists to stop
quoting.

**Re-derive is a button.** The strongest thing this system can say is "check me"
— so the close page has a control that re-ingests the source files and
re-derives every proof in the record, and prints what it finds. Nothing is
persuasive about a claim that takes a terminal to test.
"""

from __future__ import annotations

from html import escape

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import service

router = APIRouter(include_in_schema=False)

STYLE = """
:root {
  color-scheme: light dark;
  --ink: #16181d; --dim: #5b6270; --line: #dfe1e6; --bg: #fbfbfc;
  --card: #ffffff; --good: #17683a; --warn: #8a5a00; --bad: #a3231f;
  --accent: #24457a;
}
@media (prefers-color-scheme: dark) {
  :root { --ink:#e8e9ec; --dim:#9aa1ad; --line:#2c3038; --bg:#14161a;
          --card:#1b1e24; --good:#5fd08a; --warn:#e2b25c; --bad:#f08a84;
          --accent:#8fb0e8; }
}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.55
  ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 66rem; margin: 0 auto; padding: 2rem 1.25rem 5rem; }
h1 { font-size:1.5rem; margin:0 0 .2rem; letter-spacing:-.01em; }
h2 { font-size:1.05rem; margin:2.2rem 0 .7rem; letter-spacing:.02em;
     text-transform:uppercase; color:var(--dim); font-weight:600; }
a { color:var(--accent); }
.sub { color:var(--dim); margin:0 0 1.6rem; }
.card { background:var(--card); border:1px solid var(--line); border-radius:8px;
        padding:1rem 1.1rem; margin-bottom:.7rem; }
table { border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; }
th,td { text-align:left; padding:.45rem .6rem; border-bottom:1px solid var(--line);
        vertical-align:top; }
th { color:var(--dim); font-weight:600; font-size:.8rem; text-transform:uppercase;
     letter-spacing:.04em; }
td.num, th.num { text-align:right; }
.wrap { overflow-x:auto; }
code, .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
              font-size:.86em; }
.pill { display:inline-block; padding:.08rem .45rem; border-radius:999px;
        font-size:.75rem; border:1px solid var(--line); color:var(--dim); }
.good { color:var(--good); } .warn { color:var(--warn); } .bad { color:var(--bad); }
.grid { display:grid; gap:.7rem; grid-template-columns:repeat(auto-fit,minmax(11rem,1fr)); }
.stat { background:var(--card); border:1px solid var(--line); border-radius:8px;
        padding:.75rem .9rem; }
.stat .k { color:var(--dim); font-size:.75rem; text-transform:uppercase;
           letter-spacing:.04em; }
.stat .v { font-size:1.35rem; font-variant-numeric:tabular-nums; margin-top:.15rem; }
.stat .n { color:var(--dim); font-size:.78rem; }
button { font:inherit; padding:.4rem .8rem; border-radius:6px; cursor:pointer;
         border:1px solid var(--accent); background:var(--accent); color:#fff; }
button.ghost { background:transparent; color:var(--accent); }
button:disabled { opacity:.45; cursor:not-allowed; border-color:var(--line);
                  background:transparent; color:var(--dim); }
details { margin-top:.4rem; }
summary { cursor:pointer; color:var(--accent); font-size:.85rem; }
pre { background:var(--bg); border:1px solid var(--line); border-radius:6px;
      padding:.6rem .7rem; overflow-x:auto; font-size:.8rem; margin:.5rem 0 0; }
form { display:inline; }
.note { color:var(--dim); font-size:.85rem; }
nav { border-bottom:1px solid var(--line); padding:.7rem 1.25rem; font-size:.9rem; }
nav .brand { font-weight:700; letter-spacing:-.01em; }
"""


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(title)}</title><style>{STYLE}</style></head><body>"
        f"<nav><span class='brand'>recon</span> &nbsp;<a href='/ui'>closes</a>"
        f" &nbsp;<a href='/docs'>api</a> &nbsp;<a href='/v1/contracts'>contracts</a></nav>"
        f"<main>{body}</main></body></html>"
    )


def _verdict(ok: bool, yes: str, no: str) -> str:
    return f"<span class='{'good' if ok else 'bad'}'>{escape(yes if ok else no)}</span>"


@router.get("/ui", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """Pick a period. Everything a controller needs before a close exists."""
    parts: list[str] = [
        "<h1>Close the books</h1>",
        "<p class='sub'>Pick a period whose source files have arrived. "
        "Everything below is read from disk — no close has been run yet.</p>",
    ]
    for lp in service.loops():
        rules = ", ".join(lp.promoted_rules) or "none promoted"
        parts.append(
            f"<div class='card'><strong>{escape(lp.name)}</strong> "
            f"<span class='pill'>{escape(lp.policy_ref)}</span> "
            f"<span class='pill'>{escape(lp.taxonomy_ref)}</span>"
            f"<p class='note'>{escape(lp.description)}<br>"
            f"period {lp.period_start}&ndash;{lp.period_end} · "
            f"strategies: {escape(' → '.join(lp.strategies))} · "
            f"rules in force: {escape(rules)}</p>"
        )
        rows = []
        for s in service.source_sets(lp.name):
            if s.complete:
                action = (
                    f"<form method='post' action='/ui/close'>"
                    f"<input type='hidden' name='loop' value='{escape(lp.name)}'>"
                    f"<input type='hidden' name='source_set' value='{escape(s.name)}'>"
                    f"<button type='submit'>Close {escape(s.name)}</button></form>"
                )
                state = "<span class='good'>all sources present</span>"
            else:
                # Named, not counted, and the button is disabled rather than
                # missing: "October is short the settlement file" is the answer
                # a controller needs, and a period that silently vanished from
                # the list would answer "where is October?" with nothing.
                action = "<button disabled>Cannot close</button>"
                state = f"<span class='warn'>missing {escape(', '.join(s.missing))}</span>"
            rows.append(
                f"<tr><td class='mono'>{escape(s.name)}</td><td>{state}</td>"
                f"<td class='num'>{action}</td></tr>"
            )
        parts.append(
            "<div class='wrap'><table><tr><th>period</th><th>sources</th>"
            "<th class='num'>action</th></tr>" + "".join(rows) + "</table></div></div>"
        )

    runs = service.stored_runs()
    parts.append("<h2>Recorded closes</h2>")
    if runs:
        parts.append(
            "<div class='card'>"
            + " ".join(
                f"<a class='mono' href='/ui/runs/{escape(r)}'>{escape(r)}</a> " for r in runs
            )
            + "</div>"
        )
    else:
        parts.append("<div class='card note'>None yet.</div>")
    return _page("recon — close the books", "".join(parts))


@router.post("/ui/close")
def do_close(loop: str = Form(...), source_set: str = Form(...)) -> RedirectResponse:
    """Run the close, then send the controller to the record of it.

    A redirect rather than a rendered response on purpose: the page they land on
    is the one built from the decision log, which is the same page they get
    tomorrow. There is no "just after the run" view showing something the record
    does not contain.
    """
    try:
        view = service.close(loop, source_set)
    except service.ServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RedirectResponse(f"/ui/runs/{view.run_id}", status_code=303)


def _stat(key: str, value: str, note: str = "") -> str:
    return (
        f"<div class='stat'><div class='k'>{escape(key)}</div>"
        f"<div class='v'>{value}</div>"
        f"<div class='n'>{escape(note)}</div></div>"
    )


def _proof_block(match: service.MatchView) -> str:
    proof = match.proof
    if proof is None:
        return (
            "<p class='bad note'>The record does not contain this proof — a log "
            "written before contract 7.4.0. Absent evidence, not weak evidence.</p>"
        )
    legs = "".join(
        f"<tr><td>{escape(leg.side)}</td><td class='num'>{leg.subtotal}</td>"
        f"<td class='mono'>{escape(', '.join(leg.record_ids[:6]))}"
        f"{'…' if len(leg.record_ids) > 6 else ''}</td></tr>"
        for leg in proof.legs
    )
    extra = []
    if proof.rule_id:
        extra.append(f"rule {escape(proof.rule_id)}@v{proof.rule_version}")
    if proof.attested_by:
        extra.append(f"attested by {escape(proof.attested_by)}")
    if proof.declared_amount is not None:
        extra.append(f"declared gap {proof.declared_amount} — {escape(proof.declared_gap or '')}")
    return (
        f"<p class='note'>{escape(proof.proof_id)} · match tier "
        f"<strong>{escape(match.tier)}</strong> · proof tier "
        f"<strong>{escape(proof.provenance.value)}</strong> · residual "
        f"{proof.residual} · tolerance {proof.tolerance_used}/{proof.tolerance_allowed}"
        + (" · " + " · ".join(extra) if extra else "")
        + "</p><div class='wrap'><table><tr><th>side</th><th class='num'>claimed subtotal</th>"
        f"<th>records</th></tr>{legs}</table></div>"
        "<p class='note'>Claimed subtotals. A verifier recomputes them from the "
        "records and refuses the match if they disagree — use "
        "<code>POST /v1/verify</code>, or the button above to re-derive the "
        "whole close from the source files.</p>"
    )


@router.get("/ui/runs/{run_id}", response_class=HTMLResponse)
def close_page(run_id: str) -> HTMLResponse:
    """The close: scorecard, worklist, proof per row, and the way to check it."""
    try:
        view = service.view(run_id)
    except service.ServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    tiers = view.tiers
    match_tiers = " ".join(f"{k}={v}" for k, v in sorted(tiers.by_match_tier.items())) or "—"
    proof_tiers = " ".join(f"{k}={v}" for k, v in sorted(tiers.by_proof_tier.items())) or "—"
    head = [
        f"<h1>{escape(view.run_id)}</h1>",
        f"<p class='sub'>{escape(view.loop)} · policy "
        f"<span class='mono'>{escape(view.policy_ref or '—')}</span> · "
        f"{view.events} events · rebuilt from the decision log</p>",
        "<div class='grid'>",
        _stat(
            "auto-match",
            escape(tiers.rate),
            f"by tier {match_tiers}",
        ),
        _stat("proof tiers", escape(proof_tiers), f"{tiers.declared} resting on a declared gap"),
        _stat(
            "every input disposed",
            _verdict(view.complete, "yes", "NO — invariant 8"),
            "matched, excepted, or out of scope with a reason",
        ),
        _stat(
            "blocking recall",
            "<span class='warn'>absent</span>",
            "measured against labelled pairs; production has none",
        ),
        _stat(
            "books",
            _verdict(not view.blocked, "balanced", "BLOCKED"),
            "; ".join(view.blocked) or "balance assertion held",
        ),
        _stat(
            "awaiting sign-off",
            str(len(view.blocking_exceptions)),
            "exceptions a human must clear",
        ),
        "</div>",
    ]

    if view.chain_problems:
        head.append(
            "<div class='card bad'><strong>The decision log does not vouch for "
            "itself.</strong><ul>"
            + "".join(f"<li>{escape(p)}</li>" for p in view.chain_problems)
            + "</ul></div>"
        )
    if view.unproven_matches:
        head.append(
            f"<div class='card warn'>{len(view.unproven_matches)} match(es) have no "
            "proof in the record. Absent evidence, named rather than passed over.</div>"
        )

    head.append("<h2>Check this close</h2>")
    head.append(
        "<div class='card'><p class='note'>Re-ingests the source files, checks each "
        "sha256 against the hash this record pinned, and re-derives every proof in "
        "the log. Nothing is read from the process that ran the close — this is the "
        "outside auditor's check, on demand.</p>"
    )
    for s in service.source_sets(view.loop):
        if s.complete:
            head.append(
                f"<form method='post' action='/ui/runs/{escape(run_id)}/reverify'>"
                f"<input type='hidden' name='source_set' value='{escape(s.name)}'>"
                f"<button class='ghost' type='submit'>Re-derive against "
                f"{escape(s.name)}</button></form> "
            )
    head.append(
        f" &nbsp;<a href='/v1/runs/{escape(run_id)}/export'>audit export (JSON)</a>"
        f" &nbsp;<a href='/v1/runs/{escape(run_id)}/events'>decision log</a></div>"
    )

    rows = []
    for item in view.exceptions:
        exc = item.exception
        # The engine says "I do not know" out loud rather than guessing; the
        # screen has to as well, or E14 renders as a blank cell.
        why = exc.hypothesis or "no hypothesis — the engine has facts, not an explanation"
        note = (
            f" <span class='pill warn'>{escape(item.authority_note)}</span>"
            if (item.authority_note)
            else ""
        )
        evidence = "".join(f"<li>{escape(line)}</li>" for line in exc.evidence) or (
            "<li class='note'>no evidence lines</li>"
        )
        rows.append(
            f"<tr><td class='num'>{item.rank}</td>"
            f"<td><strong>{escape(exc.code)}</strong> {note}<br>"
            f"<span class='note'>{escape(item.code_title)}</span></td>"
            f"<td class='num'>{exc.amount}</td>"
            f"<td class='num'>{item.age_days}d</td>"
            f"<td class='mono'>{escape(exc.fingerprint[:8] or '—')}</td>"
            f"<td>{escape(item.owner)}</td>"
            f"<td><details><summary>evidence</summary>"
            f"<p class='note'>{escape(why)}</p>"
            f"<ul class='note'>{evidence}</ul>"
            f"<p class='note mono'>{escape(', '.join(exc.record_ids[:8]))}</p>"
            f"</details></td></tr>"
        )
    head.append(
        f"<h2>Worklist — {len(view.exceptions)} items, ranked by cash impact &times; age</h2>"
    )
    head.append(
        "<div class='card wrap'><table><tr><th class='num'>#</th><th>code</th>"
        "<th class='num'>amount</th><th class='num'>age</th><th>break</th>"
        "<th>owner</th><th>detail</th></tr>" + "".join(rows) + "</table></div>"
        if rows
        else "<div class='card note'>No exceptions.</div>"
    )

    head.append(f"<h2>Matches — {len(view.matches)}</h2><div class='card'>")
    for m in view.matches:
        head.append(
            f"<details><summary>{escape(m.anchor_external)} → "
            f"{escape(m.group_ref)} ({escape(m.tier)}, {len(m.group_ids)} rows)</summary>"
            f"{_proof_block(m)}</details>"
        )
    head.append("</div>")

    head.append(
        "<h2>Authority</h2><div class='card wrap'><table>"
        "<tr><th>bundle</th><th>signed by</th><th>trusted</th><th>why not</th></tr>"
    )
    for a in view.authority:
        head.append(
            f"<tr><td class='mono'>{escape(a['bundle'])}</td>"
            f"<td>{escape(a['signed_by'] or '—')}</td>"
            f"<td>{_verdict(a['trusted'], 'yes', 'no')}</td>"
            f"<td class='note'>{escape('; '.join(a['reasons']) or '—')}</td></tr>"
        )
    head.append("</table></div>")

    if view.rules_applied or view.rules_refused:
        head.append("<h2>Rules</h2><div class='card'>")
        for r in view.rules_applied:
            state = "observable" if r["observable"] else "fired and moved nothing"
            head.append(
                f"<p class='note'><strong>{escape(r['rule_ref'])}</strong> — fired "
                f"{r['fired']}, suppressed {r['suppressed']}, advisories "
                f"{r['advisories_applied']} · <em>{escape(state)}</em></p>"
            )
        for r in view.rules_refused:
            head.append(
                f"<p class='note bad'><strong>{escape(r['subject'])}</strong> refused: "
                f"{escape('; '.join(r['reasons']))}</p>"
            )
        head.append("</div>")

    return _page(f"recon — {run_id}", "".join(head))


@router.post("/ui/runs/{run_id}/reverify", response_class=HTMLResponse)
def do_reverify(run_id: str, source_set: str = Form(...)) -> HTMLResponse:
    """Re-derive, and print what came back — including when it disagrees."""
    try:
        report = service.reverify(run_id, source_set)
    except service.ServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    sources = "".join(
        f"<tr><td class='mono'>{escape(s.source)}</td>"
        f"<td class='mono'>{escape(s.spec_id)}</td>"
        f"<td class='mono'>{escape(s.recorded_hash[:16])}</td>"
        f"<td class='mono'>{escape(s.actual_hash[:16])}</td>"
        f"<td>{_verdict(s.same_file, 'same file', 'DIFFERENT FILE')}</td></tr>"
        for s in report.sources
    )
    refuted = "".join(
        f"<li><span class='mono'>{escape(r['proof_id'])}</span>: "
        f"{escape('; '.join(r['reasons']))}</li>"
        for r in report.refuted
    )
    body = [
        f"<h1>Re-derivation of {escape(run_id)}</h1>",
        f"<p class='sub'>Against the files in <span class='mono'>{escape(source_set)}</span>, "
        f"under {escape(report.policy_ref)}. Nothing was read from the process that "
        f"ran the close.</p>",
        "<div class='grid'>",
        _stat(
            "verdict",
            _verdict(report.holds, "holds", "DOES NOT HOLD"),
            "sources, arithmetic and evidence must all pass",
        ),
        _stat(
            "proofs re-derived",
            f"{report.proven}/{report.proofs_checked}",
            "recomputed from freshly ingested records",
        ),
        _stat("records ingested", str(report.records_ingested), report.records_digest),
        "</div>",
        "<h2>Source documents</h2><div class='card wrap'><table>"
        "<tr><th>source</th><th>spec</th><th>hash in the record</th>"
        "<th>hash on disk</th><th></th></tr>" + sources + "</table></div>",
    ]
    if refuted:
        body.append("<h2>Refuted</h2><div class='card bad'><ul>" + refuted + "</ul></div>")
    if report.missing_proofs:
        body.append(
            f"<h2>Not checkable</h2><div class='card warn'>"
            f"{len(report.missing_proofs)} match(es) have no proof in the record, so "
            f"there was nothing to re-derive. This does not pass.</div>"
        )
    if not report.sources_match:
        body.append(
            "<div class='card warn'>The files on disk are not the bytes this close "
            "ran on, so a refutation here says nothing about the close. Point it at "
            "the right period.</div>"
        )
    body.append(f"<p><a href='/ui/runs/{escape(run_id)}'>&larr; back to the close</a></p>")
    return _page(f"recon — re-derive {run_id}", "".join(body))
