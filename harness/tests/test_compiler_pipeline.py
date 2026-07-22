"""spec E1（编排/恢复/死信/manifest）+ E4.3 + E5.1/E5.3 + E6.1：管道级测试。

全部用假文档 + 桩模型客户端（page_loader 注入），不碰真实 PDF 与网关。
"""

import hashlib
import json
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

from insurance_harness.compiler import cli as compiler_cli
from insurance_harness.compiler.llm import ModelClient, ReplayClient, request_key
from insurance_harness.compiler.models import DocManifestEntry, RunManifest
from insurance_harness.compiler.pipeline import (
    ExtractionPipeline,
    PipelineConfig,
    RunResult,
)
from insurance_harness.compiler.prompts import (
    EXTRACTION_SYSTEM,
    GAPFILL_SYSTEM,
    PROMPT_VERSION,
    VOTE_VARIANT_SUFFIXES,
)
from insurance_harness.db.scope import KnowledgeScope, ScopeViolation
from insurance_harness.goldenset.eval import evaluate
from insurance_harness.goldenset.pdf import PageText
from insurance_harness.goldenset.records import GoldenRecord
from insurance_harness.goldenset.runner import read_jsonl
from insurance_harness.schemas import FieldSpec, ProductLineSchema, SchemaRegistry
from insurance_harness.sources import (
    DIRECTORY_REPLAY_PROCESSED_AT,
    DirectoryDocumentSource,
    DirectorySourceRequest,
    MaterializedBatch,
    ProcessedAtOrdering,
    SourceDocument,
    SourceRevision,
    SourceScope,
)

# --- 小 schema + 假文档夹具（E5.3） ---

FIELDS = (
    FieldSpec(name="犹豫期", field_id="hesitation_period", source_sheet="t"),
    FieldSpec(name="等待期", field_id="waiting_period", risk_level="high", source_sheet="t"),
    FieldSpec(name="满期返还", field_id="maturity_benefit", source_sheet="t"),
    FieldSpec(
        name="投被保人豁免", field_id="premium_waiver", risk_level="high", source_sheet="t"
    ),
)
LINE = ProductLineSchema(line_key="t", sheet_name="测试", fields=FIELDS)
REGISTRY = SchemaRegistry(version="v1.1+pipelinetest", lines={"t": LINE}, glossary=())

FAKE_PAGES: dict[str, list[PageText]] = {
    "保险条款.pdf": [
        PageText(
            page_no=1,
            text=(
                "第一条 投保范围与犹豫期\n投保年龄为出生满30日至65周岁，保险期间为终身，"
                "投保人自签收本合同之日起20日内为犹豫期，犹豫期内可申请退保。\n"
                "第二条 等待期\n本合同等待期为90天，等待期内因疾病出险不承担保险责任，"
                "等待期届满后投保人的保障生效，宽限期为60日。\n"
                "第三条 保险责任\n被保险人于本合同有效期内身故的，"
                "我们按基本保险金额给付身故保险金，本合同终止。"
            ),
        ),
        PageText(
            page_no=2,
            text="第四条 保费豁免\n投保人身故或全残的，免交保险费，本合同继续有效。",
        ),
    ]
}


def _make_product_dir(tmp_path: Path) -> Path:
    product_dir = tmp_path / "测试终身寿险产品"
    product_dir.mkdir()
    (product_dir / "保险条款.pdf").touch()  # 占位；页面由 page_loader 注入
    (product_dir / "product_meta.json").write_text(
        json.dumps({"planCode": "TEST01"}), encoding="utf-8"
    )
    return product_dir


def _loader(path: Path) -> list[PageText]:
    return FAKE_PAGES[path.name]


def _item(
    fid: str, value: str | None, tri: str, page: int = 0, quote: str = ""
) -> dict[str, object]:
    ev = [{"page": page, "quote": quote}] if quote else []
    return {"field_id": fid, "value": value, "tri_state": tri, "evidence": ev}


