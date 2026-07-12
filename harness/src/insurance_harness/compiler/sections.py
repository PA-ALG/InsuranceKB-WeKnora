"""章节切分（保页码映射）+ 组路由 + 文档族结构指纹（004 T3；spec E2；11 §1.1）。

- 切分是确定性的：按标题层级/条款序号切 section，目标 4~6K 字/段
  （04 Step 2；LLM-wiki-black v2.3 教训：25K→6K 后稳定性显著提升）；
- 每个 section 保留 (page_no, text) 片段列表——Claim 证据要落页码（E2.1）；
- 组路由用 routing_data.GROUP_KEYWORDS 过滤：无关章节不进该组 LLM 调用（E2.2）；
- 文档族指纹 = 章节标题序列结构 hash（11 §1.1 低成本 enabler），入 run manifest，
  供 validation-report 按族分组出分、为 006 模板归纳指路。
"""

import hashlib
import re
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from ..goldenset.pdf import PageText
from .routing_data import GROUP_KEYWORDS, GROUP_ORDER

_HEADING_RES: tuple[re.Pattern[str], ...] = (
    # 第X章 / 第X节 / 第X条 / 第X部分（中文或阿拉伯序号）
    re.compile(r"^\s*第\s*[零一二三四五六七八九十百千0-9１-９]+\s*(?:章|节|条|部分)"),
    # 一、 二、 …（顶层中文序号）
    re.compile(r"^\s*[一二三四五六七八九十]+\s*[、．]"),
    # 1. / 2.3 之类多级编号标题（行短才算标题，见 _is_heading）
    re.compile(r"^\s*\d+(?:\.\d+)+\s+\S"),
)

_MAX_HEADING_LEN = 40  # 过长的行更可能是正文而非标题
# 路由粒度默认取原子章节（条级，不合并）：13 份样本条款上标定压缩比 ≤40%（E2.2）；
# LLM 调用的上下文预算由 build_windows(4K) 二次合并保证（04 的 4~6K 稳定性经验）
_DEFAULT_TARGET_CHARS = 2_000
_DEFAULT_MIN_CHARS = 0


class DocSection(BaseModel):
    """文档章节：路由与抽取单元；fragments 保留页码映射（E2.1）。"""

    model_config = ConfigDict(frozen=True)

    section_id: str
    title: str
    headings: tuple[str, ...]  # 本节包含的全部原子标题（族指纹用）
    fragments: tuple[PageText, ...]  # (page_no, 该页归属本节的文本片段)

    @property
    def text(self) -> str:
        return "\n".join(f.text for f in self.fragments)

    @property
    def char_count(self) -> int:
        return sum(len(f.text) for f in self.fragments)

    @property
    def page_first(self) -> int:
        return min(f.page_no for f in self.fragments)

    @property
    def page_last(self) -> int:
        return max(f.page_no for f in self.fragments)


def _is_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > _MAX_HEADING_LEN:
        return False
    return any(p.match(stripped) for p in _HEADING_RES)


class _Block(BaseModel):
    title: str
    headings: list[str]
    fragments: list[PageText]

    @property
    def size(self) -> int:
        return sum(len(f.text) for f in self.fragments)


def _atomic_blocks(pages: Sequence[PageText]) -> list[_Block]:
    blocks: list[_Block] = []
    current = _Block(title="(前言)", headings=[], fragments=[])

    def flush() -> None:
        nonlocal current
        if current.fragments and current.size > 0:
            blocks.append(current)
        current = _Block(title="", headings=[], fragments=[])

    for page in pages:
        buf: list[str] = []
        for line in page.text.splitlines():
            if _is_heading(line):
                if buf:
                    current.fragments.append(
                        PageText(page_no=page.page_no, text="\n".join(buf))
                    )
                    buf = []
                flush()
                title = line.strip()
                current.title = title
                current.headings.append(title)
            buf.append(line)
        if buf:
            current.fragments.append(PageText(page_no=page.page_no, text="\n".join(buf)))
    flush()
    return blocks


