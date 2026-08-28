.DEFAULT_GOAL := help
SHELL := /bin/bash

# Gates that are GREEN in STATUS.md. `make verify` re-runs exactly these.
# Add a phase number here ONLY when its gate output is pasted into STATUS.md.
GREEN_GATES := 0 1 2 3 4 5 6 7 8 9 10 11 13 14 15

# Gates that require a live model and cannot run offline. Excluded from
# `make test` so a fresh clone still passes, and NAMED in the output so the
# exclusion is visible — a silently skipped gate that reads as green is the
# pytest-collection trap from P1 in a new costume.
LIVE_GATES := 12 12b 12c

.PHONY: help setup verify gate eval gen test e2e lint serve mcp graph status

help:
	@echo "Read CLAUDE.md, then STATUS.md, then run 'make verify'."
	@echo
	@echo "  setup     uv sync"
	@echo "  verify    re-run every currently-green gate ($(if $(GREEN_GATES),$(GREEN_GATES),none yet))"
	@echo "            (P$(LIVE_GATES) needs a live model — not in verify, see STATUS)"
	@echo "  gate P=N  run the gate for phase N"
	@echo "  eval      ablation runner - 4 arms, 9 metrics, batches A and B     [P10]"
	@echo "  gen       regenerate synthetic batches from seed                     [P0]"
	@echo "  test      unit + property"
	@echo "  e2e       end-to-end on a generated batch"
	@echo "  lint      ruff + the no-float rule"
	@echo "  serve     start the HTTP API and the screens         [P14]"
	@echo "            (http://127.0.0.1:8000/ — no terminal needed after this)"
	@echo "  mcp       start the MCP server on stdio               [P13]"
	@echo "  mcp-http  the same tools over Streamable HTTP + OAuth  [P22]"
	@echo "  ses       wire Cognito to SES once the sender is verified  [CHECK=1]"
	@echo "  graph     refresh the graphify code graph"
	@echo "  logo      re-render the README lockup from the shipped mark"
	@echo "  shots     capture the product screenshots  [needs a local close]"
	@echo "  replay    re-derive a close from its decision log alone         [P9]"
	@echo "  sign      sign the authority bundles                        SIGNER='name'"
	@echo "            (verify with RECON_BUNDLE_PUBKEY=$$(cat data/trust/authorized-key.hex))"
	@echo "  mutate    revert each control, confirm the suite goes red   [SET=p9..p21]"
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
	@echo "verify runs offline: tests marked 'live' are deselected, and named here."
	@echo "  pytest prints the count per gate as 'N deselected'. To run one whole,"
	@echo "  including its live tests: make gate P=<n>   (needs DEEPSEEK_API_KEY)."
	@for p in $(GREEN_GATES); do \
	  echo "=== gate P$$p ==="; $(MAKE) --no-print-directory gate P=$$p OFFLINE=1 || exit 1; \
	done
endif

gate:
	@test -n "$(P)" || { echo "usage: make gate P=<phase number>"; exit 2; }
	@if [ ! -f "tests/gates/gate_p$(P).py" ]; then \
	  echo "Gate P$(P) has no runner yet — that phase has not been built."; \
	  echo "Do not mark it green in STATUS.md. See CLAUDE.md rule 1."; \
	  exit 1; \
	fi
	@$(if $(OFFLINE),echo "OFFLINE=1 — tests marked 'live' are deselected; run without it for the whole gate.",true)
	uv run pytest -q "tests/gates/gate_p$(P).py" $(if $(OFFLINE),-m "not live",)

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

# The same 21 tools over Streamable HTTP. Loopback with no auth; anywhere else
# it refuses until Cognito is configured, and names the variables it wants.
mcp-http:
	uv run recon-mcp-http

# ---- AWS -----------------------------------------------------------------
# Account-specific values live in a gitignored `infra/deploy.env`, not here.
# They are identifiers rather than credentials — an account id is not a secret
# and a Cognito client id ships to browsers by design — but publishing the
# coordinates of a live estate on a public repository is free to avoid and
# tells a stranger exactly what to point at.
#
#   cp infra/deploy.env.example infra/deploy.env   and fill it in.
-include infra/deploy.env

