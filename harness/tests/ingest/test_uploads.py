"""S5b-2 acceptance (protected, written by Claude): finding uploads and applying attributions.

Spec docs/design/slices/S5b-2-上传材料发现与归属执行.md §3.2–§3.10, §3.12–§3.13. Material openings
come from the S5b-1 fixture (13 real products, 7 insurance types); WeKnora is faked offline.
"""

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from insurance_harness.ingest.raw_sources import RawSources, RawSourcesError
from insurance_harness.ingest.registry import ProductRegistry, load_registry, save_registry
from insurance_harness.ingest.uploads import attribute_uploads, main
from tests.ingest.upload_helpers import (
    PRODUCTS,
    RAW_KB,
    SPACE,
    Pages,
    entry,
    knowledge_id,
    material,
    raw,
    registry,
)

ROLES = ("terms", "brochure", "rate_table")


def kinds(value: ProductRegistry) -> dict[str, str]:
    return {
        p.attribution.outcome + ":" + p.knowledge_id: p.attribution.reason for p in value.pending
    }


# 2. Supplement --------------------------------------------------------------------------------


def test_a_brochure_joins_its_registered_product() -> None:
    run = attribute_uploads(
        registry(p1828=entry("1828", "terms")), [raw("1828", "brochure")], Pages()
    )
    assert {m.role for m in run.registry.products["1828"].materials} == {"terms", "brochure"}
    assert run.report.affected_products == ["1828"]
    assert run.report.counts == {"SUPPLEMENT": 1}
    assert len(run.registry.source_map().products["1828"]) == 2
    assert run.registry.decisions[-1].attribution.outcome == "SUPPLEMENT"


# 3. A whole new product in one batch -----------------------------------------------------------


@pytest.mark.parametrize(
    "order", [ROLES, tuple(reversed(ROLES))], ids=["terms-first", "terms-last"]
)
def test_a_new_product_uploaded_together_is_created_in_one_run(order: tuple[str, ...]) -> None:
    sources = [raw("1830", role) for role in order]
    run = attribute_uploads(registry(p1828=entry("1828", *ROLES)), sources, Pages())
    created = [pid for pid, p in run.registry.products.items() if p.origin == "created"]
    assert len(created) == 1 and created[0].startswith("sc-")
    product = run.registry.products[created[0]]
    assert {m.role for m in product.materials} == set(ROLES)
    assert product.schema_pack_id == PRODUCTS["1830"]["schema_pack_id"]
    assert run.registry.pending == []
    assert run.report.affected_products == created


# 4. A brochure ahead of its terms ---------------------------------------------------------------


def test_a_brochure_waits_until_its_terms_arrive() -> None:
    first = attribute_uploads(
        registry(p1828=entry("1828", *ROLES)), [raw("1830", "brochure")], Pages()
    )
    assert kinds(first.registry) == {
        "QUARANTINE:" + knowledge_id("1830", "brochure"): "no_product_anchor"
    }
    assert first.report.affected_products == []
    second = attribute_uploads(
        first.registry, [raw("1830", "brochure"), raw("1830", "terms")], Pages()
    )
    assert second.registry.pending == []
    created = [p for p in second.registry.products.values() if p.origin == "created"]
    assert len(created) == 1
    assert {m.role for m in created[0].materials} == {"terms", "brochure"}


# 5. New version -------------------------------------------------------------------------------


def test_new_terms_replace_the_old_ones() -> None:
    head = material("1828", "terms")["head"].replace("174号", "999号", 1)
    new = raw("1828", "terms", knowledge_id="k-1828-terms2", sha256="e" * 64)
    run = attribute_uploads(
        registry(p1828=entry("1828", *ROLES)), [new], Pages(heads={"k-1828-terms2": head})
    )
    product = run.registry.products["1828"]
    terms = [m.knowledge_id for m in product.materials if m.role == "terms"]
    assert terms == ["k-1828-terms2"]
    assert len(product.clause_codes) == 2
    assert run.registry.decisions[-1].attribution.replaces == (knowledge_id("1828", "terms"),)
    assert run.report.affected_products == ["1828"]