def split_sections(
    pages: Sequence[PageText],
    target_chars: int = _DEFAULT_TARGET_CHARS,
    min_chars: int = _DEFAULT_MIN_CHARS,
) -> list[DocSection]:
    """确定性章节切分：按标题切原子块，再贪心合并到目标 4~6K 字/段（04 Step 2）。

    页码映射始终保留：合并/超长切片都以 (page_no, fragment) 为单位（E2.1）。
    """
    blocks = _atomic_blocks(pages)
    if not blocks:
        return []

    sections: list[DocSection] = []
    acc: _Block | None = None

    def emit(block: _Block) -> None:
        sections.append(
            DocSection(
                section_id=f"s{len(sections) + 1:03d}",
                title=block.title or "(前言)",
                headings=tuple(block.headings),
                fragments=tuple(block.fragments),
            )
        )

    for block in blocks:
        # 单块超长：按页片段硬切，绝不产出超预算大段
        if block.size > target_chars:
            if acc is not None:
                emit(acc)
                acc = None
            for piece in _split_oversized(block, target_chars):
                emit(piece)
            continue
        if acc is None:
            acc = block.model_copy(deep=True)
        elif acc.size < min_chars and acc.size + block.size <= target_chars:
            acc.headings.extend(block.headings)
            acc.fragments.extend(block.fragments)
        else:
            emit(acc)
            acc = block.model_copy(deep=True)
    if acc is not None:
        emit(acc)
    return sections


def _split_oversized(block: _Block, target_chars: int) -> list[_Block]:
    pieces: list[_Block] = []
    current = _Block(title=block.title, headings=list(block.headings), fragments=[])
    for frag in block.fragments:
        text = frag.text
        while text:
            room = target_chars - current.size
            if room <= 0:
                pieces.append(current)
                current = _Block(title=f"{block.title}(续)", headings=[], fragments=[])
                room = target_chars
            take = text[:room]
            current.fragments.append(PageText(page_no=frag.page_no, text=take))
            text = text[room:]
    if current.fragments:
        pieces.append(current)
    return pieces


# --- 组路由（E2.2） ---


class RoutingResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    by_group: dict[str, tuple[str, ...]]  # group -> 命中 section_id 序列
    routed_pairs: int
    total_pairs: int

    @property
    def compression_ratio(self) -> float:
        """路由后 (组×章节) 调用组合占全量组合的比例；E2.2 要求 ≤ 0.40。"""
        return self.routed_pairs / self.total_pairs if self.total_pairs else 0.0


def route_groups(
    sections: Sequence[DocSection],
    min_hits: int = 4,
    per_chars: int = 400,
    distinct_min: int = 3,
    keywords: dict[str, re.Pattern[str] | None] | None = None,
) -> RoutingResult:
    """7 组 × GROUP_KEYWORDS 关键词路由：无关章节不进该组 LLM 调用（E2.2）。

    命中判定用密度阈值而非单次命中（源资产是 chunk 级过滤；本管道章节更大，
    单关键词误命中率高）：总命中 ≥ max(min_hits, 字数/per_chars) 且不同关键词
    ≥ distinct_min。参数在 13 份样本条款上标定（压缩比 ≤40%，validation-report）。

    ``keywords`` 可注入其他版本的组关键词（005 V6.1：归因工具复算修复前路由）。
    """
    kw = keywords if keywords is not None else GROUP_KEYWORDS
    by_group: dict[str, tuple[str, ...]] = {}
    routed = 0
    for group in GROUP_ORDER:
        pattern = kw[group]
        if pattern is None:  # coverage：扫描全部章节
            hit_ids = tuple(s.section_id for s in sections)
        else:
            hit_ids = tuple(
                s.section_id
                for s in sections
                if _dense_enough(pattern, s, min_hits, per_chars, distinct_min)
            )
        by_group[group] = hit_ids
        routed += len(hit_ids)
    return RoutingResult(
        by_group=by_group,
        routed_pairs=routed,
        total_pairs=len(GROUP_ORDER) * len(sections),
    )


