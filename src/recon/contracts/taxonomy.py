"""The exception-code registry: an open vocabulary with a lifecycle.

A closed enum gives an agent two options when it meets something genuinely new:
pick the nearest wrong code, or crash. Both are worse than saying "this is a
kind of thing I have not seen before" — a wrong code routes the item to the
wrong owner and may fire the wrong rule, which is a confident wrong answer, the
failure mode this whole project is built against.

So the vocabulary opens. What keeps that from becoming a hole is that **naming
is not authority**. A code is minted with none, and the lifecycle hands power
back one step at a time, each step requiring something a proposer cannot supply:

| status | label | route to a named owner | fire a rule | direct a posting |
|---|---|---|---|---|
| `PROPOSED` | yes | no | no | no |
| `PROVISIONAL` | yes | yes | no | no |
| `PROMOTED` | yes | yes | yes | yes |
| `RETIRED` | yes | no | no | no |

`RETIRED` still labels, deliberately. A code that stopped resolving when it was
retired would make last quarter's decision log unreadable by the act of tidying
it up.

**Shape is not meaning.** The contract validates that a code *looks* like a code;
this registry says what one *is*. A well-formed id that resolves nowhere is the
typo-becomes-a-category failure, and it fails the close rather than passing as a
novel finding.

**Ids never change.** A discovered code keeps its `X-` prefix after promotion.
Renaming on promotion would break every reference in every log already written,
and the prefix is honest provenance: this category was found, not designed.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, NamedTuple

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from . import CONTRACT_VERSION

#: `E01`-`E14` are the seeded canonical codes; `X-...` is where anything
#: discovered later lives. Anchored and length-capped: a code id ends up in a
#: filename, a log line and a queue name, so it is not a free-text field.
CODE_PATTERN = r"^(E[0-9]{2}|X-[A-Z][A-Z0-9-]{2,31})$"
CodeId = Annotated[str, StringConstraints(pattern=CODE_PATTERN)]

MIN_DEFINITION = 30
"""A promotion needs a *written* definition. Thirty characters is not a quality
bar — it is a refusal to accept "fx thing" as a specification other people will
route work by."""


class TaxonomyViolation(Exception):
    """A code was used in a way its status does not permit, or a lifecycle step
    was skipped. Raised rather than returned: a caller free to ignore a boolean
    would be granting its own permission."""


class CodeStatus(StrEnum):
    PROPOSED = "proposed"
    """Minted by anyone, including an agent. Names a finding and nothing more."""

    PROVISIONAL = "provisional"
    """A named human accepted it as a real category and gave it an owner. It can
    now route work to that owner. It still cannot decide anything."""

    PROMOTED = "promoted"
    """Ratified with a written definition. Full authority: a rule may key on it
    and it may direct where money books."""

    RETIRED = "retired"
    """No longer assignable. Still resolves, so the record stays readable."""


class Authority(NamedTuple):
    may_label: bool
    may_route_to_named_owner: bool
    may_fire_rule: bool
    may_direct_posting: bool
    assignable: bool

    def summary(self) -> str:
        granted = [
            name
            for name, on in (
                ("label", self.may_label),
                ("route", self.may_route_to_named_owner),
                ("rule", self.may_fire_rule),
                ("posting", self.may_direct_posting),
            )
            if on
        ]
        return " + ".join(granted) if len(granted) != 1 else "label only"


#: The matrix, in one place. Every check reads it rather than comparing statuses
#: inline, so there is one thing to get right and one thing to test.
AUTHORITY: dict[CodeStatus, Authority] = {
    CodeStatus.PROPOSED: Authority(True, False, False, False, True),
    CodeStatus.PROVISIONAL: Authority(True, True, False, False, True),
    CodeStatus.PROMOTED: Authority(True, True, True, True, True),
    CodeStatus.RETIRED: Authority(True, False, False, False, False),
}

assert set(AUTHORITY) == set(CodeStatus), sorted(set(CodeStatus) - set(AUTHORITY))


class CodeDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: CodeId
    title: str
    definition: str
    status: CodeStatus = CodeStatus.PROPOSED

    owner: str | None = None
    """The queue this routes to. Honoured only once the status permits it — a
    proposal naming an owner is a claim about someone else's workload."""

    books_to: str | None = None
    """An `AccountRole` value. Also a claim: read only when the code may direct a
    posting, so a proposed code asking for a revenue account gets suspense."""

    proposed_by: str
    proposed_at: datetime
    accepted_by: str | None = None
    accepted_at: datetime | None = None
    promoted_by: str | None = None
    promoted_at: datetime | None = None
    retired_at: datetime | None = None
    superseded_by: CodeId | None = None

    @model_validator(mode="after")
    def _authority_is_accounted_for(self) -> CodeDefinition:
        if not self.title.strip():
            raise ValueError(f"{self.code}: a code without a title is an id, not a category")
        if not self.proposed_by.strip():
            raise ValueError(f"{self.code}: a code must name who proposed it")
        if self.status is CodeStatus.PROMOTED:
            if not (self.promoted_by or "").strip():
                raise ValueError(f"{self.code}: promoted without a named human")
            if len(self.definition.strip()) < MIN_DEFINITION:
                raise ValueError(
                    f"{self.code}: promoted without a written definition "
                    f"({len(self.definition.strip())} chars, need {MIN_DEFINITION})"
                )
        if self.status is CodeStatus.RETIRED and self.retired_at is None:
            raise ValueError(f"{self.code}: retired without a date")
        return self

    @property
    def authority(self) -> Authority:
        return AUTHORITY[self.status]

    @property
    def is_ratified(self) -> bool:
        return self.status is CodeStatus.PROMOTED


