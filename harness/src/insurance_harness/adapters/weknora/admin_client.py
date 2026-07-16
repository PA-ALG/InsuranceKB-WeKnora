"""Documented WeKnora administrator authentication adapter."""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr

from insurance_harness.live_env.provision import (
    DesiredResource,
    KnowledgeRecord,
    OwnedResource,
    WikiPageRecord,
)


@dataclass(frozen=True)
class AdminCredentials:
    username: str
    email: str
    password: str = field(repr=False)


@dataclass(frozen=True)
class AdminSession:
    user_id: str
    tenant_id: int
    token: SecretStr
    refresh_token: SecretStr


@dataclass(frozen=True)
class TenantAPIKey:
    id: int
    tenant_id: int
    name: str
    role: str
    full_access: bool
    knowledge_base_ids: tuple[str, ...]
    capabilities: tuple[str, ...]
    token: SecretStr


class WeKnoraAdminClient:
    """Small auth boundary; resource orchestration stays in ``live_env``."""

    def __init__(self, base_url: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=30.0,
            trust_env=False,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        params: dict[str, int] | None = None,
    ) -> Any:
        response = await self._client.request(
            method,
            path,
            headers=headers,
            json=json_body,
            files=files,
            data=data,
            params=params,
        )
        response.raise_for_status()
        document: Any = response.json()
        if isinstance(document, dict) and "data" in document:
            return document["data"]
        return document

    @staticmethod
    def _bearer(session: AdminSession) -> dict[str, str]:
        return {"Authorization": f"Bearer {session.token.get_secret_value()}"}

    @staticmethod
    def _api_key(api_key: SecretStr) -> dict[str, str]:
        return {"X-API-Key": api_key.get_secret_value()}

    @classmethod
    def _resource_auth(cls, credential: SecretStr | AdminSession) -> dict[str, str]:
        if isinstance(credential, AdminSession):
            return cls._bearer(credential)
        return cls._api_key(credential)

    async def bootstrap_admin(self, credentials: AdminCredentials) -> AdminSession:
        registration = await self._client.post(
            "/auth/register",
            json={
                "username": credentials.username,
                "email": credentials.email,
                "password": credentials.password,
            },
        )
        if registration.status_code not in {201, 409}:
            registration.raise_for_status()
        login = await self._client.post(
            "/auth/login",
            json={"email": credentials.email, "password": credentials.password},
        )
        login.raise_for_status()
        document = login.json()
        user = document.get("user")
        tenant = document.get("active_tenant")
        token = document.get("token")
        refresh_token = document.get("refresh_token")
        if (
            not isinstance(user, dict)
            or not isinstance(tenant, dict)
            or not isinstance(token, str)
            or not token
            or not isinstance(refresh_token, str)
            or not refresh_token
        ):
            raise ValueError("invalid login response")
        return AdminSession(
            user_id=str(user["id"]),
            tenant_id=int(tenant["id"]),
            token=SecretStr(token),
            refresh_token=SecretStr(refresh_token),
        )

    async def list_tenants(self, session: AdminSession) -> list[dict[str, Any]]:
        data = await self._request("GET", "/tenants", headers=self._bearer(session))
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise ValueError("invalid tenant list response")
        return [dict(item) for item in items]

    async def switch_tenant(
        self,
        session: AdminSession,
        tenant_id: int,
    ) -> AdminSession:
        document = await self._request(
            "POST",
            "/auth/switch-tenant",
            headers=self._bearer(session),
            json_body={
                "tenant_id": tenant_id,
                "refresh_token": session.refresh_token.get_secret_value(),
            },
        )
        if not isinstance(document, dict):
            raise ValueError("invalid switch-tenant response")
        user = document.get("user")
        active_tenant = document.get("active_tenant")
        token = document.get("token")
        refresh_token = document.get("refresh_token")
        if (
            not isinstance(user, dict)
            or not isinstance(active_tenant, dict)
            or int(active_tenant.get("id", 0)) != tenant_id
            or not isinstance(token, str)
            or not token
            or not isinstance(refresh_token, str)
            or not refresh_token
        ):
            raise ValueError("invalid switch-tenant response")
        return AdminSession(
            user_id=str(user["id"]),
            tenant_id=tenant_id,
            token=SecretStr(token),
            refresh_token=SecretStr(refresh_token),
        )

    async def create_tenant(
        self,
        session: AdminSession,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        data = await self._request(
            "POST",
            "/tenants",
            headers=self._bearer(session),
            json_body=payload,
        )
        if not isinstance(data, dict):
            raise ValueError("invalid tenant response")
        return data

    async def list_models(
        self, credential: SecretStr | AdminSession
    ) -> list[dict[str, Any]]:
        data = await self._request("GET", "/models", headers=self._resource_auth(credential))
        if not isinstance(data, list):
            raise ValueError("invalid model list response")
        return data

    async def create_model(
        self,
        credential: SecretStr | AdminSession,
        documented_payload: dict[str, Any],
    ) -> dict[str, Any]:
        data = await self._request(
            "POST",
            "/models",
            headers=self._resource_auth(credential),
            json_body=documented_payload,
        )
        if not isinstance(data, dict):
            raise ValueError("invalid model response")
        return data

    async def list_knowledge_bases(
        self, credential: SecretStr | AdminSession
    ) -> list[dict[str, Any]]:
        data = await self._request(
            "GET",
            "/knowledge-bases",
            headers=self._resource_auth(credential),
        )
        if not isinstance(data, list):
            raise ValueError("invalid knowledge-base list response")
        return data

    async def create_knowledge_base(
        self,
        credential: SecretStr | AdminSession,
        documented_payload: dict[str, Any],
    ) -> dict[str, Any]:
        data = await self._request(
            "POST",
            "/knowledge-bases",
            headers=self._resource_auth(credential),
            json_body=documented_payload,
        )
        if not isinstance(data, dict):
            raise ValueError("invalid knowledge-base response")
        return data

    async def list_knowledge(
        self,
        api_key: SecretStr,
        kb_id: str,
    ) -> list[dict[str, Any]]:
        data = await self._request(
            "GET",
            f"/knowledge-bases/{kb_id}/knowledge",
            headers=self._api_key(api_key),
            params={"page": 1, "page_size": 100},
        )
        if not isinstance(data, list):
            raise ValueError("invalid knowledge list response")
        return data

    async def upload_file(
        self,
        api_key: SecretStr,
        kb_id: str,
        path: Path,
        *,
        metadata: dict[str, str],
    ) -> dict[str, Any]:
        with path.open("rb") as stream:
            data = await self._request(
                "POST",
                f"/knowledge-bases/{kb_id}/knowledge/file",
                headers=self._api_key(api_key),
                files={"file": (path.name, stream, "application/pdf")},
                data={"metadata": json.dumps(metadata, sort_keys=True)},
            )
        if not isinstance(data, dict):
            raise ValueError("invalid knowledge upload response")
        return data

    async def list_chunks(
        self,
        api_key: SecretStr,
        knowledge_id: str,
    ) -> list[dict[str, Any]]:
        data = await self._request(
            "GET",
            f"/chunks/{knowledge_id}",
            headers=self._api_key(api_key),
            params={"page": 1, "page_size": 100},
        )
        if not isinstance(data, list):
            raise ValueError("invalid chunk list response")
        return data

    async def get_knowledge(
        self, api_key: SecretStr, knowledge_id: str
    ) -> dict[str, Any]:
        data = await self._request(
            "GET", f"/knowledge/{knowledge_id}", headers=self._api_key(api_key)
        )
        if not isinstance(data, dict):
            raise ValueError("invalid knowledge response")
        return data

    async def list_wiki_pages(
        self, api_key: SecretStr, kb_id: str
    ) -> list[dict[str, Any]]:
        data = await self._request(
            "GET",
            f"/knowledgebase/{kb_id}/wiki/pages",
            headers=self._api_key(api_key),
            params={"page": 1, "page_size": 100},
        )
        items = data.get("items") if isinstance(data, dict) else data
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise ValueError("invalid wiki page list response")
        return [dict(item) for item in items]

    async def create_tenant_api_key(
        self,
        session: AdminSession,
        *,
        tenant_id: int,
        name: str,
        knowledge_base_ids: tuple[str, ...],
    ) -> TenantAPIKey:
        capabilities = ("retrieve", "ingest")
        data = await self._request(
            "POST",
            f"/tenants/{tenant_id}/api-keys",
            headers=self._bearer(session),
            json_body={
                "name": name,
                "full_access": False,
                "knowledge_base_ids": list(knowledge_base_ids),
                "capabilities": list(capabilities),
            },
        )
        if not isinstance(data, dict):
            raise ValueError("invalid API-key create response")
        key_id = data.get("id")
        token = data.get("token")
        returned_kbs = data.get("knowledge_base_ids")
        returned_capabilities = data.get("capabilities")
        if (
            not isinstance(key_id, int)
            or isinstance(key_id, bool)
            or key_id <= 0
            or data.get("name") != name
            or data.get("full_access") is not False
            or not isinstance(token, str)
            or not token
            or not isinstance(returned_kbs, list)
            or len(returned_kbs) != len(knowledge_base_ids)
            or set(returned_kbs) != set(knowledge_base_ids)
            or not isinstance(returned_capabilities, list)
            or len(returned_capabilities) != len(capabilities)
            or set(returned_capabilities) != set(capabilities)
        ):
            raise ValueError("invalid API-key create response")
        return TenantAPIKey(
            id=key_id,
            tenant_id=tenant_id,
            name=name,
            role="contributor",
            full_access=False,
            knowledge_base_ids=tuple(returned_kbs),
            capabilities=tuple(returned_capabilities),
            token=SecretStr(token),
        )

    async def list_tenant_api_keys(
        self,
        session: AdminSession,
        *,
        tenant_id: int,
    ) -> list[TenantAPIKey]:
        data = await self._request(
            "GET",
            f"/tenants/{tenant_id}/api-keys",
            headers=self._bearer(session),
        )
        if not isinstance(data, list):
            raise ValueError("invalid API-key list response")
        keys: list[TenantAPIKey] = []
        for item in data:
            if not isinstance(item, dict):
                raise ValueError("invalid API-key list response")
            key_id = item.get("id")
            name = item.get("name")
            token = item.get("api_key")
            full_access = item.get("full_access")
            kb_ids = item.get("knowledge_base_ids")
            capabilities = item.get("capabilities")
            if (
                not isinstance(key_id, int)
                or isinstance(key_id, bool)
                or key_id <= 0
                or not isinstance(name, str)
                or not name
                or not isinstance(token, str)
                or not token
                or not isinstance(full_access, bool)
                or not isinstance(kb_ids, list)
                or not all(isinstance(value, str) for value in kb_ids)
                or not isinstance(capabilities, list)
                or not all(isinstance(value, str) for value in capabilities)
            ):
                raise ValueError("invalid API-key list response")
            normalized_capabilities = tuple(str(value) for value in capabilities)
            role = (
                "admin"
                if full_access
                else "contributor"
                if "ingest" in normalized_capabilities
                else "viewer"
            )
            keys.append(
                TenantAPIKey(
                    id=key_id,
                    tenant_id=tenant_id,
                    name=name,
                    role=role,
                    full_access=full_access,
                    knowledge_base_ids=tuple(str(value) for value in kb_ids),
                    capabilities=normalized_capabilities,
                    token=SecretStr(token),
                )
            )
        return keys

    async def delete_tenant_api_key(
        self,
        session: AdminSession,
        *,
        tenant_id: int,
        key_id: int,
    ) -> None:
        await self._request(
            "DELETE",
            f"/tenants/{tenant_id}/api-keys/{key_id}",
            headers=self._bearer(session),
        )


def _ownership(marker: str, role: str, dimension: int | None) -> str:
    return json.dumps(
        {"dimension": dimension, "marker": marker, "role": role},
        separators=(",", ":"),
        sort_keys=True,
    )


def _parse_ownership(value: object) -> tuple[str, str, int | None]:
    if not isinstance(value, str):
        raise ValueError("resource has no ownership description")
    try:
        document = json.loads(value)
    except json.JSONDecodeError:
        raise ValueError("resource has invalid ownership description") from None
    if not isinstance(document, dict):
        raise ValueError("resource has invalid ownership description")
    marker = document.get("marker")
    role = document.get("role")
    dimension = document.get("dimension")
    if (
        not isinstance(marker, str)
        or not marker
        or not isinstance(role, str)
        or not role
        or (
            dimension is not None
            and (not isinstance(dimension, int) or isinstance(dimension, bool))
        )
    ):
        raise ValueError("resource has invalid ownership description")
    return marker, role, dimension


class WeKnoraProvisioningBackend:
    """Translate domain resource kinds into confirmed WeKnora REST calls."""

    def __init__(
        self,
        client: WeKnoraAdminClient,
        session: AdminSession,
        *,
        model_payloads: Mapping[str, dict[str, Any]],
        knowledge_base_payloads: Mapping[str, dict[str, Any]],
        poll_interval: float = 1.0,
        poll_attempts: int = 120,
    ) -> None:
        self._client = client
        self._session = session
        self._model_payloads = model_payloads
        self._kb_payloads = knowledge_base_payloads
        self._poll_interval = poll_interval
        self._poll_attempts = poll_attempts
        self._api_key: TenantAPIKey | None = None
        self._api_keys_by_id: dict[str, TenantAPIKey] = {}
        self._embedding_model_id: str | None = None

    async def select_tenant(self, tenant_id: str) -> None:
        self._session = await self._client.switch_tenant(self._session, int(tenant_id))

    async def select_resource(self, resource: OwnedResource) -> None:
        if resource.kind == "model:embedding":
            self._embedding_model_id = resource.id
        elif resource.kind == "api-key":
            try:
                self._api_key = self._api_keys_by_id[resource.id]
            except KeyError:
                if self._api_key is None or str(self._api_key.id) != resource.id:
                    raise RuntimeError("selected API key has no available token") from None

    async def list_resources(self, kind: str) -> list[OwnedResource]:
        if kind == "tenant":
            items = await self._client.list_tenants(self._session)
            return [self._resource_from_description(kind, item, tenant_id="") for item in items]
        if kind.startswith("model:"):
            items = await self._client.list_models(self._session)
            model_resources = [
                self._resource_from_description(
                    kind,
                    item,
                    tenant_id=str(item.get("tenant_id", self._session.tenant_id)),
                )
                for item in items
                if item.get("name") is not None
            ]
            return model_resources
        if kind.startswith("kb:"):
            items = await self._client.list_knowledge_bases(self._session)
            return [
                self._resource_from_description(
                    kind,
                    item,
                    tenant_id=str(item.get("tenant_id", self._session.tenant_id)),
                )
                for item in items
            ]
        if kind == "api-key":
            keys = await self._client.list_tenant_api_keys(
                self._session, tenant_id=self._session.tenant_id
            )
            key_resources: list[OwnedResource] = []
            for key in keys:
                marker = key.name.rpartition("::owner=")[2]
                self._api_keys_by_id[str(key.id)] = key
                key_resources.append(
                    OwnedResource(
                        id=str(key.id),
                        kind=kind,
                        name=key.name,
                        tenant_id=str(key.tenant_id),
                        marker=marker,
                        role=key.role,
                        capabilities=key.capabilities,
                        knowledge_base_ids=key.knowledge_base_ids,
                    )
                )
            return key_resources
        raise ValueError(f"unsupported WeKnora resource kind: {kind}")

    def _resource_from_description(
        self, kind: str, item: dict[str, Any], *, tenant_id: str
    ) -> OwnedResource:
        identifier = item.get("id")
        name = item.get("name")
        if (
            not isinstance(identifier, (str, int))
            or isinstance(identifier, bool)
            or not isinstance(name, str)
        ):
            raise ValueError("invalid owned resource response")
        try:
            marker, role, dimension = _parse_ownership(item.get("description"))
        except ValueError:
            marker, role, dimension = "", "", None
        return OwnedResource(
            id=str(identifier),
            kind=kind,
            name=name,
            tenant_id=tenant_id,
            marker=marker,
            role=role,
            dimension=dimension,
        )

    async def create_resource(self, desired: DesiredResource) -> OwnedResource:
        description = _ownership(desired.marker, desired.role, desired.dimension)
        if desired.kind == "tenant":
            item = await self._client.create_tenant(
                self._session, {"name": desired.name, "description": description}
            )
            return self._resource_from_description(desired.kind, item, tenant_id="")
        if desired.kind.startswith("model:"):
            role = desired.kind.split(":", 1)[1]
            payload = copy.deepcopy(self._model_payloads[role])
            payload.update({"name": desired.name, "description": description})
            item = await self._client.create_model(self._session, payload)
            resource = self._resource_from_description(
                desired.kind, item, tenant_id=desired.tenant_id
            )
            if role == "embedding":
                self._embedding_model_id = resource.id
            return resource
        if desired.kind.startswith("kb:"):
            role = desired.kind.split(":", 1)[1]
            if self._embedding_model_id is None:
                raise RuntimeError("embedding model is not selected")
            payload = copy.deepcopy(self._kb_payloads[role])
            payload.update(
                {
                    "name": desired.name,
                    "description": description,
                    "embedding_model_id": self._embedding_model_id,
                }
            )
            item = await self._client.create_knowledge_base(self._session, payload)
            return self._resource_from_description(
                desired.kind, item, tenant_id=desired.tenant_id
            )
        if desired.kind == "api-key":
            key = await self._client.create_tenant_api_key(
                self._session,
                tenant_id=int(desired.tenant_id),
                name=desired.name,
                knowledge_base_ids=desired.knowledge_base_ids,
            )
            self._api_key = key
            self._api_keys_by_id[str(key.id)] = key
            return OwnedResource(
                id=str(key.id),
                kind=desired.kind,
                name=key.name,
                tenant_id=str(key.tenant_id),
                marker=desired.marker,
                role=key.role,
                capabilities=key.capabilities,
                knowledge_base_ids=key.knowledge_base_ids,
            )
        raise ValueError(f"unsupported WeKnora resource kind: {desired.kind}")

    def _key(self) -> SecretStr:
        if self._api_key is None:
            raise RuntimeError("scoped tenant API key is not provisioned")
        return self._api_key.token

    def live_api_key(self) -> SecretStr:
        """Expose the selected scoped token only to the trusted local controller."""

        return self._key()

    async def list_knowledge(self, kb_id: str) -> list[KnowledgeRecord]:
        records: list[KnowledgeRecord] = []
        for item in await self._client.list_knowledge(self._key(), kb_id):
            metadata = item.get("metadata")
            if not isinstance(metadata, dict):
                continue
            knowledge_id = item.get("id")
            status = item.get("parse_status")
            if not isinstance(knowledge_id, str) or not isinstance(status, str):
                raise ValueError("invalid knowledge response")
            chunk_count = 0
            if status == "completed":
                chunk_count = len(
                    await self._client.list_chunks(self._key(), knowledge_id)
                )
            records.append(
                KnowledgeRecord(
                    id=knowledge_id,
                    kb_id=str(item.get("knowledge_base_id", kb_id)),
                    sha256=str(metadata.get("sha256", "")),
                    status=status,
                    chunk_count=chunk_count,
                    marker=str(metadata.get("owner", "")),
                )
            )
        return records

    async def upload_pdf(
        self, kb_id: str, path: Path, digest: str, marker: str
    ) -> KnowledgeRecord:
        item = await self._client.upload_file(
            self._key(), kb_id, path, metadata={"sha256": digest, "owner": marker}
        )
        return KnowledgeRecord(
            id=str(item.get("id", "")),
            kb_id=kb_id,
            sha256=digest,
            status=str(item.get("parse_status", "")),
            chunk_count=0,
            marker=marker,
        )

    async def wait_completed(self, knowledge_id: str) -> KnowledgeRecord:
        for _ in range(self._poll_attempts):
            item = await self._client.get_knowledge(self._key(), knowledge_id)
            status = str(item.get("parse_status", ""))
            metadata = item.get("metadata")
            if status == "completed" and isinstance(metadata, dict):
                chunks = await self._client.list_chunks(self._key(), knowledge_id)
                return KnowledgeRecord(
                    id=knowledge_id,
                    kb_id=str(item.get("knowledge_base_id", "")),
                    sha256=str(metadata.get("sha256", "")),
                    status=status,
                    chunk_count=len(chunks),
                    marker=str(metadata.get("owner", "")),
                )
            if status in {"failed", "cancelled"}:
                raise RuntimeError("knowledge parse failed")
            await asyncio.sleep(self._poll_interval)
        raise TimeoutError("knowledge parse did not complete")

    async def list_wiki_pages(self, kb_id: str) -> list[WikiPageRecord]:
        pages = await self._client.list_wiki_pages(self._key(), kb_id)
        records: list[WikiPageRecord] = []
        for page in pages:
            metadata = page.get("page_metadata")
            marker = metadata.get("ownership_marker", "") if isinstance(metadata, dict) else ""
            records.append(
                WikiPageRecord(
                    id=str(page.get("id", "")),
                    kb_id=kb_id,
                    marker=str(marker),
                )
            )
        return records
