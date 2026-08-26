"""The deployment, checked the way the code is.

Infrastructure gets a pass in most repositories: the template is read once,
applied, and never asserted on again. That is exactly how the two defects found
on the first container run happened — `0.0.0.0` in a set called `LOOPBACK`, and a
misconfigured pool taking the whole site down with an httpx traceback. Neither
was visible from any test, because no test looked at the deployment.

So these read `infra/fincon.yaml` and the `Dockerfile` as data and assert the
properties that would be expensive to discover in production: that the container
is not root, that the private signing key is not in the image, that nothing
reaches the tasks except the load balancer, that the filesystem holding every
decision log survives a stack delete, and that no secret is written in plain
text anywhere in the template.

Offline and free. Nothing here calls AWS.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "infra" / "fincon.yaml"
DOCKERFILE = ROOT / "Dockerfile"
DOCKERIGNORE = ROOT / ".dockerignore"


@pytest.fixture(scope="module")
def template() -> dict:
    """Parsed with a loader that tolerates CloudFormation's `!Ref` tags.

    `yaml.safe_load` refuses them outright, and the alternative — regexing a
    structured document — is how a test ends up asserting on whitespace.
    """

    class Loader(yaml.SafeLoader):
        pass

    def keep_tag(loader, tag_suffix, node):
        if isinstance(node, yaml.ScalarNode):
            return {f"Fn::{tag_suffix}": loader.construct_scalar(node)}
        if isinstance(node, yaml.SequenceNode):
            return {f"Fn::{tag_suffix}": loader.construct_sequence(node, deep=True)}
        return {f"Fn::{tag_suffix}": loader.construct_mapping(node, deep=True)}

    Loader.add_multi_constructor("!", keep_tag)
    return yaml.load(TEMPLATE.read_text(), Loader=Loader)


@pytest.fixture(scope="module")
def resources(template) -> dict:
    return template["Resources"]


# ------------------------------------------------------------------ the image


def test_the_container_does_not_run_as_root():
    """A container that mounts the audit trail should not be able to rewrite
    anything else in its own filesystem on a whim."""
    text = DOCKERFILE.read_text()
    assert re.search(r"^USER\s+fincon", text, re.M), "no USER directive, so this runs as root"
    assert re.search(r"useradd .*--uid 10001", text), "the uid must match the EFS access point"


def test_the_signing_key_is_not_in_the_image():
    """The image ships the authorized *public* key. Shipping the private one
    would let anybody holding the image mint authority, and an image is the most
    widely copied artifact a deployment has."""
    text = DOCKERFILE.read_text()
    copied = re.findall(r"^COPY\s+(\S+)", text, re.M)

    assert "data/trust/authorized-key.hex" in copied
    assert not any("signing" in path for path in copied)
    assert "data/trust/" not in copied, "the whole trust directory is copied, key and all"

    ignored = DOCKERIGNORE.read_text()
    assert "data/dev/" in ignored, "the dev env file carries the model key"
    assert "signing" in ignored


def test_the_image_pins_what_it_builds_from():
    """`:latest` in a build that produces a deployable artifact is a supply chain
    with a hole in it, and a lockfile allowed to resolve is an image nobody can
    reproduce."""
    text = DOCKERFILE.read_text()
    assert "uv:0.9.7" in text, "uv is not pinned"
    assert "--frozen" in text, "uv sync may resolve, so the image can drift from uv.lock"
    assert re.search(r"FROM python:3\.\d+", text)


def test_the_image_binds_somewhere_the_refusal_can_see():
    """The container sets a wildcard bind, which is the whole reason the
    unauthenticated-MCP refusal has to treat `0.0.0.0` as public. Asserted here
    so the two files cannot drift apart silently."""
    from recon.mcp import http as mcphttp

    host = re.search(r"FINCON_MCP_HOST=(\S+)", DOCKERFILE.read_text())
    assert host and host.group(1) not in mcphttp.LOOPBACK


# ----------------------------------------------------------------- the network


def test_nothing_but_the_load_balancer_reaches_the_container(resources):
    """The tasks have public IPs — that is how a NAT gateway is avoided — so the
    security group is the only thing standing between them and the internet."""
    task_sg = resources["TaskSecurityGroup"]["Properties"]
    for rule in task_sg["SecurityGroupIngress"]:
        assert "CidrIp" not in rule, f"the container accepts traffic from a CIDR: {rule}"
        assert "SourceSecurityGroupId" in rule
        assert rule["FromPort"] == 8000 and rule["ToPort"] == 8000


def test_the_filesystem_is_reachable_only_from_the_tasks(resources):
    efs_sg = resources["EfsSecurityGroup"]["Properties"]
    for rule in efs_sg["SecurityGroupIngress"]:
        assert "CidrIp" not in rule, "NFS is open to a CIDR"
        assert rule["FromPort"] == 2049


def test_only_the_load_balancer_takes_public_traffic(resources):
    """The one place `0.0.0.0/0` is correct, and it must stay the only one."""
    public = [
        name
        for name, body in resources.items()
        if body["Type"] == "AWS::EC2::SecurityGroup"
        for rule in body["Properties"].get("SecurityGroupIngress", [])
        if isinstance(rule, dict) and rule.get("CidrIp") == "0.0.0.0/0"
    ]
    assert public == ["AlbSecurityGroup"], f"open to the world: {public}"


# ------------------------------------------------------------------ the record


def test_the_decision_log_survives_a_stack_delete(resources):
    """`aws cloudformation delete-stack` is one command and it holds every
    decision log in the account. Losing that would destroy the one artifact this
    product asks a regulator to trust."""
    efs = resources["FileSystem"]
    assert efs["DeletionPolicy"] == "Retain"
    assert efs["UpdateReplacePolicy"] == "Retain"
    assert efs["Properties"]["Encrypted"] is True


def test_the_records_volume_is_mounted_where_the_app_writes(resources):
    """A mount at the wrong path is a container that starts, passes its health
    check, serves the screens, and writes every close to a layer that vanishes
    when the task is replaced."""
    from recon import loop as looplib

    task = resources["TaskDefinition"]["Properties"]
    mounts = task["ContainerDefinitions"][0]["MountPoints"]
    assert len(mounts) == 1
    assert mounts[0]["ReadOnly"] is False
    assert mounts[0]["ContainerPath"] == f"/app/{looplib.RUNS}", (
        f"the volume is mounted at {mounts[0]['ContainerPath']} and the app writes "
        f"to /app/{looplib.RUNS}"
    )

    volume = task["Volumes"][0]["EFSVolumeConfiguration"]
    assert volume["TransitEncryption"] == "ENABLED"
    assert volume["AuthorizationConfig"]["IAM"] == "ENABLED"


def test_the_access_point_uid_matches_the_container_user(resources):
    """Mismatched and every write is permission denied — after the task has
    started and the health check has gone green."""
    posix = resources["AccessPoint"]["Properties"]["PosixUser"]
    assert posix["Uid"] == "10001"
    assert re.search(r"--uid 10001", DOCKERFILE.read_text())


# ----------------------------------------------------------------- the secrets


def test_no_secret_is_written_in_the_template():
    """Every secret arrives by ARN and is resolved by the execution role. A value
    in here would be in git, in the CloudFormation console, and in the task
    definition anybody with read access can describe."""
    text = TEMPLATE.read_text()
    for pattern in (
        r"sk-[0-9a-f]{16,}",
        r"AKIA[0-9A-Z]{16}",
        r"(?i)password\s*:\s*['\"]?[^\s'\"]{8,}",
    ):
        assert not re.search(pattern, text), f"a literal secret matches {pattern}"

    assert "ValueFrom" in text, "secrets are not being injected by reference at all"


def test_the_execution_role_reads_only_the_secrets_it_was_given(resources):
    """`secretsmanager:*` on `*` would let a compromised container read every
    secret in the account, including the other product's database password."""
    policies = resources["ExecutionRole"]["Properties"]["Policies"]
    statements = [s for p in policies for s in p["PolicyDocument"]["Statement"]]
    assert statements

    for statement in statements:
        assert statement["Action"] == ["secretsmanager:GetSecretValue"]
        assert statement["Resource"] != "*", "the role can read every secret in the account"


