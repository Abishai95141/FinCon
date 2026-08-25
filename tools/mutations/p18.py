"""Mutations for content-derived exception identity.

Restores the positional id and the ways a fingerprint can look stable while
identifying nothing. Found by reading Formance's reconciliation service, which
dedups alerts on (rule_id, fingerprint, period_id).
"""

TARGETS = ["tests/property/test_fingerprint.py"]

MUTATIONS = [
    (
        "exceptions go back to positional identity",
        "src/recon/close.py",
        """        exceptions=fingerprint.stamp(outcome.exceptions, records),""",
        """        exceptions=list(outcome.exceptions),""",
    ),
    (
        "the fingerprint ignores the records, so every code is one break",
        "src/recon/engine/fingerprint.py",
        """    body = "|".join([exception.code, *keys])""",
        """    body = exception.code""",
    ),
    (
        "the fingerprint includes the amount, so a growing break looks new",
        "src/recon/engine/fingerprint.py",
        """    keys = sorted(records[rid].natural_key or rid for rid in exception.record_ids if rid in records)""",
        """    keys = [str(exception.amount), *sorted(records[rid].natural_key or rid for rid in exception.record_ids if rid in records)]""",
    ),
    (
        "identity is built from record ids, which carry source and row number",
        "src/recon/engine/fingerprint.py",
        """    keys = sorted(records[rid].natural_key or rid for rid in exception.record_ids if rid in records)""",
        """    keys = sorted(rid for rid in exception.record_ids if rid in records)""",
    ),
]
