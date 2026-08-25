"""Signed bundles: which authority a close ran under, and who vouched for it.

Policy, the taxonomy and the promoted rule store were pinned by digest. A digest
proves *what* ran; it does not prove *who approved it*. Anyone who can edit the
file can edit the digest with it, so the pin detected accident and not intent —
which is the whole distinction the proof-tier ladder is built on.

Modelled on Open Policy Agent's signed bundles. A bundle is a directory; its
`.signatures.json` lists a SHA-256 for every file in it, and that manifest is
signed. Verification uses a key supplied **out of band** — an argument or an env
var, never a path named inside the bundle, because a bundle that names its own
verification key is a bundle that signs itself.

Ed25519 rather than an HMAC on purpose. The signing key never has to leave the
approver, and a regulator holding only the public key can check a year-old close
without us. That is the same stance `verify()` takes: runnable by someone who
does not trust us.

**What this does not do.** It does not say the contents are *correct* — a signed
bundle full of bad rules is still bad. It says a named holder of a key put their
name to these exact bytes, which is `P2 ATTESTED` evidence about provenance and
nothing more.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

MANIFEST = ".signatures.json"
#: Where a verifier looks for the public key when a caller does not pass one.
#: An environment variable is out of band; a path inside the bundle would not be.
PUBLIC_KEY_ENV = "RECON_BUNDLE_PUBKEY"


class BundleError(ValueError):
    """The bundle cannot be trusted. Never raised for a bundle that is merely
    absent — an unsigned directory is a *state*, and the caller decides whether
    that state is acceptable."""


@dataclass(frozen=True)
class Verdict:
    """Whether a bundle's bytes are the bytes somebody signed."""

    bundle: Path
    signed: bool
    signed_by: str | None = None
    key_id: str | None = None
    digest: str = ""
    reasons: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        """What to call this bundle in a record someone else will read.

        Relative to the working directory where it can be. The rule store
        resolves to an absolute path so it works from any cwd, which meant a
        decision log — the artifact we hand a regulator — carried the home
        directory of whoever ran the close, next to two relative paths for the
        same kind of thing.
        """
        try:
            return str(self.bundle.relative_to(Path.cwd()))
        except ValueError:
            return str(self.bundle)

    @property
    def trusted(self) -> bool:
        return self.signed and not self.reasons

    def __str__(self) -> str:
        if self.trusted:
            return f"{self.bundle.name} signed by {self.signed_by} ({self.digest[:12]})"
        if not self.signed:
            return f"{self.bundle.name} is unsigned"
        return f"{self.bundle.name} REFUSED :: " + "; ".join(self.reasons)


def _files(bundle: Path) -> dict[str, str]:
    """SHA-256 of every file in the bundle, by name, manifest excluded."""
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(bundle.iterdir())
        if path.is_file() and path.name != MANIFEST
    }


def _canonical(files: dict[str, str]) -> bytes:
    """The exact bytes that get signed. Sorted and separator-pinned so a
    re-serialisation with different whitespace is not a different bundle."""
    return json.dumps(files, sort_keys=True, separators=(",", ":")).encode()


def bundle_digest(bundle: Path) -> str:
    """One id for the whole bundle's contents. Independent of the signature, so
    a decision can name the bundle it ran under whether or not it was signed."""
    return hashlib.sha256(_canonical(_files(bundle))).hexdigest()[:16]


def sign(bundle: Path, private_key: Ed25519PrivateKey, *, signed_by: str) -> Path:
    """Write `.signatures.json` over every file in the bundle.

    `signed_by` is a person. A bundle signed by "automation" answers the wrong
    question — the point of `P2 ATTESTED` is that someone is accountable.
    """
    if not signed_by.strip():
        raise BundleError("a signature needs a named signer; 'who approved it' is the point")
    files = _files(bundle)
    if not files:
        raise BundleError(f"{bundle} holds no files to sign")
    public = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    manifest = {
        "files": files,
        "signed_by": signed_by,
        "key_id": hashlib.sha256(public).hexdigest()[:16],
        "signature": private_key.sign(_canonical(files)).hex(),
    }
    path = bundle / MANIFEST
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def verify(bundle: Path, public_key: Ed25519PublicKey | None = None) -> Verdict:
    """Check the bundle's bytes against the signature over them.

    Every difference is reported rather than the first: a file changed, a file
    added, a file removed and a bad signature are different accidents, and a
    verifier that stops at the first makes the second invisible.
    """
    digest = bundle_digest(bundle) if bundle.exists() else ""
    manifest_path = bundle / MANIFEST
    if not manifest_path.exists():
        return Verdict(bundle, signed=False, digest=digest)

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return Verdict(bundle, signed=True, digest=digest, reasons=[f"unreadable manifest: {exc}"])

    key = public_key or load_public_key()
    if key is None:
        return Verdict(
            bundle,
            signed=True,
            signed_by=manifest.get("signed_by"),
            key_id=manifest.get("key_id"),
            digest=digest,
            reasons=[
                f"no verification key: pass one, or set {PUBLIC_KEY_ENV}. A key named "
                "inside the bundle would let the bundle vouch for itself"
            ],
        )

    reasons: list[str] = []
    claimed: dict[str, str] = manifest.get("files") or {}
    actual = _files(bundle)
    for name in sorted(set(claimed) | set(actual)):
        if name not in actual:
            reasons.append(f"{name} is in the manifest and not in the bundle")
        elif name not in claimed:
            reasons.append(f"{name} is in the bundle and not in the manifest — unsigned file")
        elif claimed[name] != actual[name]:
            reasons.append(f"{name} does not match its signed digest")

    try:
        key.verify(bytes.fromhex(manifest.get("signature", "")), _canonical(claimed))
    except (InvalidSignature, ValueError):
        reasons.append("the manifest's signature does not verify under this key")

    return Verdict(
        bundle,
        signed=True,
        signed_by=manifest.get("signed_by"),
        key_id=manifest.get("key_id"),
        digest=digest,
        reasons=reasons,
    )


def load_public_key(raw: str | None = None) -> Ed25519PublicKey | None:
    """The verification key, from out of band. Hex-encoded raw Ed25519."""
    material = raw if raw is not None else os.environ.get(PUBLIC_KEY_ENV)
    if not material:
        return None
    try:
        return Ed25519PublicKey.from_public_bytes(bytes.fromhex(material.strip()))
    except ValueError as exc:
        raise BundleError(f"{PUBLIC_KEY_ENV} is not a hex Ed25519 public key: {exc}") from exc


def require(bundle: Path, public_key: Ed25519PublicKey | None = None) -> Verdict:
    """Verify, and raise unless the bundle is trusted.

    For the caller that has decided an unsigned bundle is not acceptable. The
    default everywhere else is to *report* the verdict and let policy decide,
    because refusing to close the books because a key is missing is its own
    kind of failure.
    """
    verdict = verify(bundle, public_key)
    if not verdict.trusted:
        raise BundleError(str(verdict))
    return verdict