AWS_REGION ?= ap-south-1
STACK      ?= fincon
# The image is tagged with the commit, never `latest`: a service pointed at a
# moving tag cannot be rolled back to whatever was running.
ECR = $(AWS_ACCOUNT).dkr.ecr.$(AWS_REGION).amazonaws.com/$(STACK)
TAG = $(shell git rev-parse --short HEAD)

# Fail with the reason rather than pushing to `.dkr.ecr…amazonaws.com/fincon`
# and reporting an authentication error about a registry that does not exist.
guard-deploy-env:
	@test -n "$(AWS_ACCOUNT)" || { \
	  echo "infra/deploy.env is missing or has no AWS_ACCOUNT."; \
	  echo "cp infra/deploy.env.example infra/deploy.env and fill it in."; exit 2; }
	@test -n "$(COGNITO_POOL_ID)" || { echo "deploy.env: COGNITO_POOL_ID unset"; exit 2; }
	@test -n "$(COGNITO_CLIENT_ID)" || { echo "deploy.env: COGNITO_CLIENT_ID unset"; exit 2; }

# Extra flags for the image build, empty by default. An escape hatch for a
# broken *local* Docker network rather than a change to how the image is built:
# Docker Desktop's embedded resolver has been seen answering AAAA-only for
# pypi.org while the host resolves it to IPv4 fine, and a build container with no
# IPv6 route then fails `uv sync` with "Network unreachable". `--network=host`
# borrows the host's stack and the build proceeds:
#
#   make deploy DOCKER_BUILD_FLAGS=--network=host
#
# Left empty so CI, which builds with buildx on Linux and has working DNS, is
# unaffected — the flag is not portable there.
DOCKER_BUILD_FLAGS ?=

image: guard-deploy-env
	aws ecr get-login-password --region $(AWS_REGION) | \
	  docker login --username AWS --password-stdin $(firstword $(subst /, ,$(ECR)))
	docker build --platform linux/amd64 $(DOCKER_BUILD_FLAGS) -t $(ECR):$(TAG) .
	docker push $(ECR):$(TAG)

# PUBLIC_URL and CERT are passed explicitly on purpose. `cloudformation deploy`
# resets any parameter you omit to its TEMPLATE DEFAULT rather than to the
# previous value, and CertificateArn defaults to "" — so a bare `make deploy`
# on a live stack silently removes the HTTPS listener. Both default here to
# whatever deploy.env says, and either can still be overridden on the command
# line for a one-off.
deploy: image
	aws cloudformation deploy --template-file infra/fincon.yaml --stack-name $(STACK) \
	  --capabilities CAPABILITY_IAM --parameter-overrides \
	    Image=$(ECR):$(TAG) \
	    CognitoUserPoolId=$(COGNITO_POOL_ID) \
	    CognitoClientId=$(COGNITO_CLIENT_ID) \
	    CognitoClientSecretArn=$(shell aws secretsmanager describe-secret --secret-id $(STACK)/cognito-client-secret --query ARN --output text) \
	    SessionSecretArn=$(shell aws secretsmanager describe-secret --secret-id $(STACK)/session-secret --query ARN --output text) \
	    DeepSeekApiKeyArn=$(shell aws secretsmanager describe-secret --secret-id $(STACK)/deepseek-api-key --query ARN --output text) \
	    PublicUrl=$(if $(PUBLIC_URL),$(PUBLIC_URL),$(DEPLOY_PUBLIC_URL)) \
	    CertificateArn=$(if $(CERT),$(CERT),$(DEPLOY_CERT_ARN))
	aws cloudformation describe-stacks --stack-name $(STACK) \
	  --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' --output table

deploy-logs:
	aws logs tail /ecs/$(STACK) --since 15m --follow

# Finish the Cognito -> SES wiring once the sender identity is verified.
ses:
	SES_SENDER=$(SES_SENDER) COGNITO_POOL_ID=$(COGNITO_POOL_ID) AWS_REGION=$(AWS_REGION) \
	  uv run python -m tools.wire_ses $(if $(CHECK),--check,)

graph:
	graphify update .

logo:
	uv run python -m tools.logo

# Screenshots for the README and the landing page. Needs a local server with a
# close already run, and a session cookie minted against the same secret it is
# running with — see tools/shots.py.
shots:
	uv run --with playwright python -m tools.shots $(if $(BASE),--base $(BASE),) $(if $(FULL),--full,)

status:
	@sed -n '1,20p' STATUS.md
