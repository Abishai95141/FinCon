# FinCon — the web app, the JSON API and the MCP endpoint, in one image.
#
# One container because they are one process: `recon.api.serve` mounts MCP into
# the FastAPI app, so a deployment is one port, one certificate and one thing to
# roll back.
#
# Nothing writes inside the image. `data/runs` and `data/batches` are an EFS
# mount at runtime — the decision log is append-only JSONL under an flock on a
# sidecar, which NFSv4 supports and an S3 bucket does not, and that is the whole
# reason this is Fargate rather than Lambda.

FROM python:3.14-slim AS base

# uv, pinned by digest rather than by tag: `:latest` in a build that produces an
# artifact somebody signs is a supply chain with a hole in it.
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies in their own layer, so a code change does not rebuild ortools.
# `--frozen` fails rather than resolving: an image whose lockfile drifted from
# the repo is an image nobody can reproduce.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY src/ ./src/
COPY data/policy/ ./data/policy/
COPY data/taxonomy/ ./data/taxonomy/
COPY data/rules/ ./data/rules/
COPY data/profiles/ ./data/profiles/
COPY data/adapters/ ./data/adapters/
COPY data/trust/authorized-key.hex ./data/trust/authorized-key.hex
RUN uv sync --frozen --no-dev

# `dev-signing-key.hex` is NOT copied. The image ships the authorized *public* key
# and nothing else — a bundle that carried its own verification key would vouch
# for itself, and an image that carried the private one would let anyone holding
# it mint authority.

# Not root. The EFS mount is owned by this uid.
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin fincon \
    && mkdir -p /app/data/runs /app/data/batches \
    && chown -R fincon:fincon /app/data
USER fincon

ENV PATH="/app/.venv/bin:$PATH" \
    RECON_ENV=prod \
    FINCON_MCP_HOST=0.0.0.0 \
    FINCON_TRUSTED_PROXIES=*

EXPOSE 8000

# The ALB decides whether this task is healthy, and it asks here. `/healthz`
# touches no account and no disk, so a slow EFS mount does not read as a dead
# container.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=4).status==200 else 1)"

CMD ["recon-api", "--host", "0.0.0.0", "--port", "8000"]
