"""Fail-closed configuration loader for the permanent product worker."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from insurance_harness.knowledge_compiler.schema_pack_catalog_830_g3 import (
    SchemaPackCatalogV1,
)
from insurance_harness.product_ingestion.model_settings import ProductModelSettings
from insurance_harness.product_ingestion.models import ProductScope
from insurance_harness.service_shell.config import ShellConfigError, ShellSettings

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate configuration property")
        value[key] = item
    return value


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TrustedFileReference(_FrozenModel):
    path: str = Field(min_length=1, max_length=4096)
    sha256: Sha256Hex
    max_bytes: int = Field(ge=1, le=64 * 1024 * 1024)


class TrustedFiles(_FrozenModel):
    catalog: TrustedFileReference
    profile_confirmation: TrustedFileReference
    resolution_policy: TrustedFileReference


class ProductPumpSettings(_FrozenModel):
    page_size: int = Field(default=50, ge=1, le=1000)
    event_limit: int = Field(default=100, ge=1, le=1000)
    poll_interval_seconds: float = Field(default=1.0, gt=0, le=60)


class PlatformConnectionSettings(_FrozenModel):
    base_url: str = Field(min_length=1, max_length=2048)
    machine_key: SecretStr
    timeout_seconds: float = Field(gt=0, le=300)
    # Signed source snapshots include base64 native coordinates. This internal
    # transport budget is independent of model context and model response limits.
    max_response_bytes: int = Field(ge=1, le=192 * 1024 * 1024)

    @model_validator(mode="after")
    def _valid_connection(self) -> Self:
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or not self.machine_key.get_secret_value()
            or any(char.isspace() for char in self.machine_key.get_secret_value())
        ):
            raise ValueError("invalid platform connection")
        return self


class SourceAuthoritySettings(_FrozenModel):
    key_id: str = Field(min_length=1, max_length=128)
    public_key_b64: str = Field(min_length=1, max_length=256)

    @field_validator("key_id")
    @classmethod
    def _canonical_key_id(cls, value: str) -> str:
        if value != value.strip() or "\x00" in value:
            raise ValueError("invalid source key id")
        return value

    def public_key(self) -> Ed25519PublicKey:
        raw = base64.b64decode(self.public_key_b64, validate=True)
        if len(raw) != 32:
            raise ValueError("invalid source public key")
        return Ed25519PublicKey.from_public_bytes(raw)


class AutomationSignerSettings(_FrozenModel):
    scope: ProductScope
    mode: Literal["ISOLATED_NOT_FOR_PRODUCTION"]
    principal_id: str = Field(min_length=1, max_length=256)
    api_key_id: int = Field(ge=1)
    policy_id: str = Field(min_length=1, max_length=256)
    policy_version: str = Field(min_length=1, max_length=128)
    policy_sha256: Sha256Hex
    capabilities: tuple[Literal["activate", "create-draft", "review"], ...]
    expires_at: AwareDatetime
    decision_signer_key_id: str = Field(min_length=1, max_length=128)
    decision_private_key_b64: SecretStr
    publish_signer_key_id: str = Field(min_length=1, max_length=128)
    publish_private_key_b64: SecretStr

    @field_validator("expires_at")
    @classmethod
    def _utc(cls, value: AwareDatetime) -> AwareDatetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        text_values = (
            self.principal_id,
            self.policy_id,
            self.policy_version,
            self.decision_signer_key_id,
            self.publish_signer_key_id,
        )
        if any(value != value.strip() or "\x00" in value for value in text_values):
            raise ValueError("automation identity is not canonical")
        if self.capabilities != ("activate", "create-draft", "review"):
            raise ValueError("automation capabilities are not exact")
        if self.decision_signer_key_id == self.publish_signer_key_id:
            raise ValueError("automation signing keys must be distinct")
        if self.expires_at <= datetime.now(UTC):
            raise ValueError("automation policy expired")
        for secret in (
            self.decision_private_key_b64,
            self.publish_private_key_b64,
        ):
            try:
                raw = base64.b64decode(secret.get_secret_value(), validate=True)
            except (ValueError, TypeError):
                raise ValueError("automation private key is invalid") from None
            if len(raw) != 32:
                raise ValueError("automation private key is invalid")
        return self


class ProductScopeRuntimeSettings(_FrozenModel):
    scope: ProductScope
    platform: PlatformConnectionSettings
    source_authorities: tuple[SourceAuthoritySettings, ...] = Field(min_length=1)
    model: ProductModelSettings
    automation: AutomationSignerSettings

    @model_validator(mode="after")
    def _same_scope_and_unique_keys(self) -> Self:
        if self.scope != self.model.scope or self.scope != self.automation.scope:
            raise ValueError("product runtime scope binding mismatch")
        key_ids = tuple(item.key_id for item in self.source_authorities)
        if len(key_ids) != len(set(key_ids)):
            raise ValueError("source authority key ids must be unique")
        for item in self.source_authorities:
            item.public_key()
        return self


class ProductRuntimeSettings(_FrozenModel):
    contract: Literal["product-ingestion-runtime.830.v1"]
    trusted_files: TrustedFiles
    pump: ProductPumpSettings = ProductPumpSettings()
    bindings: tuple[ProductScopeRuntimeSettings, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_scopes(self) -> Self:
        spaces = tuple(item.scope.space_id for item in self.bindings)
        if len(spaces) != len(set(spaces)):
            raise ValueError("product runtime spaces must be unique")
        return self


@dataclass(frozen=True, slots=True)
class LoadedProductBinding:
    settings: ProductScopeRuntimeSettings
    source_public_keys: Mapping[str, Ed25519PublicKey]

    @property
    def scope(self) -> ProductScope:
        return self.settings.scope

    @property
    def platform(self) -> PlatformConnectionSettings:
        return self.settings.platform

    @property
    def model(self) -> ProductModelSettings:
        return self.settings.model

    @property
    def automation(self) -> AutomationSignerSettings:
        return self.settings.automation


@dataclass(frozen=True, slots=True)
class ProductRuntimeConfiguration:
    settings: ProductRuntimeSettings
    bindings: Mapping[str, LoadedProductBinding]
    catalog: SchemaPackCatalogV1 = field(repr=False)
    catalog_json: bytes = field(repr=False)
    profile_confirmation_json: bytes = field(repr=False)
    resolution_policy_json: bytes = field(repr=False)


def _read_trusted_file(reference: TrustedFileReference) -> bytes:
    with Path(reference.path).open("rb") as stream:
        raw = stream.read(reference.max_bytes + 1)
    if len(raw) > reference.max_bytes or hashlib.sha256(raw).hexdigest() != reference.sha256:
        raise ValueError("trusted product configuration file changed")
    return raw


def _configured_scopes(settings: ShellSettings) -> tuple[ProductScope, ...]:
    raw = json.loads(
        settings.product_ingestion_scopes_json.get_secret_value(),
        object_pairs_hook=_object,
    )
    if not isinstance(raw, list) or not raw:
        raise ValueError("product scopes are empty")
    scopes = tuple(ProductScope.model_validate(item) for item in raw)
    if len({scope.space_id for scope in scopes}) != len(scopes):
        raise ValueError("product scopes are ambiguous")
    return scopes


def load_product_runtime_configuration(
    shell: ShellSettings,
) -> ProductRuntimeConfiguration | None:
    """Load the enabled worker boundary without surfacing configured values."""
    if not shell.product_ingestion_enabled:
        return None
    try:
        payload = json.loads(
            shell.product_ingestion_runtime_json.get_secret_value(),
            object_pairs_hook=_object,
        )
        configured = ProductRuntimeSettings.model_validate_json(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )
        if len(configured.bindings) != 1:
            raise ValueError("one exact product scope is required per worker")
        scopes = _configured_scopes(shell)
        by_space = {item.scope.space_id: item for item in configured.bindings}
        if by_space.keys() != {item.space_id for item in scopes} or any(
            by_space[item.space_id].scope != item for item in scopes
        ):
            raise ValueError("runtime scopes do not match API scopes")
        trusted = configured.trusted_files
        catalog_json = _read_trusted_file(trusted.catalog)
        profile_json = _read_trusted_file(trusted.profile_confirmation)
        resolution_json = _read_trusted_file(trusted.resolution_policy)
        catalog = SchemaPackCatalogV1.model_validate_json(catalog_json)
        for raw in (profile_json, resolution_json):
            if not isinstance(json.loads(raw, object_pairs_hook=_object), dict):
                raise ValueError("trusted product configuration must be an object")
        bindings = MappingProxyType(
            {
                space_id: LoadedProductBinding(
                    settings=item,
                    source_public_keys=MappingProxyType(
                        {
                            authority.key_id: authority.public_key()
                            for authority in item.source_authorities
                        }
                    ),
                )
                for space_id, item in by_space.items()
            }
        )
        return ProductRuntimeConfiguration(
            settings=configured,
            bindings=bindings,
            catalog=catalog,
            catalog_json=catalog_json,
            profile_confirmation_json=profile_json,
            resolution_policy_json=resolution_json,
        )
    except (OSError, ValueError, TypeError, ValidationError) as error:
        raise ShellConfigError(("product_ingestion_runtime_json",)) from error


__all__ = [
    "AutomationSignerSettings",
    "LoadedProductBinding",
    "PlatformConnectionSettings",
    "ProductPumpSettings",
    "ProductRuntimeConfiguration",
    "ProductRuntimeSettings",
    "ProductScopeRuntimeSettings",
    "SourceAuthoritySettings",
    "TrustedFileReference",
    "TrustedFiles",
    "load_product_runtime_configuration",
]
