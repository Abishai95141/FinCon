# The AWS estate

*What runs where, what it costs, and the four decisions that are not obvious.*

Live at **<https://fincon.astutecomputer.com>** · region `ap-south-1` (Mumbai) ·
one CloudFormation stack named `fincon` · [infra/fincon.yaml](../infra/fincon.yaml).

---

## 1. The shape

```
                        Cloudflare DNS  (astutecomputer.com)
                         │  A → ALB          CAA → amazon.com
                         ▼
              ┌──────────────────────────────────────────┐
   :443 ──────│  Application Load Balancer                │
   :80  ──────│  ACM cert · TLS 1.3 · :80 → :443 redirect │
              └───────────────────┬──────────────────────┘
                                  │  target group /healthz, 30s
                    ┌─────────────▼─────────────┐
                    │  ECS Fargate  ·  1 task    │
                    │  256 CPU / 512 MB          │
                    │  recon-api :8000           │
                    │  ┌──────────────────────┐  │
                    │  │ HTTP screens  /      │  │
                    │  │ OpenAPI       /docs  │  │
                    │  │ MCP           /mcp   │  │
                    │  └──────────────────────┘  │
                    └──┬────────┬────────┬───────┘
                       │        │        │
          ┌────────────▼──┐  ┌──▼─────┐  ┌▼──────────────┐
          │ EFS           │  │ Cognito│  │ Secrets Mgr   │
          │ /fincon  runs │  │ pool + │  │ session key   │
          │ /uploads srcs │  │ client │  │ client secret │
          └───────────────┘  └────────┘  │ deepseek key  │
                                          └───────────────┘
                    │
              CloudWatch Logs  ·  ECR (images by commit sha)
```

**19 resources**, all in one template: a VPC with two public subnets and an
internet gateway, three security groups, two IAM roles, the ALB and its two
listeners, a target group, the ECS cluster / service / task definition, an EFS
filesystem with two mount targets and two access points, and a log group.

---

## 2. The four decisions worth arguing about

### 2.1 EFS, not S3 — and the bug that nearly ended it

The decision log is **append-only and hash-chained**, and the code that writes it
takes a POSIX lock. S3 has no locks and no append; every write would have been a
read-modify-write of the whole object, which is exactly the race the chain exists
to detect. So: a filesystem.

That choice nearly did not survive contact. **`flock` does not work on EFS.**
Every read of a just-written log blocked for the full 30-second timeout and then
reported a stuck writer — a truthful message about a lock and a useless one about
the bug. NFSv4 supports `fcntl` byte-range locks and not BSD `flock`, and the
locking was the *entire justification* for choosing EFS over S3. Rebuilt on
`fcntl.lockf` with an in-process reader-writer gate and a refcounted
cross-process exclusive lock; see [`journal/__init__.py`](../src/recon/journal/__init__.py).

**Two access points, not one.** `/fincon` holds run records, `/uploads` holds
per-account source files. They were one for a while, and `data/sources` was not
on EFS at all — so **every deployment deleted every uploaded file**, silently,
because a container filesystem is ephemeral and nothing said so.

`DeletionPolicy: Retain` on the filesystem. Deleting a stack should not delete
the books.

### 2.2 Public subnets, no NAT gateway

A NAT gateway is about **$32/month** before a byte moves. The task needs
outbound egress for Cognito, Secrets Manager and the DeepSeek API, and it gets
it from a public subnet with `AssignPublicIp: ENABLED` behind a security group
that accepts inbound **only** from the ALB's security group.

The trade is stated rather than hidden: the task has a public IP, and its
protection is the security group rather than the absence of a route. For a
single-tenant demo estate that is the right end of the trade; for a regulated
production deployment it is not, and the fix is private subnets plus a NAT or
VPC endpoints.

### 2.3 One task, and what that means

`DesiredCount: 1`, `MinimumHealthyPercent: 100`, `MaximumPercent: 200` — so a
deploy starts the new task, waits for two healthy checks, then stops the old
one. **`DeploymentCircuitBreaker: {Enable: true, Rollback: true}`**: a task that
cannot pass its health check rolls the service back rather than leaving the
service draining.

One task means **no concurrent-writer problem in production** — which is a
convenience, not a design. The locking is written for many, tested at 8 threads
and 6 processes, and the count is a cost decision that can change without
touching the code.

### 2.4 Identity is never a parameter

Cognito issues the session; the pool id, client id and client secret are stack
parameters and the secret arrives by **ARN**, resolved by the task role at
runtime, never as an environment literal in the task definition.

Over HTTP the account is the token's `sub` claim. Over stdio it is
`RECON_TENANT`. It is **never a request parameter** — a caller that could name
an account could name someone else's, and an MCP caller may be a model. The same
rule governs the write tools: the name on a decision comes off the credential.

---

## 3. Everything, itemised

