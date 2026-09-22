"""Secret-bearing, exact-scope configuration for product model execution."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from insurance_harness.model_policy.models import ModelIdentity
from insurance_harness.model_policy.policy import ModelPolicyDenied, ProductionModelPolicy
from insurance_harness.product_ingestion.models import ProductScope

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def _digest(domain: str, value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(domain.encode() + b"\0" + raw).hexdigest()


class ModelTemplatePolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    template_id: str = Field(min_length=1, max_length=128)
    role: Literal["classify", "extract", "verify"]
    purpose: str = Field(min_length=1, max_length=128)
    run_schema_version: str = Field(min_length=1, max_length=64)
    prompt_sha256: Sha256Hex
    max_context_bytes: int = Field(ge=1)
    max_output_tokens: int = Field(ge=1)

    @field_validator("template_id", "purpose", "run_schema_version")
    @classmethod
    def _clean_identity(cls, value: str) -> str:
        if value != value.strip() or "\x00" in value:
            raise ValueError("model template identity must be canonical")
        return value


class ProductModelSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    scope: ProductScope
    endpoint: HttpUrl
    api_key: SecretStr = Field(exclude=True)
    model: Literal["gemini-3.7-flash-medium"]
    policy_version: Literal["g3-user-gemini-gateway-v1"]
    expires_at: AwareDatetime
    templates: tuple[ModelTemplatePolicy, ...] = Field(min_length=1)
    field_template_id: str = Field(min_length=1, max_length=128)
    max_request_bytes: int = Field(ge=1)
    max_response_bytes: int = Field(ge=1)
    timeout_seconds: float = Field(gt=0, le=300)

    @field_validator("expires_at")
    @classmethod
    def _utc(cls, value: AwareDatetime) -> AwareDatetime:
        return value.astimezone(UTC)

    @field_validator("endpoint")
    @classmethod
    def _exact_endpoint(cls, value: HttpUrl) -> HttpUrl:
        if value.query is not None or value.fragment is not None or value.username is not None:
            raise ValueError("model endpoint cannot contain query, fragment, or userinfo")
        return value

    @model_validator(mode="after")
    def _coherent(self) -> ProductModelSettings:
        if not self.api_key.get_secret_value():
            raise ValueError("model API key must not be empty")
        if self.policy_version != self.policy_version.strip() or "\x00" in self.policy_version:
            raise ValueError("model policy version must be canonical")
        ids = [item.template_id for item in self.templates]
        if len(ids) != len(set(ids)):
            raise ValueError("model template ids must be unique")
        field = next(
            (item for item in self.templates if item.template_id == self.field_template_id),
            None,
        )
        if field is None or field.role != "extract":
            raise ValueError("field template must name one extract policy")
        identities = tuple(
            ModelIdentity(
                provider="g3-user-gateway",
                deployment_id=self.model,
                family="gemini",
                role=item.role,
                policy_version=self.policy_version,
            )
            for item in self.templates
        )
        policy = ProductionModelPolicy({identity.identity_key for identity in identities})
        try:
            for identity in identities:
                policy.evaluate(identity)
        except ModelPolicyDenied:
            raise ValueError("configured Gemini identity is not approved") from None
        return self

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        values = self.model_dump(mode="python")
        values["api_key"] = self.api_key
        if update:
            values.update(update)
        return type(self).model_validate(values)

    def template(self, template_id: str) -> ModelTemplatePolicy:
        try:
            return next(item for item in self.templates if item.template_id == template_id)
        except StopIteration:
            raise ValueError("model template is not approved") from None

    def _public_policy(self) -> dict[str, object]:
        return self.model_dump(mode="json")

    @property
    def policy_sha256(self) -> str:
        return _digest("product-model-policy.v1", self._public_policy())

    @property
    def scope_sha256(self) -> str:
        return _digest("product-model-scope.v1", self.scope.model_dump(mode="json"))

    @property
    def model_plan_sha256(self) -> str:
        return _digest(
            "product-model-plan.v1",
            {
                "model": self.model,
                "policy_version": self.policy_version,
                "templates": [item.model_dump(mode="json") for item in self.templates],
            },
        )
