# The demo film

*Eleven shots, 4:23. The voiceover is recorded last, against picture.*

**The script is [16-SCRIPT.md](16-SCRIPT.md)** — a line per shot, timed against
the real cut. `make script-check` fails on any line that no longer fits its
shot, which is the thing that goes wrong when a beat is retuned.

Shot-by-shot planning notes: <https://claude.ai/code/artifact/4940ca23-6c75-4f8f-a0a8-cd12328b0f18>

---

## Make it

```bash
make demo-seed     # a tenant with nothing in it, batches on disk, authority signed
make serve         # in another shell, with DEEPSEEK_API_KEY set — shot 6 is a real call
make demo-film     # graphics + scripted capture + cut
make script-check  # does each voiceover line still fit its shot
```

Out the other end:

| | |
|---|---|
| `demo/cut-clean.mp4` | the picture cut, silent — what the final mix is built on |
| `demo/cut-timecoded.mp4` | the same edit with a clock, shot number and *seconds left in this shot* — **record the voiceover against this one** |
| `demo/shots.json` | where every shot begins and ends, for the edit |
| `demo/cuts.json` | where every *beat* landed inside the capture |

---

## Why the product footage is scripted

A person driving a browser for four continuous minutes always produces a hunt
for a button or a scroll that overshoots. Ten takes later you are still cutting
around a stumble, and the result reads as somebody demonstrating software rather
than somebody using it.

So `tools/demo.py` drives a real Chromium through a written beat list, with a
cursor injected into the page and tweened between targets at a constant
1400 px/s. Three properties fall out of that, and all three matter more than
they sound:

**Pacing is a table.** Every dwell is a number in `BEATS`. When a line comes in
four seconds long, change the integer and re-render — the alternative is
re-shooting a four-minute take because one sentence ran over.

**It cannot miss.** Targets are selectors. It will not click the wrong row when
the worklist reorders, and it cannot fumble a form.

**It re-shoots in one command.** This UI is under active development — a guided
tour and a landing screen landed the week this was written. Footage that costs
an afternoon to re-record is footage nobody re-records, and the film silently
goes stale.

### Two things it refuses to do

**Ship the development banner.** The local server renders a
development-credential notice, true of the machine and false of the deployed
product. It is stripped on every navigation *and asserted gone* —
`tools/shots.py` once shipped fourteen screenshots with that banner because its
selector was wrong and nothing checked.

**Use `?tour=`.** The guided tour is the right thing for a first-time user and
would fight the voiceover for the same attention.

---

## What each piece is

| | |
|---|---|
| `tools/demo_seed.py` | The starting state. Wipes the demo tenant so shot 3 shows somebody *loading* the sample rather than finding it already there, regenerates batches, signs the authority bundles, and burns the first-close import cost on a throwaway close nobody films. |
| `tools/demo.py` | Shots 3–8 and 10, in one continuous capture. Logs where each beat landed. |
| `motion/src/*.tsx` | Shots 1, 2 and 11, plus a `Fence` inset for shot 6. Remotion, 1080p60. |
| `tools/demo_verify_shot.sh` | Shot 9, in a terminal. Points at the **deployed** host on purpose. |
| `tools/demo_assemble.py` | Cuts the capture at the logged beats, normalises geometry, concatenates, and overlays the timecode strip. |

---

## Three things that bit, and what they taught

**The close beat burned 47 seconds on a 120-millisecond close.** The processing
page refreshes itself once a second and, when the job finishes, *stays where it
is* — it drops the refresh and grows an “Open the close” link. The first version
waited for the URL to change, which never happens, and sat there until its
45-second deadline. Waiting on the completion marker instead made the shot
better as well as shorter: it now holds on the receipt that says **no model was
involved**, then clicks through.

**Shot 6 recorded nothing the first time.** The worklist ranks by cash impact ×
age and the heaviest item is an `E06` the engine *derived*, so the model is
correctly not offered on it. The film has to stand on an `E14` — the place where
the arithmetic ran out is the only place a model belongs, and it is the shot the
whole thesis turns on. The recorder now targets one and **fails loudly** if the
corpus stops producing one, rather than filming an empty panel.

**The timecode overlay was rendering 16,474 PNG frames at 1080p.** Alpha forces
PNG, and that took longer than every other step combined to composite a bar
occupying six percent of the picture. It is a 1920×72 opaque strip now, encoded
from JPEG frames, dropped at the bottom edge with `overlay`. (`drawtext` was the
obvious answer and is unavailable — the ffmpeg here is built without
libfreetype, so the filter is absent entirely and no font path fixes it.)

---

## Before you roll

- `make replay` on the morning of. The script quotes the tier split and the item
  count; both must match what the recording shows.
- `DEEPSEEK_API_KEY` exported **in the server's environment**, not just yours.
  Shot 6 makes a real call, and a slow day is a longer dwell, not a faked panel.
- Rehearse first: `make demo SCALE=0.15` runs the whole path in a fifth of the
  time and proves every selector still resolves.

**Every number in every graphic is a real number from a real run.** ₹51,990.42
is the credit from `docs/10-THE-USER-FLOW.md`; the tampered verification in shot
9 refutes against that same figure. If a figure cannot be traced to
`make replay` or `make eval`, it does not go on screen — a demo that overstated
the engine would be the exact defect this product exists to refuse, and it is
the first thing an informed viewer will check.