def test_the_deployment_rolls_back_rather_than_serving_a_broken_task(resources):
    """A container that will not start must not replace one that is running."""
    config = resources["Service"]["Properties"]["DeploymentConfiguration"]
    breaker = config["DeploymentCircuitBreaker"]
    assert breaker["Enable"] is True
    assert breaker["Rollback"] is True
    assert config["MinimumHealthyPercent"] == 100


def test_the_deployment_names_its_credential_store(resources):
    """`build_identity` refuses a local store outside dev, and the container did
    not say which store to use — so the first signup on the deployed site created
    the Cognito user and then 500'd on the next line.

    The refusal was right. What was missing was the deployment stating what it
    wanted, and an environment that leaves it unset is one that only works
    because something else defaults."""
    env = {
        e["Name"]: e["Value"]
        for e in resources["TaskDefinition"]["Properties"]["ContainerDefinitions"][0]["Environment"]
    }
    assert env.get("RECON_ENV") == "prod"
    assert env.get("RECON_AUTH") == "cognito", (
        "the task does not name a credential store, so it falls back to the "
        "development one and is refused"
    )
    assert env.get("RECON_COGNITO_POOL_ID"), "cognito is named and no pool is given"


def test_the_deployment_sets_no_variable_the_code_does_not_read(resources):
    """The general form of a defect I chased three times in one afternoon.

    `COGNITO_USER_POOL_ID` against `RECON_COGNITO_POOL_ID`, then
    `FINCON_SESSION_SECRET` against `RECON_SESSION_SECRET`. Each time the
    container set a name nothing read, the code fell back to a default or
    refused, and the failure appeared only after a deploy — one signup at a time.

    A variable the code never reads is not harmless: it is a setting somebody
    believes is in force. Checked by scanning what `src/` actually looks up.
    """
    import re as _re

    read = set()
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text()
        # Literal lookups...
        read |= set(_re.findall(r"environ(?:\.get)?\[?\(?[\"'](\w+)[\"']", text))
        # ...and the module constants some of them are named by, which is why a
        # regex alone reported FINCON_PUBLIC_URL as unread while the transport
        # was reading it through `PUBLIC_URL_VAR`.
        read |= set(_re.findall(r"^[A-Z_]*VAR\s*=\s*[\"'](\w+)[\"']", text, _re.M))

    container = resources["TaskDefinition"]["Properties"]["ContainerDefinitions"][0]
    names = {e["Name"] for e in container["Environment"]}
    names |= {s["Fn::If"][1]["Name"] for s in container["Secrets"] if "Fn::If" in s}

    unread = sorted(n for n in names if n not in read)
    assert not unread, (
        f"the task sets variables nothing in src/ reads: {unread}. Each one is a "
        f"setting somebody believes is in force."
    )


