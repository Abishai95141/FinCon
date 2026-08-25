"""Point Cognito at SES, once the sender identity is verified.

Two steps, and only one of them is mine. Creating the identity makes AWS email a
verification link to that address; clicking it is the account owner's to do.
This finishes the job afterwards, and refuses clearly if the click has not
happened rather than leaving Cognito half-configured.

    python -m tools.wire_ses --check      # is the identity verified yet?
    python -m tools.wire_ses              # verified? then wire the pool to it

**The sandbox limit is real and is not a bug.** In sandbox SES delivers only to
*verified* addresses, so a stranger signing up gets no email. Leaving the pool on
COGNITO_DEFAULT would cap at 50/day and look like it works; wiring SES caps at
200/day and only reaches addresses you have verified. Neither is production.
Production access is a request through the SES console, and it is the account
owner's to make.
"""

from __future__ import annotations

import argparse
import sys

REGION = "ap-south-1"
SENDER = "tarunstark3000@gmail.com"
POOL = "ap-south-1_kNSrctMRo"
CONFIG_SET = "fincon-auth"


def main(argv: list[str] | None = None) -> int:
    import boto3

    ap = argparse.ArgumentParser(prog="tools.wire_ses")
    ap.add_argument("--check", action="store_true", help="report status and stop")
    ap.add_argument("--sender", default=SENDER)
    ap.add_argument("--pool", default=POOL)
    args = ap.parse_args(argv)

    ses = boto3.client("sesv2", region_name=REGION)
    identity = ses.get_email_identity(EmailIdentity=args.sender)
    verified = identity["VerifiedForSendingStatus"]
    account = ses.get_account()
    production = account.get("ProductionAccessEnabled", False)

    print(f"sender    {args.sender}: {'verified' if verified else 'NOT VERIFIED'}")
    print(f"account   {'production' if production else 'SANDBOX — only verified recipients'}")
    print(f"quota     {account['SendQuota']['Max24HourSend']:.0f}/day")

    if not verified:
        print(
            f"\nAWS emailed a verification link to {args.sender}. Click it, then run "
            f"this again. Until then Cognito stays on its own sender, which is "
            f"capped at 50/day — wiring SES to an unverified identity would fail "
            f"every sign-up instead of some."
        )
        return 1
    if args.check:
        return 0

    account_id = boto3.client("sts").get_caller_identity()["Account"]
    arn = f"arn:aws:ses:{REGION}:{account_id}:identity/{args.sender}"
    boto3.client("cognito-idp", region_name=REGION).update_user_pool(
        UserPoolId=args.pool,
        AutoVerifiedAttributes=["email"],
        EmailConfiguration={
            "SourceArn": arn,
            "From": args.sender,
            "EmailSendingAccount": "DEVELOPER",
            "ConfigurationSet": CONFIG_SET,
        },
    )
    print(f"\nwired: pool {args.pool} now sends through SES as {args.sender}")
    if not production:
        print(
            "Still sandboxed. Sign-ups from addresses you have not verified will "
            "not receive a code. Request production access in the SES console."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
