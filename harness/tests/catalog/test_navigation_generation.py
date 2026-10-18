"""Navigation generation and loading beyond the acceptance cases (S3e Spec §2.1; review of PR #217).

Groups come from the catalog's packs (display name and labels as filed), keep the order already in
the file and need a new version when they change; a malformed navigation file, whatever its root,
stops publishing with a stable code before anything is read or sent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.catalog import navigation as module
from insurance_harness.catalog.navigation import NavigationError, generate, parse_navigation
from insurance_harness.compilers.schema_fields import publish as command


def pack(key: str, name: str, entity_type: str = "insurance_product") -> dict[str, Any]:
    return {"pack": {"schema_pack_id": key, "display_name": name, "entity_type": entity_type,
                     "applicable_classifications": [f"{key}_class"]}}  # fmt: skip


def group(key: str, name: str) -> dict[str, Any]:
    return {"group_key": key, "display_name": name, "classification_labels": [f"{key}_class"]}


def navigation(groups: list[dict[str, Any]], version: str = "v1") -> dict[str, Any]:
    return {
        "navigation_id": "enterprise",
        "navigation_version": version,
        "basis": "maintainer note",
        "domains": [
            {"domain_key": "product", "display_name": "产品库",
             "entity_types": ["insurance_product"], "groups": groups},
            {"domain_key": "service_benefit", "display_name": "服务权益",
             "entity_types": ["service_benefit"], "groups": [group("hand", "手工分组")]},
        ],
    }  # fmt: skip


def test_groups_follow_the_catalog_and_keep_the_order_in_the_file() -> None:
    current = navigation([group("b", "乙"), group("a", "甲"), group("gone", "已删")])
    catalog = {"entries": [pack("a", "甲（新名）"), pack("b", "乙"), pack("c", "丙")]}
    generated = generate(catalog, current, "v2")
    product, service = generated["domains"]
    assert product["groups"] == [group("b", "乙"), group("a", "甲（新名）"), group("c", "丙")]
    assert service == current["domains"][1]  # no pack serves it: kept as written
    assert generated["navigation_version"] == "v2" and generated["basis"] == "maintainer note"


def test_changed_groups_need_a_new_version_and_unchanged_ones_do_not() -> None:
    current = navigation([group("a", "甲")])
    assert generate({"entries": [pack("a", "甲")]}, current) == current
    with pytest.raises(NavigationError) as refused:
        generate({"entries": [pack("a", "甲"), pack("b", "乙")]}, current)
    assert refused.value.code == "NAVIGATION_VERSION_UNCHANGED"


@pytest.mark.parametrize(
    "catalog",
    [{"entries": [pack("x", "未知", "other_type")]}, {"entries": [pack("a", "甲")] * 2}, []],
    ids=["undeclared entity type", "repeated pack", "not a catalog"],
)
def test_a_catalog_the_file_cannot_take_is_refused(catalog: Any) -> None:
    with pytest.raises(NavigationError) as refused:
        generate(catalog, navigation([]), "v2")
    assert refused.value.code == "CATALOG_INVALID"


def test_the_command_writes_checks_and_the_shipped_file_is_current(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert module.main(["--check"]) == 0  # the shipped file against the repository catalog
    target, catalog = tmp_path / "navigation.json", tmp_path / "catalog.json"
    target.write_text(module.render(navigation([group("a", "甲")])), encoding="utf-8")
    catalog.write_text(json.dumps({"entries": [pack("a", "甲"), pack("b", "乙")]}), "utf-8")
    assert module.main(["--catalog", str(catalog), "--check"], navigation=target) == 2
    assert module.main(["--catalog", str(catalog), "--version", "v2"], navigation=target) == 0
    assert module.main(["--catalog", str(catalog), "--check"], navigation=target) == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines[1:] == [{"stopped": "NAVIGATION_STALE"}, {"written": True}, {"written": False}]
    assert parse_navigation(target.read_text("utf-8")).domains[0].groups[1].group_key == "b"


@pytest.mark.parametrize("text", ["[]", "null", '"x"', "3", "{}", "{", '{"basis": 1}'])
def test_any_malformed_navigation_is_one_stable_error(text: str) -> None:
    with pytest.raises(NavigationError) as refused:
        parse_navigation(text)
    assert refused.value.code == "NAVIGATION_INVALID"


def test_publishing_stops_on_a_malformed_navigation_before_reading_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def malformed() -> None:
        raise NavigationError()

    def unreachable(*args: object, **kwargs: object) -> None:
        raise AssertionError("nothing is read or sent after a malformed navigation")

    monkeypatch.setattr(command, "load_navigation", malformed)
    monkeypatch.setattr(command, "load_source_map", unreachable)
    monkeypatch.setattr(command, "PlatformClient", unreachable)
    monkeypatch.setattr(command, "require_cards_version", lambda output: "cards-x")
    monkeypatch.setattr(command, "display_name", lambda directory: "演示")
    monkeypatch.setattr(command, "source_directory", lambda repo, product: tmp_path)
    monkeypatch.setattr(command, "product_page", lambda *args, **kwargs: None)
    output = {"pack_id": "pack", "entity_id": "1828", "model": "m", "fields": []}
    (tmp_path / "1828").mkdir()
    (tmp_path / "1828" / "output.json").write_text(json.dumps(output), encoding="utf-8")
    code = command.main(
        ["--run-root", str(tmp_path), "--product", "1828", "--source-map", str(tmp_path / "m")]
    )
    assert code == 2
    assert capsys.readouterr().out.splitlines() == ['{"stopped": "NAVIGATION_INVALID"}']
