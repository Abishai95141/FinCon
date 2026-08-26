# ruff: noqa: E501 — SVG path data and CSS declarations are single tokens. Wrapping
# a path changes the drawing; wrapping a CSS rule just makes it harder to diff.
"""Clear Ledger — the design system, as code rather than as a description.

One place for the tokens, the mark and the icons, because a design system that
lives in three files becomes three design systems. Every screen imports `CSS`;
nothing sets a colour, a radius or a shadow inline.

Two rules here are load-bearing rather than decorative, and both were settled by
measurement rather than taste:

**Glass holds containers, never a figure.** The effective background of a
translucent panel is whatever shows through it, so its contrast varies pixel by
pixel. Any surface carrying money uses `--surface` — opaque. The shell, the
login and overlays can be as translucent as they like.

**Blur only where there is contrast behind it.** Side by side on this near-white
ground, `backdrop-filter: blur(24px)` and a plain `rgba(255,255,255,.72)` fill
are indistinguishable: there is nothing behind a white panel on a white page
worth blurring. So the glass look comes from translucency, a hairline top
highlight and a shadow, and real `backdrop-filter` is spent only on `.frost` —
the card that floats over the login's blue panel, and later drawers over content.
"""

from __future__ import annotations

from html import escape

#: The mark. Three paths, flat fills, three tones of one hue.
#: `viewBox` is the artwork's measured bounding box — `getBBox()` on the first
#: draft reported 15.28 units of empty space below the drawing in a 62-unit box,
#: which pushed the visual mass high and made the wordmark beside it read low.
MARK_VIEWBOX = "2 3 38 44"
_MARK_PATHS = (
    '<path d="M14 3 H35 C39.5 3 41.5 7.6 38.6 11L30.5 20.6 L14.5 25.2 L7.4 44.4 '
    'C6.1 48 1.6 47.2 2 43.4 L6.4 10.4 C6.9 6.2 9.9 3 14 3 Z" fill="{c1}"/>'
    '<path d="M8.4 30.2 L30 24 C34.6 22.7 37.6 27.4 34.6 31 L27.6 39.4 '
    'C26.2 41.1 24.2 42.2 22 42.6 L9.8 45 C7.1 45.5 5.7 42.8 6.8 40.4 Z" fill="{c2}"/>'
    '<path d="M14.5 25.2 L30.5 20.6 L28.8 25.5 C27.7 28.6 25 30.3 21.8 30.9 L11.9 32.8 Z" '
    'fill="{c3}"/>'
)


def mark(height: int = 26, *, c1: str = "#2F7BFF", c2: str = "#93B4FA", c3: str = "#12327E") -> str:
    """The FinCon mark at a given height. Width follows the measured aspect."""
    width = round(height * 38 / 44)
    return (
        f'<svg width="{width}" height="{height}" viewBox="{MARK_VIEWBOX}" fill="none" '
        f'role="img" aria-label="FinCon">{_MARK_PATHS.format(c1=c1, c2=c2, c3=c3)}</svg>'
    )


def wordmark(height: int = 26, size: str = "17px") -> str:
    return (
        f'<span class="wordmark">{mark(height)}'
        f'<span class="wordmark-text" style="font-size:{size}">Fin<span>Con</span></span></span>'
    )


