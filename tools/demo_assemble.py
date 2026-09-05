"""Cut the picture. Silent, timecoded, ready for a voiceover.

    make demo-cut

Reads `demo/cuts.json` — the beat offsets `tools/demo.py` logged while it was
recording — and slices the single continuous capture at those boundaries, so the
edit points are generated rather than eyeballed. Then it lays the Remotion
graphics in front, between and after.

**It outputs silence on purpose.** Recording a voiceover to a written plan
rather than to a picture is how a demo ends up with narration describing
something that left the screen two seconds ago. Burnt-in timecode and a shot
label sit in the corner so you can call out "shot 6 runs four seconds long" and
have somebody change one number in `BEATS`.

Delivers two files:

    demo/cut-timecoded.mp4   what you record against
    demo/cut-clean.mp4       the same edit with no burn-in, for the final mix
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

OUT = Path("demo")
MOTION = Path("motion/out")

#: The film, in order. `motion` entries are rendered comps; `capture` entries
#: are (first beat, beat after the last) into the recording — a half-open range,
#: so a shot ends exactly where the next begins and no frame is dropped or
#: shown twice.
FILM: list[dict] = [
    {"shot": 1, "kind": "motion", "src": "ThePlug.mp4", "title": "one line is forty transactions"},
    {
        "shot": 2,
        "kind": "motion",
        "src": "SolvedAndNotSolved.mp4",
        "title": "the match is not the problem",
    },
    {
        "shot": 3,
        "kind": "capture",
        "from": "login",
        "to": "periods",
        "title": "sign in, and what this is",
    },
    {"shot": 4, "kind": "capture", "from": "periods", "to": "scorecard", "title": "close a period"},
    {
        "shot": 5,
        "kind": "capture",
        "from": "scorecard",
        "to": "worklist",
        "title": "the scorecard, and a proof",
    },
    {
        "shot": 6,
        "kind": "capture",
        "from": "worklist",
        "to": "dispose",
        "title": "the tail, and the model",
    },
    # `settle`, not `signoff`: the span between them is the rest of the desk
    # being cleared so sign-off can succeed, and no shot spans it.
    {"shot": 7, "kind": "capture", "from": "dispose", "to": "settle", "title": "four endings"},
    {
        "shot": 8,
        "kind": "capture",
        "from": "signoff",
        "to": "agent",
        "title": "sign off, and the pack",
    },
    # Rendered like the other comps, from a transcript of two real requests
    # against the deployed endpoint. It was "optional, dropped in by hand if
    # present" and was therefore the only shot that never got made — a shot the
    # pipeline cannot re-make goes stale, and then goes absent.
    {"shot": 9, "kind": "motion", "src": "Verify.mp4", "title": "check it without us"},
    {
        "shot": 10,
        "kind": "capture",
        "from": "agent",
        "to": "end",
        "title": "point an assistant at it",
    },
    {"shot": 11, "kind": "motion", "src": "Card.mp4", "title": "card"},
]

W, H, FPS = 1920, 1080, 60


def ffmpeg(*args: str) -> None:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    subprocess.run(cmd, check=True)


def offsets(cuts: list[dict]) -> dict[str, float]:
    return {c["beat"]: c["at"] for c in cuts}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--motion", default=str(MOTION))
    args = ap.parse_args(argv)

    if shutil.which("ffmpeg") is None:
        print("ffmpeg is not on PATH", file=sys.stderr)
        return 2

    out, motion = Path(args.out), Path(args.motion)
    raw = out / "raw.webm"
    cuts_file = out / "cuts.json"
    if not raw.exists() or not cuts_file.exists():
        print(f"run `make demo` first — {raw} and {cuts_file} are what this cuts", file=sys.stderr)
        return 2

    at = offsets(json.loads(cuts_file.read_text(encoding="utf-8")))
    parts = out / "parts"
    parts.mkdir(exist_ok=True)
    for stale in parts.glob("*.mp4"):
        stale.unlink()

    pieces: list[Path] = []
    shots: list[dict] = []
    running = 0.0
    for entry in FILM:
        shot = entry["shot"]
        target = parts / f"{shot:02d}.mp4"

        if entry["kind"] in {"motion", "optional"}:
            src = motion / entry["src"] if entry["kind"] == "motion" else out / entry["src"]
            if not src.exists():
                if entry["kind"] == "optional":
                    print(f"  shot {shot:>2}  skipped — {src} absent")
                    continue
                print(f"  shot {shot:>2}  MISSING {src} — render the comps first", file=sys.stderr)
                return 3
            # Normalise: the comps are already 1080p60, the terminal capture may
            # not be. A concat of mixed geometry silently produces garbage.
            ffmpeg(
                "-i",
                str(src),
                "-vf",
                f"scale={W}:{H}:flags=lanczos,fps={FPS}",
                "-c:v",
                "libx264",
                "-crf",
                "18",
                "-preset",
                "slow",
                "-pix_fmt",
                "yuv420p",
                "-an",
                str(target),
            )
        else:
            start, end = at.get(entry["from"]), at.get(entry["to"])
            if start is None or end is None:
                print(
                    f"  shot {shot:>2}  MISSING beat {entry['from']}→{entry['to']}", file=sys.stderr
                )
                return 3
            ffmpeg(
                "-ss",
                f"{start:.3f}",
                "-to",
                f"{end:.3f}",
                "-i",
                str(raw),
                "-vf",
                f"scale={W}:{H}:flags=lanczos,fps={FPS}",
                "-c:v",
                "libx264",
                "-crf",
                "18",
                "-preset",
                "slow",
                "-pix_fmt",
                "yuv420p",
                "-an",
                str(target),
            )

        secs = float(
            subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=nw=1:nk=1",
                    str(target),
                ],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
        print(f"  shot {shot:>2}  {secs:6.2f}s  {entry['title']}")
        shots.append(
            {
                "n": shot,
                "title": entry["title"],
                "from": round(running, 3),
                "to": round(running + secs, 3),
            }
        )
        running += secs
        pieces.append(target)

    listing = parts / "concat.txt"
    listing.write_text("".join(f"file '{p.name}'\n" for p in pieces), encoding="utf-8")

    clean = out / "cut-clean.mp4"
    ffmpeg(
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(listing),
        "-c:v",
        "libx264",
        "-crf",
        "18",
        "-preset",
        "slow",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(clean),
    )

    total = float(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(clean),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )

    # The version you record against: running clock, shot number and how much of
    # the shot is left, so a note reads "shot 6, 3:14" rather than "the bit with
    # the model".
    #
    # Rendered by Remotion and composited, NOT by ffmpeg's `drawtext`. The
    # ffmpeg on this machine is built without libfreetype, so drawtext is absent
    # as a filter and no font path fixes it. `overlay` needs no text support, and
    # the result carries the shot label as well, which drawtext could not.
    timecoded = out / "cut-timecoded.mp4"
    strip = out / "timecode.mp4"
    props = out / "timecode-props.json"
    props.write_text(json.dumps({"shots": shots}), encoding="utf-8")

    if shutil.which("npx") is None:
        print(f"\n  {clean}  — npx absent, so no timecoded version", file=sys.stderr)
    else:
        subprocess.run(
            [
                "npx",
                "remotion",
                "render",
                "Timecode",
                str(Path("..") / strip),
                "--props",
                str(Path("..") / props),
                "--codec",
                "h264",
                "--log",
                "error",
            ],
            cwd="motion",
            check=True,
        )
        ffmpeg(
            "-i",
            str(clean),
            "-i",
            str(strip),
            "-filter_complex",
            "[0:v][1:v]overlay=0:H-h:format=auto",
            "-c:v",
            "libx264",
            "-crf",
            "20",
            "-preset",
            "medium",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(timecoded),
        )

    print(f"\n  {clean}          {total // 60:.0f}:{total % 60:04.1f}")
    if timecoded.exists():
        print(f"  {timecoded}   <- record the voiceover against this one")
    (out / "shots.json").write_text(json.dumps(shots, indent=2), encoding="utf-8")
    print(f"  {out / 'shots.json'}        the shot boundaries, for the edit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