# 6. Waiting for a person ----------------------------------------------------------------------


def test_items_for_a_person_are_not_judged_again() -> None:
    second = raw("1828", "brochure", knowledge_id="k-1828-brochure2", sha256="f" * 64)
    heads = {"k-1828-brochure2": material("1828", "brochure")["head"]}
    first = attribute_uploads(registry(p1828=entry("1828", *ROLES)), [second], Pages(heads=heads))
    assert kinds(first.registry) == {"NEEDS_CONFIRM:k-1828-brochure2": "same_role_differs"}
    pages = Pages(heads=heads)
    again = attribute_uploads(first.registry, [second], pages)
    assert pages.calls == []
    assert again.registry == first.registry


# 7. Duplicates and skipped entries ---------------------------------------------------------------


def test_a_duplicate_is_recorded_but_not_added() -> None:
    copy = raw("1828", "brochure", knowledge_id="k-copy")
    run = attribute_uploads(
        registry(p1828=entry("1828", *ROLES)),
        [copy],
        Pages(heads={"k-copy": material("1828", "brochure")["head"]}),
    )
    assert "k-copy" not in {m.knowledge_id for m in run.registry.products["1828"].materials}
    assert run.registry.decisions[-1].attribution.outcome == "DUPLICATE"
    assert run.report.affected_products == []


def test_registered_materials_are_not_judged_again() -> None:
    pages = Pages()
    run = attribute_uploads(
        registry(p1828=entry("1828", *ROLES)), [raw("1828", r) for r in ROLES], pages
    )
    assert pages.calls == []
    assert run.report.counts == {}


# 8. Idempotence -------------------------------------------------------------------------------


def test_running_twice_changes_nothing_the_second_time() -> None:
    sources = [raw("1830", role) for role in ROLES] + [raw("1814", "brochure")]
    first = attribute_uploads(registry(p1814=entry("1814", "terms")), sources, Pages())
    second = attribute_uploads(first.registry, sources, Pages())
    assert second.registry == first.registry
    assert second.report.affected_products == []


# 9. Unreadable pages ----------------------------------------------------------------------------


def test_an_unreadable_material_is_retried_later_and_others_continue() -> None:
    failing = knowledge_id("1814", "brochure")
    run = attribute_uploads(
        registry(p1814=entry("1814", "terms"), p1828=entry("1828", "terms")),
        [raw("1814", "brochure"), raw("1828", "brochure")],
        Pages(failing=(failing,)),
    )
    assert run.report.unreadable == [failing]
    assert failing not in {
        m.knowledge_id for p in run.registry.products.values() for m in p.materials
    }
    assert failing not in {p.knowledge_id for p in run.registry.pending}
    assert run.report.affected_products == ["1828"]


# 10. RAW listing ------------------------------------------------------------------------------


def listing_item(product_id: str, role: str, status: str = "completed") -> dict[str, object]:
    m = material(product_id, role)
    return {
        "id": knowledge_id(product_id, role),
        "parse_status": status,
        "current_parse_attempt": 1,
        "file_name": m["file_name"],
        "file_sha256": m["sha256"],
    }


def listing_transport(
    items: list[dict[str, object]], total: int | None = None
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/api/v1/knowledge-bases/{RAW_KB}/knowledge"
        page = int(request.url.params["page"])
        size = int(request.url.params["page_size"])
        chunk = items[(page - 1) * size : page * size]
        body = {
            "success": True,
            "data": chunk,
            "total": len(items) if total is None else total,
            "page": page,
            "page_size": size,
        }
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handler)