#: Lucide, 24px grid, 2px stroke. Named for what they mean here, not for what
#: they look like — a rename in the icon set should not silently change a label.
_ICONS: dict[str, str] = {
    "periods": '<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/>',
    "worklist": '<path d="M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L14.7 3.9a2 2 0 00-3.4 0z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "verify": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M9 12l2 2 4-4"/>',
    "sources": '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v6c0 1.7 4 3 9 3s9-1.3 9-3V5"/><path d="M3 11v6c0 1.7 4 3 9 3s9-1.3 9-3v-6"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 00.3 1.9l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.9-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1A1.7 1.7 0 007.9 19a1.7 1.7 0 00-1.9.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.9 1.7 1.7 0 00-1.5-1H2a2 2 0 110-4h.1A1.7 1.7 0 004.6 8a1.7 1.7 0 00-.3-1.9l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.9.3H9a1.7 1.7 0 001-1.5V2a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.9-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.9V9a1.7 1.7 0 001.5 1H22a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z"/>',
    "bell": '<path d="M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 01-3.4 0"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.1 9a3 3 0 015.8 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
    "calendar": '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/>',
    "trend": '<path d="M22 7l-8.5 8.5-5-5L2 17"/><path d="M16 7h6v6"/>',
    "layers": '<path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>',
    "scale": '<path d="M12 3v18"/><path d="M5 7h14"/><path d="M3 12l3-5 3 5a3 3 0 01-6 0z"/><path d="M15 12l3-5 3 5a3 3 0 01-6 0z"/>',
    "user": '<path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    "alert": '<path d="M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L14.7 3.9a2 2 0 00-3.4 0z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "inbox": '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.4 5.1L2 12v6a2 2 0 002 2h16a2 2 0 002-2v-6l-3.4-6.9A2 2 0 0016.8 4H7.2a2 2 0 00-1.8 1.1z"/>',
    "file": '<path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/>',
    "key": '<circle cx="7.5" cy="15.5" r="4.5"/><path d="M10.7 12.3L21 2"/><path d="M17 6l3 3"/>',
    "refresh": '<path d="M21 12a9 9 0 11-2.6-6.4"/><path d="M21 3v6h-6"/>',
    "check": '<path d="M20 6L9 17l-5-5"/>',
    "x": '<path d="M18 6L6 18"/><path d="M6 6l12 12"/>',
    "download": '<path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/>',
    "arrow": '<path d="M5 12h14"/><path d="M12 5l7 7-7 7"/>',
    "chevron": '<path d="M6 9l6 6 6-6"/>',
    "lock": '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/>',
    "signout": '<path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/>',
    "log": '<path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/><path d="M9 13h6"/><path d="M9 17h4"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
}


class IconError(KeyError):
    """An icon nobody drew. Raised rather than rendering an empty box, because a
    missing icon in a nav is a control a user cannot find."""


def icon(name: str, size: int = 17, stroke: float = 2) -> str:
    if name not in _ICONS:
        raise IconError(f"no icon {name!r}; known: {sorted(_ICONS)}")
    return (
        f'<svg class="ico" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="{stroke}" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true">{_ICONS[name]}</svg>'
    )


