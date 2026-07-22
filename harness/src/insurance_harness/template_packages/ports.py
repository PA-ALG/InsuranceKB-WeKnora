"""Read-only ports for pure TemplatePackage resolution."""

from __future__ import annotations

from typing import Protocol

from insurance_harness.template_packages.models import TemplateCatalogEntry, TemplateScope


class TemplateCatalog(Protocol):
    """Return an approved candidate for one exact Space/applicability scope."""

    def get_approved(self, scope: TemplateScope) -> TemplateCatalogEntry | None: ...
