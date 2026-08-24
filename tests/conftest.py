"""Which tests need a live model, derived rather than declared.

The P12 gates are excluded from `make test` by filename because they can call
DeepSeek and CLAUDE.md rule 1 forbids an offline mode. Excluding the *file*
excluded everything in it — including assertions that never touch a model: the
closed parse vocabulary, the producer table, the AST guard keeping model text
out of the posting layer. Those only ran when someone had a key and chose to
pay, and four of them were quietly stale by 2026-08-24, one of them a security
assertion about ADR-001.

So the split is computed, not written down. A test is `live` if it constructs a
`ModelEdge` — in its own body, or in any fixture it pulls in. The first version
of this file keyed on a fixture named `edge`, which is exactly the hand-kept
list it was meant to replace: `gate_p12c` builds its edge inside `authored` and
was mis-marked immediately.
"""

from __future__ import annotations

import inspect

import pytest

#: What the model edge is called at its construction site. A test or fixture
#: whose source names it reaches a real model when it runs.
EDGE = "ModelEdge"


def _reaches_model(func) -> bool:
    try:
        return EDGE in inspect.getsource(func)
    except (OSError, TypeError):
        return False


def pytest_collection_modifyitems(items):
    for item in items:
        sources = [getattr(item, "function", None)]
        for defs in getattr(item, "_fixtureinfo", None).name2fixturedefs.values():
            sources.extend(d.func for d in defs)
        if any(f is not None and _reaches_model(f) for f in sources):
            item.add_marker(pytest.mark.live)


def pytest_configure(config):
    config.addinivalue_line("markers", "live: reaches a real model; needs DEEPSEEK_API_KEY")
