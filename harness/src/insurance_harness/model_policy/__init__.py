"""Stable public production model-policy boundary."""

from .admission import (
    AdmissionBinding,
    AdmissionPolicyDenied,
    AdmissionVerificationReceipt,
    AdmissionVerifier,
    IssuedModelPermit,
    StrictAdmissionRequestBinding,
    VerifiedAdmission,
)
from .composition import ProductionModelComposition
from .gateway import GuardedModelClient, ModelGatewayDenied, ModelTransportError
from .models import (
    IdentityKey,
    ModelCallContext,
    ModelCallFacts,
    ModelCallRequest,
    ModelFamily,
    ModelIdentity,
    ModelPermitView,
    ModelRole,
    PolicyReceipt,
    ReceiptSink,
)
from .policy import ModelPolicyDenied, ProductionModelPolicy

__all__ = [
    "AdmissionBinding",
    "AdmissionPolicyDenied",
    "AdmissionVerificationReceipt",
    "AdmissionVerifier",
    "IdentityKey",
    "GuardedModelClient",
    "IssuedModelPermit",
    "ModelCallFacts",
    "ModelCallRequest",
    "ModelCallContext",
    "ModelFamily",
    "ModelIdentity",
    "ModelGatewayDenied",
    "ModelPermitView",
    "ModelPolicyDenied",
    "ModelRole",
    "ModelTransportError",
    "PolicyReceipt",
    "ProductionModelComposition",
    "ProductionModelPolicy",
    "ReceiptSink",
    "StrictAdmissionRequestBinding",
    "VerifiedAdmission",
    "build_g3_bounded_model_client",
]


def __getattr__(name: str) -> object:
    if name == "build_g3_bounded_model_client":
        from .g3_bounded_gateway import build_g3_bounded_model_client

        return build_g3_bounded_model_client
    raise AttributeError(name)
