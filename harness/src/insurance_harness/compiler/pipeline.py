"""LangGraph 编排（004 T7；spec E1；设计 04 §5.1）。

- 每产品一个 graph run；节点 = load → split_route → extract → gapfill → vote → finalize；
- **状态机是确定性的，LLM 只存在于节点内部**；状态为 JSON 可序列化 dict（pydantic
  模型 dump 后入 state），SqliteSaver checkpoint 持久化，kill 后从最后完成节点续跑（E1.1）；
- 节点内传输级失败指数退避重试，超限记死信且**不中断其他字段组**（E1.2）；
- run manifest 记录 schema 版本/模型/prompt 版本/耗时/调用与 token 统计/族指纹（E1.3）。
"""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict, cast

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field

from ..goldenset.pdf import PageText, ScannedPdfError, extract_pages
from ..schemas import FieldSpec, ProductLineSchema, SchemaRegistry
from .extract import (
    Sleeper,
    TransportRetryError,
    Window,
    WindowExtractor,
    build_windows,
    with_transport_retry,
)
from .feedability import score_feedability
from .gapfill import gapfill_field
from .judge import JudgeDispatcher, make_judge_request, write_judge_queue
from .llm import CallStats, MeteredClient, ModelClient
from .models import (
    DataQuality,
    DeadLetter,
    DocManifestEntry,
    DocPayload,
    FieldCandidate,
    JudgeRequest,
    PredRecord,
    RunManifest,
)
from .prompts import PROMPT_VERSION
from .routing_data import GROUP_ORDER, group_of_field
from .sections import family_fingerprint, route_groups, split_sections
from .templates import TemplateRegistry, run_fastpath
from .templates.tables import TableStructureProvider
from .voting import vote_field


class PipelineConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_fields_per_call: int = 10  # E3.1
    window_chars: int = 4_000
    section_target_chars: int = 2_000
    transport_attempts: int = 3  # E1.2（可配）
    backoff_base_s: float = 1.0
    gapfill_top_n: int = 3
    concurrency: int = 6
    judge_mode: str = "claude-session"


class PipelineState(TypedDict, total=False):
    product_dir: str
    run_dir: str
    run_id: str
    line_key: str
    product_id: str
    product_name: str
    fail_nodes: list[str]  # 测试用注入失败节点（E1.1 用例）
    docs: list[dict[str, Any]]
    candidates: list[dict[str, Any]]
    dead_letters: list[dict[str, Any]]
    judge_queue: list[dict[str, Any]]
    manifest: dict[str, Any]


class RunResult(BaseModel):
    manifest: RunManifest
    records: list[PredRecord] = Field(default_factory=list)
    pred_path: Path
    manifest_path: Path
    judge_queue_path: Path


_DOC_PRIORITY = ("保险条款", "条款", "产品说明书", "说明书")  # 合并时的来源优先级


def _doc_rank(doc: str) -> int:
    for i, kw in enumerate(_DOC_PRIORITY):
        if kw in doc:
            return i
    return len(_DOC_PRIORITY)


def merge_candidates(cands: list[FieldCandidate]) -> dict[str, FieldCandidate]:
    """按 field_id 合并多 (doc, window) 候选：present>absent>unknown、
    judge>fastpath>vote>gapfill>extract、证据多/值长者优先、条款优先于说明书。

    fastpath 是确定性直取（006 F3.4），可信度仅次于裁决。"""
    tri_rank = {"present": 0, "absent_explicitly": 1, "unknown": 2}
    origin_rank = {"judge": 0, "fastpath": 1, "vote": 2, "gapfill": 3, "extract": 4}

    def rank(c: FieldCandidate) -> tuple[int, int, int, int, int, int]:
        return (
            tri_rank[c.tri_state],
            origin_rank[c.origin],
            0 if c.pending_judge else 1,  # 在途裁决必须在 pred 中显性可见
            _doc_rank(c.doc),
            -len(c.evidence),
            -len(c.value or ""),
        )

    best: dict[str, FieldCandidate] = {}
    for c in cands:
        cur = best.get(c.field_id)
        if cur is None or rank(c) < rank(cur):
            best[c.field_id] = c
    return best


