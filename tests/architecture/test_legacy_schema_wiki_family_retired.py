"""The old 830 / SchemaWiki family is gone (S7d-2c-3c).

After S7d-2c-3a/3b no enterprise path calls it. What stays is what the enterprise path uses: the
wiki_release repository and types (enterprise Heads and Releases) and the field catalog data file,
which the Harness reads until S7d-2c-3d moves it. Standard library only.
Run from the repository root:  python -m pytest -q tests/architecture
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import REPO_ROOT  # noqa: E402

SERVICE = "internal/application/service"
TYPES = "internal/types"
HANDLER = "internal/handler"
RETIRED = (
    *(
        f"{SERVICE}/{name}.go"
        for name in (
            "concept_free_wiki_830_g2",
            "concept_free_wiki_830_g3",
            "concept_source_authority_830_g2",
            "concept_source_locator_830_g3",
            "concept_source_reuse_830_g3",
            "concept_source_reuse_legacy_830_g3",
            "entity_page_graph_830_g1",
            "g3_platform_source_snapshot",
            "g3_product_bindings",
            "g3_published_legacy_baseline",
            "g3_published_provenance",
            "g3_published_read_reuse",
            "g3_published_source_reuse",
            "schema_wiki",
            "schema_wiki_citation_content",
            "schema_wiki_citation_revision",
            "schema_wiki_golden_successor_status",
            "wiki_release",
        )
    ),
    *(
        f"{TYPES}/{name}.go"
        for name in (
            "concept_free_wiki_830_g2",
            "concept_free_wiki_830_g3",
            "concept_free_wiki_830_g3_identity_v2",
            "concept_free_wiki_830_g3_identity_v3",
            "concept_free_wiki_830_g3_issuer_alias",
            "entity_page_graph_830_g1",
            "schema_wiki",
            "knowledge_content_provenance",
            "knowledge_quality",
            "product_concept_relation",
        )
    ),
    "internal/application/repository/schema_wiki_formal_candidate_preview.go",
    "internal/application/repository/schema_wiki_c5_revision_manifest.go",
    *(
        f"{HANDLER}/{name}.go"
        for name in (
            "schema_wiki",
            "wiki_release",
            "concept_free_wiki_830_g2",
            "entity_page_graph_830_g1",
            "schema_pack_catalog_830_g3",
            "g3_product_bindings",
        )
    ),
    "internal/router/routes_schema_wiki.go",
    "cmd/release-proof-596-1/main.go",
    "scripts/deployment/g3_replace_app.py",
)
WIRED = (
    "internal/router/router.go",
    "internal/router/routes_knowledge.go",
    "internal/container/container.go",
)
GONE = (
    "SchemaWiki",
    "WikiReleaseService",
    "ConceptSourceAuthority",
    "ConceptFreeWiki",
    "EntityPageGraph",
    "release-scopes",
)
KEPT = (
    "internal/application/repository/wiki_release.go",
    "internal/types/wiki_release.go",
    f"{HANDLER}/schema_pack_catalog_830_g3.generated.json",
)


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_the_family_files_are_gone() -> None:
    assert [rel for rel in RETIRED if (REPO_ROOT / rel).exists()] == []


def test_routing_and_wiring_no_longer_name_the_family() -> None:
    for rel in WIRED:
        source = _read(rel)
        assert [name for name in GONE if name in source] == [], rel


def test_the_capture_store_keeps_no_family_helpers() -> None:
    assert "830" not in _read(f"{SERVICE}/g3_first_parse.go")


def test_what_the_enterprise_path_uses_stays() -> None:
    assert [rel for rel in KEPT if not (REPO_ROOT / rel).is_file()] == []
