"""Replay is bound to the source snapshot and pack, not only to the request text.

Two runs can send identical text for different files (a re-issued PDF with the same text, a
renamed file) or packs; answers recorded for one must not be replayed as the other.
"""

import hashlib
import json
from pathlib import Path

import pytest

from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.compilers.schema_fields.engine import CompletionPort
from insurance_harness.eval import product_sources
from insurance_harness.eval.compile_run import compile_products
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.models import CallLedger

TEXT = "等待期为90日。\n阅读指引"


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def build_repo(root: Path, *, file_name: str, pack: str) -> Path:
    folder = root / "dataset/shouxian_product/产品一"
    write_json(folder / "product_meta.json", {"planCode": "p1", "clauseName": "产品一"})
    (folder / file_name).write_bytes(b"pdf")
    write_json(root / "dataset/golden/v1/manifest.json", {"products": {"p1": {"pack_id": pack}}})
    fields = [
        {
            "field_key": "waiting_period",
            "short_title": "等待期",
            "description": "等待期",
            "formation_method": "原文抽取",
        }
    ]
    write_json(
        root / SCHEMA_PACK_CATALOG,
        {"entries": [{"pack": {"schema_pack_id": pack, "fields": fields}}]},
    )
    return root


class Recorded:
    model = "recorded"

    def __init__(self) -> None:
        self._answers = iter(
            [
                {
                    "fields": [
                        {
                            "ordinal": 0,
                            "field_key": "waiting_period",
                            "state": "present",
                            "segments": ["D1P1S1"],
                        }
                    ]
                },
                {"fields": [{"ordinal": 0, "field_key": "waiting_period", "value": "90日"}]},
            ]
        )

    def complete(self, *, system: str, user: str) -> str:
        return json.dumps(next(self._answers), ensure_ascii=False)


def never(ledger: CallLedger) -> CompletionPort:
    raise AssertionError("replay must not construct a model client")


def pages_with(digest_salt: str):  # type: ignore[no-untyped-def]
    def pages(path: Path) -> list[PageText]:
        digest = hashlib.sha256(path.read_bytes() + digest_salt.encode()).hexdigest()
        return [PageText(path.name, digest, 1, TEXT)]

    return pages


@pytest.mark.parametrize(
    ("file_name", "pack", "salt"),
    [
        ("保险条款.pdf", "pack-a", "reissued"),  # same text, new file fingerprint
        ("新保险条款.pdf", "pack-a", "same"),  # same text, renamed file
        ("保险条款.pdf", "pack-b", "same"),  # same text and fields, another pack
    ],
)
def test_replay_refuses_a_different_source_or_pack_with_identical_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    file_name: str,
    pack: str,
    salt: str,
) -> None:
    monkeypatch.setattr(product_sources, "read_pdf", pages_with("same"))
    recorded = build_repo(tmp_path / "recorded-repo", file_name="保险条款.pdf", pack="pack-a")
    source = tmp_path / "earlier"
    compile_products(
        recorded, ["p1"], completion_factory=lambda ledger: Recorded(), run_root=source, max_sent=2
    )

    monkeypatch.setattr(product_sources, "read_pdf", pages_with(salt))
    current = build_repo(tmp_path / "current-repo", file_name=file_name, pack=pack)
    with pytest.raises(ValueError):
        compile_products(
            current,
            ["p1"],
            completion_factory=never,
            run_root=tmp_path / "out",
            max_sent=0,
            replay_from=source,
        )


def test_replay_of_the_same_source_and_pack_still_works(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(product_sources, "read_pdf", pages_with("same"))
    repo = build_repo(tmp_path / "repo", file_name="保险条款.pdf", pack="pack-a")
    source = tmp_path / "earlier"
    compile_products(
        repo, ["p1"], completion_factory=lambda ledger: Recorded(), run_root=source, max_sent=2
    )
    runs = compile_products(
        repo,
        ["p1"],
        completion_factory=never,
        run_root=tmp_path / "out",
        max_sent=0,
        replay_from=source,
    )
    assert [(run.product_id, run.fields) for run in runs] == [("p1", 1)]