def _dense_enough(
    pattern: re.Pattern[str],
    section: DocSection,
    min_hits: int,
    per_chars: int,
    distinct_min: int,
) -> bool:
    hits = pattern.findall(section.text)
    need = max(min_hits, section.char_count // per_chars)
    return len(hits) >= need and len(set(hits)) >= distinct_min


# --- 文档族结构指纹（11 §1.1；006 F6 无标题 fallback） ---

_DIGITS_WS_RE = re.compile(r"[\s0-9０-９]+")

# 文档类型特征（fallback 指纹用；顺序即优先级：先匹配更具体的）
_DOC_TYPE_RE = re.compile(r"(产品说明书|利益演示|投保须知|保险条款|费率表|说明书|条款)")
_CJK_RE = re.compile(r"[一-鿿]")
# 页数桶：同族文档页数近似（费率表 2 页、说明书 7~10 页、条款几十页），
# 精确页数会把同版式不同排版密度的文档拆散，取对数级桶
_PAGE_BUCKETS: tuple[tuple[int, str], ...] = ((2, "xs"), (16, "s"), (40, "m"))


def _page_bucket(page_count: int) -> str:
    for limit, name in _PAGE_BUCKETS:
        if page_count <= limit:
            return name
    return "l"


def _header_tokens(page_texts: Sequence[str]) -> list[str]:
    """表头 token 集合（fallback 指纹特征之一，F6.2 "表格列名"）。

    表头行启发式：≥3 个空白分隔 token 且 ≥80% 为短 token（≤6 字）——
    费率表列名行（"趸交 3年 6年 …"）命中，正文长句不命中。
    token 归一化去数字（"3年"→"年"），只保留含中文的短 token。
    """
    tokens: set[str] = set()
    for text in page_texts:
        for line in text.splitlines():
            parts = line.split()
            if len(parts) < 3 or sum(1 for p in parts if len(p) <= 6) < 0.8 * len(parts):
                continue
            for part in parts:
                norm = _DIGITS_WS_RE.sub("", part)
                if norm and len(norm) <= 6 and _CJK_RE.search(norm):
                    tokens.add(norm)
    return sorted(tokens)


def _fallback_fingerprint(sections: Sequence[DocSection]) -> str:
    """无标题文档的 fallback 指纹（006 F6.2）。

    004 疑点修复：章节标题序列为空时旧算法退化为空串哈希 fam-e3b0c44298fc，
    说明书/费率表全部混为一族。fallback 用 文档类型特征 + 页数桶 + 表头 token
    集合 哈希，保证无标题文档按版式分族且与空串指纹必不相同。
    """
    by_page: dict[int, list[str]] = {}
    for sec in sections:
        for frag in sec.fragments:
            by_page.setdefault(frag.page_no, []).append(frag.text)
    page_nos = sorted(by_page)
    page_texts = ["\n".join(by_page[p]) for p in page_nos]
    first_page = _DIGITS_WS_RE.sub("", page_texts[0]) if page_texts else ""
    m = _DOC_TYPE_RE.search(first_page)
    doc_type = m.group(1) if m else "unknown"
    payload = "\x01".join(
        ["fallback", doc_type, _page_bucket(len(page_nos)), *_header_tokens(page_texts)]
    )
    return "fam-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def family_fingerprint(sections: Sequence[DocSection]) -> str:
    """章节标题序列 → 结构指纹：同版式文档（族）得到相同 family_id。

    归一化去掉空白与数字（同模板不同序号/年份不影响族归属），哈希取前 12 位。
    标题序列非空时算法与 004 完全一致（既有族 id 不漂移）；为空时走
    fallback（F6.2：文档类型 + 页数桶 + 表头 token），修复空串指纹退化。
    """
    titles = [h for s in sections for h in s.headings]
    if not titles:
        return _fallback_fingerprint(sections)
    normalized = "\x00".join(_DIGITS_WS_RE.sub("", t) for t in titles)
    return "fam-" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
