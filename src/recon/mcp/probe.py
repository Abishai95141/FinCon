"""Start the MCP server in a real process and see whether it answers.

A configuration page that renders a JSON block and says "you're all set" has
checked nothing. The whole failure surface of an MCP integration is *between*
processes — the interpreter is wrong, the module does not import, the working
directory has no `data/`, the tenant environment variable points at a directory
that does not exist — and none of that is visible from inside the process that
wrote the config.

So this spawns the server the same way a client will, over stdio, with the same
command the page tells the user to paste, and speaks the protocol to it. What
comes back is a fact about the machine the user is on. `handshake_ms` is a
measurement and lives here rather than in any decision — a wall clock inside a
close is banned for good reason, but a diagnostic is exactly where a stopwatch
belongs.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import serve_command

#: Long enough for a cold interpreter to import pydantic and beancount on a
#: laptop, short enough that a hung server does not hold a request open. A
#: timeout is reported as a timeout, never as a failure to connect — they have
#: different causes and different fixes.
TIMEOUT_SECONDS = 30.0

#: The tool the probe actually calls. Stateless, needs no account, no period and
#: no files on disk — so a failure here is the transport or the server, never the
#: user's data. Calling something heavier would make a green probe depend on a
#: batch existing, which is a different question than "is the server reachable".
PROBE_TOOL = "get_contracts"


@dataclass(frozen=True)
class Probe:
    """What happened when we tried. Every field is observed, none inferred."""

    ok: bool
    command: str
    """The exact command line, as a client would run it."""

    cwd: str
    tenant: str | None
    tools: tuple[str, ...] = ()
    handshake_ms: int = 0
    called: str = ""
    """The tool the probe invoked, and got an answer from."""

    contract_version: str = ""
    """Read back off the wire — proof the answer came from the server rather
    than from this process importing the same module."""

    error: str = ""
    hint: str = ""
    """What to do about `error`. An error with no remedy is a dead end."""

    warnings: tuple[str, ...] = field(default_factory=tuple)


def _hint_for(exc: BaseException) -> str:
    text = str(exc)
    if isinstance(exc, TimeoutError):
        return (
            f"The server did not complete a handshake in {TIMEOUT_SECONDS:.0f}s. That is "
            "usually a first run compiling dependencies — try again, and if it repeats, "
            "run the command in a terminal to see what it prints."
        )
    if "ModuleNotFoundError" in text or "No module named" in text:
        return (
            "The interpreter that starts the server cannot import `recon`. Use the "
            "absolute path to this project's virtualenv python, shown above, rather "
            "than a system `python3`."
        )
    if "No such file or directory" in text or "cwd" in text.lower():
        return "Set the client's working directory to this project root, shown above."
    return "Run the command in a terminal — the server prints its own reason on stderr."


def probe(*, timeout: float = TIMEOUT_SECONDS) -> Probe:
    """Spawn, handshake, list tools, call one, and report.

    Never raises. A configuration screen that 500s when the thing it is
    diagnosing is broken has inverted its own purpose — the failure *is* the
    answer, and it is more useful than the success.
    """
    command, args = serve_command()
    cwd = str(Path.cwd())
    tenant = os.environ.get("RECON_TENANT")
    line = " ".join([command, *args])

    warnings: list[str] = []
    if tenant and not (Path("data/runs") / tenant).exists():
        warnings.append(
            f"RECON_TENANT is set to {tenant} but data/runs/{tenant} does not exist yet. "
            "The server will start and show no closes until this account runs one."
        )

    async def go() -> tuple[tuple[str, ...], str]:
        from fastmcp import Client
        from fastmcp.client.transports import StdioTransport

        async with Client(StdioTransport(command=command, args=args)) as client:
            names = tuple(sorted(t.name for t in await client.list_tools()))
            result = await client.call_tool(PROBE_TOOL, {})
            data = result.data or {}
            return names, str(data.get("contract_version", ""))

    started = time.monotonic()
    try:
        tools, version = asyncio.run(asyncio.wait_for(go(), timeout))
    except BaseException as exc:
        return Probe(
            ok=False,
            command=line,
            cwd=cwd,
            tenant=tenant,
            handshake_ms=int((time.monotonic() - started) * 1000),
            error=f"{type(exc).__name__}: {exc}".strip()[:400],
            hint=_hint_for(exc),
            warnings=tuple(warnings),
        )

    elapsed = int((time.monotonic() - started) * 1000)
    if not tools:
        return Probe(
            ok=False,
            command=line,
            cwd=cwd,
            tenant=tenant,
            handshake_ms=elapsed,
            error="The server connected and advertised no tools.",
            hint="A server with an empty tool list is a broken import, not a configuration.",
            warnings=tuple(warnings),
        )

    return Probe(
        ok=True,
        command=line,
        cwd=cwd,
        tenant=tenant,
        tools=tools,
        handshake_ms=elapsed,
        called=PROBE_TOOL,
        contract_version=version,
        warnings=tuple(warnings),
    )


# ---------------------------------------------------------------------------
# the catalogue
#
# Read in-process, because a page render must not pay 1.3s to spawn a server
# just to list names. The *boundary* below is the part worth reading twice: it
# is computed from the schemas FastMCP generates, not from a list somebody
# maintained by hand, so a tool added next month is checked by the same code
# that renders it. `tests/gates/gate_p13.py::test_no_tool_can_supply_authority`
# asserts the same thing across a real process boundary.
# ---------------------------------------------------------------------------

#: Parameters that would let a caller supply its own permission. Every finding
#: in `docs/04-CONTROL-PLANE-AUDIT.md` reduces to exactly that, and a parameter
#: is how a caller supplies anything.
AUTHORITY_PARAMS = frozenset(
    {"policy", "tolerance", "tolerance_ceiling", "side_signs", "rules", "chart", "profile"}
)

#: The one tool allowed to take a policy, and safe for the opposite reason: it
#: holds no state, reads nothing of ours, and a caller verifying under their own
#: policy learns about their own constraints. That is an auditor checking our
#: answer under their rules, which is the entire point of publishing it.
STATELESS_TOOL = "verify_proof"

#: Tools that change something on disk. Everything else is a read. Derived from
#: what each one calls rather than from its name — `reverify_close` sounds like a
#: write and is not.
WRITING_TOOLS = frozenset({"run_close"})


@dataclass(frozen=True)
class Tool:
    name: str
    summary: str
    params: tuple[str, ...]
    writes: bool
    stateless: bool
    """Needs no account, no period and no state of ours — `verify_proof` only."""


@dataclass(frozen=True)
class Catalog:
    tools: tuple[Tool, ...]
    offenders: dict[str, tuple[str, ...]]
    """Tools accepting an authority parameter, excluding the deliberate one.
    Non-empty means the boundary has been breached and the page says so."""

    @property
    def boundary_holds(self) -> bool:
        return not self.offenders

    @property
    def writes(self) -> tuple[str, ...]:
        return tuple(t.name for t in self.tools if t.writes)


def catalog() -> Catalog:
    """Every tool, its parameters, and whether the authority boundary holds."""
    from .server import mcp

    async def go():
        return await mcp.list_tools()

    tools, offenders = [], {}
    for spec in asyncio.run(go()):
        params = tuple(sorted((spec.parameters or {}).get("properties", {})))
        summary = (spec.description or "").strip().split("\n")[0]
        tools.append(
            Tool(
                name=spec.name,
                summary=summary,
                params=params,
                writes=spec.name in WRITING_TOOLS,
                stateless=spec.name == STATELESS_TOOL,
            )
        )
        breach = tuple(sorted(AUTHORITY_PARAMS.intersection(params)))
        if breach and spec.name != STATELESS_TOOL:
            offenders[spec.name] = breach

    return Catalog(tools=tuple(sorted(tools, key=lambda t: t.name)), offenders=offenders)