def _maybe_fail(node: str, state: PipelineState) -> None:
    if node in (state.get("fail_nodes") or []):
        raise RuntimeError(f"注入失败：节点 {node}（E1.1 测试用）")


class ExtractionPipeline:
    def __init__(
        self,
        client: ModelClient,
        registry: SchemaRegistry,
        model_id: str,
        config: PipelineConfig | None = None,
        judge: JudgeDispatcher | None = None,
        sleep: Sleeper | None = None,
        page_loader: Callable[[Path], list[PageText]] | None = None,
        template_registry: TemplateRegistry | None = None,
        table_provider: TableStructureProvider | None = None,
    ) -> None:
        self._client = client
        self._registry = registry
        self._model_id = model_id
        self._cfg = config or PipelineConfig()
        self._judge = judge or JudgeDispatcher(mode=self._cfg.judge_mode)
        self._sleep: Sleeper = sleep if sleep is not None else asyncio.sleep
        self._page_loader = page_loader or extract_pages
        # 006 F3：模板注册表未提供/为空 → fast path 整体旁路（004 行为不变）
        self._templates = template_registry
        self._table_provider = table_provider

    # --- 节点 ---

    def _line(self, state: PipelineState) -> ProductLineSchema:
        return self._registry.line(state["line_key"])

    async def _node_load(self, state: PipelineState) -> dict[str, Any]:
        # 延迟导入：goldenset 包 __init__ 会加载 annotator（其依赖 compiler.llm），
        # 模块级互相导入会成环（annotator→compiler→pipeline→goldenset）
        from ..goldenset.runner import infer_line_key
        from ..goldenset.verify import load_product_meta

        _maybe_fail("load", state)
        product_dir = Path(state["product_dir"])
        product_name = product_dir.name
        meta = load_product_meta(product_dir)
        product_id = str(meta.get("planCode") or product_name).strip()
        line_key = state.get("line_key") or infer_line_key(product_name)
        docs: list[dict[str, Any]] = []
        dead: list[dict[str, Any]] = list(state.get("dead_letters") or [])
        for pdf_path in sorted(product_dir.glob("*.pdf")):
            try:
                pages = self._page_loader(pdf_path)
            except ScannedPdfError as exc:
                dead.append(
                    DeadLetter(
                        product=product_name, doc=pdf_path.name, group="*",
                        window_ref="*", field_ids=[], error=str(exc), attempts=0,
                    ).model_dump(mode="json")
                )
                continue
            docs.append(DocPayload(doc=pdf_path.name, pages=pages).model_dump(mode="json"))
        manifest = RunManifest(
            run_id=state["run_id"],
            product_dir=str(product_dir),
            product_id=product_id,
            product_name=product_name,
            line_key=line_key,
            schema_version=self._registry.version,
            model_id=self._model_id,
            judge_mode=self._judge.mode,
            prompt_version=PROMPT_VERSION,
            started_at=datetime.now(UTC),
        )
        return {
            "product_id": product_id,
            "product_name": product_name,
            "line_key": line_key,
            "docs": docs,
            "dead_letters": dead,
            "manifest": manifest.model_dump(mode="json"),
        }

    async def _node_split_route(self, state: PipelineState) -> dict[str, Any]:
        _maybe_fail("split_route", state)
        manifest = RunManifest.model_validate(state["manifest"])
        docs: list[dict[str, Any]] = []
        manifest.docs = []
        for raw in state["docs"]:
            payload = DocPayload.model_validate(raw)
            sections = split_sections(
                payload.pages, target_chars=self._cfg.section_target_chars, min_chars=0
            )
            routing = route_groups(sections)
            payload.sections = sections
            payload.by_group = {g: list(ids) for g, ids in routing.by_group.items()}
            payload.family_id = family_fingerprint(sections)
            # 006 F4.2：可喂性评分记入 manifest（只报告不拦截；硬门禁待升级链 L1+）
            feed = score_feedability(payload.doc, payload.pages)
            manifest.docs.append(
                DocManifestEntry(
                    doc=payload.doc,
                    doc_pages=len(payload.pages),
                    sections=len(sections),
                    family_id=payload.family_id,
                    routed_pairs=routing.routed_pairs,
                    total_pairs=routing.total_pairs,
                    compression_ratio=routing.compression_ratio,
                    feedability_score=feed.score,
                    feedability_ok=feed.feedable,
                )
            )
            docs.append(payload.model_dump(mode="json"))
        return {"docs": docs, "manifest": manifest.model_dump(mode="json")}

    async def _node_extract(self, state: PipelineState) -> dict[str, Any]:
        _maybe_fail("extract", state)
        manifest = RunManifest.model_validate(state["manifest"])
        line = self._line(state)
        stats = CallStats()
        metered = MeteredClient(self._client, stats)
        sem = asyncio.Semaphore(self._cfg.concurrency)
        candidates: list[FieldCandidate] = []
        dead: list[DeadLetter] = [
            DeadLetter.model_validate(d) for d in state.get("dead_letters") or []
        ]

        async def do_window(
            extractor: WindowExtractor,
            window: Window,
            fields: list[FieldSpec],
            doc: str,
            group: str,
        ) -> list[FieldCandidate]:
            async with sem:
                try:
                    return await with_transport_retry(
                        lambda: extractor.extract(window, fields),
                        attempts=self._cfg.transport_attempts,
                        base_delay_s=self._cfg.backoff_base_s,
                        sleep=self._sleep,
                    )
                except TransportRetryError as exc:  # 死信，不中断其他字段组（E1.2）
                    dead.append(
                        DeadLetter(
                            product=state["product_name"], doc=doc, group=group,
                            window_ref=window.ref, field_ids=[f.field_id for f in fields],
                            error=str(exc), attempts=self._cfg.transport_attempts,
                        )
                    )
                    return [
                        FieldCandidate(
                            field_id=f.field_id, field_name=f.name, group=group,
                            doc=doc, tri_state="unknown", unknown_reason="dead_letter",
                        )
                        for f in fields
                    ]

        # 006 F3：fast path 先行——命中字段确定性直取并退出通用抽取（战场缩小）
        fastpath_covered: set[str] = set()
        if self._templates is not None:
            fields_by_id = {f.field_id: f for f in line.extractable_fields}
            for raw in state["docs"]:
                payload = DocPayload.model_validate(raw)
                template = self._templates.find(payload.family_id, payload.doc)
                if template is None:
                    continue
                fp_cands = run_fastpath(
                    template,
                    fields_by_id,
                    payload.doc,
                    payload.pages,
                    pdf_path=Path(state["product_dir"]) / payload.doc,
                    provider=self._table_provider,
                    sections=payload.sections,
                )
                candidates.extend(fp_cands)
                fastpath_covered |= {c.field_id for c in fp_cands}
                for entry in manifest.docs:
                    if entry.doc == payload.doc:
                        entry.fastpath_fields = len(fp_cands)
            manifest.template_registry_version = self._templates.version
            manifest.fastpath_fields = len(fastpath_covered)

        tasks: list[asyncio.Task[list[FieldCandidate]]] = []
        for raw in state["docs"]:
            payload = DocPayload.model_validate(raw)
            sec_by_id = {s.section_id: s for s in payload.sections}
            extractor = WindowExtractor(
                metered, state["product_name"], payload.doc, payload.pages,
                max_fields_per_call=self._cfg.max_fields_per_call,
            )
            for group in GROUP_ORDER:
                fields = [
                    f
                    for f in line.extractable_fields
                    if group_of_field(f.name) == group and f.field_id not in fastpath_covered
                ]
                sec_ids = payload.by_group.get(group, [])
                if not fields or not sec_ids:
                    continue
                windows = build_windows(
                    [(sid, sec_by_id[sid].fragments) for sid in sec_ids],
                    window_chars=self._cfg.window_chars,
                )
                for window in windows:
                    tasks.append(
                        asyncio.ensure_future(
                            do_window(extractor, window, fields, payload.doc, group)
                        )
                    )
        for chunk in await asyncio.gather(*tasks):
            candidates.extend(chunk)

        manifest.stats = _merge_stats(manifest.stats, stats)
        return {
            "candidates": [c.model_dump(mode="json") for c in candidates],
            "dead_letters": [d.model_dump(mode="json") for d in dead],
            "manifest": manifest.model_dump(mode="json"),
        }

    async def _node_gapfill(self, state: PipelineState) -> dict[str, Any]:
        _maybe_fail("gapfill", state)
        manifest = RunManifest.model_validate(state["manifest"])
        line = self._line(state)
        stats = CallStats()
        metered = MeteredClient(self._client, stats)
        candidates = [FieldCandidate.model_validate(c) for c in state.get("candidates") or []]
        merged = merge_candidates(candidates)
        payloads = [DocPayload.model_validate(raw) for raw in state["docs"]]
        section_pool = [(p.doc, s) for p in payloads for s in p.sections]
        pages_by_doc: dict[str, list[PageText]] = {p.doc: p.pages for p in payloads}
        sem = asyncio.Semaphore(self._cfg.concurrency)

        async def do_field(field: FieldSpec) -> FieldCandidate | None:
            async with sem:
                try:
                    cand = await with_transport_retry(
                        lambda: gapfill_field(
                            metered, state["product_name"], field, section_pool,
                            pages_by_doc, top_n=self._cfg.gapfill_top_n,
                        ),
                        attempts=self._cfg.transport_attempts,
                        base_delay_s=self._cfg.backoff_base_s,
                        sleep=self._sleep,
                    )
                except TransportRetryError:
                    return None
                return cand

        # 补漏只针对 extractable 且当前 unknown 的字段（E4.1）
        targets = [
            f
            for f in line.extractable_fields
            if (merged.get(f.field_id) is None or merged[f.field_id].tri_state == "unknown")
        ]
        results = await asyncio.gather(*(do_field(f) for f in targets))
        for cand in results:
            if cand is not None:
                candidates.append(cand)
        manifest.stats = _merge_stats(manifest.stats, stats)
        return {
            "candidates": [c.model_dump(mode="json") for c in candidates],
            "manifest": manifest.model_dump(mode="json"),
        }

    async def _node_vote(self, state: PipelineState) -> dict[str, Any]:
        _maybe_fail("vote", state)
        manifest = RunManifest.model_validate(state["manifest"])
        line = self._line(state)
        stats = CallStats()
        metered = MeteredClient(self._client, stats)
        candidates = [FieldCandidate.model_validate(c) for c in state.get("candidates") or []]
        merged = merge_candidates(candidates)
        payloads = {p.doc: p for p in (DocPayload.model_validate(r) for r in state["docs"])}
        judge_queue = list(state.get("judge_queue") or [])
        sem = asyncio.Semaphore(self._cfg.concurrency)

        async def do_vote(field: FieldSpec, cand: FieldCandidate) -> FieldCandidate:
            async with sem:
                pages = payloads[cand.doc].pages if cand.doc in payloads else []
                try:
                    return await with_transport_retry(
                        lambda: vote_field(
                            metered, state["product_name"], field, cand, pages
                        ),
                        attempts=self._cfg.transport_attempts,
                        base_delay_s=self._cfg.backoff_base_s,
                        sleep=self._sleep,
                    )
                except TransportRetryError:
                    return cand.model_copy(update={"confidence": "low"})

        # 投票只对 risk_level=high 且已有 present 候选的字段发生（E4.2/E4.3）；
        # fastpath 确定性直取字段退出投票（006 F3.4，12 #1：数字类字段退出投票）
        vote_targets = [
            (f, merged[f.field_id])
            for f in line.extractable_fields
            if f.risk_level == "high"
            and f.field_id in merged
            and merged[f.field_id].tri_state == "present"
            and merged[f.field_id].origin != "fastpath"
        ]
        voted = await asyncio.gather(*(do_vote(f, c) for f, c in vote_targets))
        for (_field, _), cand in zip(vote_targets, voted, strict=True):
            if cand.vote_agreement == 1:  # 三票三样 → 裁决（E4.2）
                context = "\n".join(e.quote for e in cand.evidence)
                req = make_judge_request(
                    state["product_id"], state["product_name"], cand,
                    "vote_disagreement", context,
                )
                judgement = await self._judge.dispatch(req)
                if judgement is None:
                    cand = cand.model_copy(update={"pending_judge": True})
                    judge_queue.append(req.model_dump(mode="json"))
                else:
                    cand = cand.model_copy(
                        update={
                            "value": judgement.value,
                            "tri_state": judgement.tri_state,
                            "evidence": judgement.evidence,
                            "confidence": judgement.confidence,
                            "origin": "judge",
                        }
                    )
            candidates.append(cand)

        # E3.2 高风险字段二次回验仍失败 → 裁决请求（不出场，但留裁决线索）
        for f in line.extractable_fields:
            cand2 = merged.get(f.field_id)
            if (
                cand2 is not None
                and f.risk_level == "high"
                and cand2.tri_state == "unknown"
                and cand2.unknown_reason == "quote_mismatch"
                and cand2.metadata.get("rejected_value") is not None
            ):
                req = make_judge_request(
                    state["product_id"], state["product_name"], cand2,
                    "quote_mismatch_high_risk", "",
                )
                judgement = await self._judge.dispatch(req)
                if judgement is None:
                    candidates.append(cand2.model_copy(update={"pending_judge": True}))
                    judge_queue.append(req.model_dump(mode="json"))

        manifest.stats = _merge_stats(manifest.stats, stats)
        return {
            "candidates": [c.model_dump(mode="json") for c in candidates],
            "judge_queue": judge_queue,
            "manifest": manifest.model_dump(mode="json"),
        }

    async def _node_finalize(self, state: PipelineState) -> dict[str, Any]:
        _maybe_fail("finalize", state)
        manifest = RunManifest.model_validate(state["manifest"])
        line = self._line(state)
        candidates = [FieldCandidate.model_validate(c) for c in state.get("candidates") or []]
        merged = merge_candidates(candidates)
        created = datetime.now(UTC)
        records: list[PredRecord] = []
        for f in line.extractable_fields:
            cand = merged.get(f.field_id)
            if cand is None:
                cand = FieldCandidate(
                    field_id=f.field_id, field_name=f.name,
                    group=group_of_field(f.name), doc="", tri_state="unknown",
                )
            records.append(_to_pred(cand, state, self._model_id, manifest, created))

        manifest.dead_letters = [
            DeadLetter.model_validate(d) for d in state.get("dead_letters") or []
        ]
        manifest.pending_judge_count = sum(1 for r in records if r.pending_judge)
        manifest.finished_at = datetime.now(UTC)
        if manifest.started_at is not None:
            manifest.duration_s = (manifest.finished_at - manifest.started_at).total_seconds()

        run_dir = Path(state["run_dir"])
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "pred.jsonl").write_text(
            "".join(r.model_dump_json() + "\n" for r in records), encoding="utf-8"
        )
        (run_dir / "manifest.json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )
        # 裁决队列以 state 为准（resume 后 dispatcher 内存队列会丢）
        write_judge_queue(
            run_dir / "judge-queue.jsonl",
            [JudgeRequest.model_validate(j) for j in state.get("judge_queue") or []],
        )
        (run_dir / "dead-letters.jsonl").write_text(
            "".join(d.model_dump_json() + "\n" for d in manifest.dead_letters),
            encoding="utf-8",
        )
        return {"manifest": manifest.model_dump(mode="json")}

    # --- 编排 ---

    def _build(self, checkpointer: AsyncSqliteSaver) -> Any:
        g: StateGraph[PipelineState] = StateGraph(PipelineState)
        g.add_node("load", self._node_load)
        g.add_node("split_route", self._node_split_route)
        g.add_node("extract", self._node_extract)
        g.add_node("gapfill", self._node_gapfill)
        g.add_node("vote", self._node_vote)
        g.add_node("finalize", self._node_finalize)
        g.add_edge(START, "load")
        g.add_edge("load", "split_route")
        g.add_edge("split_route", "extract")
        g.add_edge("extract", "gapfill")
        g.add_edge("gapfill", "vote")
        g.add_edge("vote", "finalize")
        g.add_edge("finalize", END)
        return g.compile(checkpointer=checkpointer)

    async def run(
        self,
        product_dir: Path,
        run_dir: Path,
        line_key: str | None = None,
        thread_id: str | None = None,
        checkpoint_path: Path | None = None,
        resume: bool = False,
        fail_nodes: list[str] | None = None,
        state_patch: dict[str, Any] | None = None,
    ) -> RunResult:
        """执行（或续跑）一个产品的抽取 run；checkpoint 落 SQLite（E1.1）。"""
        run_dir.mkdir(parents=True, exist_ok=True)
        ckpt = checkpoint_path or (run_dir / "checkpoint.sqlite")
        tid = thread_id or product_dir.name
        async with aiosqlite.connect(str(ckpt)) as conn:
            saver = AsyncSqliteSaver(conn)
            app = self._build(saver)
            config = {"configurable": {"thread_id": tid}}
            if state_patch:
                await app.aupdate_state(config, state_patch)
            initial: PipelineState | None
            if resume:
                initial = None
            else:
                initial = {
                    "product_dir": str(product_dir),
                    "run_dir": str(run_dir),
                    "run_id": tid,
                    "fail_nodes": fail_nodes or [],
                }
                if line_key:
                    initial["line_key"] = line_key
            out = cast(PipelineState, await app.ainvoke(initial, config=config))
        manifest = RunManifest.model_validate(out["manifest"])
        pred_path = run_dir / "pred.jsonl"
        records = [
            PredRecord.model_validate_json(line)
            for line in pred_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return RunResult(
            manifest=manifest,
            records=records,
            pred_path=pred_path,
            manifest_path=run_dir / "manifest.json",
            judge_queue_path=run_dir / "judge-queue.jsonl",
        )


def _merge_stats(a: CallStats, b: CallStats) -> CallStats:
    return CallStats(
        calls=a.calls + b.calls,
        prompt_chars=a.prompt_chars + b.prompt_chars,
        completion_chars=a.completion_chars + b.completion_chars,
    )


def _to_pred(
    cand: FieldCandidate,
    state: PipelineState,
    model_id: str,
    manifest: RunManifest,
    created: datetime,
) -> PredRecord:
    # 置信度分级（04 Step 7 简化版）：quote 回验通过+投票一致=high；补漏=medium；其余 low
    confidence = cand.confidence
    if cand.origin == "extract" and cand.tri_state in ("present", "absent_explicitly"):
        confidence = "high"  # 出场即已通过回验（校验链保证）
    # 006 F3.5（12 #2）：来源可信度分级——fastpath 由锚点类型决定，其余为模型抽取
    dq_raw = cand.metadata.get("data_quality")
    data_quality: DataQuality = (
        cast(DataQuality, dq_raw)
        if dq_raw in ("structured_direct", "table_parsed", "llm_extracted", "llm_inferred")
        else "llm_extracted"
    )
    return PredRecord(
        data_quality=data_quality,
        product_id=state["product_id"],
        product_name=state["product_name"],
        doc=cand.doc or "-",
        field_id=cand.field_id,
        field_name=cand.field_name,
        value=cand.value,
        tri_state=cand.tri_state,
        evidence=cand.evidence,
        annotator_model=model_id,
        schema_version=manifest.schema_version,
        created_at=created,
        confidence=confidence,
        pending_judge=cand.pending_judge,
        unknown_reason=cand.unknown_reason,
    )