CSS = """
:root{
  --primary:#2F7BFF; --primary-light:#E9F1FF; --primary-deep:#1D5FD8; --secondary:#7BA7FF;
  --success:#22C55E; --warning:#F59E0B; --error:#EF4444;
  --n100:#FFFFFF; --n200:#F1F5F9; --n300:#E2E8F0; --n400:#CBD5E1;
  --n500:#94A3B8; --n600:#64748B; --n700:#334155;
  --ink:#1E293B; --ink-deep:#0B1E45;
  --surface:#FFFFFF; --raised:#F8FAFF;
  --g-fill:rgba(255,255,255,.66); --g-strong:rgba(255,255,255,.82);
  --g-line:rgba(255,255,255,.85);
  --e1:0 1px 2px rgba(30,41,59,.04);
  --e2:0 2px 6px rgba(30,41,59,.05),0 1px 2px rgba(30,41,59,.04);
  --e3:0 6px 16px -6px rgba(30,41,59,.10),0 2px 6px rgba(30,41,59,.04);
  --e4:0 16px 32px -12px rgba(30,41,59,.13),0 4px 10px rgba(30,41,59,.04);
  --r4:4px; --r8:8px; --r12:12px; --r16:16px; --r24:24px;
}
*{box-sizing:border-box}
html{
  -webkit-text-size-adjust:100%;
  background-color:#FCFDFF;
  /* An ordinary background, deliberately not `background-attachment: fixed`:
     a fixed attachment forces a full-page repaint on every scroll frame for a
     gradient nobody is looking at. */
  background-image:
    radial-gradient(52rem 34rem at 6% 0%,   rgba(123,167,255,.17), transparent 62%),
    radial-gradient(46rem 30rem at 98% 6%,  rgba(47,123,255,.11),  transparent 58%),
    radial-gradient(50rem 34rem at 24% 100%,rgba(163,201,255,.15), transparent 62%);
  background-repeat:no-repeat;
  background-position:top left,top right,bottom left;
  background-size:100% 90vh,100% 70vh,100% 80vh;
  min-height:100%;
}
body{
  margin:0;background:transparent;color:var(--ink);min-height:100vh;
  font-family:Inter,-apple-system,"Segoe UI",Roboto,sans-serif;
  font-size:14px;line-height:1.6;-webkit-font-smoothing:antialiased;
}
a{color:var(--primary);text-underline-offset:2px}
.ico{flex:none}
.num,td.num,th.num{font-variant-numeric:tabular-nums}
.right{text-align:right}

/* ---- type scale: the reference's, exactly ---- */
h1{font-size:32px;line-height:1.16;font-weight:600;letter-spacing:-.022em;margin:0 0 .5rem}
h2{font-size:24px;line-height:1.25;font-weight:600;letter-spacing:-.018em;margin:0 0 .4rem}
h3{font-size:20px;line-height:1.3;font-weight:600;letter-spacing:-.012em;margin:0 0 .4rem}
.body-lg{font-size:16px}
.cap{font-size:12px;color:var(--n500)}
.sec{font-size:12px;font-weight:600;letter-spacing:.13em;text-transform:uppercase;color:var(--n500);margin:0 0 .7rem}

/* ---- brand ---- */
.wordmark{display:inline-flex;align-items:center;gap:.55rem}
.wordmark-text{font-weight:600;letter-spacing:-.032em;color:var(--ink-deep);line-height:1}
.wordmark-text span{color:var(--primary)}

/* ---- surfaces ---- */
.glass{
  position:relative;border-radius:var(--r24);background:var(--g-fill);
  border:1px solid var(--g-line);box-shadow:var(--e3);
}
.panel{
  position:relative;border-radius:var(--r16);background:rgba(255,255,255,.76);
  border:1px solid var(--g-line);box-shadow:var(--e2);
}
.glass::after,.panel::after{
  content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.9),inset 0 0 0 1px rgba(47,123,255,.045);
}
.solid{background:var(--surface)}
/* Real blur, only where something with contrast sits behind. */
.frost{backdrop-filter:blur(16px) saturate(180%);-webkit-backdrop-filter:blur(16px) saturate(180%)}
@media (prefers-reduced-transparency:reduce){
  .glass,.panel{background:rgba(255,255,255,.96)}
  .frost{backdrop-filter:none;-webkit-backdrop-filter:none;background:rgba(255,255,255,.92)}
}

/* ---- shell ---- */
.shell{display:grid;grid-template-columns:1fr;min-height:100vh}
@media(min-width:60rem){.shell{grid-template-columns:15.5rem 1fr}}
.rail{
  padding:1.4rem 1rem;background:var(--g-strong);border-right:1px solid var(--g-line);
  display:flex;flex-direction:column;gap:1.2rem;
}
@media(min-width:60rem){.rail{position:sticky;top:0;height:100vh}}
.nav{display:flex;flex-direction:column;gap:.15rem}
.nav a{
  display:flex;align-items:center;gap:.65rem;padding:.55rem .7rem;border-radius:var(--r8);
  font-size:13.5px;color:var(--n600);text-decoration:none;transition:background .14s,color .14s;
}
.nav a:hover{background:rgba(255,255,255,.72);color:var(--ink)}
.nav a[aria-current="page"]{
  background:var(--surface);color:var(--primary-deep);font-weight:500;
  box-shadow:var(--e2),inset 0 0 0 1px rgba(47,123,255,.10);
}
.nav a[aria-current="page"] .ico{color:var(--primary)}
.nav .count{
  margin-left:auto;font-size:11px;font-weight:600;color:#B45309;background:#FEF4E2;
  padding:.05rem .42rem;border-radius:999px;
}
.rail-foot{margin-top:auto;padding-top:1rem;border-top:1px solid var(--n300)}
.who{display:flex;align-items:center;gap:.6rem}
.avatar{
  width:32px;height:32px;border-radius:999px;flex:none;display:grid;place-items:center;
  background:linear-gradient(145deg,#7BA7FF,#2F7BFF);color:#fff;font-size:11.5px;font-weight:600;
}
.stage{padding:1.6rem 1.8rem 4rem;min-width:0}
.crumb{
  display:flex;align-items:center;gap:.45rem;flex-wrap:wrap;
  font-size:12.5px;color:var(--n500);margin-bottom:1.2rem;
}
.crumb b{color:var(--ink);font-weight:500}
.crumb a{color:var(--n500);text-decoration:none}
.crumb a:hover{color:var(--primary)}

/* ---- buttons ---- */
.btn{
  font:inherit;font-size:13px;font-weight:500;border-radius:var(--r8);
  padding:.55rem 1.05rem;border:1px solid transparent;cursor:pointer;text-decoration:none;
  display:inline-flex;align-items:center;gap:.45rem;transition:background .16s,box-shadow .16s,border-color .16s;
}
.btn-primary{
  background:linear-gradient(180deg,#4A8BFF,#2F7BFF);color:#fff;
  box-shadow:0 4px 10px -3px rgba(47,123,255,.5),inset 0 1px 0 rgba(255,255,255,.32);
}
.btn-primary:hover{background:linear-gradient(180deg,#2F7BFF,#1F6AEB)}
.btn-secondary{background:rgba(255,255,255,.78);border-color:#BFD6FF;color:var(--primary-deep);box-shadow:var(--e1)}
.btn-secondary:hover{background:#fff;border-color:var(--secondary)}
.btn-ghost{background:transparent;color:var(--n600)}
.btn-ghost:hover{background:rgba(255,255,255,.7);color:var(--ink)}
.btn:disabled,.btn[aria-disabled="true"]{opacity:.42;cursor:not-allowed;box-shadow:none;pointer-events:none}
.btn-wide{width:100%;justify-content:center;padding:.7rem}
.btn:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible{
  outline:2px solid var(--primary);outline-offset:2px;
}

/* ---- badges ---- */
.badge{
  display:inline-flex;align-items:center;gap:.3rem;font-size:11.5px;font-weight:500;
  padding:.22rem .6rem;border-radius:999px;border:1px solid transparent;white-space:nowrap;
}
.badge-ok{background:#E7F8EE;color:#15803D;border-color:#BBEFCE}
.badge-rule{background:#EDEBFE;color:#5B4BD6;border-color:#D6D1FB}
.badge-declared{background:#FEF4E2;color:#B45309;border-color:#FBDCA6}
.badge-info{background:var(--primary-light);color:var(--primary-deep);border-color:#C9DEFF}
.badge-bad{background:#FEECEC;color:#B91C1C;border-color:#FAC7C7}
.badge-mute{background:var(--n200);color:var(--n600);border-color:var(--n300)}

/* ---- forms ---- */
.field{margin-bottom:1rem}
.field label{display:block;font-size:12px;font-weight:500;color:var(--n600);margin-bottom:.35rem}
.input{
  width:100%;font:inherit;font-size:13.5px;padding:.62rem .8rem;border-radius:var(--r8);
  border:1px solid var(--n300);background:rgba(255,255,255,.85);color:var(--ink);
  box-shadow:inset 0 1px 2px rgba(30,41,59,.03);
}
.input::placeholder{color:var(--n500)}
.input:focus{outline:none;border-color:var(--secondary);box-shadow:0 0 0 3px rgba(47,123,255,.14)}
.input-icon{position:relative}
.input-icon .input{padding-left:2.2rem}
.input-icon .ico{position:absolute;left:.72rem;top:50%;transform:translateY(-50%);color:var(--n500)}

/* ---- tables: opaque, always. money never sits on glass ---- */
.tbl{overflow-x:auto;border-radius:var(--r16);background:var(--surface);border:1px solid var(--n300)}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:.72rem 1rem;border-bottom:1px solid var(--n200);vertical-align:top}
tr:last-child td{border-bottom:0}
th{
  font-size:11px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;
  color:var(--n500);background:rgba(241,245,249,.62);white-space:nowrap;
}
td{color:var(--n700)}
tbody tr:hover td{background:rgba(233,241,255,.4)}
td .sub{display:block;color:var(--n500);font-size:.92em;margin-top:.1rem}

/* ---- metrics ---- */
.metrics{display:grid;gap:.9rem;grid-template-columns:repeat(auto-fit,minmax(13rem,1fr));margin-bottom:1.2rem}
.metric{padding:1.05rem 1.15rem}
.metric .k{font-size:12.5px;color:var(--n500);font-weight:500}
.metric .v{font-size:28px;font-weight:600;letter-spacing:-.02em;margin:.2rem 0 .1rem;font-variant-numeric:tabular-nums}
.metric .v small{font-size:16px;color:var(--n500);font-weight:400}
.metric .d{font-size:11.5px;color:var(--n500)}

/* ---- stage strip ---- */
.stages{display:flex;flex-wrap:wrap;gap:.3rem;margin-bottom:1.2rem}
.st{
  display:flex;align-items:center;gap:.35rem;font-size:11.5px;padding:.32rem .6rem;
  border-radius:999px;background:rgba(255,255,255,.75);border:1px solid var(--n300);color:var(--n600);
}
.st-ok{color:#15803D;border-color:#BBEFCE;background:#F2FCF6}
.st-now{color:var(--primary-deep);border-color:#C9DEFF;background:var(--primary-light);font-weight:500}

/* ---- login ---- */
/* Full-bleed. A centred card floating in the middle of a 2000px display reads
   as a dialog that lost its page — the split *is* the screen. The form column
   is a fixed measure so the inputs stay a comfortable width whatever the
   viewport does, and the art panel takes everything left over. */
.auth{min-height:100vh;display:grid;grid-template-columns:1fr}
@media(min-width:56rem){.auth{grid-template-columns:minmax(28rem,40rem) 1fr}}
.split-form{
  background:var(--surface);display:flex;flex-direction:column;justify-content:center;
  padding:3rem clamp(1.5rem,4vw,3.5rem);
}
.split-form > *{width:100%;max-width:23rem;margin-left:auto;margin-right:auto}
.split-art{
  position:relative;overflow:hidden;display:none;
  place-items:center;padding:clamp(2rem,5vw,4rem);
  background:
    radial-gradient(38rem 30rem at 78% 6%,rgba(47,123,255,.30),transparent 62%),
    radial-gradient(32rem 26rem at 10% 96%,rgba(123,167,255,.40),transparent 62%),
    linear-gradient(150deg,#EAF3FF 0%,#DCEBFF 48%,#EEF6FF 100%);
}
@media(min-width:56rem){.split-art{display:grid}}
/* The art side keeps its own measure. Without this the quote and the proof
   card stretch across a 1400px column on a wide display and the composition
   falls apart — a panel filling the viewport is not the same as content
   filling the panel. */
.art-inner{position:relative;width:100%;max-width:34rem;display:flex;flex-direction:column;gap:2.2rem}
.orb{position:absolute;border-radius:999px;pointer-events:none}
.quote{
  position:relative;font-size:clamp(24px,2.6vw,34px);line-height:1.24;font-weight:600;
  letter-spacing:-.024em;color:#12305F;max-width:16ch;
}
.proofcard{
  position:relative;border-radius:var(--r16);padding:1.15rem 1.3rem;max-width:30rem;
  background:rgba(255,255,255,.62);border:1px solid rgba(255,255,255,.9);box-shadow:var(--e4);
}
.proofcard .row{display:flex;justify-content:space-between;gap:1rem;font-size:12.5px;padding:.26rem 0;color:var(--n600);font-variant-numeric:tabular-nums}
.proofcard .row b{color:var(--ink);font-weight:500}
.rule-line{display:flex;align-items:center;gap:.7rem;margin:1.1rem 0;color:var(--n500);font-size:11.5px}
.rule-line::before,.rule-line::after{content:"";height:1px;background:var(--n300);flex:1}

/* ---- page header ---- */
.pagehead{display:flex;gap:1.2rem;align-items:flex-start;flex-wrap:wrap;margin-bottom:1.4rem}
.pagehead .lhs{min-width:0;flex:1 1 22rem}
.pagehead .rhs{display:flex;gap:.6rem;align-items:center;flex-wrap:wrap}
.pagehead h1{margin:0 0 .3rem}
.pagehead .sub{font-size:12.5px;color:var(--n500);margin:0}
.crumb-row{display:flex;align-items:center;justify-content:space-between;gap:1rem;margin-bottom:1.2rem}
.crumb-tools{display:flex;align-items:center;gap:.35rem;color:var(--n500)}
.iconbtn{
  width:34px;height:34px;border-radius:999px;display:grid;place-items:center;position:relative;
  border:1px solid var(--g-line);background:rgba(255,255,255,.7);color:var(--n600);
  text-decoration:none;transition:background .14s,color .14s;
}
.iconbtn:hover{background:#fff;color:var(--primary)}
.iconbtn .dot{
  position:absolute;top:-3px;right:-3px;min-width:16px;height:16px;border-radius:999px;
  background:var(--error);color:#fff;font-size:10px;font-weight:600;display:grid;place-items:center;
  padding:0 4px;border:2px solid #F6F9FF;
}
.chip-select{
  display:flex;align-items:center;gap:.6rem;padding:.4rem .85rem;border-radius:var(--r12);
  background:rgba(255,255,255,.78);border:1px solid var(--g-line);box-shadow:var(--e1);
}
.chip-select .k{font-size:10.5px;color:var(--n500);line-height:1.2}
.chip-select .v{font-size:13px;font-weight:500;line-height:1.25}

/* ---- metric card, reference layout ---- */
.metric{position:relative;padding:1.15rem 1.25rem;display:flex;flex-direction:column;gap:.15rem}
.metric .head{display:flex;align-items:flex-start;justify-content:space-between;gap:.8rem}
/* One tint. Six cards in six colours is a dashboard shouting every number at
   the same volume, and it leaves nothing louder to say when something is
   actually wrong — so the badges are all `--primary-light`, the values are all
   ink, and colour is spent only on `.bad`, which is reserved for a close that
   is blocked or a record that does not vouch for itself. */
.metric-ico{
  width:34px;height:34px;border-radius:var(--r12);display:grid;place-items:center;flex:none;
  background:var(--primary-light);color:var(--primary);
}
.metric-ico.bad{background:#FEECEC;color:#B91C1C}
.metric .v{color:var(--ink-deep)}
.metric .v.bad{color:var(--error)}
.bar{height:5px;border-radius:999px;background:var(--n200);overflow:hidden;margin:.55rem 0 .1rem}
.bar i{display:block;height:100%;border-radius:999px;background:linear-gradient(90deg,#5B9BFF,#2F7BFF)}

/* ---- toolbar / filters ---- */
.toolbar{display:flex;gap:.5rem;flex-wrap:wrap;align-items:center;margin-bottom:1rem}
.pillnav{display:flex;gap:.3rem;flex-wrap:wrap}
.pillnav a{
  font-size:12.5px;padding:.35rem .8rem;border-radius:999px;text-decoration:none;
  border:1px solid var(--n300);background:rgba(255,255,255,.7);color:var(--n600);
}
.pillnav a:hover{background:#fff;color:var(--ink)}
.pillnav a[aria-current="true"]{background:var(--primary);border-color:var(--primary);color:#fff;font-weight:500}

/* ---- empty state ---- */
.empty{
  border-radius:var(--r16);border:1px dashed var(--n300);background:rgba(255,255,255,.6);
  padding:2.6rem 1.5rem;text-align:center;
}
.empty .ring{
  width:52px;height:52px;border-radius:999px;background:var(--primary-light);color:var(--primary);
  display:grid;place-items:center;margin:0 auto .9rem;
}
.empty h3{margin:0 0 .3rem;font-size:16px}
.empty p{margin:0 auto;max-width:34ch;color:var(--n500);font-size:13px}

/* ---- key/value ---- */
.kv{display:grid;grid-template-columns:1fr;gap:.1rem}
.kv .row{display:flex;justify-content:space-between;gap:1rem;padding:.5rem 0;border-bottom:1px solid var(--n200)}
.kv .row:last-child{border-bottom:0}
.kv .k{font-size:12.5px;color:var(--n500)}
.kv .v{font-size:13px;font-weight:500;text-align:right;font-variant-numeric:tabular-nums;word-break:break-all}

/* ---- decision log timeline ---- */
.log{position:relative;padding-left:1.9rem}
.log::before{content:"";position:absolute;left:.62rem;top:.4rem;bottom:.4rem;width:2px;background:var(--n200)}
.ev{position:relative;padding:.55rem 0}
.ev .node{
  position:absolute;left:-1.9rem;top:.72rem;width:1.25rem;height:1.25rem;border-radius:999px;
  display:grid;place-items:center;background:var(--surface);border:2px solid var(--n300);
}
.ev.k-ok .node{border-color:#7ED4A6;color:#15803D}
.ev.k-warn .node{border-color:#F3C570;color:#B45309}
.ev.k-bad .node{border-color:#F5A3A0;color:#B91C1C}
.ev.k-info .node{border-color:var(--secondary);color:var(--primary)}
.ev .line{display:flex;gap:.6rem;align-items:baseline;flex-wrap:wrap}
.ev .kind{font-size:13px;font-weight:500;color:var(--ink)}
.ev .meta{font-size:11.5px;color:var(--n500);font-variant-numeric:tabular-nums}
.ev pre{
  margin:.5rem 0 0;padding:.7rem .85rem;border-radius:var(--r8);background:var(--n200);
  font-size:11.5px;line-height:1.55;overflow-x:auto;color:var(--n700);
}

/* ---- processing ---- */
.run{max-width:44rem;margin:0 auto}
.steps{display:flex;flex-direction:column;gap:.15rem;margin:1.4rem 0}
.step{
  display:flex;align-items:flex-start;gap:.85rem;padding:.8rem .95rem;border-radius:var(--r12);
  border:1px solid transparent;transition:background .2s,border-color .2s;
}
.step.running{background:var(--surface);border-color:var(--g-line);box-shadow:var(--e2)}
.step .mark{
  width:22px;height:22px;border-radius:999px;flex:none;display:grid;place-items:center;
  border:2px solid var(--n300);background:var(--surface);color:var(--n400);margin-top:.05rem;
}
.step.done .mark{border-color:#7ED4A6;color:#15803D}
.step.running .mark{border-color:var(--primary);color:var(--primary)}
.step.failed .mark{border-color:#F5A3A0;color:#B91C1C}
.step .what{min-width:0;flex:1}
.step .name{font-size:13.5px;font-weight:500;color:var(--n500)}
.step.done .name,.step.running .name{color:var(--ink)}
.step .why{font-size:12px;color:var(--n500);margin-top:.1rem}
.step .fact{font-size:12.5px;color:var(--primary-deep);margin-top:.2rem;font-variant-numeric:tabular-nums}
.step .ms{font-size:11px;color:var(--n400);font-variant-numeric:tabular-nums;margin-top:.15rem}
/* A two-dot pulse, not a spinner: it says "still going" without implying a
   fraction of the work that nobody has measured. */
.pulse{display:inline-flex;gap:3px;align-items:center}
.pulse i{width:4px;height:4px;border-radius:999px;background:currentColor;animation:p 1.1s infinite}
.pulse i:nth-child(2){animation-delay:.18s}
@keyframes p{0%,60%,100%{opacity:.25}30%{opacity:1}}
@media (prefers-reduced-motion:reduce){.pulse i{animation:none;opacity:.6}}

/* ---- messages ---- */
.note{border-left:2px solid var(--primary);padding:.1rem 0 .1rem 1rem;margin:1rem 0;color:var(--n600);font-size:13px}
.note-bad{border-color:var(--error);color:#B91C1C}
.note-warn{border-color:var(--warning)}
.alert{
  border-radius:var(--r8);padding:.6rem .85rem;font-size:12.5px;margin-bottom:1rem;
  background:#FEECEC;color:#B91C1C;border:1px solid #FAC7C7;
}
.alert-info{background:var(--primary-light);color:var(--primary-deep);border-color:#C9DEFF}
.devbanner{
  background:#FEF4E2;color:#8A5A05;border-bottom:1px solid #FBDCA6;
  font-size:12px;padding:.4rem 1rem;text-align:center;
}
details summary{cursor:pointer;color:var(--primary);font-size:12.5px}
details[open] summary{margin-bottom:.5rem}
"""

FONT_LINK = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    'family=Inter:wght@300;400;500;600;700&display=swap">'
)


def document(title: str, body: str, *, body_class: str = "") -> str:
    cls = f' class="{escape(body_class)}"' if body_class else ""
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(title)}</title>{FONT_LINK}<style>{CSS}</style></head>"
        f"<body{cls}>{body}</body></html>"
    )


def money(amount, *, symbol: str = "₹") -> str:
    """Indian grouping — 1,28,542.00, not 128,542.00.

    The product reconciles Indian settlement files and a controller reads these
    numbers all day; `90259.47` is a number you have to count digits on. Written
    out rather than reached for from `locale`, which is process-global, depends
    on what the host happens to have installed, and would make a page render
    differently on two machines.
    """
    negative = amount < 0
    whole, _, fraction = f"{abs(amount):.2f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join([*groups, tail])
    # `&minus;` rather than a literal U+2212: a typographic minus is right for
    # money and ruff flags the character as ambiguous in source, correctly.
    return f"{'&minus;' if negative else ''}{symbol}{whole}.{fraction}"
