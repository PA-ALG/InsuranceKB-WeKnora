"""The shipped navigation: how readers organise a release's entries (S3e Spec §2.1).

Versioned data, published with every release like the presentation profile. Domains are declared
by hand (display name, entity types), so a domain can exist before its entities do, as service
benefits do today. A domain's groups are generated from the schema pack catalog: one group per
pack of the domain's entity types, with the pack's display name and classification labels as
filed. Regenerating keeps the order of the groups already in the file, so a maintainer may reorder
them by hand; new packs follow in catalog order and packs gone from the catalog are dropped.
A domain no pack serves keeps its groups as written.

usage: python -m insurance_harness.catalog.navigation [--catalog FILE] [--version V] [--check]

Rewrites navigation.json from the catalog. Changed groups need a new --version; --check only
reports whether the file is current. Exit 0 when written or current, 2 with one line
{"stopped": <code>} otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any, NoReturn

from pydantic import BaseModel, ConfigDict, ValidationError

from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.contracts import NavigationProfile

_REPO = Path(__file__).resolve().parents[4]
NAVIGATION = Path(__file__).with_name("navigation.json")


class NavigationError(ValueError):
    """A stable code, never file content or a local path."""

    def __init__(self, code: str = "NAVIGATION_INVALID") -> None:
        self.code = code
        super().__init__(self.code)


def _profile(raw: object) -> NavigationProfile:
    if not isinstance(raw, dict):
        raise NavigationError()
    # "basis" is provenance for maintainers, not part of the contract.
    content = {key: value for key, value in raw.items() if key != "basis"}
    try:
        return NavigationProfile.model_validate(content)
    except ValidationError:
        raise NavigationError() from None


def parse_navigation(text: str) -> NavigationProfile:
    """A navigation file's contract content; any other text is NAVIGATION_INVALID."""
    try:
        raw = json.loads(text)
    except (ValueError, RecursionError):
        raise NavigationError() from None
    return _profile(raw)


@lru_cache(maxsize=1)
def load_navigation() -> NavigationProfile:
    try:
        text = files(__package__).joinpath("navigation.json").read_text(encoding="utf-8")
    except (OSError, ValueError):
        raise NavigationError() from None
    return parse_navigation(text)


class _Record(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class _Pack(_Record):
    schema_pack_id: str
    display_name: str
    entity_type: str
    applicable_classifications: list[str]


class _Entry(_Record):
    pack: _Pack


class _Catalog(_Record):
    entries: list[_Entry]


def generate(catalog: object, current: object, version: str | None = None) -> dict[str, Any]:
    """The navigation file regenerated from the catalog (rules in the module docstring).

    Raises NavigationError: NAVIGATION_INVALID for a malformed file, CATALOG_INVALID for a
    malformed catalog, a repeated pack id or a pack no declared domain takes,
    NAVIGATION_VERSION_UNCHANGED when the groups change under the same version.
    """
    profile = _profile(current)
    assert isinstance(current, dict)  # checked by _profile
    try:
        packs = [entry.pack for entry in _Catalog.model_validate(catalog).entries]
    except ValidationError:
        raise NavigationError("CATALOG_INVALID") from None
    # A pack id names one pack across the whole catalog, whichever domain takes it.
    if len({pack.schema_pack_id for pack in packs}) != len(packs):
        raise NavigationError("CATALOG_INVALID")
    # The contract's view of the file, defaults included: a domain may omit its groups.
    declared = [domain.model_dump(mode="json") for domain in profile.domains]
    domains = [domain.model_dump(mode="json") for domain in profile.domains]
    if any(not any(pack.entity_type in d["entity_types"] for d in domains) for pack in packs):
        raise NavigationError("CATALOG_INVALID")
    for domain in domains:
        mine = [pack for pack in packs if pack.entity_type in domain["entity_types"]]
        if not mine:
            continue  # no pack serves it: its groups stay as written
        by_key = {pack.schema_pack_id: pack for pack in mine}
        kept = [group["group_key"] for group in domain["groups"] if group["group_key"] in by_key]
        order = kept + [pack.schema_pack_id for pack in mine if pack.schema_pack_id not in kept]
        domain["groups"] = [
            {
                "group_key": key,
                "display_name": by_key[key].display_name,
                "classification_labels": list(by_key[key].applicable_classifications),
            }
            for key in order
        ]
    generated = {**current, "domains": domains}
    if version is not None:
        generated["navigation_version"] = version
    changed = domains != declared
    if changed and generated["navigation_version"] == current["navigation_version"]:
        raise NavigationError("NAVIGATION_VERSION_UNCHANGED")
    _profile(generated)
    return generated


def render(navigation: dict[str, Any]) -> str:
    return json.dumps(navigation, ensure_ascii=False, indent=1) + "\n"


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise NavigationError("INVALID_ARGUMENTS")


def main(argv: list[str] | None = None, *, navigation: Path = NAVIGATION) -> int:
    try:
        parser = _Parser(description=__doc__)
        parser.add_argument("--catalog", type=Path, default=_REPO / SCHEMA_PACK_CATALOG)
        parser.add_argument("--version")
        parser.add_argument("--check", action="store_true")
        args = parser.parse_args(argv)
        try:
            catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise NavigationError("CATALOG_INVALID") from None
        try:
            current_text = navigation.read_text(encoding="utf-8")
            current = json.loads(current_text)
        except (OSError, ValueError):
            raise NavigationError() from None
        try:
            text = render(generate(catalog, current, args.version))
        except NavigationError as error:
            # Checking only asks whether the file is current, not how to update it.
            if args.check and error.code == "NAVIGATION_VERSION_UNCHANGED":
                raise NavigationError("NAVIGATION_STALE") from None
            raise
        if args.check:
            if text != current_text:
                raise NavigationError("NAVIGATION_STALE")
        elif text != current_text:
            try:
                navigation.write_text(text, encoding="utf-8")
            except OSError:
                raise NavigationError("NAVIGATION_WRITE_FAILED") from None
    except NavigationError as error:
        print(json.dumps({"stopped": error.code}))
        return 2
    print(json.dumps({"written": not args.check and text != current_text}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
