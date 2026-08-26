# The screens, start to finish

*Written 2026-08-26 after the data-sources page was described as "so confusing on
what source to add where and what". It was, and the reason was that no screen
ever said what the product is for.*

Each screen answers one question. If a screen cannot be described by one, it is
doing two jobs and should be two screens.

---

## The journey

```
  Sign in  ──▶  Data sources  ──▶  Close a period  ──▶  Worklist  ──▶  Item  ──▶  Sign off  ──▶  Close pack
              "what do I feed it"   "run it"        "what's on    "resolve    "I accept   "hand this
                                                     my desk"      this one"    it"        to the auditor"
```

Six steps. A person who has never seen this should get from the first to the
last without asking anybody, and the only place they should have to think is the
Item screen — because that is where the actual judgement is.

---

## What each screen says

### Data sources — *"what do I feed it?"*

Opens with **what this is**: a reconciliation compares two independent records
of the same money and proves every match from the raw rows; whatever cannot be
matched becomes a ranked worklist with a named reason.

Then, once, why there are **two** reconciliations:

| | |
|---|---|
| **Money from your payment gateway** | Did every rupee the gateway says it paid out actually arrive in the bank? |
| **Tax deducted at source** | Has every rupee of tax withheld from you actually reached the government against your PAN? |

**One button** — *Load the example data* — brings a worked example for both.
There used to be three, one per loop plus one at the bottom, so a person had to
guess which gave them a working example. The answer was all of them, separately.

Bring-your-own is behind a disclosure. Four file pickers open by default were
most of why this screen read as a form rather than as a thing to try. Each picker
names **what to go and find** — "Form 26AS: download it from the TRACES portal as
text" — with the filename we save it under as the detail underneath.

**A period belongs to one loop.** Before, every loop listed every directory, so
the settlement screen reported the tax period as *"missing
bank_icici_camt053.xml"*. True, and nonsense: it was never a candidate.

### Close a period — *"run it"*

Says what pressing the button *does*: reads one period's two files, matches what
it can prove, writes the journal entries, hands back everything it could not
match, takes a few seconds.

Each loop shows only its own periods. A period short of a file stays on the list,
named for what it lacks and un-closeable — *"where is October?"* answered with
silence is the same failure as a filter before the completeness audit.

### The close ran — *"what happened"*

Six stages, each reporting the fact it produced: rows read, pairs narrowed,
matches proposed, matches re-derived, entries written, events sealed. **No model
runs here**, and the receipt says so.

### Worklist — *"what is on my desk"*

Every open item across every close, ranked by cash impact × age, routed by desk.
Three states, because they need three different things from a person:

| | |
|---|---|
| **derived** | the arithmetic named it — act on it |
| **either / or** | the files cannot separate two causes — go and get the third document |
| **unexplained** | no reading at all — read the evidence yourself |

One line each; the full reading is on the item. Every row opens the item it
describes.

**One error is one row.** A two-sided break used to appear twice, once per
unmatched record.

### Item — *"resolve this one"*

The only screen that asks for judgement. What the engine says, the near misses it
derived, the records, the model's reading if you ask for one, and then:

**Resolve it — pick one.** An unresolved break stays on the worklist and blocks
sign-off. Each ending writes a journal entry, moves the money where it belongs,
and takes the item off your desk.

| | |
|---|---|
| **Book it** | the difference is real and explained → an expense |
| **Carry forward** | timing, the money has not landed → cash in transit, an asset |
| **Chase it** | somebody owes us → a receivable with an owner and a date |
| **Write it off** | value leaving for good → bounded twice by the signed policy |

All four are `P2 ATTESTED` and carry your name. This was headed *"How this ends"*,
which said nothing about what it was for.

### Check the arithmetic — *"can this be checked without trusting us?"*

Two readers, one question, and it used to serve one of them. An auditor gets the
four steps — fetch the files, confirm each sha256, `POST /v1/verify` with no
account, confirm the hash chain — because that claim is what the product rests
on and is written out rather than asserted.

A **signed-in controller** gets a button. Their version of the question is
"re-check the close I just ran", and they were being handed curl. Same code path
either way: `service.reverify` routes through the same stateless `check` an
external caller gets, because a re-derivation taking an internal shortcut would
be measuring the shortcut.

Renders with no session at all. Requiring a login here would undercut the claim.

### What this account runs under — *"what am I being judged by, and who says so?"*

Was "Settings", which promises things you can change; nothing here is changeable
and the page now says **why** — a screen of values with no controls reads as
half-built unless it explains itself. The reason is the whole control plane: a
system where the person being judged can edit the judgement has no control.

Three tables, each with the sentence that makes it mean something: bundles are
signed with a key held outside them (one naming its own verification key would
vouch for itself); a rule reaches the list only by passing a regression against
every historical match *and* a named approval; and naming a code grants nothing
— labelling is free, directing a journal entry needs promotion with a written
definition.

The tolerance shows as a figure with what it *does* beside it — "largest gap
absorbed silently, above this an item is raised, never rounded away" — not as a
labelled number.

### Let an assistant help — *"can I let an AI work on this, and what could it do?"*

Was "Agent access", opening with *"point an agent at this controller over MCP"* —
three pieces of jargon before the first full stop, assuming the reader already
knows what MCP is and why they would want one. Somebody closing books for a
living does not, and does not have to.

Now: **what it could do for you**, in a controller's words — *"what is blocking
the October close, biggest first?"* — then how to connect, then the part that is
actually interesting.

**What it cannot do** is stated as things, not as parameter names. Not "no tool
accepts a policy", which is true and means nothing to the person deciding, but
"it cannot sign off a close, because sign-off names a person and it cannot name
one". Checked against the tool definitions on every render.

The eighteen-tool reference is real and belongs on the page. It does not belong
between why-you-would and how-to, so it is behind a disclosure, as is the
run-it-locally case.

### Sign off — *"I accept this"*

A named person, a note, and the count of what was still open at signature. The
pack never says "approved" for a close nobody approved.

### Close pack — *"hand this to the auditor"*

The seal, the figures, every source file with its hash and the spec that parsed
it, the journal with both downloads, the tail, the signed authority, and *check
this without us*.

---

## The rules the screens follow

**One question per screen.** Named at the top, in the words a controller would
use, not ours.

**A number is never alone.** A rate ships with its decomposition; a count of
items says what kind; an amount says what is at stake.

**An identifier is a detail, not a title.** `settlement_3way` and
`tds-26as-in@v1` matter — an auditor asks which policy a close ran under — and
they sit below the sentence, not in place of it.

**Say what a button does before it is pressed.** Especially the ones that cannot
be: a disabled control names what it is waiting for.

**Never claim more than the record holds.** An unsigned close says so where a
reader looks first. A provisional code says it may label and route and not direct
a posting. An ambiguity names both candidates rather than picking.

---

## Still rough

- There is no empty state on **Worklist** for an account that has closed a period
  and resolved everything — the good ending is unwritten.
- Nothing on any screen explains *why* a close is worth running to somebody who
  has not already decided to run one. That is a landing page, and there is none.
