"""Pure-domain TemplatePackage contracts and resolver (OpenSpec 028a)."""

from insurance_harness.template_packages.models import (
    EvidencePolicy,
    FieldGroup,
    ProvenanceReceipt,
    ResolutionRequest,
    ResolvedTemplate,
    ResolvedTemplateSource,
    TemplateApproval,
    TemplateCatalogEntry,
    TemplatePackageContent,
    TemplateScope,
    TemplateVersion,
    ValidatorRef,
    canonical_content_hash,
)
from insurance_harness.template_packages.ports import TemplateCatalog
from insurance_harness.template_packages.resolver import (
    TemplateResolutionError,
    resolve_template,
)

__all__ = [
    "EvidencePolicy",
    "FieldGroup",
    "ProvenanceReceipt",
    "ResolutionRequest",
    "ResolvedTemplate",
    "ResolvedTemplateSource",
    "TemplateApproval",
    "TemplateCatalog",
    "TemplateCatalogEntry",
    "TemplatePackageContent",
    "TemplateResolutionError",
    "TemplateScope",
    "TemplateVersion",
    "ValidatorRef",
    "canonical_content_hash",
    "resolve_template",
]