class ScriptedClient:
    """规则化假弱模型：按 prompt 内容确定性作答（可被 Recording/Replay 包装）。"""

    def __init__(self, fail_field: str | None = None) -> None:
        self.calls = 0
        self.extract_batch_calls = 0
        self.vote_prompts: list[str] = []
        self._fail_field = fail_field

    async def complete(self, system: str, user: str) -> str:
        self.calls += 1
        fids = re.findall(r"field_id=(\w+)", user)
        if self._fail_field and system == EXTRACTION_SYSTEM and self._fail_field in fids:
            raise httpx.ConnectError("模拟网关连接失败")
        if system == GAPFILL_SYSTEM:
            fid = fids[0]
            if fid == "premium_waiver" and "免交保险费" in user:
                return json.dumps(
                    [_item(fid, "投保人身故或全残时豁免保费", "present", 2,
                           "免交保险费，本合同继续有效")],
                    ensure_ascii=False,
                )
            return json.dumps([_item(fid, None, "unknown")], ensure_ascii=False)
        if any(suffix in user for suffix in VOTE_VARIANT_SUFFIXES):  # 投票采样
            self.vote_prompts.append(user)
            fid = fids[0]
            if fid == "waiting_period":
                return json.dumps(
                    [_item(fid, "90天", "present", 1, "等待期为90天")], ensure_ascii=False
                )
            # premium_waiver：三个变体三个答案 → 三票三样
            variant = next(
                i for i, s in enumerate(VOTE_VARIANT_SUFFIXES) if s in user
            )
            values = ["有豁免", "投保人豁免", "全残豁免"]
            return json.dumps(
                [_item(fid, values[variant], "present", 2, "免交保险费")],
                ensure_ascii=False,
            )
        # 分批抽取
        self.extract_batch_calls += 1
        items = []
        for fid in fids:
            if fid == "hesitation_period" and "犹豫期" in user:
                items.append(_item(fid, "20日", "present", 1, "20日内为犹豫期"))
            elif fid == "waiting_period" and "等待期为90天" in user:
                items.append(_item(fid, "90天", "present", 1, "等待期为90天"))
            elif fid == "maturity_benefit" and "身故保险金" in user:
                items.append(
                    _item(fid, None, "absent_explicitly", 1,
                          "我们按基本保险金额给付身故保险金")
                )
            else:
                items.append(_item(fid, None, "unknown"))
        return json.dumps(items, ensure_ascii=False)


async def _fast_sleep(_: float) -> None:
    return None


class _ScopedFixtureSource:
    """Explicit scoped source used only by the 016 compiler boundary tests."""

    def __init__(
        self,
        scope: KnowledgeScope,
        page_loader: Callable[[Path], list[PageText]],
    ) -> None:
        self._scope = SourceScope.from_knowledge_scope(scope)
        self._page_loader = page_loader

    @asynccontextmanager
    async def materialize(
        self,
        request: DirectorySourceRequest,
    ) -> AsyncIterator[MaterializedBatch]:
        digest = hashlib.sha256(b"").hexdigest()
        revision = SourceRevision(
            file_hash=digest,
            ordering=ProcessedAtOrdering(value=DIRECTORY_REPLAY_PROCESSED_AT),
            parser_fingerprint="fixture-parser-v1",
        )
        path = request.product_dir / "保险条款.pdf"
        source_id = "compiler-pipeline-test/保险条款.pdf"
        document = SourceDocument(
            source_id=source_id,
            scope=self._scope,
            knowledge_id="fixture-knowledge-1",
            raw_kb_id=self._scope.raw_kb_id,
            title=path.stem,
            file_name=path.name,
            file_type="application/pdf",
            source_revision=revision,
            original_digest=digest,
            pages=tuple(self._page_loader(path)),
            chunks=(),
        )
        yield MaterializedBatch(
            documents=(document,),
            local_paths={source_id: path},
        )


