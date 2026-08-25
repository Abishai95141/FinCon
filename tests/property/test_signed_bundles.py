"""A digest proves what ran. A signature proves who approved it.

Policy, the taxonomy and the promoted rule store were pinned by digest, and
anyone who can edit the file can edit the digest with it — so the pin detected
accident and never intent. That is the distinction the whole proof-tier ladder
rests on: `P2 ATTESTED` means a named human is accountable, and a digest names
nobody.

Modelled on Open Policy Agent's signed bundles. Ed25519 rather than an HMAC on
purpose: the signing key never leaves the approver, and a regulator holding only
the public key can check a year-old close without us.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from recon import trust

AUTHORIZED = Path("data/trust/authorized-key.hex")
BUNDLES = [Path("data/policy"), Path("data/taxonomy"), Path("data/rules")]


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    b = tmp_path / "rules"
    b.mkdir()
    (b / "settlement_3way.json").write_text('{"profile":"settlement_3way","promoted":[]}')
    return b


@pytest.fixture(scope="module")
def signer() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def test_an_unsigned_bundle_is_a_state_not_an_error(bundle, signer):
    """Absent is not the same as forged, and collapsing them would make every
    fresh checkout look like an attack."""
    verdict = trust.verify(bundle, signer.public_key())
    assert not verdict.signed and not verdict.trusted
    assert verdict.reasons == []
    assert verdict.digest, "a bundle has an identity whether or not anyone signed it"


def test_a_signed_bundle_verifies_and_names_its_signer(bundle, signer):
    trust.sign(bundle, signer, signed_by="meera")
    verdict = trust.verify(bundle, signer.public_key())
    assert verdict.trusted and verdict.signed_by == "meera"


@pytest.mark.parametrize(
    ("name", "tamper", "expect"),
    [
        (
            "a signed file is edited",
            lambda b: (b / "settlement_3way.json").write_text("{}"),
            "does not match",
        ),
        ("a file is added", lambda b: (b / "extra.json").write_text("{}"), "unsigned file"),
        ("a file is removed", lambda b: (b / "settlement_3way.json").unlink(), "not in the bundle"),
    ],
)
def test_every_way_a_bundle_can_change_is_refused(bundle, signer, name, tamper, expect):
    """Each is a different accident, and a verifier that stops at the first
    makes the rest invisible — so every difference is reported."""
    trust.sign(bundle, signer, signed_by="meera")
    tamper(bundle)
    verdict = trust.verify(bundle, signer.public_key())

    assert not verdict.trusted, name
    assert any(expect in r for r in verdict.reasons), verdict.reasons


def test_another_key_cannot_vouch_for_this_bundle(bundle, signer):
    trust.sign(bundle, signer, signed_by="meera")
    verdict = trust.verify(bundle, Ed25519PrivateKey.generate().public_key())
    assert not verdict.trusted
    assert any("does not verify" in r for r in verdict.reasons)


def test_a_bundle_cannot_supply_its_own_verification_key(bundle, signer, monkeypatch):
    """The property the whole design turns on. A bundle that names the key it is
    checked against vouches for itself, which is decoration, not a signature."""
    monkeypatch.delenv(trust.PUBLIC_KEY_ENV, raising=False)
    trust.sign(bundle, signer, signed_by="meera")
    pub = signer.public_key().public_bytes_raw().hex()
    (bundle / "trusted-key.hex").write_text(pub)
    trust.sign(bundle, signer, signed_by="meera")  # re-sign so the planted key is covered

    verdict = trust.verify(bundle)
    assert not verdict.trusted, "the bundle talked the verifier into trusting it"
    assert any(trust.PUBLIC_KEY_ENV in r for r in verdict.reasons)


def test_a_signature_needs_a_named_person(bundle, signer):
    with pytest.raises(trust.BundleError, match="named signer"):
        trust.sign(bundle, signer, signed_by="  ")


def test_the_manifest_is_not_signed_over_itself(bundle, signer):
    """A manifest covering its own bytes could never verify. It covers the files
    beside it, and is itself the thing the signature is over."""
    trust.sign(bundle, signer, signed_by="meera")
    manifest = json.loads((bundle / trust.MANIFEST).read_text())
    assert trust.MANIFEST not in manifest["files"]
    assert set(manifest["files"]) == {"settlement_3way.json"}


# --------------------------------------------------------------------------
# the bundles this repository actually ships
# --------------------------------------------------------------------------


def test_the_shipped_authority_bundles_are_signed():
    key = trust.load_public_key(AUTHORIZED.read_text())
    for path in BUNDLES:
        verdict = trust.verify(path, key)
        assert verdict.trusted, str(verdict)
        assert verdict.signed_by


def test_the_authorized_key_does_not_live_inside_a_bundle_it_verifies():
    """Out of band is a property of *where the key is*, not of the code that
    reads it."""
    for path in BUNDLES:
        assert AUTHORIZED.resolve().parent != path.resolve()
        assert not (path / AUTHORIZED.name).exists()


def test_a_close_records_which_authority_it_ran_under(monkeypatch):
    from bench.run import close

    monkeypatch.setenv(trust.PUBLIC_KEY_ENV, AUTHORIZED.read_text().strip())
    result = close("A")

    assert len(result.authority) == 3
    assert all(v.trusted for v in result.authority), [str(v) for v in result.authority]
    assert {v.bundle.name for v in result.authority} == {"policy", "taxonomy", "rules"}


def test_the_authority_reaches_the_decision_log(monkeypatch, tmp_path):
    from bench.run import close

    from recon.contracts import EventKind
    from recon.journal import read

    monkeypatch.setenv(trust.PUBLIC_KEY_ENV, AUTHORIZED.read_text().strip())
    result = close("A", journal_dir=tmp_path)
    events = [e for e in read(result.journal_path) if e.kind is EventKind.AUTHORITY_VERIFIED]

    assert len(events) == 3
    assert all(e.payload.trusted and e.payload.signed_by for e in events)


def test_an_untrusted_bundle_is_recorded_and_does_not_stop_the_close(monkeypatch):
    """Report, do not refuse, by default. Refusing to close the books because a
    verification key is missing is its own kind of failure — which risk is worse
    belongs to policy, not to this function."""
    from bench.run import close

    monkeypatch.delenv(trust.PUBLIC_KEY_ENV, raising=False)
    result = close("A")

    assert result.ok, "a missing key stopped the books"
    assert not any(v.trusted for v in result.authority)


def test_a_caller_that_demands_signed_authority_gets_a_refusal(monkeypatch, tmp_path):
    from recon.close import run_close
    from tests.property.test_one_entry_point import _request

    monkeypatch.delenv(trust.PUBLIC_KEY_ENV, raising=False)
    request = _request("A", tmp_path, bundles=[Path("data/policy")], require_signed=True)
    with pytest.raises(trust.BundleError, match="requires signed authority"):
        run_close(request)
