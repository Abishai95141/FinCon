"""Sign the authority bundles. See `src/recon/trust.py` and data/trust/README.md.

`make sign`. The signer's name is required and is a person: the point of a
signature is that somebody is accountable, and "automation" answers a different
question than the one being asked.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from recon import trust  # noqa: E402

BUNDLES = [Path("data/policy"), Path("data/taxonomy"), Path("data/rules")]
DEV_KEY = Path("data/trust/dev-signing-key.hex")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--signed-by", default=os.environ.get("RECON_SIGNER", ""))
    ap.add_argument(
        "--key",
        default=os.environ.get("RECON_SIGNING_KEY", ""),
        help="hex Ed25519 private key; falls back to the committed development key",
    )
    args = ap.parse_args(argv)
    if not args.signed_by.strip():
        print("REFUSING — --signed-by is required and must name a person.")
        return 2

    material = args.key.strip() or DEV_KEY.read_text().strip()
    if not args.key.strip():
        print(f"note: using {DEV_KEY}, which is a development key and not a secret.")
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(material))

    for bundle in BUNDLES:
        if not bundle.exists():
            print(f"  {bundle} absent — nothing to sign")
            continue
        trust.sign(bundle, key, signed_by=args.signed_by)
        print(f"  {trust.verify(bundle, key.public_key())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
