"""A field left at its default must still produce something a reader can consume.

Found at P13: `Policy.max_reference_selectivity` defaulted to the *string*
`"0.25"`, pydantic does not run a field's validator on its default unless the
model says to, and so a `Policy` that omitted the field raised on
`model_dump_json()`. Four phases, unexercised, because the one policy file on
disk sets the field — the default was code nobody ran, inside the object every
permission decision reads from. The published OpenAPI schema then dropped it
with a warning, so an external implementer reading our contract would never
learn what we do when the field is absent.

**Three drafts of this test were vacuous, and the third is why the second two
are described rather than deleted.** Walking whole models skipped 37 of 39 for
want of seed values. Checking each default was *convertible* passed with the bug
reintroduced — convertibility was never the problem. Building a one-field probe
passed too, because pydantic warns on a bad serialiser there and raises in a
real model. Each draft looked like a test and measured nothing, which is the
exact failure this file is about.

So: one direct test of the object that broke, and one structural rule that
generalises it. Both were run against the reverted fix and both go red.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from recon import contracts
from recon.contracts import Policy, event

MINIMAL_POLICY = dict(
    policy_id="seed",
    profile="seed_loop",
    side_signs={"a": 1, "b": -1},
    tolerance_ceiling=Decimal("1.00"),
    rejection_budget_pct="0.10",
    rounding_threshold=Decimal("0.50"),
    approved_by="a named human",
    approved_at=datetime(2026, 1, 1, tzinfo=UTC),
)


def test_a_policy_that_omits_its_optional_fields_still_serialises():
    """The object that broke, built the way a caller would build it.

    Not a probe and not a schema check — the real model, every optional field
    left alone, dumped to JSON. This is what a caller writing a policy for a
    second loop does on their first attempt.
    """
    policy = Policy(**MINIMAL_POLICY)
    text = policy.model_dump_json()
    assert Policy.model_validate_json(text).ref == policy.ref
    assert policy.max_reference_selectivity == Decimal("0.2500")
    assert policy.consistency_tolerance == Decimal("1.00")


def test_the_default_a_schema_publishes_is_the_default_a_reader_gets():
    """Pydantic warns and *drops* an unserialisable default rather than failing,
    so the loss is silent in exactly the document outsiders build against."""
    published = Policy.model_json_schema()["properties"]
    missing = [
        field
        for field, info in Policy.model_fields.items()
        if info.default is not PydanticUndefined
        and info.default is not None
        and "default" not in published.get(field, {})
    ]
    assert not missing, f"defaults dropped from the published Policy schema: {missing}"


def _models() -> dict[str, type[BaseModel]]:
    found: dict[str, type[BaseModel]] = {}
    for module in (contracts, event):
        for name in dir(module):
            obj = getattr(module, name)
            if isinstance(obj, type) and issubclass(obj, BaseModel) and obj is not BaseModel:
                found[obj.__name__] = obj
    assert len(found) >= 20, f"only {len(found)} contract models found — the walk has gone blind"
    return found


def _has_custom_serialiser(info: object) -> bool:
    """Whether this field's type carries a serialiser that can reject a value.

    `Money` and `Ratio` are `Annotated[Decimal, BeforeValidator, PlainSerializer]`
    — the serialiser assumes the validator has run. A plain `str` or `int` has
    no such assumption and its default cannot be wrong in this way.

    Read off `FieldInfo.metadata`, not off the annotation: pydantic unwraps
    `Annotated` and moves the metadata onto the field, so `info.annotation` is a
    bare `Decimal` and looking there found **nothing at all**. The first version
    of this did exactly that and passed over the very field it was written for —
    the fourth vacuous draft in one file, and the one that made the point: a
    structural rule that finds zero instances is not a rule, it is a decoration.
    """
    return any(type(meta).__name__ == "PlainSerializer" for meta in getattr(info, "metadata", ()))


def test_a_model_with_a_serialised_default_validates_its_defaults():
    """The structural rule the specific bug is an instance of.

    A default on a field whose type has a custom serialiser is a value the
    serialiser will be handed without the validator ever having seen it — unless
    the model sets `validate_default`. That is a property of the model, so it is
    checked on the model rather than inferred from one field that happened to
    break.
    """
    offenders: list[str] = []
    checked: set[str] = set()
    for name, model in sorted(_models().items()):
        risky = [
            field
            for field, info in model.model_fields.items()
            if info.default is not PydanticUndefined
            and info.default is not None
            and _has_custom_serialiser(info)
        ]
        checked.update(f"{name}.{f}" for f in risky)
        if risky and not model.model_config.get("validate_default", False):
            offenders.append(f"{name}: {risky} default without validate_default")

    # The guard the first four drafts of this file needed. A walk that finds
    # nothing passes, and goes on passing after the thing it guards is deleted.
    assert checked, "the walk found no serialised defaults at all — it is measuring nothing"
    assert not offenders, (
        "these defaults reach a serialiser the validator never ran:\n  " + "\n  ".join(offenders)
    )
