"""Change 016: product registration and routing require an explicit scope."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, func, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from insurance_harness.db.models import (
    InsuranceProduct,
    KnowledgeSpace,
    ProductAlias,
    ProductDocument,
    ProductVersion,
    UnassignedItem,
)
from insurance_harness.db.scope import (
    KnowledgeScope,
    ScopeViolation,
    UnboundKnowledgeSpace,
)
from insurance_harness.goldenset.pdf import PageText
from insurance_harness.product.cli import main
from insurance_harness.product.register import register_products
from insurance_harness.product.routing import (
    MatchIndex,
    ProductCandidate,
    UnassignedDraft,
    persist_unassigned,
    route_document,
)

HARNESS_ROOT = Path(__file__).resolve().parents[1]


def _make_scope(
    factory: Callable[..., KnowledgeScope], suffix: str
) -> KnowledgeScope:
    return factory(
        tenant_id=f"tenant-{suffix}",
        raw_kb_id=f"raw-{suffix}",
        wiki_kb_id=f"wiki-{suffix}",
    )


@pytest.fixture
def product_root(tmp_path: Path) -> Path:
    root = tmp_path / "products"
    product = root / "跨空间同码产品"
    product.mkdir(parents=True)
    product.joinpath("product_meta.json").write_text(
        json.dumps(
            {
                "planCode": "SAME-001",
                "versionNo": "v1",
                "clauseName": "平安跨空间同码年金保险",
                "planSalesStatus": "在售",
                "reportPreparedFileCode": "备案-SAME-001",
                "sccode": "注册-SAME-001",
            },
            ensure_ascii=False,
        )
    )
    product.joinpath("保险条款.pdf").write_bytes(b"%PDF-scoped")
    return root


def test_register_same_product_code_is_idempotent_per_scope(
    session: Session,
    bound_scope: Callable[..., KnowledgeScope],
    product_root: Path,
) -> None:
    scope_a = _make_scope(bound_scope, "a")
    scope_b = _make_scope(bound_scope, "b")

    report_a = register_products(session, product_root, scope=scope_a)
    report_b = register_products(session, product_root, scope=scope_b)
    report_a_again = register_products(session, product_root, scope=scope_a)

    assert report_a.created == ["SAME-001"]
    assert report_b.created == ["SAME-001"]
    assert report_a_again.created == []
    assert report_a_again.unchanged == ["SAME-001"]

    products_a = session.scalars(
        select(InsuranceProduct).where(InsuranceProduct.space_id == scope_a.space_id)
    ).all()
    products_b = session.scalars(
        select(InsuranceProduct).where(InsuranceProduct.space_id == scope_b.space_id)
    ).all()
    assert [row.product_code for row in products_a] == ["SAME-001"]
    assert [row.product_code for row in products_b] == ["SAME-001"]
    assert products_a[0].id != products_b[0].id

    assert session.scalars(
        select(ProductVersion).where(ProductVersion.space_id == scope_a.space_id)
    ).one().space_id == scope_a.space_id
    assert session.scalars(
        select(ProductVersion).where(ProductVersion.space_id == scope_b.space_id)
    ).one().space_id == scope_b.space_id
    assert session.scalars(
        select(ProductDocument).where(ProductDocument.space_id == scope_a.space_id)
    ).one().space_id == scope_a.space_id
    assert session.scalars(
        select(ProductDocument).where(ProductDocument.space_id == scope_b.space_id)
    ).one().space_id == scope_b.space_id


def test_product_mutation_rejects_forged_matching_bound_scope_before_write(
    session: Session,
    bound_scope: Callable[..., KnowledgeScope],
    product_root: Path,
) -> None:
    loaded = _make_scope(bound_scope, "forged-product")
    forged = KnowledgeScope(**loaded.model_dump())
    before = session.scalar(select(func.count()).select_from(InsuranceProduct))

    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        register_products(session, product_root, scope=forged)

    assert session.scalar(select(func.count()).select_from(InsuranceProduct)) == before
    assert session.is_active


def test_product_read_rejects_scope_loaded_by_different_engine_before_query(
    session: Session,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    loaded = _make_scope(bound_scope, "cross-engine")
    session.commit()
    first_engine = session.get_bind()
    assert isinstance(first_engine, Engine)
    other_engine = create_engine(str(first_engine.url))
    statements: list[str] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        statements.append(statement)

    event.listen(other_engine, "before_cursor_execute", record_statement)
    try:
        with Session(other_engine) as other_session:
            with pytest.raises(ScopeViolation, match="^scope mismatch$"):
                MatchIndex.from_session(other_session, loaded)
            assert other_session.is_active
    finally:
        event.remove(other_engine, "before_cursor_execute", record_statement)
        other_engine.dispose()

    assert statements == []


def test_match_index_excludes_other_scope_products_aliases_and_identifiers(
    session: Session,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope_a = _make_scope(bound_scope, "index-a")
    scope_b = _make_scope(bound_scope, "index-b")
    product_a = InsuranceProduct(
        space_id=scope_a.space_id,
        product_code="A-001",
        canonical_name="甲空间养老年金保险",
        category="annuity",
        status="在售",
        filing_no="备案-A-001",
    )
    product_b = InsuranceProduct(
        space_id=scope_b.space_id,
        product_code="B-ONLY-001",
        canonical_name="乙空间专属终身寿险",
        category="whole-life",
        status="在售",
        filing_no="备案-B-ONLY-001",
    )
    session.add_all([product_a, product_b])
    session.flush()
    session.add_all(
        [
            ProductAlias(
                product_id=product_b.id,
                alias="乙空间独有别名",
                alias_type="manual",
            ),
            ProductAlias(
                product_id=product_b.id,
                alias="注册-B-ONLY-001",
                alias_type="registration_no",
            ),
        ]
    )
    session.flush()

    index_a = MatchIndex.from_session(session, scope_a)

    for marker in (
        product_b.canonical_name,
        product_b.product_code,
        product_b.filing_no,
        "乙空间独有别名",
        "注册-B-ONLY-001",
    ):
        assert marker is not None
        result = route_document(
            index_a,
            "b-only.pdf",
            [PageText(page_no=1, text=f"页面只包含乙空间标识：{marker}")],
        )
        assert result.candidates == ()
        assert result.unassigned
        assert all(
            candidate.product_id != product_b.id
            for draft in result.unassigned
            for candidate in draft.candidates
        )


def test_route_result_and_unassigned_draft_retain_index_scope(
    session: Session,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope_b = _make_scope(bound_scope, "route-identity-b")
    product_b = InsuranceProduct(
        space_id=scope_b.space_id,
        product_code="B-ROUTE-001",
        canonical_name="乙空间专属终身寿险",
        category="whole-life",
        status="在售",
        filing_no=None,
    )
    session.add(product_b)
    session.flush()

    result = route_document(
        MatchIndex.from_session(session, scope_b),
        "b-fuzzy.pdf",
        [PageText(page_no=1, text="乙空间专属保障")],
    )

    assert result.space_id == scope_b.space_id
    assert result.unassigned[0].space_id == scope_b.space_id
    assert [candidate.product_id for candidate in result.unassigned[0].candidates] == [
        product_b.id
    ]


def test_persist_unassigned_rejects_draft_from_other_scope_before_writing(
    session: Session,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope_a = _make_scope(bound_scope, "reject-a")
    scope_b = _make_scope(bound_scope, "reject-b")
    product_b = InsuranceProduct(
        space_id=scope_b.space_id,
        product_code="B-REJECT-001",
        canonical_name="乙空间拒绝错写终身寿险",
        category="whole-life",
        status="在售",
        filing_no=None,
    )
    session.add(product_b)
    session.flush()
    result_b = route_document(
        MatchIndex.from_session(session, scope_b),
        "b-fuzzy.pdf",
        [PageText(page_no=1, text="乙空间拒绝错写保障")],
    )
    assert result_b.unassigned[0].candidates[0].product_id == product_b.id

    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        persist_unassigned(session, scope_a, result_b.unassigned)

    assert session.scalar(select(func.count()).select_from(UnassignedItem)) == 0


def test_persist_unassigned_rejects_forged_candidate_before_writing(
    session: Session,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope_a = _make_scope(bound_scope, "forged-a")
    product_a = InsuranceProduct(
        space_id=scope_a.space_id,
        product_code="A-REAL-001",
        canonical_name="甲空间真实年金保险",
        category="annuity",
        status="在售",
        filing_no=None,
    )
    session.add(product_a)
    session.flush()
    forged = ProductCandidate(
        product_id=product_a.id,
        product_code="FORGED-001",
        canonical_name=product_a.canonical_name,
        confidence="fuzzy",
        basis="伪造候选",
    )
    draft = UnassignedDraft(
        space_id=scope_a.space_id,
        doc_ref="forged.pdf",
        section_ref=None,
        excerpt="伪造候选",
        candidates=(forged,),
        reason="无 exact/alias 命中",
    )

    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        persist_unassigned(session, scope_a, (draft,))

    assert session.scalar(select(func.count()).select_from(UnassignedItem)) == 0


def test_match_index_alias_query_scopes_through_product_join(
    session: Session,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope_a = _make_scope(bound_scope, "join-a")
    product_a = InsuranceProduct(
        space_id=scope_a.space_id,
        product_code="A-JOIN-001",
        canonical_name="甲空间联结年金保险",
        category="annuity",
        status="在售",
        filing_no=None,
    )
    session.add(product_a)
    session.flush()
    session.add(
        ProductAlias(product_id=product_a.id, alias="甲空间联结别名", alias_type="manual")
    )
    session.flush()
    statements: list[str] = []

    def capture_sql(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    bind = session.get_bind()
    event.listen(bind, "before_cursor_execute", capture_sql)
    try:
        MatchIndex.from_session(session, scope_a)
    finally:
        event.remove(bind, "before_cursor_execute", capture_sql)

    alias_sql = [sql for sql in statements if "FROM product_aliases" in sql]
    assert len(alias_sql) == 1
    assert "JOIN insurance_products" in alias_sql[0]
    assert "insurance_products.space_id" in alias_sql[0]


def test_empty_scope_index_has_no_product_or_alias_candidates(
    session: Session,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope_empty = _make_scope(bound_scope, "empty")
    scope_b = _make_scope(bound_scope, "empty-b")
    product_b = InsuranceProduct(
        space_id=scope_b.space_id,
        product_code="B-EMPTY-001",
        canonical_name="乙空间空索引终身寿险",
        category="whole-life",
        status="在售",
        filing_no=None,
    )
    session.add(product_b)
    session.flush()
    session.add(
        ProductAlias(product_id=product_b.id, alias="乙空间空索引别名", alias_type="manual")
    )
    session.flush()

    result = route_document(
        MatchIndex.from_session(session, scope_empty),
        "empty.pdf",
        [PageText(page_no=1, text="乙空间空索引终身寿险 乙空间空索引别名")],
    )

    assert result.candidates == ()
    assert len(result.unassigned) == 1
    assert result.unassigned[0].candidates == ()


def test_persist_unassigned_writes_only_requested_scope(
    session: Session,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope_a = _make_scope(bound_scope, "pool-a")
    scope_b = _make_scope(bound_scope, "pool-b")
    draft = UnassignedDraft(
        space_id=scope_a.space_id,
        doc_ref="unmatched.pdf",
        section_ref=None,
        excerpt="没有产品标识",
        candidates=(),
        reason="无 exact/alias 命中",
    )

    assert persist_unassigned(session, scope_a, (draft,)) == 1
    session.flush()

    rows_a = session.scalars(
        select(UnassignedItem).where(UnassignedItem.space_id == scope_a.space_id)
    ).all()
    rows_b = session.scalars(
        select(UnassignedItem).where(UnassignedItem.space_id == scope_b.space_id)
    ).all()
    assert len(rows_a) == 1
    assert rows_a[0].space_id == scope_a.space_id
    assert rows_b == []


@pytest.mark.parametrize(
    "argv",
    [
        ["register-products", "/tmp/products"],
        ["classify", "/tmp/products", "--report", "/tmp/report.md"],
    ],
)
def test_product_cli_requires_space_id(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(argv)
    assert exc_info.value.code == 2


@pytest.mark.parametrize("command_name", ["register-products", "classify"])
@pytest.mark.parametrize("space_state", ["missing", "unbound"])
def test_product_cli_fails_closed_for_missing_and_unbound_space(
    tmp_path: Path,
    command_name: str,
    space_state: str,
) -> None:
    db_url = f"sqlite:///{tmp_path}/{command_name}-{space_state}.db"
    rejected_id = "missing-space"
    if space_state == "unbound":
        cfg = Config(str(HARNESS_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(HARNESS_ROOT / "migrations"))
        cfg.set_main_option("sqlalchemy.url", db_url)
        command.upgrade(cfg, "head")
        engine = create_engine(db_url)
        with Session(engine) as session:
            unbound = KnowledgeSpace(
                name="unbound",
                binding_status="unbound",
                tenant_id=None,
                raw_kb_id=None,
                wiki_kb_id=None,
            )
            session.add(unbound)
            session.commit()
            rejected_id = unbound.id
        engine.dispose()

    root = tmp_path / "empty-products"
    root.mkdir()
    argv = [
        command_name,
        str(root),
        "--db-url",
        db_url,
        "--space-id",
        rejected_id,
    ]
    if command_name == "classify":
        argv.extend(["--report", str(tmp_path / "report.md")])

    with pytest.raises(UnboundKnowledgeSpace, match="knowledge space is unavailable"):
        main(argv)


def test_product_cli_db_flag_overrides_environment_for_migration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flag_db_url = f"sqlite:///{tmp_path}/flag.db"
    environment_db = tmp_path / "environment.db"
    monkeypatch.setenv("HARNESS_DB_URL", f"sqlite:///{environment_db}")
    root = tmp_path / "empty-flag-products"
    root.mkdir()

    with pytest.raises(UnboundKnowledgeSpace, match="knowledge space is unavailable"):
        main(
            [
                "register-products",
                str(root),
                "--db-url",
                flag_db_url,
                "--space-id",
                "missing-space",
            ]
        )

    flag_engine = create_engine(flag_db_url)
    try:
        assert "knowledge_spaces" in sa_inspect(flag_engine).get_table_names()
    finally:
        flag_engine.dispose()
    assert not environment_db.exists()


def test_product_cli_environment_db_url_preserves_percent_dsn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_url = f"sqlite:///{tmp_path}/environment%scope.db"
    monkeypatch.setenv("HARNESS_DB_URL", db_url)
    root = tmp_path / "empty-environment-products"
    root.mkdir()

    with pytest.raises(UnboundKnowledgeSpace, match="knowledge space is unavailable"):
        main(
            [
                "register-products",
                str(root),
                "--space-id",
                "missing-space",
            ]
        )

    engine = create_engine(db_url)
    try:
        assert "knowledge_spaces" in sa_inspect(engine).get_table_names()
    finally:
        engine.dispose()