| Resource | Id / setting | Why this one |
|---|---|---|
| **Region** | `ap-south-1` | Rupee-denominated books, Indian tax loop, lowest latency to the operator |
| **ECS cluster** | `fincon` | Fargate only — no EC2 to patch |
| **Task** | 256 CPU · 512 MB | A close on 517 rows peaks well under this. Raise before scaling out |
| **Image** | `…/fincon:<git-sha>` | Tagged by commit, never `latest`: `latest` makes a rollback un-nameable |
| **ALB** | 2 listeners | `:80` → 301 `:443`. Idle timeout raised above the 300s default — MCP over Streamable HTTP holds a connection open and the default cut long tool calls into transport errors |
| **Target group** | `/healthz`, 30s, 2 healthy / 3 unhealthy | 60s grace period covers cold start |
| **ACM** | TLS 1.3 (`ELBSecurityPolicy-TLS13-1-2-2021-06`) | DNS-validated |
| **EFS** | `fs-056df8e0…`, 2 mount targets | One per AZ, both required for a task in either |
| **Access points** | `/fincon` (runs), `/uploads` (sources) | uid/gid `10001`, matching the container's non-root user |
| **Cognito** | pool `ap-south-1_kNSrctMRo` | `USER_PASSWORD_AUTH` with `SECRET_HASH`; confidential client |
| **Secrets** | session key, Cognito client secret, DeepSeek key | Injected by ARN, read by the task role |
| **Logs** | CloudWatch, `/ecs/fincon` | |
| **DNS** | Cloudflare, `fincon.astutecomputer.com` | Proxy **off** — an orange-cloud proxy in front of an ALB with its own ACM cert doubles TLS termination for nothing |

---

## 4. Deploying

```bash
cp infra/deploy.env.example infra/deploy.env   # once — account, pool, cert, url
make deploy
```

`infra/deploy.env` is gitignored and holds the estate's coordinates. They are
identifiers rather than credentials — every real secret is fetched by ARN from
Secrets Manager at deploy time — but publishing the address of a live estate on
a public repository is free to avoid.

**Two footguns, both of which have fired.**

**`TAG` comes from `git rev-parse --short HEAD`.** Build with the fix
uncommitted and the image pushes to the tag already deployed — CloudFormation
sees `Image` unchanged, and ECS never rolls. Commit first.

**`cloudformation deploy` falls back to *template defaults* for any parameter
you do not pass, not to the previous value.** `CertificateArn` defaults to `""`,
which serves plain HTTP, so omitting it on an update **drops the HTTPS
listener** — silently, on a live service. This is why `PublicUrl` and
`CertificateArn` are now always passed, defaulted from `deploy.env` rather than
left off:

```make
PublicUrl=$(if $(PUBLIC_URL),$(PUBLIC_URL),$(DEPLOY_PUBLIC_URL)) \
CertificateArn=$(if $(CERT),$(CERT),$(DEPLOY_CERT_ARN))
```

To read what the live stack currently believes:

```bash
aws cloudformation describe-stacks --stack-name fincon \
  --query 'Stacks[0].Parameters[].[ParameterKey,ParameterValue]' --output text
```

---

## 5. Three deployed 500s, and the test that came out of them

The first deploy returned 500 on every authenticated route, three times in a
row, for three different missing-configuration reasons:

1. `RECON_AUTH` was unset, so the app fell back to the local credential store
   and found no user file.
2. The task role was missing `cognito-idp:AdminGetUser`.
3. The task definition set `FINCON_SESSION_SECRET`; the code reads
   `RECON_SESSION_SECRET`.

The third is the interesting one — nothing was misconfigured, the two halves
simply disagreed about a name, and no test could see it because each half was
internally consistent. Generalised into
[`tests/property/test_infrastructure.py`](../tests/property/test_infrastructure.py),
which parses the CloudFormation template and **fails on any task-definition
environment variable nothing under `src/` reads**, and on any variable the code
requires that the template does not set.

## 6. Cloudflare CAA blocked certificate issuance

ACM validation failed with `CAA_ERROR`. Cloudflare adds a CAA record set for its
own CA list on any zone using its certificates, and Amazon is not in it — so the
DNS record said, correctly, that Amazon was not permitted to issue for this name.

Added `amazon.com` on the subdomain. Worth knowing: **a FAILED ACM certificate
cannot be revalidated.** Delete it and request a new one.

---

## 7. What this estate does not have

Stated because an architecture document that lists only what exists is a sales
brochure.

| | |
|---|---|
| **No multi-AZ redundancy in practice** | Two subnets exist; one task runs. An AZ failure is an outage until ECS reschedules |
| **No backup of the decision log** | EFS has no automatic backup configured. `Retain` protects against stack deletion, not against deletion |
| **No WAF, no rate limit at the edge** | Sign-up and sign-in are rate-limited *in the application*, per caller, in memory — which does not survive a restart and does not coordinate across tasks |
| **SES is in sandbox** | Confirmation email reaches verified addresses only. Production access is an AWS request, not a code change |
| **No alarms** | Logs go to CloudWatch and nobody is paged. There is no metric filter and no SNS topic |
| **Secrets are not rotated** | Three secrets, all manual. Rotation is a Lambda nobody has written |
| **One environment** | No staging. `make deploy` goes to the thing the URL points at |
