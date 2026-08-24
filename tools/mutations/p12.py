"""Mutations for the P12 controls. See tools/mutate.py."""

TARGETS = ["tests/gates/gate_p12.py"]

MUTATIONS = [
    (
        "the edge accepts a prose reply",
        "src/recon/triage/client.py",
        """        if choice.get("finish_reason") != "tool_calls":""",
        """        if False:""",
    ),
    (
        "tool_choice stops being required",
        "src/recon/triage/client.py",
        '''SCHEMA_TOOL_CHOICE = "required"''',
        '''SCHEMA_TOOL_CHOICE = "auto"''',
    ),
    (
        "unparseable arguments are swallowed",
        "src/recon/triage/client.py",
        """        except json.JSONDecodeError as exc:
            record(False, f"arguments are not JSON: {exc}")
            raise ProposalRefused(f"tool arguments did not parse: {exc}") from exc""",
        """        except json.JSONDecodeError:
            record(True, None)
            return {}""",
    ),
    (
        "thinking is left on",
        "src/recon/triage/client.py",
        """            "thinking": {"type": "disabled"},""",
        """            "thinking": {"type": "enabled"},""",
    ),
    (
        "the edge stops recording what it spent",
        "src/recon/triage/client.py",
        """            self.calls.append(""",
        """            [].append(""",
    ),
    (
        "cost is reported as zero instead of absent",
        "src/recon/triage/client.py",
        """            "usd": None,""",
        """            "usd": 0.0,""",
    ),
    (
        "a code outside the registry is accepted",
        "src/recon/triage/classify.py",
        """            taxonomy.resolve(code)
            taxonomy.check_assignable(code)""",
        """            pass""",
    ),
    (
        "evidence is no longer checked against the exception",
        "src/recon/triage/classify.py",
        """        if not cited:""",
        """        if False:""",
    ),
    (
        "a proposal for an unknown exception is accepted",
        "src/recon/triage/classify.py",
        """    if exception is None:
        reasons.append(f"exception_id {exception_id!r} is not one we asked about")""",
        """    if False:
        reasons.append("")""",
    ),
    (
        "a derived code is offered to the model",
        "src/recon/triage/classify.py",
        """        if not reclassifiable(exception):""",
        """        if False:""",
    ),
    (
        "the checker allows overwriting a derived code",
        "src/recon/triage/classify.py",
        """    elif not reclassifiable(exception):""",
        """    elif False:""",
    ),
    (
        "proposals arrive pre-accepted",
        "src/recon/triage/classify.py",
        """            refusals=list(verdict.reasons),
        )
        results.append(classification)""",
        """            refusals=list(verdict.reasons),
            accepted=True,
        )
        results.append(classification)""",
    ),
    (
        "attestation needs no actor",
        "src/recon/triage/classify.py",
        """    if not (actor or "").strip():
        raise PolicyViolation("an attestation must name who accepted it")""",
        """    if False:
        raise PolicyViolation("")""",
    ),
    (
        "a refused proposal can be attested",
        "src/recon/triage/classify.py",
        """    if classification.refusals:""",
        """    if False:""",
    ),
    (
        "unattested proposals are applied anyway",
        "src/recon/triage/classify.py",
        """    accepted = {c.exception_id: c for c in classifications if c.accepted}""",
        """    accepted = {c.exception_id: c for c in classifications}""",
    ),
    (
        "source text is put in the system prompt",
        "src/recon/triage/classify.py",
        """        f"REGISTRY\\n{code_menu}"
    )""",
        """        f"REGISTRY\\n{code_menu}\\n\\nSOURCE TEXT\\n"
        + "\\n".join((f.get("text") or "") for f in facts)
    )""",
    ),
    (
        "the untrusted fence is dropped",
        "src/recon/triage/classify.py",
        """<untrusted_source_text record=""",
        """source_text record=""",
    ),
    (
        "a skipped exception is not recorded",
        "src/recon/triage/classify.py",
        """            if journal is not None:
                journal.append(
                    EventKind.PROPOSAL_REFUSED,
                    actor=ACTOR,
                    outcome="not_offered",""",
        """            if False:
                journal.append(
                    EventKind.PROPOSAL_REFUSED,
                    actor=ACTOR,
                    outcome="not_offered",""",
    ),
    (
        "retired codes are offered on the menu",
        "src/recon/triage/classify.py",
        """        if entry.authority.assignable""",
        """        if True""",
    ),
    (
        "the posting layer reaches model-authored text",
        "src/recon/ledger/posting_rules.py",
        """        override = (overrides or {}).get(exc.exception_id)""",
        """        _seen = exc.hypothesis
        override = (overrides or {}).get(exc.exception_id)""",
    ),
]