def _pipeline(
    client: ModelClient,
    page_loader: Callable[[Path], list[PageText]] = _loader,
    *,
    scope: KnowledgeScope | None = None,
) -> ExtractionPipeline:
    source = (
        DirectoryDocumentSource(
            replay_identity="compiler-pipeline-test",
            parser_fingerprint="fixture-parser-v1",
            page_loader=page_loader,
        )
        if scope is None
        else _ScopedFixtureSource(scope, page_loader)
    )
    return ExtractionPipeline(
        client=client,
        registry=REGISTRY,
        model_id="scripted-test",
        source=source,
        config=PipelineConfig(
            concurrency=2,
            transport_attempts=2,
            backoff_base_s=0.0,
            model_profile="offline-eval",
        ),
        sleep=_fast_sleep,
        scope=scope,
    )


async def _run_pipeline(
    pipeline: ExtractionPipeline,
    *,
    product_dir: Path,
    **kwargs: object,
) -> RunResult:
    return await pipeline.run(
        product_dir=product_dir,
        source_request=DirectorySourceRequest(product_dir=product_dir),
        **kwargs,  # type: ignore[arg-type]
    )


async def _run_ok(tmp_path: Path, client: ScriptedClient) -> RunResult:
    product_dir = _make_product_dir(tmp_path)
    return await _run_pipeline(
        _pipeline(client),
        product_dir=product_dir, run_dir=tmp_path / "run", line_key="t"
    )


def _source_manifest_entry() -> DocManifestEntry:
    digest = hashlib.sha256(b"").hexdigest()
    revision = SourceRevision(
        file_hash=digest,
        ordering=ProcessedAtOrdering(value=DIRECTORY_REPLAY_PROCESSED_AT),
        parser_fingerprint="fixture-parser-v1",
    )
    return DocManifestEntry(
        doc="保险条款.pdf",
        source_id="compiler-pipeline-test/保险条款.pdf",
        knowledge_id="fixture-knowledge-1",
        source_revision=revision.value,
        ordering=revision.ordering,
        file_hash=digest,
        original_digest=digest,
        parser_fingerprint=revision.parser_fingerprint,
    )


# --- E5.3 端到端 + E1.3 manifest + E4.3 成本断言 ---


async def test_e5_3_end_to_end_with_scripted_model(tmp_path: Path) -> None:
    client = ScriptedClient()
    result = await _run_ok(tmp_path, client)
    by_id = {r.field_id: r for r in result.records}
    assert len(result.records) == 4  # 每个 extractable 字段必有一行（unknown 也要出）

    hes = by_id["hesitation_period"]
    assert hes.tri_state == "present" and hes.value == "20日"
    assert hes.evidence[0].page == 1 and hes.confidence == "high"

    wait = by_id["waiting_period"]  # 高风险：3/3 一致 → high
    assert wait.tri_state == "present" and wait.confidence == "high"

    mat = by_id["maturity_benefit"]
    assert mat.tri_state == "absent_explicitly" and mat.evidence

    waiver = by_id["premium_waiver"]  # 补漏得出 + 投票三票三样 → pending_judge
    assert waiver.tri_state == "present" and waiver.pending_judge
    assert waiver.confidence == "low"

    # E1.3 run manifest
    m = result.manifest
    assert m.schema_version == "v1.1+pipelinetest"
    assert m.model_id == "scripted-test" and m.prompt_version == PROMPT_VERSION
    assert m.stats.calls == client.calls > 0
    assert m.stats.est_tokens > 0 and m.duration_s is not None
    assert m.docs[0].family_id.startswith("fam-")
    assert 0 < m.docs[0].compression_ratio <= 1
    assert m.pending_judge_count == 1

    # E4.3：投票只对 high 字段发生（低风险字段绝不进采样）
    assert client.vote_prompts, "高风险字段必须投票"
    assert not any("hesitation_period" in p for p in client.vote_prompts)
    assert not any("maturity_benefit" in p for p in client.vote_prompts)

    # 裁决队列落盘（claude-session 模式）
    queue_lines = result.judge_queue_path.read_text(encoding="utf-8").splitlines()
    assert len(queue_lines) == 1
    req = json.loads(queue_lines[0])
    assert req["field_id"] == "premium_waiver" and req["reason"] == "vote_disagreement"


