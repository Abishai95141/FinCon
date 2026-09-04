"""Does the script still fit the picture?

    make script-check

`docs/16-SCRIPT.md` carries a line per shot and `demo/shots.json` carries how
long each shot actually is. Both move: a beat gets retuned, a shot gets re-cut,
a sentence gets a clause. This is the thing that notices.

**Why a checker rather than care.** The first version of the script was written
against *planned* durations, and the cut came back with shot 3 at 16.9s where
the plan said 32. Half the lines no longer fitted and nothing said so — the
failure mode is discovering it with a microphone in front of you.

It reports words, the rate each line implies, and the slack. It fails only on a
line that cannot be read at `CEILING` words a minute, because that is the point
where fitting the line means rushing it, and rushing it is the one delivery this
particular film cannot afford.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT = Path("docs/16-SCRIPT.md")
SHOTS = Path("demo/shots.json")

#: The pace the script is written for. Slow, and deliberately: every sentence
#: carries a number or a claim, and a listener needs the gap between them.
TARGET = 125.0

#: Above this, fitting the line means rushing it. A demo whose narrator sounds
#: hurried is arguing against its own thesis.
CEILING = 150.0

#: `## 7 - 2:50 to 3:15 - four endings`. Only the shot number is parsed: the
#: timecodes in the heading are prose for a reader, and two sources for one fact
#: is how they come to disagree.
HEADING = re.compile(r"^##\s+(\d+)\s+·")


def lines(text: str) -> dict[int, int]:
    """shot -> how many words are actually in its quoted block.

    Counted, never asserted. The script used to carry a hand-typed count under
    each shot and all ten of them were wrong — a number maintained beside a
    computable one only ever drifts.
    """
    out: dict[int, int] = {}
    shot: int | None = None
    spoken: list[str] = []

    def flush() -> None:
        if shot is not None:
            out[shot] = len(" ".join(spoken).split())

    for line in text.splitlines():
        head = HEADING.match(line)
        if head:
            flush()
            shot, spoken = int(head.group(1)), []
            continue
        if shot is None or not line.startswith(">"):
            continue
        # Strip the quote marker and any emphasis: `**no model ran.**` is three
        # words spoken, not three plus four asterisks.
        body = re.sub(r"[*_`]", "", line[1:]).strip()
        if body:
            spoken.append(body)
    flush()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--script", default=str(SCRIPT))
    ap.add_argument("--shots", default=str(SHOTS))
    ap.add_argument("--ceiling", type=float, default=CEILING)
    args = ap.parse_args(argv)

    script = Path(args.script)
    shots_file = Path(args.shots)
    if not script.exists():
        print(f"{script} is absent", file=sys.stderr)
        return 2
    if not shots_file.exists():
        print(f"{shots_file} is absent — run `make demo-cut` first", file=sys.stderr)
        return 2

    spoken = lines(script.read_text(encoding="utf-8"))
    shots = {s["n"]: s for s in json.loads(shots_file.read_text(encoding="utf-8"))}

    print(f"  {'shot':<5} {'secs':>6} {'words':>6} {'wpm':>6} {'slack':>7}")
    too_fast: list[str] = []
    total_words = total_secs = 0.0

    for n in sorted(spoken):
        words = spoken[n]
        shot = shots.get(n)
        if shot is None:
            # Shot 9 lives in the script and not in the cut until its terminal
            # capture is recorded. Reported, not failed — it is a shot that has
            # not been shot, which the script already says.
            print(f"  {n:<5} {'—':>6} {words:>6} {'—':>6} {'not cut':>7}")
            continue
        secs = shot["to"] - shot["from"]
        wpm = words / secs * 60
        # Seconds this line leaves over at the ceiling pace.
        slack = secs - (words / args.ceiling * 60)
        flag = "" if wpm <= args.ceiling else "  <-- too fast"
        print(f"  {n:<5} {secs:>6.1f} {words:>6} {wpm:>6.0f} {slack:>+7.1f}{flag}")
        if wpm > args.ceiling:
            too_fast.append(
                f"shot {n}: {words} words in {secs:.1f}s is {wpm:.0f} wpm, over the "
                f"{args.ceiling:.0f} ceiling. Widen its beat in tools/demo.py or cut "
                f"{words - int(secs * args.ceiling / 60)} words."
            )
        total_words += words
        total_secs += secs

    if total_secs:
        print(
            # `:.0f` on the minutes ROUNDS: 285.7s printed as 5:45.7 rather than
            # 4:45.7. Truncate.
            f"\n  {total_words:.0f} words over {int(total_secs // 60)}:{total_secs % 60:04.1f}"
            f" — {total_words / total_secs * 60:.0f} wpm overall (target {TARGET:.0f})"
        )

    if too_fast:
        print(file=sys.stderr)
        for problem in too_fast:
            print(f"  {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
