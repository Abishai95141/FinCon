"""Mutation harness. Revert a control, confirm the suite goes red.

    python -m tools.mutate                 # every mutation set
    python -m tools.mutate --set p12       # one set
    python -m tools.mutate --list

Every "N/N mutations caught" claim in STATUS.md came from scripts in `/tmp`, so
none of them was reproducible by anyone else — the single most load-bearing
verification in this build was also the least checkable. It lives here now and
`make mutate` runs it.

Three properties learned the hard way:

**Pre-flight or refuse.** An interrupted run once left a mutation in the source
and every result after it described a tree nobody meant to test. Each anchor
must be present exactly once before anything is touched, and the tree is
compared afterwards.

**A mutant proves reachability, not meaning.** `max_selectivity_pct` shipped
with a mutation that killed it and was still refuted by a metamorphic relation.
Mutation testing is necessary and insufficient; `tests/property/` is the other
half.

**A surviving mutant is usually a weak test, not a missing control.** Of the
survivors this harness has found, almost all were assertions of mine that passed
for the wrong reason — a guard masking a dead one, a fixture that could not
distinguish what it claimed to test.
"""

from __future__ import annotations

import argparse
import atexit
import importlib
import os
import pathlib
import signal
import subprocess
import sys

SETS = ("p9", "p10", "p11", "p12", "p12b", "p12d", "p13")


def _module(name: str):
    return importlib.import_module(f"tools.mutations.{name}")


def _load(name: str):
    return _module(name).MUTATIONS


def run_set(name: str, env: dict) -> tuple[int, int]:
    mutations = _load(name)
    files = {path for _, path, _, _ in mutations}

    # Pre-flight. Anchors must be unambiguous or nothing is touched.
    problems = [
        label
        for label, path, old, _ in mutations
        if pathlib.Path(path).read_text(encoding="utf-8").count(old) != 1
    ]
    if problems:
        print(f"[{name}] REFUSING — anchors missing or ambiguous:")
        for label in problems:
            print(f"    {label}")
        return 0, len(mutations)

    baseline = {p: pathlib.Path(p).read_text(encoding="utf-8") for p in files}

    def restore(*_args) -> None:
        """Put every file back, whatever happened.

        A `finally` block is not enough: a timeout kills the process and the
        mutation stays on disk, which is how one got committed. Registered for
        SIGINT and SIGTERM as well as normal exit.
        """
        for path, text in baseline.items():
            target = pathlib.Path(path)
            if target.read_text(encoding="utf-8") != text:
                target.write_text(text, encoding="utf-8")

    atexit.register(restore)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *a: (restore(), sys.exit(130)))

    caught = 0
    width = max(len(label) for label, _, _, _ in mutations)

    for label, path, old, new in mutations:
        target = pathlib.Path(path)
        original = target.read_text(encoding="utf-8")
        target.write_text(original.replace(old, new, 1), encoding="utf-8")
        try:
            proc = subprocess.run(
                [
                    ".venv/bin/python",
                    "-m",
                    "pytest",
                    "-q",
                    "-x",
                    "--no-header",
                    "-p",
                    "no:cacheprovider",
                    *_module(name).TARGETS,
                ],
                capture_output=True,
                text=True,
                timeout=900,
                env=env,
            )
        finally:
            target.write_text(original, encoding="utf-8")
        red = proc.returncode != 0
        caught += red
        print(f"  {label:<{width}}  {'RED' if red else '*** SURVIVED ***'}")

    for path, text in baseline.items():
        if pathlib.Path(path).read_text(encoding="utf-8") != text:
            print(f"  !! {path} was not restored — results above are untrustworthy")
            pathlib.Path(path).write_text(text, encoding="utf-8")
    return caught, len(mutations)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools.mutate")
    ap.add_argument("--set", dest="only", choices=SETS)
    ap.add_argument("--list", action="store_true")
    ap.add_argument(
        "--preflight",
        action="store_true",
        help="check every anchor without applying anything or calling a model",
    )
    args = ap.parse_args(argv)

    if args.preflight:
        stale = 0
        for name in [args.only] if args.only else SETS:
            bad = [
                label
                for label, path, old, _ in _load(name)
                if pathlib.Path(path).read_text(encoding="utf-8").count(old) != 1
            ]
            stale += len(bad)
            print(f"  {name:<6} {len(_load(name)):>3} mutations, {len(bad)} stale")
            for label in bad:
                print(f"           - {label}")
        # Cheap, offline, and the thing that keeps a ported set from rotting:
        # a mutation whose anchor no longer matches is silently not applied, and
        # a set of those reports a perfect score over nothing.
        return 1 if stale else 0

    if args.list:
        for name in SETS:
            print(f"  {name:<6} {len(_load(name))} mutations")
        return 0

    dirty = subprocess.run(
        ["git", "status", "--porcelain", "src", "bench"], capture_output=True, text=True
    ).stdout.strip()
    if dirty:
        print(
            "REFUSING — src/ or bench/ has uncommitted changes. A mutation run "
            "rewrites files in place; commit or stash first so a crash cannot "
            "lose work."
        )
        return 2

    env = dict(os.environ)
    total_caught = total = 0
    for name in [args.only] if args.only else SETS:
        if name in ("p12", "p12b") and not env.get("DEEPSEEK_API_KEY"):
            print(f"[{name}] skipped — needs DEEPSEEK_API_KEY (no offline mode, rule 1)")
            continue
        print(f"\n[{name}]")
        caught, count = run_set(name, env)
        total_caught += caught
        total += count

    print(f"\n{total_caught}/{total} mutations caught")
    return 0 if total_caught == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
