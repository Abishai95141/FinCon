"""A dependency list is a claim about what this is built on.

Ten of seventeen declared dependencies were imported nowhere until 2026-08-26 —
splink, duckdb, polars, lxml, ofxparse, python-calamine, sqlalchemy, psycopg,
anthropic and beanquery. Nobody had lied; they were aspirations from the build
plan that never got wired, and they sat in `pyproject.toml` reading as
capability.

That matters here more than in most projects. Somebody assessing this reads the
dependency list to see whether the accounting is real or hand-rolled, and a list
naming a probabilistic record-linkage library we never call answers that question
wrongly in our favour. It is the same defect as an unmeasured thing reported as
zero: it flatters us for free.

Two directions, because a one-way check rots. **Declared but unimported** is the
defect we found. **Imported but undeclared** is the one that breaks a fresh
install — and it is invisible locally, where the package is already sitting in
the virtualenv from some earlier version of the file.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE_DIRS = ("src", "bench", "tools")

#: PyPI name -> the name you actually `import`. Only where they differ; anything
#: absent from here is assumed to import under its own (normalised) name.
IMPORT_NAME = {
    "python-calamine": "calamine",
    "psycopg[binary]": "psycopg",
    "beautifulsoup4": "bs4",
    "pyyaml": "yaml",
    "pillow": "PIL",
}

#: Declared for a reason other than being imported. Each needs a stated reason,
#: because "it is needed indirectly" with no explanation is how the ten got in.
JUSTIFIED_UNIMPORTED: dict[str, str] = {}


def _declared() -> list[str]:
    text = (ROOT / "pyproject.toml").read_text()
    block = text[text.index("dependencies = [") :]
    block = block[: block.index("\n]")]
    return re.findall(r'"([^"]+)"', block)


def _requirement_name(spec: str) -> str:
    return re.split(r"[<>=!~;\s]", spec, maxsplit=1)[0].strip()


def _import_name(requirement: str) -> str:
    return IMPORT_NAME.get(requirement, requirement.split("[")[0].replace("-", "_")).lower()


def _imported_roots() -> set[str]:
    """Top-level module names imported anywhere we ship or run.

    Parsed rather than grepped: a comment mentioning `polars` is not a use of
    polars, and the string "duckdb" inside a docstring explaining why we do not
    use duckdb would satisfy a grep exactly backwards.
    """
    roots: set[str] = set()
    for directory in SOURCE_DIRS:
        for path in (ROOT / directory).rglob("*.py"):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    roots.add(node.module.split(".")[0])
    return {r.lower() for r in roots}


def test_every_declared_dependency_is_actually_imported():
    """The defect that was here. A library nobody calls is a claim nobody earned."""
    imported = _imported_roots()
    unused = [
        spec
        for spec in _declared()
        if _import_name(_requirement_name(spec)) not in imported
        and _requirement_name(spec) not in JUSTIFIED_UNIMPORTED
    ]
    assert not unused, (
        f"declared and imported nowhere under {'/, '.join(SOURCE_DIRS)}/: {unused}. "
        f"Either wire it or drop it — a dependency list is read as a statement "
        f"about what this is built on. If it is genuinely needed indirectly, add "
        f"it to JUSTIFIED_UNIMPORTED with the reason."
    )


def test_every_third_party_import_is_declared():
    """The other direction, and the one that only breaks on somebody else's machine.

    A package left over in the local virtualenv imports fine here and is missing
    from a fresh install. Standard library and first-party names are excluded by
    asking the interpreter rather than by keeping a list, because a list of
    stdlib modules is a thing that goes stale between Python releases.
    """
    declared = {_import_name(_requirement_name(spec)) for spec in _declared()}
    declared |= {"pytest", "hypothesis", "ruff"}  # the dev group
    first_party = {"recon", "bench", "tools", "tests"}

    missing = sorted(
        root
        for root in _imported_roots()
        if root not in declared
        and root not in first_party
        and root not in sys.stdlib_module_names
        and not root.startswith("_")
    )
    assert not missing, (
        f"imported and not declared: {missing}. These work here because the "
        f"virtualenv still has them and fail on a fresh `uv sync`."
    )


def test_the_accounting_engine_is_not_ours():
    """The specific claim this file exists to keep true.

    `post_and_assert` renders the journal to text and hands it to beancount's
    own loader; whatever the loader says is the answer. If that import ever goes
    away, this project has started hand-rolling double entry and the sentence
    "we do not write ledger code" stops being true.
    """
    io_module = ROOT / "src" / "recon" / "ledger" / "beancount_io.py"
    tree = ast.parse(io_module.read_text(), filename=str(io_module))
    imported = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "beancount" in imported

    from recon.ledger import beancount_io

    source = pathlib.Path(beancount_io.__file__).read_text()
    assert "loader.load_string" in source, (
        "the ledger no longer round-trips through beancount's loader, so its "
        "errors are no longer the verdict"
    )