def test_the_listing_returns_only_completed_materials_across_pages() -> None:
    items = [listing_item(pid, role) for pid in PRODUCTS for role in ROLES]
    items.append(listing_item("1828", "terms", status="processing") | {"id": "k-pending"})
    sources = RawSources(
        "http://weknora.test", "key", transport=listing_transport(items)
    ).completed(RAW_KB)
    assert len(sources) == len(PRODUCTS) * 3
    assert "k-pending" not in {s.knowledge_id for s in sources}


@pytest.mark.parametrize("breakage", ["total", "sha"])
def test_an_inconsistent_listing_fails_as_a_whole(breakage: str) -> None:
    items = [listing_item("1828", role) for role in ROLES]
    if breakage == "sha":
        items[1]["file_sha256"] = "not-a-digest"
    transport = listing_transport(items, total=5 if breakage == "total" else None)
    with pytest.raises(RawSourcesError) as caught:
        RawSources("http://weknora.test", "key", transport=transport).completed(RAW_KB)
    assert caught.value.code == "RAW_LISTING_INVALID"


# 12–13. Command -------------------------------------------------------------------------------


def wiki_transport(items: list[dict[str, object]]) -> httpx.MockTransport:
    listing = listing_transport(items)

    def handler(request: httpx.Request) -> httpx.Response:
        if "/sources/" not in request.url.path:
            return listing.handle_request(request)
        parts = request.url.path.split("/")
        kid, attempt = parts[parts.index("sources") + 1], int(parts[parts.index("attempts") + 1])
        _, product_id, role = kid.split("-", 2)
        texts = [material(product_id, role)["head"], ""]
        body = {
            "knowledge_id": kid,
            "parse_attempt": attempt,
            "document": material(product_id, role)["file_name"],
            "document_sha256": material(product_id, role)["sha256"],
            "parser_identity_sha256": "1" * 64,
            "native_sha256": "2" * 64,
            "pages": [
                {
                    "page_number": n,
                    "text": t,
                    "page_text_sha256": hashlib.sha256(t.encode()).hexdigest(),
                }
                for n, t in enumerate(texts, 1)
            ],
        }
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handler)


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARNESS_WEKNORA_BASE_URL", "http://weknora.test")
    monkeypatch.setenv("HARNESS_WEKNORA_API_KEY", "key")


def test_the_command_applies_and_reports_without_material_text(
    tmp_path: Path, environment: None, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "registry.json"
    save_registry(registry(p1828=entry("1828", "terms")), path)
    items = [listing_item("1828", "terms"), listing_item("1828", "brochure")]
    assert main(["run", "--registry", str(path)], transport=wiki_transport(items)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["affected_products"] == ["1828"]
    assert material("1828", "brochure")["head"][:20] not in json.dumps(report, ensure_ascii=False)
    assert len(load_registry(path).products["1828"].materials) == 2


def test_a_dry_run_writes_nothing(tmp_path: Path, environment: None) -> None:
    path = tmp_path / "registry.json"
    save_registry(registry(p1828=entry("1828", "terms")), path)
    before = path.read_bytes()
    items = [listing_item("1828", "terms"), listing_item("1828", "brochure")]
    assert main(["run", "--registry", str(path), "--dry-run"], transport=wiki_transport(items)) == 0
    assert path.read_bytes() == before


def test_a_busy_registry_is_refused(
    tmp_path: Path, environment: None, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "registry.json"
    save_registry(registry(p1828=entry("1828", "terms")), path)
    before = path.read_bytes()
    (tmp_path / "registry.json.lock").write_text("", encoding="utf-8")
    items = [listing_item("1828", "terms"), listing_item("1828", "brochure")]
    assert main(["run", "--registry", str(path)], transport=wiki_transport(items)) != 0
    assert "REGISTRY_BUSY" in capsys.readouterr().err
    assert path.read_bytes() == before


def test_the_space_of_the_listing_comes_from_the_registry() -> None:
    pages = Pages()
    attribute_uploads(registry(p1828=entry("1828", "terms")), [raw("1828", "brochure")], pages)
    assert pages.calls == [(SPACE, knowledge_id("1828", "brochure"), 1)]
