# The voiceover script

*Timed against `demo/cut-timecoded.mp4`. Every timecode below is read from
`demo/shots.json`, which the assembler writes — not from the plan.*

Read it against picture, not against this page. The burnt-in strip shows the
shot number and **seconds left in the shot**, so when a line runs out of room
you can see it happen rather than discover it in the mix.

**Pace.** 548 words over 4:23 — **125 words a minute**, plus 52 more for shot 9
when it is recorded. Slow for narration, deliberately: every sentence here
carries a number or a claim, and a listener needs the gap between them.

Don't count words by hand. `make script-check` reads the block and the real
shot length and prints the rate and the slack for each — the first version of
this page asserted a count per shot and every one of the ten was wrong, which
is what a hand-maintained number beside a computable one always comes to.
It fails on any line that cannot be read at 150 wpm.

**Every figure is real.** They come from `make replay` on batch A and from the
recording itself. If you improvise a number, it stops being true.

---

## 1 · 0:00 – 0:18 · the plug

> One line on a bank statement.
>
> Not one sale — forty charges, minus the gateway's fee, two refunds, and a
> chargeback that arrived after the period closed.
>
> The books have to tie tonight. So the difference goes… here.

Land "here" as the **Suspense : Unreconciled** row appears, about
14 seconds in. The stamp that says *plug* follows it — let it sit silent.

---

## 2 · 0:18 – 0:50 · the match is not the problem

> That's a plug. Every controller knows it, and every reconciliation tool leaves
> room for one.
>
> Not because matching is hard. Matching is solved — Trintech publishes
> ninety-nine per cent, and the industry bar is ninety.
>
> What nobody solved is the remainder. It comes back as a flat queue with no
> reason attached. And it's the same queue every month.

The two columns build left then right. "The same queue every month"
wants a beat before shot 3 cuts in.

---

## 3 · 0:50 – 1:07 · sign in, and what this is

> This is FinCon.
>
> Sign in, and the first screen says what a reconciliation actually is: two
> independent records of the same money.
>
> Load the worked example — real files, whose answers are already known.

Tight shot, 16.9s. Don't add to it.

---

## 4 · 1:07 – 1:36 · close a period

> A period is one month of one reconciliation. Press close.
>
> Six stages — read the rows, narrow the candidates, match, re-derive every
> match, write the journal, seal the record.
>
> And read the receipt: **no model ran.** Not one call, at any stage. Every
> match in here is arithmetic over raw rows, which is the only kind of number a
> controller can defend.

The stages fill in sequence. "No model ran" should land while that
line is on screen.

---

## 5 · 1:36 – 2:11 · the scorecard, and a proof

> Twenty of twenty-three matched. Eighty-seven per cent — with the split beside
> it, always, because a headline rate on its own is gameable.
>
> Nineteen rest on arithmetic; one on a declared gap, and it says so.
>
> Blocking recall reads *absent*, not zero. We haven't measured it, so we don't
> claim it.
>
> Open any match and this is the proof: both sides, the residual closing to
> zero, the tolerance spent. Not a confidence score — arithmetic.

The longest line in the film against 35.5s. The *absent* sentence
is the one to slow down on.

---

## 6 · 2:11 – 2:50 · the tail, and the model

> What didn't match is the work.
>
> Seven items, ranked by cash impact times age, each routed to a desk. Three of
> them say **E14 — unexplained**: the engine cannot say why, and it says that
> rather than guessing.
>
> Open one. Eighty-four thousand rupees. No near miss — nothing on the other
> side agrees on any key component.
>
> This is where the model belongs: the place the arithmetic ran out. One call,
> one exception. It sees the amounts, the dates and the keys — and it cannot
> write anything.

38.8s, the longest shot. The model call takes about two seconds on
screen; let it happen in silence rather than talking over it.

---

## 7 · 2:50 – 3:15 · four endings

> Its answer goes through the same checker before you're shown it. And it
> moves nothing — a proposal stays a proposal.
>
> You decide. Four endings: book it, carry it forward, chase it, write it off.
>
> Chase needs an owner and a date, because a receivable with no date is never
> late.

That last clause is the product's own refusal text, verbatim. It is
worth saying exactly.

---

## 8 · 3:15 – 3:48 · sign off, and the pack

> Each ending writes double entry, under your name.
>
> Now sign off. Nothing outstanding — and sign-off refuses while any item is
> untaken, which is the entire point of having one.
>
> Signed, by a named person, in a record chained separately from the engine's:
> what the machine decided and what a person decided are two different
> statements.
>
> And the close pack — the seal, the figures, every source file with its hash,
> the journal, and the tail.

The pack scrolls for six seconds. Narrate the list over the scroll.

---

## 9 · check it without us  *(not yet recorded)*

> Here is the part that matters.
>
> An auditor doesn't have to trust us. Post the proof to a public endpoint — no
> account, none of our state — and it re-derives the arithmetic itself.
>
> Change one number by a single rupee, and it refuses. Naming the leg whose
> subtotal stopped adding up.

Budget about 24s. Record `tools/demo_verify_shot.sh` full-screen,
save to `demo/verify.mp4`, then `make demo-cut` — the assembler slots it here
and every timecode after this point shifts by its length.

---

## 10 · 3:48 – 4:09 · point an assistant at it

> And you can point an assistant at this.
>
> Twenty-one tools over MCP. It can close a period, resolve an item, even sign
> off — as you, because it's holding a token you issued.
>
> What it can't do is act without the record saying an assistant did it.

20.9s. This is the AI claim landing for the second time, from the
other side — first that it does real work, now that it's fenced.

---

## 11 · 4:09 – 4:23 · the card

> Close the books with a proof, not a plug.
>
> FinCon. It's live, and the whole thing is open.

Deliberately short. The card holds for fourteen seconds; let the
last four run silent under the URL.

---

## If a line doesn't fit

Change the number, not the sentence. Every dwell is an entry in `BEATS` in
[tools/demo.py](../tools/demo.py) — widen the one that's tight and re-run
`make demo && make demo-cut`. That is the whole reason the footage is scripted:
retiming costs three minutes, and re-shooting a four-minute take by hand costs
an afternoon and never quite matches.

**What not to do:** speed up to fit. At 125 words a minute this reads as
somebody who knows the system. At 160 it reads as somebody selling it, which is
the opposite of the argument the film is making — and shot 7 was at 159 until
the checker said so.
