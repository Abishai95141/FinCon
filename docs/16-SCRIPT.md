# The voiceover script

*Timed against `demo/cut-timecoded.mp4`. Every timecode is read from
`demo/shots.json`, which the assembler writes.*

Read it against picture, not against this page. The burnt-in strip shows the
shot number and how many seconds are left in the shot.

## How this is written

The first draft opened nearly every paragraph with a line that sounded good and
explained nothing — *"That's a plug"*, *"What didn't match is the work"*,
*"Here is the part that matters"* — and then moved on before saying what the
thing actually was. Shot 5 used five undefined terms in seventy-five words.
Somebody who has never done a reconciliation would have finished the film
impressed and none the wiser.

So the rules for this draft:

**Say what is on screen.** Not what it signifies. If the shot shows a list, the
line says what is in the list.

**Define a word before using it, or don't use it.** *Plug*, *close*, *proof*
and *unexplained* each get one plain sentence the first time. `T0`, `P0`,
*residual*, *tolerance* and *blocking recall* are on screen and are never
spoken — a viewer can read a label; they cannot decode a term they have not
been given.

**No arguing with the audience.** *"Because a headline rate on its own is
gameable"* is a rebuttal to a sceptic who is not in the room. Show the number,
say what it means, move on.

**Lead with what the AI does, not what it is stopped from doing.** The second
draft mentioned AI four times and three of those were limits — it can't post,
can't overwrite, isn't used in the close. All true, none of it a reason to
want the product. Shot 6 now shows an answer: an item nobody could account
for, named as a fee variance. The limits still appear, once, where they
belong — after the thing they are protecting.

**Numbers keep their meaning attached.** "Twenty of the twenty-three bank
deposits" rather than "twenty of twenty-three".

**Pace.** 684 words over 5:05 — about **135 words a minute**. Explaining costs
words, and the AI shots cost the most: 6 and 7 carry the argument and were
widened by six seconds each rather than having their sentences compressed back
into slogans. Run `make script-check` after any edit; it reads each block
against the real shot length and fails anything that cannot be read at
150 wpm.

**Every figure is real**, from `make replay` and from the recording. Improvising
a number makes it false.

---

## 1 · 0:00 – 0:21 · the plug

> A payment gateway pays you in batches.
>
> This one deposit covers forty sales, less the gateway's fee, less two
> refunds, less a chargeback that came in late.
>
> The amounts don't line up — so the accountant parks the difference in a
> holding account and moves on.

Land "parks the difference" as the **Suspense : Unreconciled** row appears,
around 14 seconds. Let the last four seconds run silent.

---

## 2 · 0:21 – 0:56 · the match is not the problem

> That holding account is called a plug, and it hides real problems — money that
> never arrived, a fee charged twice, a refund against the wrong sale.
>
> Most accounting software already matches the easy transactions, ninety to
> ninety-nine percent of them. That part is solved.
>
> The problem is the rest. When something doesn't match, the software lists it
> and stops. No reason, no ranking. Somebody works through them by hand, and the
> same ones come back next month.

The two columns build left then right. Pause before shot 3.

---

## 3 · 0:56 – 1:13 · sign in, and what this is

> FinCon does that second part.
>
> You sign in, and the first screen explains the job: compare your bank
> statement against what the payment gateway says it sent you.
>
> This button loads a worked example, so you can run one now.

16.9 seconds and the tightest in the film at 142 wpm. Nothing can be added
here without widening the beat and re-recording.

---

## 4 · 1:13 – 1:43 · close a period

> A period is one month. Closing it means proving those two records agree.
>
> Six steps: read both files, work out which rows could pair up, pair them,
> re-check every pair by recalculating it, write the accounting entries, and
> save a record of every decision made.
>
> It takes about a second, and every pairing there is arithmetic — no AI
> involved, which is what that line on screen is confirming.

The stages fill in sequence. Keep this one brisk — the AI is the next two
shots, and dwelling here on what it *doesn't* do sets the wrong expectation
for them.

---

## 5 · 1:43 – 2:19 · the scorecard, and a proof

