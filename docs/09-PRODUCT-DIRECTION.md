# Product direction — PROPOSED, not approved, not built

Date: 2026-08-25. Artifact: https://claude.ai/code/artifact/22e06f61-e217-4959-943c-692dffd14479

**Status: awaiting approval.** Nothing in §§2–6 exists. This file is the durable
mirror of the artifact so the URL and the reasoning survive the conversation that
produced them. When a decision here is taken, it moves into an ADR or into
`06-PLAN-V2.md`; until then it is a proposal and this heading says so.

---

## 1. What is already built and verified

| Was | Now |
|---|---|
| `run_match` returned **397 KB** — ~100k tokens, most of a context window, for 543 rows | **28 KB**. Events 114→20, close 58→16, audit 54→42 |
| Two concurrent closes corrupted the record and reported it as **tampering** | 8 threads / 6 processes, one identical result, chain verifies |

A **byte** budget, not a row count: rows differ in size by two orders of
magnitude. Nothing is capped silently — `total` is real, `next_offset` exists
exactly when more remains, `stopped_at_budget` says why a page ended. The lock is
`flock` on a *sidecar*, because the writer deletes the log and a lock on a deleted
inode protects nothing; readers take a shared lock, which is where the symptom
appeared.

One defect introduced while fixing the first: with proofs withheld at
`detail=summary` the proof-tier split was counted off the withheld proofs, so
every match read `unrecorded`. A projection must never change an answer —
`test_a_projection_never_changes_an_answer` is what holds it.

607 offline tests · p20 12/12 · p19 20/20.

---

## 2. The journey

**Sign in → Periods → Add sources → Close → Review → Work the tail → Close pack.**

One linear spine, no branch a controller has to think about. A correction produces
a **new** close with its own record — the run id is derived from the source bytes
and the authority in force, so nothing overwrites a prior answer.

A period is always in exactly one state:
`Draft → Ready → Closing → Needs review → Signed off`, with `Blocked` (books do
not balance, or a rule broke a match) as a distinct terminal state that is never
silent.

The six questions, answered by construction:

| Question | What answers it |
|---|---|
| Where am I | A breadcrumb that is always three parts: `Settlement · October 2026 · Needs review`. The third part is the *state*, not a page name. |
| What is it doing | The six real stages — ingest, block, match, verify, post, record — each reporting the fact it produced. Not a spinner. |
| What next | Exactly one primary action per screen. Two would be two screens. |
| What is done | The period list is the completion record. Rates carry their decomposition (`20/23`), never a bare percentage. |
| What needs me | A count on `Needs review`; the worklist ranked by cash impact × age; unratified codes marked as such. |
| Where are my results | The **close pack** — one downloadable self-contained bundle. Nothing else is a "final output". |

**Deliberately absent:** dashboard-first landing, onboarding wizard, notifications
centre, settings a first-time user must visit.

## 3. Screens

`/` sign-in (public) · `/verify` (**public** — an auditor should not need an
account) · `/periods` (home) · `/periods/new` · `/periods/{id}` ·
`/periods/{id}/items/{n}` (drawer) · `/periods/{id}/pack`.

Thin left rail, four destinations, account at the bottom. Rail rather than top nav
so the top edge stays free for breadcrumb + state, and so there is room when the
second loop lands.

## 4. Design direction — "glass for the frame, paper for the evidence"

Glassmorphism's real problem: the effective background of a glass panel is
whatever shows through it, so contrast varies pixel by pixel. A governance tool
whose numbers are sometimes unreadable is a contradiction. So glass gets a job:
the shell, the login, overlays, the verify surface — and **never** under a number,
a table row, or a proof.

Spec: `backdrop-filter: blur(12px) saturate(1.15)`, a tint with an opacity floor
that holds 4.5:1 regardless of backdrop, one 1px top-edge highlight, no outer
glow, solid fallback under `@supports not (backdrop-filter)` and
`prefers-reduced-transparency`.

**Colour.** Monochrome cool-biased base, one accent. Ground `#F0F4FA`, ink
`#0C1526`, muted `#5F6D87`, accent `#1B3FA0` (deep ink blue, not the Tailwind
default), azure `#4A9BF0` **as glass tint only — it never carries text**.

**The palette carries the epistemics.** The proof tiers *are* the semantic set:
`P0` takes the accent (re-derivable arithmetic is the strongest evidence), `P1`
green, `P2` amber (a *person* is accountable), `P3` outlined and dashed (a stated
gap is not a success and must not be tinted like one).