def test_one_pool_is_named_once(resources):
    """The web login read `RECON_COGNITO_POOL_ID` and the MCP transport read
    `COGNITO_USER_POOL_ID` — one pool, two names, and a deployment that sets one
    has a working endpoint and a broken login with nothing saying so."""
    from recon.mcp import http as mcphttp

    container = resources["TaskDefinition"]["Properties"]["ContainerDefinitions"][0]
    env = {e["Name"] for e in container["Environment"]}
    secrets = {s["Fn::If"][1]["Name"] for s in container["Secrets"] if "Fn::If" in s}

    assert mcphttp.POOL_VAR in env
    assert mcphttp.CLIENT_VAR in env
    assert mcphttp.SECRET_VAR in secrets

    stray = {name for name in env | secrets if name.startswith("COGNITO_")}
    assert not stray, f"a second name for the same fact: {stray}"


def test_the_task_role_grants_exactly_the_cognito_calls_the_app_makes(resources):
    """Read off `api/auth.py` rather than kept in step by hand.

    `AdminGetUser` was missing and every signup on the deployed site 500'd after
    the Cognito user had already been created — an account that exists and an app
    that cannot read it back. Nothing offline could see it, because nothing
    offline calls Cognito.

    The other direction matters as much: a role holding actions the app never
    makes is standing permission for whatever gets written next.
    """
    import re as _re

    source = (ROOT / "src" / "recon" / "api" / "auth.py").read_text()
    called = {
        "".join(part.title() for part in name.split("_"))
        for name in _re.findall(
            r"\.(admin_get_user|sign_up|initiate_auth|confirm_sign_up|"
            r"resend_confirmation_code|get_user|list_users)\(",
            source,
        )
    }
    assert called, "no Cognito calls found; this test has lost its subject"

    statements = [
        s
        for p in resources["TaskRole"]["Properties"]["Policies"]
        for s in p["PolicyDocument"]["Statement"]
    ]
    granted = {
        action.split(":", 1)[1]
        for s in statements
        for action in (s["Action"] if isinstance(s["Action"], list) else [s["Action"]])
        if action.startswith("cognito-idp:")
    }

    assert not (called - granted), f"the app calls what the role cannot: {called - granted}"
    assert not (granted - called), f"the role grants what the app never calls: {granted - called}"