> Twenty of the twenty-three bank deposits matched. Seventeen exactly; three
> took more working out.
>
> Nineteen of those matches are pure arithmetic — anyone can recheck them from
> the original files. One rests on a stated assumption, and it's labelled as
> one.
>
> The books balance.
>
> Open any match and you see the working: which rows on each side, and the
> difference between them coming to zero. That's a proof, not a score. The
> software isn't telling you it's confident. It's showing you the sum.

The longest line, against 35.5 seconds. Slow down on the last two sentences.

---

## 6 · 2:19 – 3:03 · the tail, and the model

> Seven things to deal with, sorted by how much money is at stake.
>
> Some say "unexplained" — the arithmetic found nothing close enough on the
> other side, so it won't guess.
>
> This is what the AI is for. Nearly forty thousand rupees nobody could
> account for. Ask, and it reads the twelve rows underneath and answers:
> Razorpay settled this batch on one set of fee terms, but these fee rows
> disagree with the others. A fee variance — and it says a person has to
> decide which side is wrong.
>
> That's a lead, out of a line that said nothing.

The longest shot. The call takes about two seconds on screen — stay silent
through it, then read the answer off the panel as it appears.

**The item is chosen by `make demo-pick`, which asks the model first.** The
first cut used the top unexplained item and the model returned "unexplained"
again — a true answer, and thirty seconds of the AI doing nothing in the shot
that carries the whole argument. The recorder now refuses to film an item
where the answer echoes the code back.

---

## 7 · 3:03 – 3:34 · four endings

> It won't always have an answer, and it says so when it doesn't. About half
> the time it names something the arithmetic couldn't.
>
> It only ever proposes. Nothing moves until you agree.
>
> Four ways to finish an item: record it as a cost, expect it next month,
> chase someone for the money, or write it off. Chasing needs a name and a
> date, or nobody follows it up.

"About half the time" is the measured figure — `make replay` reports
classification at 50%. Say it plainly rather than skipping it: a viewer who
suspects the demo was cherry-picked stops believing the rest, and this is the
sentence that answers them.

---

## 8 · 3:34 – 4:07 · sign off, and the pack

> Whichever you choose writes a real accounting entry with your name on it.
>
> Then you sign off. It won't let you sign until every item has been looked at.
>
> Your signature is stored separately from the software's own record, so it's
> always clear which decisions the machine made and which ones you made.
>
> And this is what you hand your auditor: the source files with their
> checksums, the entries, and anything still open.

The pack scrolls for six seconds. Read the last list over the scroll.

---

## 9 · 4:07 – 4:32 · check it without us

> Your auditor doesn't have to take any of this on trust.
>
> They send one of these proofs to a public web address — no login, nothing of
> ours involved — and it recalculates the sum.
>
> Change one number by a single rupee, and it comes back rejected, naming the
> exact total that stopped adding up.

22.7 seconds. The transcript is two real requests to the deployed service,
captured by `make demo-verify` — the rejection on screen is one the live server
actually returned. Let it sit.

---

## 10 · 4:32 – 4:53 · point an assistant at it

> You can also connect an AI assistant to this.
>
> It can run a close, work through an item, even sign off — acting as you, using
> a key you gave it.
>
> And every action it takes is recorded as having come from an assistant, so you
> can always tell afterwards.

20.9 seconds. This is the second time the AI comes up, from the other side:
shot 6 showed what it does, this shows what is written down when it does it.

---

## 11 · 4:53 – 5:04 · the card

> FinCon. Every match shows its working, and everything left over comes with a
> reason.
>
> It's live now, and the code is public.

Short on purpose. The card holds fourteen seconds — let the last four run
silent under the address.

---

## If a line doesn't fit

Change the timing, not the sentence. Every pause is a number in `BEATS` in
[tools/demo.py](../tools/demo.py); widen the tight one and re-run
`make demo && make demo-cut`. Re-timing takes about three minutes, which is the
reason the footage is scripted rather than hand-recorded.

**Don't speed up to fit.** At 135 words a minute this sounds like someone
explaining their work. At 160 it sounds like someone selling something, and
the film is making the opposite case.