**Type.** IBM Plex Sans (UI) + IBM Plex Mono (money, ids, digests, proofs;
`tabular-nums` everywhere) + IBM Plex Serif for exactly one editorial moment, the
login's identity panel. Not Inter — that is the default that makes a page read as
generated. Alternative: Geist / Geist Mono, colder and more engineered.

**Icons.** Lucide — 24px grid, 2px stroke, MIT. 16px in tables, 20px in the rail,
never decorative, always labelled when meaning-bearing.

**Density.** Visually sparse, interaction-dense. Whitespace goes around tables,
not inside them.

## 5. Login

Asymmetric vertical split, 40/60. Left: a narrow, quiet, **opaque** form column —
one field decides sign-in vs sign-up, no tabs. Right: the only place in the
product where a gradient is permitted, carrying a **real proof** rendered in the
real monospace rather than a stock illustration. The auditor's door (`/verify`)
is on the login screen. On narrow screens the identity panel collapses to one line
above the form rather than stacking as a block nobody scrolls past.

## 6. AWS — probed, not assumed

Account `531728396678`, `ap-south-1`, AdministratorAccess. **Shared with another
project** (`fampire`: `c7i-flex.large`, RDS `db.t4g.micro`, ECR, S3, 3 secrets).
**App Runner is unavailable** — `SubscriptionRequiredException`.

CloudFront (TLS, rate limit on `/verify`) → one always-warm ECS Fargate task
(0.25 vCPU / 0.5 GB) in a private subnet. Cognito for identity, tenant = `sub`.
S3 for everything durable. **No database, deliberately** — users live in Cognito,
the durable record is a file, a run index is an S3 prefix. Postgres to hold a list
of files is the infrastructure we were asked to avoid; it arrives when cross-close
history does.

**The strongest item costs the least: S3 Object Lock in compliance mode on the
decision logs.** `recon/journal` says outright that a hash chain proves internal
consistency and *not custody*. Object Lock is the missing half — the chain proves
the contents, the store proves nobody touched them.

**And what that breaks.** The `flock` write lock is correct on one host and
**meaningless across two**. One task keeps it correct. Two tasks require an S3
conditional write (`If-None-Match`) or a DynamoDB lock table. This belongs in the
deploy docs, not in a discovery.

Estimated ~**$15/month** (list price, not measured). NAT Gateway deliberately
avoided — it alone would be ~$35; VPC endpoints for S3 and ECR instead.
Fargate ~$9 dominates.

**Security.** Authority stays non-configurable at the deployment boundary too:
policy, taxonomy and rules ship *in the image*, verified against a signature whose
public key comes from SSM, out of band. No environment variable can widen what a
close accepts. Tenant prefix resolved from the session, never from the request.
`data/trust/dev-signing-key.hex` must be excluded from the image by a build step
**and a test**. Recommend moving the signing key to KMS asymmetric (ECDSA P-256)
so the private key never leaves the HSM — a change to `trust.py`, needs a decision.

**Nine declared dependencies are imported in zero files** — polars (184 MB),
duckdb (43 MB), splink, sqlalchemy, psycopg, ofxparse, calamine, anthropic,
beanquery: ~350 MB of a 553 MB tree. Pruning cuts the image by two-thirds and
removes unused attack surface.

**Observability without duplication.** CloudWatch carries operational truth
(latency, 5xx, task health); the decision log carries business truth. They meet at
one alarm: a close whose chain does not verify, or which finishes `ok=false`.

## 7. What I pushed back on

- Glass is **constrained, not adopted**. More glass than §4 allows costs legibility
  of money.
- **Resolution is not in v1.** A worklist you cannot act on is a report — but
  resolving *with a posting* needs the attestation path, which is the most
  carefully guarded part of this codebase. v1 acknowledges, assigns, annotates.
- **One loop only.** The generality claim is still asserted; the UI must not imply
  a product that reconciles "anything".
- **Toy scale.** 22 payouts, ~540 rows, two synthetic batches. The upload path is
  where that hurts first.
- **The AWS account is shared.** Defensible for a demo, not for a customer.

## 8. Open decisions

1. Approve the journey / screens / rail — or say where the flow is wrong. The
   period-first list over a dashboard is a real bet.
2. IBM Plex or Geist.
3. KMS asymmetric signing key, or Ed25519 in Secrets Manager for now.
4. **Only you can do these:** a domain name for the certificate, and an SES
   sandbox exit if email verification should actually work.

**Build order on approval:** prune dependencies and containerise → Cognito and the
split login → S3-backed storage with tenant prefixes → period and close screens
over the existing service → deploy → the close pack.
