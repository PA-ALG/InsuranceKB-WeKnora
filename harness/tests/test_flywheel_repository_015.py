"""OpenSpec 015 F3.3: Space-scoped durable flywheel unit of work."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session

from insurance_harness.db.models import (
    InsuranceProduct,
    KnowledgeSpace,
    ProductAlias,
    ProductVersion,
)
from insurance_harness.db.scope import load_scope
from insurance_harness.flywheel import repository
from insurance_harness.flywheel.models import Trace
from insurance_harness.flywheel.repository import (
    apply_pull,
    list_unaligned_observations,
    preview_pull,
)
from insurance_harness.flywheel.tables import (
    FlywheelCheckpoint,
    FlywheelObservation,
    KnowledgeGapRow,
)
from insurance_harness.knowledge.tables import Claim
from insurance_harness.product.aliases import generate_aliases

HARNESS_ROOT = Path(__file__).resolve().parents[1]
PRODUCT = ("1824", "平安盛世金越尊享版终身寿险", "平保寿发〔2025〕366号")


@pytest.fixture()
def engine(tmp_path: Path) -> Iterator[Engine]:
    url = f"sqlite:///{tmp_path}/flywheel-repository.db"
    config = Config(str(HARNESS_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(HARNESS_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    value = create_engine(url)
    yield value
    value.dispose()


def _seed_space(session: Session, suffix: str) -> tuple[str, str]:
    space = KnowledgeSpace(
        name=f"flywheel-{suffix}",
        binding_status="bound",
        tenant_id=f"tenant-{suffix}",
        raw_kb_id=f"raw-{suffix}",
        wiki_kb_id=f"wiki-{suffix}",
    )
    session.add(space)
    session.flush()
    code, name, filing = PRODUCT
    product = InsuranceProduct(
        space_id=space.id,
        product_code=f"{code}-{suffix}",
        canonical_name=f"{name}{suffix}",
        category="whole-life",
        status="在售",
        filing_no=f"{filing}-{suffix}",
    )
    session.add(product)
    session.flush()
    for alias, alias_type in generate_aliases(product.canonical_name):
        session.add(ProductAlias(product_id=product.id, alias=alias, alias_type=alias_type))
    return space.id, product.id


def _trace(trace_id: str, timestamp: str, product_name: str, answer: str) -> Trace:
    return Trace(
        trace_id=trace_id,
        timestamp=timestamp,
        question=f"{product_name} 的等待期是多久？",
        answer=answer,
    )


def test_f3_3_apply_persists_all_three_tables_and_retry_is_exactly_once(
    engine: Engine,
) -> None:
    with Session(engine) as session, session.begin():
        space_id, product_id = _seed_space(session, "A")
    product_name = f"{PRODUCT[1]}A"
    traces = [
        _trace("t-gap", "2026-07-01T10:00:00Z", product_name, "抱歉，无法确定。"),
        Trace(
            trace_id="t-clean",
            timestamp="2026-07-01T11:00:00Z",
            question=f"{product_name} 的保额？",
            answer="基本保额为五十万元。",
            source_refs=("chunk-1",),
            score=0.9,
        ),
    ]

    with Session(engine) as session, session.begin():
        scope = load_scope(session, space_id)
        first = apply_pull(session, scope, "export-A", traces)
        assert first.processed == 2
        assert first.empty_knowledge_active is True

    with Session(engine) as session, session.begin():
        scope = load_scope(session, space_id)
        retry = apply_pull(session, scope, "export-A", traces)
        assert retry.processed == 0

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(FlywheelCheckpoint)) == 1
        assert session.scalar(select(func.count()).select_from(FlywheelObservation)) == 2
        assert session.scalar(select(func.count()).select_from(KnowledgeGapRow)) == 1
        checkpoint = session.scalar(select(FlywheelCheckpoint))
        gap = session.scalar(select(KnowledgeGapRow))
        assert checkpoint is not None and checkpoint.cursor.endswith("|t-clean")
        assert gap is not None
        assert gap.space_id == space_id
        assert gap.product_id == product_id
        assert gap.hit_count == 2
        # No published Claim exists, so even the otherwise clean trace contributes
        # empty_knowledge to the same product-level gap.
        assert set(gap.signal_types) == {"empty_knowledge", "low_confidence_refusal"}


def test_f3_3_preview_is_read_only_and_real_published_claim_suppresses_empty_signal(
    engine: Engine,
) -> None:
    with Session(engine) as session, session.begin():
        space_id, product_id = _seed_space(session, "claim")
        version = ProductVersion(
            space_id=space_id,
            product_id=product_id,
            version_label="v1",
        )
        session.add(version)
        session.flush()
        session.add(
            Claim(
                space_id=space_id,
                product_version_id=version.id,
                predicate="waiting_period",
                value_state="present",
                value={"days": 90},
                status="published",
                confidence=1.0,
                extraction_method="manual",
                schema_version="test",
            )
        )
    product_name = f"{PRODUCT[1]}claim"
    clean = Trace(
        trace_id="t-clean",
        timestamp="2026-07-01T10:00:00Z",
        question=f"{product_name} 的等待期？",
        answer="等待期为九十天，详见条款。",
        source_refs=("chunk-1",),
        score=0.9,
    )

    with Session(engine) as session:
        scope = load_scope(session, space_id)
        result = preview_pull(
            session,
            scope,
            "claim-source",
            [clean],
            field_names={"等待期": "waiting_period"},
        )
        assert result.empty_knowledge_active is True
        assert result.report.total == 0

        uncovered_field = clean.model_copy(
            update={
                "trace_id": "t-uncovered-field",
                "question": f"{product_name} 的保额？",
            }
        )
        uncovered = preview_pull(
            session,
            scope,
            "claim-source",
            [uncovered_field],
            field_names={"保额": "sum_assured"},
        )
        assert uncovered.report.total == 1
        assert uncovered.gaps[0].signal_types == ("empty_knowledge",)

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(FlywheelCheckpoint)) == 0
        assert session.scalar(select(func.count()).select_from(FlywheelObservation)) == 0
        assert session.scalar(select(func.count()).select_from(KnowledgeGapRow)) == 0


def test_f3_3_claim_in_another_space_never_counts_as_coverage(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        space_a, _product_a = _seed_space(session, "claim-space-a")
        space_b, product_b = _seed_space(session, "claim-space-b")
        version_b = ProductVersion(
            space_id=space_b,
            product_id=product_b,
            version_label="v1",
        )
        session.add(version_b)
        session.flush()
        session.add(
            Claim(
                space_id=space_b,
                product_version_id=version_b.id,
                predicate="waiting_period",
                value_state="present",
                value={"days": 90},
                status="published",
                confidence=1.0,
                extraction_method="manual",
                schema_version="test",
            )
        )
    trace_a = Trace(
        trace_id="t-space-a",
        timestamp="2026-07-01T10:00:00Z",
        question=f"{PRODUCT[1]}claim-space-a 的等待期？",
        answer="等待期为九十天，详见条款。",
        source_refs=("chunk-1",),
        score=0.9,
    )

    with Session(engine) as session:
        scope_a = load_scope(session, space_a)
        result = preview_pull(
            session,
            scope_a,
            "claim-source",
            [trace_a],
            field_names={"等待期": "waiting_period"},
        )

    assert result.report.total == 1
    assert result.gaps[0].signal_types == ("empty_knowledge",)


def test_f3_3_apply_failure_rolls_back_all_state_and_healthy_retry_counts_once(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(engine) as session, session.begin():
        space_id, _ = _seed_space(session, "rollback")
    trace = _trace(
        "t-rollback",
        "2026-07-01T10:00:00Z",
        f"{PRODUCT[1]}rollback",
        "抱歉，无法确定。",
    )
    real_persist = repository._persist_evaluations

    def fail_after_gap_flush(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected ledger failure")

    monkeypatch.setattr(repository, "_persist_evaluations", fail_after_gap_flush)
    with pytest.raises(RuntimeError, match="injected ledger failure"):
        with Session(engine) as session, session.begin():
            scope = load_scope(session, space_id)
            apply_pull(session, scope, "rollback-source", [trace])

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(FlywheelCheckpoint)) == 0
        assert session.scalar(select(func.count()).select_from(FlywheelObservation)) == 0
        assert session.scalar(select(func.count()).select_from(KnowledgeGapRow)) == 0

    monkeypatch.setattr(repository, "_persist_evaluations", real_persist)
    with Session(engine) as session, session.begin():
        scope = load_scope(session, space_id)
        result = apply_pull(session, scope, "rollback-source", [trace])
        assert result.processed == 1

    with Session(engine) as session:
        gap = session.scalar(select(KnowledgeGapRow))
        assert gap is not None and gap.hit_count == 1
        assert session.scalar(select(func.count()).select_from(FlywheelObservation)) == 1
        assert session.scalar(select(func.count()).select_from(FlywheelCheckpoint)) == 1


def test_f2_1_same_source_is_isolated_across_spaces_and_queue_query_is_scoped(
    engine: Engine,
) -> None:
    with Session(engine) as session, session.begin():
        space_a, _ = _seed_space(session, "space-a")
        space_b, _ = _seed_space(session, "space-b")
    unaligned_a = Trace(
        trace_id="same-trace",
        timestamp="2026-07-01T10:00:00Z",
        question="A 空间怎么退保？",
        answer="抱歉，无法回答。",
    )
    unaligned_b = unaligned_a.model_copy(update={"question": "B 空间怎么退保？"})

    for space_id, trace in ((space_a, unaligned_a), (space_b, unaligned_b)):
        with Session(engine) as session, session.begin():
            scope = load_scope(session, space_id)
            result = apply_pull(session, scope, "shared-source", [trace])
            assert result.processed == 1

    with Session(engine) as session:
        scope_a = load_scope(session, space_a)
        scope_b = load_scope(session, space_b)
        queue_a = list_unaligned_observations(session, scope_a, source_id="shared-source")
        queue_b = list_unaligned_observations(session, scope_b, source_id="shared-source")
        assert [row.question for row in queue_a] == ["A 空间怎么退保？"]
        assert [row.question for row in queue_b] == ["B 空间怎么退保？"]
        assert {row.space_id for row in queue_a} == {space_a}
        assert {row.space_id for row in queue_b} == {space_b}
        assert session.scalar(select(func.count()).select_from(FlywheelCheckpoint)) == 2
