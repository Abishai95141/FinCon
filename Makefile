.DEFAULT_GOAL := help
SHELL := /bin/bash

# Gates that are GREEN in STATUS.md. `make verify` re-runs exactly these.
# Add a phase number here ONLY when its gate output is pasted into STATUS.md.
GREEN_GATES := 0 1 2 3 4 5 6 7 8 9 10 11 13 14

# Gates that require a live model and cannot run offline. Excluded from
# `make test` so a fresh clone still passes, and NAMED in the output so the
# exclusion is visible — a silently skipped gate that reads as green is the
# pytest-collection trap from P1 in a new costume.
LIVE_GATES := 12 12b 12c

.PHONY: help setup verify gate eval gen test e2e lint serve mcp graph status

help:
	@echo "Read CLAUDE.md, then STATUS.md, then run 'make verify'."
	@echo
	@echo "  setup     uv sync + install hooks"
	@echo "  verify    re-run every currently-green gate ($(if $(GREEN_GATES),$(GREEN_GATES),none yet))"
	@echo "            (P$(LIVE_GATES) needs a live model — not in verify, see STATUS)"
	@echo "  gate P=N  run the gate for phase N"
	@echo "  eval      ablation runner - 4 arms, 8 metrics, batches A and B     [P10]"
	@echo "  gen       regenerate synthetic batches from seed                     [P0]"
	@echo "  test      unit + property"
	@echo "  e2e       end-to-end on a generated batch"
	@echo "  lint      ruff + the no-float rule"
	@echo "  serve     start the HTTP API and the screens         [P14]"
	@echo "            (http://127.0.0.1:8000/ui — no terminal needed after this)"
	@echo "  mcp       start the MCP server on stdio               [P13]"
	@echo "  ses       wire Cognito to SES once the sender is verified  [CHECK=1]"
	@echo "  graph     refresh the graphify code graph"
	@echo "  replay    re-derive a close from its decision log alone         [P9]"
	@echo "  sign      sign the authority bundles                        SIGNER='name'"
	@echo "            (verify with RECON_BUNDLE_PUBKEY=$$(cat data/trust/authorized-key.hex))"
	@echo "  mutate    revert each control, confirm the suite goes red   [SET=p9..p19]"
	@echo "            (rewrites src/ in place - do not run anything else meanwhile)"
	@echo "  mutate-preflight  check every mutation anchor, offline and free"
	@echo "  status-table  regenerate the known-broken table from its reproducers"
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

# One command, from a clean checkout: regenerates the batches from the seed if
# they are absent, re-hashes them against the committed manifest, and refuses to
# print a number if they do not tie.
eval:
	uv run python -m bench.run

# The gate's own claim, runnable by hand: rebuild the scorecard from the record.
replay:
	uv run python -m bench.replay_cli $(or $(B),A)

# The verification that finds shallow proxies. Lived in /tmp until now, which
# meant every "N/N caught" in STATUS was a claim nobody could check.
sign:
	uv run python -m tools.sign_bundles --signed-by "$(SIGNER)"

mutate:
	uv run python -m tools.mutate $(if $(SET),--set $(SET),)

# Offline, free, and the thing that keeps a ported mutation set from rotting: an
# anchor that no longer matches is silently not applied, and a set of those
# reports a perfect score over nothing.
mutate-preflight:
	uv run python -m tools.mutate --preflight

# The known-broken table, generated rather than written. An xfail that starts
# passing fails the suite and forces its row out.
status-table:
	uv run python -m tools.status_table

test:
	@echo "note: tests that construct a ModelEdge are deselected here (-m 'not live')."
	@echo "      the rest of P$(LIVE_GATES) does run. all of it: DEEPSEEK_API_KEY=... make gate P=12"
	uv run pytest -q tests/property tests/gates tests/known_broken.py -m "not live"

# The gates that run a full close against a generated batch with known labels.
# `tests/e2e/` was an empty directory this target pointed at, so the command
# measured layout rather than behaviour — these are where the end-to-end tests
# actually live and always were.
e2e:
	uv run pytest -q tests/gates/gate_p3.py tests/gates/gate_p9.py tests/gates/gate_p10.py

lint:
	uv run ruff check src bench tests
	uv run ruff format --check src bench tests
	@# CLAUDE.md rule 4: float is banned in the engine and ledger.
	@! grep -rnE '\bfloat\s*\(|:\s*float\b' src/recon/engine src/recon/ledger \
	  || { echo "float found in engine/ledger — see CLAUDE.md rule 4"; exit 1; }

# The product's two surfaces. `src/recon/api/` and `src/recon/mcp/` were 0-byte
# files until P13, so everything the engine did was real and none of it was
# reachable by anyone not running Python in this repo.
# Sign-in is at /login. `source .env.aws` first for real Cognito; with no
# configuration this runs RECON_AUTH=local — a real
# scrypt credential store in a JSON file that the app REFUSES to use unless
# RECON_ENV=dev, so a development account cannot follow the image to production.
serve:
	uv run recon-api $(if $(PORT),--port $(PORT),)

# stdio, for a local MCP client. `--transport http` for a remote one.
mcp:
	uv run recon-mcp

# The same 18 tools over Streamable HTTP. Loopback with no auth; anywhere else
# it refuses until Cognito is configured, and names the variables it wants.
mcp-http:
	uv run recon-mcp-http

# ---- AWS -----------------------------------------------------------------
# The image is tagged with the commit, never `latest`: a service pointed at a
# moving tag cannot be rolled back to whatever was running.
ECR = 531728396678.dkr.ecr.ap-south-1.amazonaws.com/fincon
TAG = $(shell git rev-parse --short HEAD)

image:
	aws ecr get-login-password --region ap-south-1 | \
	  docker login --username AWS --password-stdin $(firstword $(subst /, ,$(ECR)))
	docker build --platform linux/amd64 -t $(ECR):$(TAG) .
	docker push $(ECR):$(TAG)

deploy: image
	aws cloudformation deploy --template-file infra/fincon.yaml --stack-name fincon \
	  --capabilities CAPABILITY_IAM --parameter-overrides \
	    Image=$(ECR):$(TAG) \
	    CognitoUserPoolId=ap-south-1_kNSrctMRo \
	    CognitoClientId=4scuq8j5s68siqgnikmnskcir6 \
	    CognitoClientSecretArn=$(shell aws secretsmanager describe-secret --secret-id fincon/cognito-client-secret --query ARN --output text) \
	    SessionSecretArn=$(shell aws secretsmanager describe-secret --secret-id fincon/session-secret --query ARN --output text) \
	    DeepSeekApiKeyArn=$(shell aws secretsmanager describe-secret --secret-id fincon/deepseek-api-key --query ARN --output text) \
	    $(if $(PUBLIC_URL),PublicUrl=$(PUBLIC_URL),) $(if $(CERT),CertificateArn=$(CERT),)
	aws cloudformation describe-stacks --stack-name fincon \
	  --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' --output table

deploy-logs:
	aws logs tail /ecs/fincon --since 15m --follow

# Finish the Cognito -> SES wiring once the sender identity is verified.
ses:
	uv run python -m tools.wire_ses $(if $(CHECK),--check,)

graph:
	graphify update .

status:
	@sed -n '1,20p' STATUS.md
