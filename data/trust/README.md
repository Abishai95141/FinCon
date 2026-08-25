# Trust material

`authorized-key.hex` is the Ed25519 **public** key a verifier checks bundle
signatures against. It lives here rather than inside any bundle on purpose: a
bundle that names its own verification key vouches for itself, which is not a
signature, it is a decoration. Anything reading it must treat this directory as
out-of-band material — an operator supplies it, the artifact never does.

`dev-signing-key.hex` is a **development signing key and not a secret.** It is
committed so `make sign` works in a clone and so the mechanism is exercised by
the test suite rather than asserted. A deployment replaces it: the private key
belongs with the person whose name goes in `signed_by`, and if it sits in the
repository then "who approved this" is answered by "anyone with a checkout".

What a signature here does and does not say:

- **Does:** these exact bytes are the bytes a named holder of this key put their
  name to. That is `P2 ATTESTED` evidence about provenance.
- **Does not:** that the contents are correct. A signed bundle of bad rules is
  still a bundle of bad rules.
