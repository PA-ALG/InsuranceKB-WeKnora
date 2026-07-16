"""Concrete local command boundary for an isolated GitHub live run."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol
from urllib.parse import quote_plus

import psycopg
from psycopg import sql
from pydantic import SecretStr

from insurance_harness.adapters.weknora.admin_client import (
    AdminCredentials,
    WeKnoraAdminClient,
)
from insurance_harness.live_env.compose import read_runtime_environment
from insurance_harness.live_env.github_live import (
    CleanupAction,
    EphemeralResources,
    LiveRunRequest,
    LiveRunResult,
    PullRequest,
    RunnerPlan,
    TemporaryCredentials,
)

TenantMinter = Callable[
    [Mapping[str, str], EphemeralResources], tuple[str, SecretStr]
]
DatabaseMinter = Callable[
    [Mapping[str, str], EphemeralResources], tuple[str, SecretStr]
]
TenantRevoker = Callable[[Mapping[str, str], str], None]
DatabaseDropper = Callable[[Mapping[str, str], str], None]


class BackendCommandRunner(Protocol):
    def __call__(
        self,
        arguments: tuple[str, ...],
        *,
        cwd: Path,
        input_text: str | None,
        environment: dict[str, str] | None,
    ) -> subprocess.CompletedProcess[str]: ...


def _run_command(
    arguments: tuple[str, ...],
    *,
    cwd: Path,
    input_text: str | None,
    environment: dict[str, str] | None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        cwd=cwd,
        input=input_text,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def _runner_environment(values: dict[str, str]) -> dict[str, str]:
    forbidden_prefixes = (
        "HARNESS_LIVE_",
        "HARNESS_LLM_",
        "LOCAL_LIVE_",
        "RUNNER_",
        "WEKNORA_ADMIN_",
    )
    environment = {
        name: value
        for name, value in os.environ.items()
        if not any(name.startswith(prefix) for prefix in forbidden_prefixes)
    }
    environment.update(values)
    return environment


class ConcreteLiveBackend:
    """Use ``gh`` and Docker without putting either live secret in argv."""

    def __init__(
        self,
        *,
        repo_root: Path,
        runtime_path: Path,
        runner: BackendCommandRunner | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        poll_attempts: int = 90,
        poll_interval: float = 10.0,
        tenant_minter: TenantMinter | None = None,
        database_minter: DatabaseMinter | None = None,
        tenant_revoker: TenantRevoker | None = None,
        database_dropper: DatabaseDropper | None = None,
    ) -> None:
        self._repo_root = repo_root
        self._runtime_path = runtime_path
        self._runner = _run_command if runner is None else runner
        self._sleeper = sleeper
        self._poll_attempts = poll_attempts
        self._poll_interval = poll_interval
        self._repository = ""
        self._runner_name = ""
        self._runner_image = ""
        self._volume_name = ""
        self._tenant_key_id = ""
        self._db_role = ""
        self._live_values_set: set[str] = set()
        self._tenant_minter = self._mint_tenant_key if tenant_minter is None else tenant_minter
        self._database_minter = (
            self._mint_database_role if database_minter is None else database_minter
        )
        self._tenant_revoker = (
            self._revoke_tenant_key if tenant_revoker is None else tenant_revoker
        )
        self._database_dropper = (
            self._drop_database_role if database_dropper is None else database_dropper
        )

    def _command(
        self,
        arguments: tuple[str, ...],
        *,
        input_text: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> str:
        result = self._runner(
            arguments,
            cwd=self._repo_root,
            input_text=input_text,
            environment=environment,
        )
        if result.returncode != 0:
            raise RuntimeError("live backend command failed")
        return result.stdout

    def approve(self, request: LiveRunRequest) -> PullRequest:
        document = json.loads(
            self._command(
                (
                    "gh",
                    "api",
                    f"repos/{request.repository}/pulls/{request.pr_number}",
                )
            )
        )
        try:
            pull = PullRequest(
                number=int(document["number"]),
                state=str(document["state"]),
                base_repository=str(document["base"]["repo"]["full_name"]),
                head_repository=str(document["head"]["repo"]["full_name"]),
                head_sha=str(document["head"]["sha"]),
            )
        except (KeyError, TypeError, ValueError):
            raise ValueError("invalid GitHub pull response") from None
        self._repository = request.repository
        return pull

    def set_live_value(self, name: str, value: str, *, secret: bool) -> None:
        if not self._repository:
            raise RuntimeError("repository is not approved")
        if secret:
            self._command(
                (
                    "gh",
                    "secret",
                    "set",
                    name,
                    "--repo",
                    self._repository,
                    "--env",
                    "harness-live",
                ),
                input_text=value,
            )
            self._live_values_set.add(name)
            return
        self._command(
            (
                "gh",
                "variable",
                "set",
                name,
                "--repo",
                self._repository,
                "--env",
                "harness-live",
                "--body",
                value,
            )
        )
        self._live_values_set.add(name)

    def build_runner(self, plan: RunnerPlan) -> None:
        image = f"insurancekb-live-runner:{plan.package.version}-{plan.package.arch}"
        self._runner_image = image
        self._command(
            (
                "docker",
                "build",
                "--file",
                "deploy/local-live/runner/Dockerfile",
                "--build-arg",
                f"RUNNER_VERSION={plan.package.version}",
                "--build-arg",
                f"RUNNER_ARCH={plan.package.arch}",
                "--build-arg",
                f"RUNNER_ARCHIVE={plan.package.archive}",
                "--build-arg",
                f"RUNNER_SHA256={plan.package.sha256}",
                "--tag",
                image,
                "deploy/local-live/runner",
            )
        )

    def registration_token(self, repository: str) -> SecretStr:
        token = self._command(
            (
                "gh",
                "api",
                "--method",
                "POST",
                f"repos/{repository}/actions/runners/registration-token",
                "--jq",
                ".token",
            )
        ).strip()
        if not token:
            raise RuntimeError("runner registration token is empty")
        return SecretStr(token)

    def start_runner(self, plan: RunnerPlan, token: SecretStr) -> None:
        image = f"insurancekb-live-runner:{plan.package.version}-{plan.package.arch}"
        self._runner_name = plan.identity.name
        environment = _runner_environment(
            {
                "RUNNER_REPOSITORY_URL": f"https://github.com/{self._repository}",
                "RUNNER_NAME": plan.identity.name,
                "RUNNER_LABEL": plan.identity.label,
            }
        )
        self._command(
            (
                "docker",
                "create",
                "--name",
                plan.identity.name,
                "--network",
                plan.attached_networks[0],
                "--tmpfs",
                (
                    "/run/insurancekb:rw,noexec,nosuid,nodev,size=64k,"
                    "mode=0700,uid=10001,gid=10001"
                ),
                "--mount",
                "type=volume,volume-nocopy,destination=/home/runner/actions-runner/_work",
                "--env",
                "RUNNER_REPOSITORY_URL",
                "--env",
                "RUNNER_NAME",
                "--env",
                "RUNNER_LABEL",
                image,
            ),
            environment=environment,
        )
        self._volume_name = self._command(
            (
                "docker",
                "inspect",
                plan.identity.name,
                "--format",
                (
                    "{{range .Mounts}}{{if eq .Destination "
                    '"/home/runner/actions-runner/_work"}}{{.Name}}{{end}}{{end}}'
                ),
            )
        ).strip()
        if not self._volume_name:
            raise RuntimeError("runner anonymous volume was not observed")
        self._command(
            (
                "docker",
                "network",
                "connect",
                plan.attached_networks[1],
                plan.identity.name,
            )
        )
        self._command(("docker", "start", plan.identity.name))
        token_pipe = "/run/insurancekb/registration-token"
        for attempt in range(50):
            result = self._runner(
                ("docker", "exec", plan.identity.name, "test", "-p", token_pipe),
                cwd=self._repo_root,
                input_text=None,
                environment=None,
            )
            if result.returncode == 0:
                break
            if attempt + 1 < 50:
                self._sleeper(0.1)
        else:
            raise RuntimeError("runner token channel was not ready")
        self._command(
            (
                "docker",
                "exec",
                "--interactive",
                plan.identity.name,
                "sh",
                "-c",
                f"cat > {token_pipe}",
            ),
            input_text=token.get_secret_value(),
        )

    def dispatch(self, request: LiveRunRequest) -> None:
        self._command(
            (
                "gh",
                "workflow",
                "run",
                "harness-live.yml",
                "--repo",
                request.repository,
                "--ref",
                "main",
                "-f",
                f"pr_number={request.pr_number}",
                "-f",
                f"head_sha={request.head_sha}",
                "-f",
                f"runner_nonce={request.nonce}",
            )
        )

    def wait(self, request: LiveRunRequest) -> LiveRunResult:
        title = (
            f"harness-live PR #{request.pr_number} {request.head_sha} "
            f"runner-{request.nonce}"
        )
        for attempt in range(self._poll_attempts):
            document = json.loads(
                self._command(
                    (
                        "gh",
                        "run",
                        "list",
                        "--repo",
                        request.repository,
                        "--workflow",
                        "harness-live.yml",
                        "--event",
                        "workflow_dispatch",
                        "--limit",
                        "20",
                        "--json",
                        "displayTitle,status,conclusion,url",
                    )
                )
            )
            if not isinstance(document, list) or not all(
                isinstance(item, dict) for item in document
            ):
                raise ValueError("invalid GitHub run list response")
            matching = [item for item in document if item.get("displayTitle") == title]
            if len(matching) > 1:
                raise RuntimeError("multiple trusted live runs matched")
            if matching and matching[0].get("status") == "completed":
                return LiveRunResult(
                    url=str(matching[0].get("url", "")),
                    conclusion=str(matching[0].get("conclusion", "")),
                )
            if attempt + 1 < self._poll_attempts:
                self._sleeper(self._poll_interval)
        raise TimeoutError("trusted live workflow did not complete")

    @staticmethod
    def _admin_database_url(values: Mapping[str, str]) -> str:
        return (
            "postgresql://harness:"
            f"{quote_plus(values['HARNESS_POSTGRES_PASSWORD'])}"
            "@127.0.0.1:5442/insurance_kb"
        )

    @staticmethod
    def _mint_tenant_key(
        values: Mapping[str, str], resources: EphemeralResources
    ) -> tuple[str, SecretStr]:
        async def create() -> tuple[str, SecretStr]:
            client = WeKnoraAdminClient("http://127.0.0.1:8080/api/v1")
            try:
                session = await client.bootstrap_admin(
                    AdminCredentials(
                        username=values["WEKNORA_ADMIN_USERNAME"],
                        email=values["WEKNORA_ADMIN_EMAIL"],
                        password=values["WEKNORA_ADMIN_PASSWORD"],
                    )
                )
                tenant_id = int(values["LOCAL_LIVE_TENANT_ID"])
                session = await client.switch_tenant(session, tenant_id)
                key = await client.create_tenant_api_key(
                    session,
                    tenant_id=tenant_id,
                    name=resources.tenant_key,
                    knowledge_base_ids=(
                        values["LOCAL_LIVE_RAW_KB_ID"],
                        values["LOCAL_LIVE_WIKI_KB_ID"],
                    ),
                )
                return str(key.id), key.token
            finally:
                await client.aclose()

        return asyncio.run(create())

    @classmethod
    def _mint_database_role(
        cls, values: Mapping[str, str], resources: EphemeralResources
    ) -> tuple[str, SecretStr]:
        password = secrets.token_urlsafe(32)
        try:
            with psycopg.connect(
                cls._admin_database_url(values), autocommit=True
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        sql.SQL(
                            "CREATE ROLE {} WITH LOGIN PASSWORD {} "
                            "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT"
                        ).format(
                            sql.Identifier(resources.db_role),
                            sql.Literal(password),
                        )
                    )
                    cursor.execute(
                        sql.SQL("GRANT CONNECT, CREATE ON DATABASE {} TO {}").format(
                            sql.Identifier("insurance_kb"),
                            sql.Identifier(resources.db_role),
                        )
                    )
                    cursor.execute(
                        sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                            sql.Identifier("public"),
                            sql.Identifier(resources.db_role),
                        )
                    )
                    cursor.execute(
                        sql.SQL(
                            "GRANT SELECT, INSERT, UPDATE, DELETE "
                            "ON ALL TABLES IN SCHEMA {} TO {}"
                        ).format(
                            sql.Identifier("public"),
                            sql.Identifier(resources.db_role),
                        )
                    )
                    cursor.execute(
                        sql.SQL(
                            "GRANT USAGE, SELECT, UPDATE "
                            "ON ALL SEQUENCES IN SCHEMA {} TO {}"
                        ).format(
                            sql.Identifier("public"),
                            sql.Identifier(resources.db_role),
                        )
                    )
        except BaseException:
            try:
                cls._drop_database_role(values, resources.db_role)
            except BaseException:
                pass
            raise
        runner_url = (
            "postgresql+psycopg://"
            f"{quote_plus(resources.db_role)}:{quote_plus(password)}"
            "@insurance-harness-postgres:5432/insurance_kb"
        )
        return resources.db_role, SecretStr(runner_url)

    @staticmethod
    def _revoke_tenant_key(values: Mapping[str, str], key_id: str) -> None:
        async def revoke() -> None:
            client = WeKnoraAdminClient("http://127.0.0.1:8080/api/v1")
            try:
                session = await client.bootstrap_admin(
                    AdminCredentials(
                        username=values["WEKNORA_ADMIN_USERNAME"],
                        email=values["WEKNORA_ADMIN_EMAIL"],
                        password=values["WEKNORA_ADMIN_PASSWORD"],
                    )
                )
                tenant_id = int(values["LOCAL_LIVE_TENANT_ID"])
                session = await client.switch_tenant(session, tenant_id)
                await client.delete_tenant_api_key(
                    session,
                    tenant_id=tenant_id,
                    key_id=int(key_id),
                )
            finally:
                await client.aclose()

        asyncio.run(revoke())

    @classmethod
    def _drop_database_role(cls, values: Mapping[str, str], role: str) -> None:
        with psycopg.connect(cls._admin_database_url(values), autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
                if cursor.fetchone() is None:
                    return
                cursor.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE usename = %s AND pid <> pg_backend_pid()",
                    (role,),
                )
                cursor.execute(
                    sql.SQL("DROP OWNED BY {} CASCADE").format(sql.Identifier(role))
                )
                cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))

    def mint_credentials(
        self, resources: EphemeralResources
    ) -> TemporaryCredentials:
        values = read_runtime_environment(self._runtime_path)
        key_id, tenant_token = self._tenant_minter(values, resources)
        self._tenant_key_id = key_id
        db_role, db_url = self._database_minter(values, resources)
        self._db_role = db_role
        return TemporaryCredentials(
            tenant_key_id=key_id,
            tenant_token=tenant_token,
            db_role=db_role,
            db_url=db_url,
        )

    def _remove_runner_registration(self, runner_name: str) -> None:
        if not self._repository:
            return
        document = json.loads(
            self._command(
                (
                    "gh",
                    "api",
                    f"repos/{self._repository}/actions/runners?per_page=100",
                )
            )
        )
        runners = document.get("runners") if isinstance(document, dict) else None
        if not isinstance(runners, list):
            raise ValueError("invalid GitHub runner list response")
        if not all(isinstance(item, dict) for item in runners):
            raise ValueError("invalid GitHub runner list response")
        matching = [item for item in runners if item.get("name") == runner_name]
        if len(matching) > 1:
            raise RuntimeError("multiple runner registrations matched")
        if matching:
            self._command(
                (
                    "gh",
                    "api",
                    "--method",
                    "DELETE",
                    (
                        f"repos/{self._repository}/actions/runners/"
                        f"{matching[0]['id']}"
                    ),
                )
            )

    def execute(self, action: CleanupAction) -> None:
        if action.kind == "delete_secret":
            if self._repository and action.resource in self._live_values_set:
                self._command(
                    (
                        "gh",
                        "secret",
                        "delete",
                        action.resource,
                        "--repo",
                        self._repository,
                        "--env",
                        "harness-live",
                    )
                )
                self._live_values_set.discard(action.resource)
            return
        if action.kind == "delete_variable":
            if self._repository and action.resource in self._live_values_set:
                self._command(
                    (
                        "gh",
                        "variable",
                        "delete",
                        action.resource,
                        "--repo",
                        self._repository,
                        "--env",
                        "harness-live",
                    )
                )
                self._live_values_set.discard(action.resource)
            return
        if action.kind == "revoke_tenant_key":
            if self._tenant_key_id:
                self._tenant_revoker(
                    read_runtime_environment(self._runtime_path),
                    self._tenant_key_id,
                )
                self._tenant_key_id = ""
            return
        if action.kind == "drop_db_role":
            if self._db_role:
                self._database_dropper(
                    read_runtime_environment(self._runtime_path),
                    self._db_role,
                )
                self._db_role = ""
            return
        if action.kind == "remove_runner_registration":
            self._remove_runner_registration(action.resource)
            return
        if action.kind == "remove_logs":
            # Runner diagnostics live only in the ephemeral container layer;
            # the following remove_container action deletes that layer.
            return
        if action.kind == "remove_workspace":
            if self._volume_name and self._runner_image:
                self._command(
                    (
                        "docker",
                        "run",
                        "--rm",
                        "--network",
                        "none",
                        "--entrypoint",
                        "sh",
                        "--mount",
                        (
                            f"type=volume,source={self._volume_name},"
                            "destination=/work"
                        ),
                        self._runner_image,
                        "-c",
                        "rm -rf -- /work/*",
                    )
                )
            return
        if action.kind == "remove_container":
            if self._runner_name:
                command = ["docker", "rm", "--force"]
                if not self._volume_name:
                    command.append("--volumes")
                command.append(self._runner_name)
                self._command(tuple(command))
                self._runner_name = ""
            return
        if action.kind == "remove_volume":
            if self._volume_name:
                self._command(("docker", "volume", "rm", "--force", self._volume_name))
                self._volume_name = ""
            return
        raise ValueError("unsupported cleanup action")