async def test_s4_3_scoped_run_writes_scope_ids_without_secrets(
    tmp_path: Path,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope = bound_scope(
        tenant_id="tenant-manifest",
        raw_kb_id="raw-manifest",
        wiki_kb_id="wiki-manifest",
    )
    product_dir = _make_product_dir(tmp_path)

    result = await _run_pipeline(
        _pipeline(ScriptedClient(), scope=scope),
        product_dir=product_dir,
        run_dir=tmp_path / "run-scoped",
        line_key="t",
    )

    assert result.manifest.space_id == scope.space_id
    assert result.manifest.tenant_id == "tenant-manifest"
    assert result.manifest.raw_kb_id == "raw-manifest"
    manifest_json = result.manifest_path.read_text(encoding="utf-8").lower()
    assert "tenant-manifest" in manifest_json
    assert "raw-manifest" in manifest_json
    assert "api_key" not in manifest_json
    assert "token" not in manifest_json
    assert "secret" not in manifest_json
    assert "wiki-manifest" not in manifest_json


async def test_e5_1_pred_jsonl_feeds_eval_runner(tmp_path: Path) -> None:
    """pred JSONL 与 002 eval runner 输入格式对齐；confidence 扩展字段被容忍。"""
    result = await _run_ok(tmp_path, ScriptedClient())
    records = read_jsonl(result.pred_path)  # 用 002 的读取器解析（忽略未知字段）
    assert len(records) == 4
    golden = [
        GoldenRecord(
            product_id="TEST01", product_name="测试终身寿险产品", doc="保险条款.pdf",
            field_id="hesitation_period", field_name="犹豫期", value="20日",
            tri_state="present", evidence=[], annotator_model="gs", schema_version="v1.1",
            created_at=records[0].created_at,
        ),
        GoldenRecord(
            product_id="TEST01", product_name="测试终身寿险产品", doc="保险条款.pdf",
            field_id="waiting_period", field_name="等待期", value="90日",
            tri_state="present", evidence=[], annotator_model="gs", schema_version="v1.1",
            created_at=records[0].created_at,
        ),
    ]
    eval_result = evaluate(golden, records)
    # 犹豫期=20日 命中；等待期 90天 vs 90日 归一化后……（日≠天字符串不等但都无单位换算）
    assert eval_result.micro.tp >= 1
    assert eval_result.confusion[("present", "present")] == 2


async def test_e5_3_replay_client_reproduces_run(tmp_path: Path) -> None:
    """ReplayClient 模式全管道复跑：录制后回放，产出一致（E5.3 不依赖真实模型）。"""
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()

    class RecordingClient:
        def __init__(self, inner: ScriptedClient) -> None:
            self._inner = inner

        async def complete(self, system: str, user: str) -> str:
            out = await self._inner.complete(system, user)
            (fixtures / f"{request_key(system, user)}.txt").write_text(out, encoding="utf-8")
            return out

    rec_result = await _run_pipeline(
        _pipeline(RecordingClient(ScriptedClient())),
        product_dir=_make_product_dir(tmp_path), run_dir=tmp_path / "run-rec", line_key="t"
    )
    replay_result = await _run_pipeline(
        _pipeline(ReplayClient(fixtures)),
        product_dir=tmp_path / "测试终身寿险产品", run_dir=tmp_path / "run-replay", line_key="t"
    )
    strip = {"created_at"}
    a = [r.model_dump(exclude=strip) for r in rec_result.records]
    b = [r.model_dump(exclude=strip) for r in replay_result.records]
    assert a == b


# --- E1.1 断点恢复 / E1.2 死信 ---


async def test_e1_1_kill_and_resume_from_checkpoint(tmp_path: Path) -> None:
    """注入失败节点 → run 中断；修复后 resume：已完成节点不重跑，从断点继续。"""
    product_dir = _make_product_dir(tmp_path)
    client = ScriptedClient()
    pipeline = _pipeline(client)
    run_dir = tmp_path / "run"

    with pytest.raises(RuntimeError, match="注入失败"):
        await _run_pipeline(
            pipeline,
            product_dir=product_dir, run_dir=run_dir, line_key="t",
            fail_nodes=["gapfill"],
        )
    assert (run_dir / "checkpoint.sqlite").exists()
    calls_before = client.extract_batch_calls
    assert calls_before > 0  # extract 节点已完成

    result = await _run_pipeline(
        pipeline,
        product_dir=product_dir, run_dir=run_dir, line_key="t",
        resume=True, state_patch={"fail_nodes": []},
    )
    # 抽取节点不重跑（E1.1：从最后完成节点继续）
    assert client.extract_batch_calls == calls_before
    assert {r.field_id for r in result.records} == {f.field_id for f in FIELDS}
    assert result.manifest.pending_judge_count == 1


async def test_s4_3_scoped_pipeline_rejects_other_space_checkpoint_before_resume(
    tmp_path: Path,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    product_dir = _make_product_dir(tmp_path)
    run_dir = tmp_path / "run-cross-space"
    scope_a = bound_scope(
        tenant_id="tenant-checkpoint-a",
        raw_kb_id="raw-checkpoint-a",
        wiki_kb_id="wiki-checkpoint-a",
    )
    scope_b = bound_scope(
        tenant_id="tenant-checkpoint-b",
        raw_kb_id="raw-checkpoint-b",
        wiki_kb_id="wiki-checkpoint-b",
    )
    with pytest.raises(RuntimeError, match="注入失败"):
        await _run_pipeline(
            _pipeline(ScriptedClient(), scope=scope_b),
            product_dir=product_dir,
            run_dir=run_dir,
            line_key="t",
            fail_nodes=["gapfill"],
        )
    reader = ScriptedClient()

    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        await _run_pipeline(
            _pipeline(reader, scope=scope_a),
            product_dir=product_dir,
            run_dir=run_dir,
            line_key="t",
            resume=True,
            state_patch={"fail_nodes": []},
        )

    assert reader.calls == 0


async def test_s4_3_scoped_pipeline_rejects_legacy_unscoped_checkpoint(
    tmp_path: Path,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    product_dir = _make_product_dir(tmp_path)
    run_dir = tmp_path / "run-unscoped-to-scoped"
    with pytest.raises(RuntimeError, match="注入失败"):
        await _run_pipeline(
            _pipeline(ScriptedClient()),
            product_dir=product_dir,
            run_dir=run_dir,
            line_key="t",
            fail_nodes=["gapfill"],
        )
    scope = bound_scope(
        tenant_id="tenant-checkpoint-scoped",
        raw_kb_id="raw-checkpoint-scoped",
        wiki_kb_id="wiki-checkpoint-scoped",
    )
    reader = ScriptedClient()

    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        await _run_pipeline(
            _pipeline(reader, scope=scope),
            product_dir=product_dir,
            run_dir=run_dir,
            line_key="t",
            resume=True,
            state_patch={"fail_nodes": []},
        )

    assert reader.calls == 0


async def test_s4_3_offline_pipeline_rejects_scoped_checkpoint(
    tmp_path: Path,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    product_dir = _make_product_dir(tmp_path)
    run_dir = tmp_path / "run-scoped-to-unscoped"
    scope = bound_scope(
        tenant_id="tenant-checkpoint-writer",
        raw_kb_id="raw-checkpoint-writer",
        wiki_kb_id="wiki-checkpoint-writer",
    )
    with pytest.raises(RuntimeError, match="注入失败"):
        await _run_pipeline(
            _pipeline(ScriptedClient(), scope=scope),
            product_dir=product_dir,
            run_dir=run_dir,
            line_key="t",
            fail_nodes=["gapfill"],
        )
    reader = ScriptedClient()

    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        await _run_pipeline(
            _pipeline(reader),
            product_dir=product_dir,
            run_dir=run_dir,
            line_key="t",
            resume=True,
            state_patch={"fail_nodes": []},
        )

    assert reader.calls == 0


@pytest.mark.parametrize("field", ["space_id", "tenant_id", "raw_kb_id"])
async def test_s4_3_state_patch_cannot_change_manifest_scope(
    tmp_path: Path,
    bound_scope: Callable[..., KnowledgeScope],
    field: str,
) -> None:
    product_dir = _make_product_dir(tmp_path)
    run_dir = tmp_path / f"run-state-patch-{field}"
    scope = bound_scope(
        tenant_id=f"tenant-patch-{field}",
        raw_kb_id=f"raw-patch-{field}",
        wiki_kb_id=f"wiki-patch-{field}",
    )
    pipeline = _pipeline(ScriptedClient(), scope=scope)
    with pytest.raises(RuntimeError, match="注入失败"):
        await _run_pipeline(
            pipeline,
            product_dir=product_dir,
            run_dir=run_dir,
            line_key="t",
            fail_nodes=["gapfill"],
        )
    manifest = RunManifest(
        run_id=product_dir.name,
        product_dir=str(product_dir),
        space_id=scope.space_id,
        tenant_id=scope.tenant_id,
        raw_kb_id=scope.raw_kb_id,
        docs=[_source_manifest_entry()],
    ).model_dump(mode="json")
    marker = f"forged-{field}"
    manifest[field] = marker

    with pytest.raises(ScopeViolation, match="^state patch mismatch$"):
        await _run_pipeline(
            pipeline,
            product_dir=product_dir,
            run_dir=run_dir,
            line_key="t",
            resume=True,
            state_patch={"fail_nodes": [], "manifest": manifest},
        )
    assert marker.encode() not in (run_dir / "checkpoint.sqlite").read_bytes()


@pytest.mark.parametrize(
    ("field", "forged_value", "checkpoint_marker"),
    [
        ("run_id", "forged-run-identity", b"forged-run-identity"),
        ("product_dir", "/forged/product/directory", b"/forged/product/directory"),
        ("product_id", "FORGED-PRODUCT-ID", b"FORGED-PRODUCT-ID"),
        ("product_name", "Forged Product Name", b"Forged Product Name"),
        ("model_id", "forged-model-id", b"forged-model-id"),
        ("schema_version", "forged-schema-version", b"forged-schema-version"),
        (
            "stats",
            {"calls": 987_654_321, "prompt_chars": 123, "completion_chars": 456},
            b"987654321",
        ),
        ("started_at", "2099-01-02T03:04:05.123456+00:00", b"2099-01-02"),
        ("finished_at", "2099-02-03T04:05:06.654321+00:00", b"2099-02-03"),
    ],
)
async def test_resume_rejects_every_manifest_patch_before_checkpoint_write(
    tmp_path: Path,
    bound_scope: Callable[..., KnowledgeScope],
    field: str,
    forged_value: object,
    checkpoint_marker: bytes,
) -> None:
    product_dir = _make_product_dir(tmp_path)
    run_dir = tmp_path / f"run-forged-manifest-{field}"
    scope = bound_scope(
        tenant_id=f"tenant-forged-{field}",
        raw_kb_id=f"raw-forged-{field}",
        wiki_kb_id=f"wiki-forged-{field}",
    )
    pipeline = _pipeline(ScriptedClient(), scope=scope)
    with pytest.raises(RuntimeError, match="注入失败"):
        await _run_pipeline(
            pipeline,
            product_dir=product_dir,
            run_dir=run_dir,
            line_key="t",
            fail_nodes=["gapfill"],
        )
    manifest = RunManifest(
        run_id=product_dir.name,
        product_dir=str(product_dir),
        space_id=scope.space_id,
        tenant_id=scope.tenant_id,
        raw_kb_id=scope.raw_kb_id,
        product_id="TEST01",
        product_name=product_dir.name,
        line_key="t",
        schema_version=REGISTRY.version,
        model_id="scripted-test",
        judge_mode="claude-session",
        prompt_version=PROMPT_VERSION,
        docs=[_source_manifest_entry()],
    ).model_dump(mode="json")
    manifest[field] = forged_value

    with pytest.raises(ScopeViolation, match="^state patch mismatch$"):
        await _run_pipeline(
            pipeline,
            product_dir=product_dir,
            run_dir=run_dir,
            line_key="t",
            resume=True,
            state_patch={"fail_nodes": [], "manifest": manifest},
        )

    assert checkpoint_marker not in (run_dir / "checkpoint.sqlite").read_bytes()


async def test_s4_3_malformed_manifest_patch_is_generic_and_secret_free(
    tmp_path: Path,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    product_dir = _make_product_dir(tmp_path)
    run_dir = tmp_path / "run-malformed-patch"
    scope = bound_scope(
        tenant_id="tenant-malformed",
        raw_kb_id="raw-malformed",
        wiki_kb_id="wiki-malformed",
    )
    pipeline = _pipeline(ScriptedClient(), scope=scope)
    with pytest.raises(RuntimeError, match="注入失败"):
        await _run_pipeline(
            pipeline,
            product_dir=product_dir,
            run_dir=run_dir,
            line_key="t",
            fail_nodes=["gapfill"],
        )

    with pytest.raises(ScopeViolation) as error:
        await _run_pipeline(
            pipeline,
            product_dir=product_dir,
            run_dir=run_dir,
            line_key="t",
            resume=True,
            state_patch={
                "fail_nodes": [],
                "manifest": {"space_id": {"api_key": "leak-me"}},
            },
        )

    assert str(error.value) == "state patch mismatch"
    assert repr(error.value) == "ScopeViolation('state patch mismatch')"
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    assert "leak-me" not in repr(error.value)


async def test_s4_3_manifest_patch_is_rejected_before_checkpoint_write(
    tmp_path: Path,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    marker = "leak-me-checkpoint"
    product_dir = _make_product_dir(tmp_path)
    run_dir = tmp_path / "run-canonical-patch"
    scope = bound_scope(
        tenant_id="tenant-canonical",
        raw_kb_id="raw-canonical",
        wiki_kb_id="wiki-canonical",
    )
    pipeline = _pipeline(ScriptedClient(), scope=scope)
    with pytest.raises(RuntimeError, match="注入失败"):
        await _run_pipeline(
            pipeline,
            product_dir=product_dir,
            run_dir=run_dir,
            line_key="t",
            fail_nodes=["gapfill"],
        )
    manifest: dict[str, object] = RunManifest(
        run_id=product_dir.name,
        product_dir=str(product_dir),
        space_id=scope.space_id,
        tenant_id=scope.tenant_id,
        raw_kb_id=scope.raw_kb_id,
        docs=[_source_manifest_entry()],
    ).model_dump(mode="json")
    manifest["api_key"] = marker
    manifest["arbitrary_extra"] = {"secret": marker}
    stats = manifest["stats"]
    assert isinstance(stats, dict)
    stats["api_key"] = marker
    patch = {"fail_nodes": [], "manifest": manifest}

    with pytest.raises(ScopeViolation, match="^state patch mismatch$"):
        await _run_pipeline(
            pipeline,
            product_dir=product_dir,
            run_dir=run_dir,
            line_key="t",
            resume=True,
            state_patch=patch,
        )

    assert manifest["api_key"] == marker, "caller-owned patch must not be mutated"
    assert marker.encode() not in (run_dir / "checkpoint.sqlite").read_bytes()


async def test_s4_3_same_scope_checkpoint_resumes_normally(
    tmp_path: Path,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    product_dir = _make_product_dir(tmp_path)
    run_dir = tmp_path / "run-same-scope"
    scope = bound_scope(
        tenant_id="tenant-same-scope",
        raw_kb_id="raw-same-scope",
        wiki_kb_id="wiki-same-scope",
    )
    client = ScriptedClient()
    pipeline = _pipeline(client, scope=scope)
    with pytest.raises(RuntimeError, match="注入失败"):
        await _run_pipeline(
            pipeline,
            product_dir=product_dir,
            run_dir=run_dir,
            line_key="t",
            fail_nodes=["gapfill"],
        )
    extract_calls = client.extract_batch_calls

    result = await _run_pipeline(
        pipeline,
        product_dir=product_dir,
        run_dir=run_dir,
        line_key="t",
        resume=True,
        state_patch={"fail_nodes": []},
    )

    assert client.extract_batch_calls == extract_calls
    assert result.manifest.space_id == scope.space_id


async def test_e1_2_transport_failure_becomes_dead_letter_not_abort(tmp_path: Path) -> None:
    """coverage 组网关持续失败 → 死信 + 该批字段 unknown；其他字段组不受影响。"""
    client = ScriptedClient(fail_field="maturity_benefit")
    result = await _run_ok(tmp_path, client)
    by_id = {r.field_id: r for r in result.records}

    dead = result.manifest.dead_letters
    assert dead and dead[0].group == "coverage"
    assert "maturity_benefit" in dead[0].field_ids
    assert dead[0].attempts == 2  # 可配置重试次数

    # 死信字段：unknown + 原因（补漏也补不到 → 维持 unknown）
    assert by_id["maturity_benefit"].tri_state == "unknown"
    # 其他字段组照常完成（E1.2 不中断）
    assert by_id["hesitation_period"].tri_state == "present"
    assert by_id["waiting_period"].tri_state == "present"

    # 死信清单落盘可重放
    dead_path = result.pred_path.parent / "dead-letters.jsonl"
    assert dead_path.exists() and dead_path.read_text(encoding="utf-8").strip()


# --- 裁决回写 CLI ---


async def test_apply_judgements_cli_updates_pred(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = await _run_ok(tmp_path, ScriptedClient())
    run_dir = result.pred_path.parent
    judgements = tmp_path / "judgements.jsonl"
    judgements.write_text(
        json.dumps(
            {
                "product_id": "TEST01", "field_id": "premium_waiver",
                "value": "投保人身故或全残豁免保费", "tri_state": "present",
                "evidence": [{"page": 2, "quote": "免交保险费，本合同继续有效"}],
                "confidence": "medium", "reasoning": "三候选中与原文一致的表述",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HARNESS_MODEL_PROFILE", "manual")
    rc = compiler_cli.main(["apply-judgements", str(run_dir), str(judgements)])
    assert rc == 0
    updated = {r.field_id: r for r in read_jsonl(result.pred_path)}
    waiver = updated["premium_waiver"]
    assert waiver.value == "投保人身故或全残豁免保费"


def test_e6_1_prompt_version_constant() -> None:
    """prompt 集中 compiler/prompts/ 且带版本常量（E6.1）；manifest 记录同一版本。"""
    assert re.fullmatch(r"ep-v\d+\.\d+", PROMPT_VERSION)
    assert EXTRACTION_SYSTEM and GAPFILL_SYSTEM
    assert len(VOTE_VARIANT_SUFFIXES) == 3