class TaxonomyRegistry(BaseModel):
    """Versioned, frozen, and supplied out-of-band — like `Policy`.

    Mutations return a new registry rather than changing this one. The engine
    functions that produce those are in `recon.engine.taxonomy`; keeping them out
    of the contract is the same split as `Policy` and `promotion`: the contract
    says what is true, the engine says what may change and records it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: str = CONTRACT_VERSION
    registry_id: str
    version: int = 1
    approved_by: str
    approved_at: datetime

    default_owner: str
    """Where an unratified finding goes. Not a dumping ground — it is the queue
    of the person who decides whether a proposed category is real."""

    codes: dict[CodeId, CodeDefinition]

    @model_validator(mode="after")
    def _codes_agree_with_their_keys(self) -> TaxonomyRegistry:
        if not self.approved_by.strip():
            raise ValueError("a taxonomy must name who approved it")
        if not self.default_owner.strip():
            raise ValueError("a taxonomy must name a fallback owner")
        for key, entry in self.codes.items():
            if key != entry.code:
                raise ValueError(f"registry key {key!r} does not match code {entry.code!r}")
            if entry.superseded_by and entry.superseded_by not in self.codes:
                raise ValueError(f"{key} is superseded by {entry.superseded_by}, which is unknown")
        return self

    @property
    def ref(self) -> str:
        return f"{self.registry_id}@v{self.version}"

    def __contains__(self, code: str) -> bool:
        return code in self.codes

    def __getitem__(self, code: str) -> CodeDefinition:
        return self.resolve(code)

    def resolve(self, code: str) -> CodeDefinition:
        """A well-formed id that resolves nowhere is not a novel finding — it is
        a typo that would otherwise become a category."""
        try:
            return self.codes[code]
        except KeyError:
            raise TaxonomyViolation(
                f"{code!r} resolves in no registry entry ({self.ref}). A code is "
                f"minted by proposing it, never by using it."
            ) from None

    def authority_of(self, code: str) -> Authority:
        return self.resolve(code).authority

    def route(self, code: str) -> str:
        """Who works this. A code that may not name an owner routes to the
        fallback, which is the queue that decides whether it is real."""
        entry = self.resolve(code)
        if entry.authority.may_route_to_named_owner and entry.owner:
            return entry.owner
        return self.default_owner

    def booking_for(self, code: str):
        """The account role this code directs money to, or `None`.

        `None` means the caller decides — in practice, suspense. Read through
        the authority matrix so an unratified code's `books_to` is not consulted
        at all rather than consulted and overridden.
        """
        from ..ledger.accounts import AccountRole

        entry = self.resolve(code)
        if not entry.authority.may_direct_posting or not entry.books_to:
            return None
        return AccountRole(entry.books_to)

    def assignable(self, code: str) -> bool:
        return self.resolve(code).authority.assignable

    def check_assignable(self, code: str) -> None:
        entry = self.resolve(code)
        if not entry.authority.assignable:
            raise TaxonomyViolation(
                f"{code} is {entry.status.value} and cannot be assigned to a new "
                f"finding" + (f"; use {entry.superseded_by}" if entry.superseded_by else "")
            )

    def check_may_fire_rule(self, code: str) -> None:
        entry = self.resolve(code)
        if not entry.authority.may_fire_rule:
            raise TaxonomyViolation(
                f"{code} is {entry.status.value}, not promoted — a rule may not "
                f"act on a category nobody has ratified"
            )
