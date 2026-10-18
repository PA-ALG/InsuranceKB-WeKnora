"""The shipped navigation: how readers organise a release's entries (S3e Spec §2.1).

Versioned data, published with every release like the presentation profile. The product domain
lists the schema pack catalog's packs in catalog order; further domains (service benefits) are
declared here before their entities exist, so adding them later is a data change only.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files

from pydantic import ValidationError

from insurance_harness.contracts import NavigationProfile


class NavigationError(ValueError):
    """A stable code, never file content or a local path."""

    def __init__(self) -> None:
        self.code = "NAVIGATION_INVALID"
        super().__init__(self.code)


@lru_cache(maxsize=1)
def load_navigation() -> NavigationProfile:
    try:
        raw = json.loads(files(__package__).joinpath("navigation.json").read_text(encoding="utf-8"))
        raw.pop("basis", None)  # provenance for maintainers; not part of the contract
        return NavigationProfile.model_validate(raw)
    except (OSError, ValueError, ValidationError) as error:
        raise NavigationError() from error
