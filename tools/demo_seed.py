"""Put the machine in the state the demo film starts from.

    make demo-seed

Three things have to be true before the camera rolls, and each of them has bitten
a capture already:

**A tenant with nothing in it.** Shot 3 shows a person *loading* the worked
example. An account that already has sources skips straight past the only screen
that explains what a reconciliation is, and the film loses its opening.

**Batches on disk and the authority signed.** A close over unsigned bundles
records the authority as untrusted and the scorecard says so on camera.

**A warm process.** The first close in a fresh interpreter pays for beancount and
ortools importing. That is real and it is not what shot 4 is about, so it is
spent on a throwaway close of batch B that nobody films.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

EMAIL = "controller@fincon.demo"
PASSWORD = "Dem0!Fincon#2026"


def run(*cmd: str) -> None:
    print(f"  $ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, capture_output=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--email", default=EMAIL)
    ap.add_argument("--password", default=PASSWORD)
    ap.add_argument("--signer", default="demo@fincon")
    ap.add_argument("--keep", action="store_true", help="do not wipe the tenant's state")
    args = ap.parse_args(argv)

    os.environ.setdefault("RECON_ENV", "dev")
    os.environ.setdefault("RECON_AUTH", "local")

    from recon.api import auth

    ident = auth.build_identity()
    if ident.exists(args.email):
        try:
            user = ident.sign_in(args.email, args.password)
            print(f"  account exists: {args.email}")
        except auth.AuthError:
            # The account is here with some other password — an earlier capture
            # session, most likely. Re-seat it rather than failing: this is a
            # local development store whose whole purpose is being disposable,
            # and a seeding step that cannot run twice is not a seeding step.
            records = json.loads(ident.path.read_text(encoding="utf-8"))
            records.pop(args.email.strip().lower(), None)
            ident.path.write_text(json.dumps(records, indent=2, sort_keys=True), encoding="utf-8")
            user = ident.sign_up(args.email, args.password)
            print(f"  re-seated: {args.email} (the stored password was not ours)")
    else:
        user = ident.sign_up(args.email, args.password)
        print(f"  created: {args.email}")

    if not args.keep:
        for root in (Path("data/runs") / user.user_id, Path("data/sources") / user.user_id):
            if root.exists():
                shutil.rmtree(root)
                print(f"  wiped {root}")

    if not Path("data/batches/A").exists():
        run("make", "gen")
    run("make", "sign", f"SIGNER={args.signer}")

    # Warm the interpreter's heavy imports on a close nobody films.
    print("  warming beancount + ortools on a throwaway close…")
    from recon import service
    from recon.profiles import settlement  # noqa: F401  (registers the loop)

    try:
        service.close("settlement_3way", "B", runs_dir=Path("data/runs") / "_warm")
    except Exception as exc:  # a warm-up that fails is not fatal to the shoot
        print(f"  warm-up said: {type(exc).__name__}: {exc}", file=sys.stderr)
    finally:
        shutil.rmtree(Path("data/runs") / "_warm", ignore_errors=True)

    print(
        "\n  ready. Start the server, then record:\n"
        f"    FINCON_DEMO_EMAIL={args.email} \\\n"
        f"    FINCON_DEMO_PASSWORD='{args.password}' make demo\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
