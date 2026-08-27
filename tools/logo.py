"""Render the README lockup from the mark the product actually ships.

Derived from `recon.api.theme.mark()` rather than drawn again, so the logo on
GitHub cannot drift from the one in the application header — two copies of a
brand is the same defect as two copies of a fact, and the copy nobody looks at
is the one that rots.

Two variants because GitHub serves a README in whichever theme the reader has
chosen and an SVG cannot ask: the mark is identical (its blues hold on both
grounds) and only the wordmark ink changes.

    make logo
"""

from __future__ import annotations

from pathlib import Path

OUT = Path("docs/media")

#: Ink for the wordmark, per ground. The mark's own palette is unchanged — it
#: was picked to sit on either.
INK = {"light": "#0B1E45", "dark": "#EAF0FA"}
ACCENT = "#2F7BFF"

MARK_H = 44
PAD = 10
GAP = 14
TEXT_SIZE = 40


def lockup(ink: str) -> str:
    """Mark + wordmark, baseline-aligned.

    The type is `text` with a system stack rather than a converted path: a
    reader with the font gets real type, and a reader without gets a near
    fallback. Outlining it would be sharper and would also make the wordmark
    un-editable by anyone who ever needs to.
    """
    from recon.api import theme

    inner = theme.mark(MARK_H)
    # Lift the paths out of the shipped mark and re-place them, so the lockup is
    # one document rather than a nested `<svg>` that some renderers mis-scale.
    body = inner.split(">", 1)[1].rsplit("</svg>", 1)[0]
    mark_w = round(MARK_H * 38 / 44)
    # viewBox of the shipped mark is "2 3 38 44"; translate so it starts at 0.
    scale = MARK_H / 44
    text_x = PAD + mark_w + GAP
    width = text_x + 172 + PAD
    height = MARK_H + PAD * 2
    baseline = PAD + MARK_H - 7

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" fill="none" role="img" '
        f'aria-label="FinCon">'
        f'<g transform="translate({PAD},{PAD}) scale({scale}) translate(-2,-3)">{body}</g>'
        f'<text x="{text_x}" y="{baseline}" '
        f'font-family="Inter,-apple-system,BlinkMacSystemFont,\'Segoe UI\',Helvetica,Arial,sans-serif" '
        f'font-size="{TEXT_SIZE}" font-weight="600" letter-spacing="-1.3">'
        f'<tspan fill="{ink}">Fin</tspan><tspan fill="{ACCENT}">Con</tspan></text>'
        f"</svg>"
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, ink in INK.items():
        target = OUT / f"logo-{name}.svg"
        target.write_text(lockup(ink), encoding="utf-8")
        print(f"  {target}  {target.stat().st_size} bytes")

    from recon.api import theme

    mark = OUT / "mark.svg"
    mark.write_text(theme.mark(160), encoding="utf-8")
    print(f"  {mark}  {mark.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
