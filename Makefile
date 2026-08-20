.DEFAULT_GOAL := help
SHELL := /bin/bash

# Gates that are GREEN in STATUS.md. `make verify` re-runs exactly these.
# Add a phase number here ONLY when its gate output is pasted into STATUS.md.
GREEN_GATES := 0 1 2 3 4

.PHONY: help setup verify gate eval gen test e2e lint graph status

help:
	@echo "Read CLAUDE.md, then STATUS.md, then run 'make verify'."
	@echo
	@echo "  setup     uv sync + install hooks"
	@echo "  verify    re-run every currently-green gate ($(if $(GREEN_GATES),$(GREEN_GATES),none yet))"
	@echo "  gate P=N  run the gate for phase N"
	@echo "  eval      ablation runner - 4 arms, 8 metrics, batches A and B      [P6]"
	@echo "  gen       regenerate synthetic batches from seed                     [P0]"
	@echo "  test      unit + property"
	@echo "  e2e       end-to-end on a generated batch"
	@echo "  lint      ruff + the no-float rule"
	@echo "  graph     refresh the graphify code graph"
	@echo "  status    print the tracker header"

setup:
	uv sync
	@echo "setup done. Next: read STATUS.md -> Next action."

# verify re-runs only gates recorded green. With none green it says so and exits 0 —
# it must never imply the build works when nothing has been proven.
verify:
ifeq ($(strip $(GREEN_GATES)),)
	@echo "No gates are green yet. Nothing to verify."
	@echo "See STATUS.md -> Next action."
else
	@for p in $(GREEN_GATES); do \
	  echo "=== gate P$$p ==="; $(MAKE) --no-print-directory gate P=$$p || exit 1; \
	done
endif

gate:
	@test -n "$(P)" || { echo "usage: make gate P=<phase number>"; exit 2; }
	@if [ ! -f "tests/gates/gate_p$(P).py" ]; then \
	  echo "Gate P$(P) has no runner yet — that phase has not been built."; \
	  echo "Do not mark it green in STATUS.md. See CLAUDE.md rule 1."; \
	  exit 1; \
	fi
	uv run pytest -q "tests/gates/gate_p$(P).py"

gen:
	@test -d bench/generator && test -n "$$(ls -A bench/generator 2>/dev/null | grep -v __init__)" \
	  || { echo "P0 not built — bench/generator/ is empty."; exit 1; }
	uv run python -m bench.generator

eval:
	uv run python -m bench.run

test:
	uv run pytest -q tests/unit tests/property tests/gates

e2e:
	uv run pytest -q tests/e2e

lint:
	uv run ruff check src bench tests
	uv run ruff format --check src bench tests
	@# CLAUDE.md rule 4: float is banned in the engine and ledger.
	@! grep -rnE '\bfloat\s*\(|:\s*float\b' src/recon/engine src/recon/ledger \
	  || { echo "float found in engine/ledger — see CLAUDE.md rule 4"; exit 1; }

graph:
	graphify update .

status:
	@sed -n '1,20p' STATUS.md
