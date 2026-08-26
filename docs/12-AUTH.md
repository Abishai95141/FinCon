# Signing in, and what the two tabs cost

*Written 2026-08-26, when sign-in and create-account became separate screens.*

## The bug

`auth.confirm()` and `auth.resend()` were implemented, granted in IAM, and
referenced **nowhere** in `ui.py`. So a new account was told

> Confirm your email to finish signing in.

by a form that offered no way to do it. Cognito had sent a six-digit code and the
product had no field to type it into. That is the defect this codebase keeps
finding — a capability nothing exercises — sitting in front of every new user.

There is now a `/confirm` screen with the code field and a resend button, and
both sign-in and sign-up route to it when the account is unconfirmed.

## The trade

One form used to do both. It called `identity.exists(email)` and routed
accordingly, which had a real property: **the failure text was identical for an
unknown address and a wrong password**, so the screen could not be used to find
out who has an account.

Splitting the tabs costs that, on one path. Create-account has to say

> An account with that email already exists. Sign in instead.

or somebody who typo'd into the wrong tab is told it worked and then cannot sign
in. That sentence is an account-enumeration oracle: anyone can type addresses in
and learn which have FinCon accounts. For a finance product that is a phishing
list with the targets pre-qualified — *"your October close is blocked, sign in
here."*

**We took it deliberately**, because the merged form failed people in a way that
had no workaround, and because the alternative has its own cost (below).

### What we did instead of hiding it

| | |
|---|---|
| **Sign-in keeps the property.** | Unknown address and wrong password are still one message. Splitting cost it once; it must not cost it twice. |
| **The leak is bounded.** | `throttle.SIGNUP` — five per source address per five minutes. A person creating one account never notices; a thousand-address list takes a fortnight per source. |
| **Counted by caller, never by the address asked about.** | Keyed on the email, one attacker walks a list at full speed by never repeating a value, which is the attack. |

### The bound is honest about being small

`throttle.THROTTLE` is **per-process and in-memory**. It resets on deploy and
does not add up across tasks. With one Fargate task that is the whole system;
with two it is half a bound, and the fix then is a shared store, not a bigger
number. `THROTTLE.state()` reports `shared_across_tasks: False` so no surface can
overstate it.

## The way out

The strongest version is what Google and Stripe do: signup **always** answers
"check your email for a code", and an address that already has an account gets a
*different email* — "you already have an account, here is a sign-in link". The
disambiguation moves into the mailbox, which only the owner reads, and the leak
disappears.

We did not do that yet for one reason: the pool sends through **Cognito's own
email service at 50 messages/day** and there is no SES production access. That
version's failure mode is a person staring at a screen waiting for an email that
may be the day's fifty-first. It is a two-line change to `signup_submit` once SES
production access lands, and it should be made then.

## Two bugs the split introduced, both in the token

Worth recording because neither was visible to any existing test.

**The page minted one token and the cookie got another.** `new_csrf()` was called
twice for one render, so a **first-time visitor's first submit was a 403**. Every
other test in the repo starts from a client that already holds a cookie, so the
only person who could hit it was somebody arriving at FinCon for the first time
— which is every real new user and no test.

**Then the fix had its own version.** The auth pages are f-strings, so a
`{{csrf}}` placeholder renders as the literal `{csrf}` and the token still never
lands. The sentinel is `CSRF_SLOT` now, which cannot collide with brace escaping.

`test_a_first_time_visitor_can_submit_the_very_first_form` builds a fresh client
per screen and asserts the form token equals the cookie.

## Operationally, today

- The pool auto-verifies email and sends `CONFIRM_WITH_CODE` through
  `COGNITO_DEFAULT`. Codes do arrive; they are valid 24 hours.
- **SES has no production access**, so it is 50/day and the sender is Amazon's.
- An address that is not a real mailbox never gets a code. Confirm it by hand:
  `aws cognito-idp admin-confirm-sign-up --user-pool-id <pool> --username <sub>`.
