# S6c · 原生 Wiki 页面进入发布版本：模型整理的阅读材料，按产品挂接，出处逐字定位

> 状态：用户 2026-10-19 选方向 A，2026-10-20 批准试点（"批准 S6c 试点"）｜ 作者：Claude Code ｜ Issue #253
> 实现方：Claude（Harness）｜ 审核方：Codex（新合同与新模块）｜ 真实模型调用：0（页面已由 #253 的发现库生成）
> 后续：S6d 展示（导航中的"延伸阅读（模型整理）"、页面视图、问答读取页面）

## 1. 目标

把原生 Wiki 在"发现库"里自由整理出的页面，作为 `wiki_page` 成员放进企业 Space 的发布版本：

- **定位**：页面是模型整理的阅读材料，标 `MODEL_GENERATED`，阅读时显示"模型整理，未逐条审核"；产品事实仍以字段（Claim）为准。
- **范围**：每个页面挂到一个产品（`entity_refs`）上；一个发现库只放一个产品的材料。
- **出处**：在 Space 原始材料的页文本中逐字定位，能定位的才作为出处，平台提交时会再逐字回验；定位不到的不猜，直接丢弃。
- **版本**：页面与字段在同一个版本中发布；人与 Agent 读到的都是这个版本。

不做：

- 不改 Go 平台：成员 `kind` 本来就是通用字符串，出处固定沿用现有机制；
- 不改原生 Wiki 的生成；
- 不把页面内容拆成字段；
- 不做页面审核分数。

## 2. 合同：`WikiPage`（`contracts/knowledge.py`，导出 `contracts/wiki_page.schema.json`）

```python
class WikiPage(ContractModel):
    page_key: NonBlank            # 原生页面 slug，如 "concept/bao-xian-fei"
    entity_refs: list[NonBlank]   # 至少 1 个产品 entity_id
    title: NonBlank
    page_type: Literal["concept", "entity"]
    summary: str = ""
    content: NonBlank             # Markdown；页面间链接已改写（§3.2）
    aliases: list[NonBlank] = []
    evidence: list[Evidence] = [] # 至多 3 条
    origin: Literal["MODEL_GENERATED"]
    generator: NonBlank           # 固定 "weknora-native-wiki"
    model: NonBlank               # 生成所用模型名
```

- 不允许多余字段，沿用 `ContractModel` 的约定。
- 成员 `logical_slug` 为 `wiki/<entity_id>/<page_key>`，`access_scope` 为 `space`。
- 成员的 `evidence_refs` 取各条出处的 `source_ref`，平台据此固定来源。

## 3. 转换（新包 `harness/src/insurance_harness/compilers/wiki_pages/`）

### 3.1 输入：`NativePage`

发现库原生页面的只读快照：

- 字段：`slug`、`title`、`page_type`、`summary`、`content`、`aliases`；
- `chunks`：所引分块，按原顺序排列，每块含 `content`。

### 3.2 `wiki_page(page, *, entity_id, titles, source, sources, model) -> WikiPage | None`

- **跳过**：`page_type` 不是 `concept` 或 `entity` 的页面（如 `summary`、`index`），返回 None。
- **链接改写**：`titles` 是本次导出的全部 `page_key → title`。
  - `[[key|文字]]`、`[[key]]`：`key` 在 `titles` 中时，改写为 `[[wiki/<entity_id>/<key>|文字]]`；没有文字时用 `titles[key]`；
  - `key` 不在 `titles` 中时，只保留文字；没有文字时，保留 `key` 最后一段。
- **出处**：
  - 按分块顺序，在 `source`（该产品原始材料的 `SegmentedSource`）中找规范化后**整段包含在分块文本里**的分段：去空白、NFKC；分段至少 8 个字。
  - 每块取它包含的第一个尚未使用的分段，生成 `Evidence`：`PDF_TEXT_SPAN` 加页码与起止位置、`source_ref`、`file_sha256`、`quote`。生成方式与字段出处相同（`claims.py` 的做法）。
  - 全页最多 3 条；找不到就没有出处，页面照常导出。
- 其他字段照搬；`origin` 固定为 `MODEL_GENERATED`，`generator` 固定为 `weknora-native-wiki`。

### 3.3 发布命令

```
python -m insurance_harness.compilers.wiki_pages.publish \
    --discovery-kb KB --product P --entity-id E --source-map F \
    --model M --decide human --reason TEXT --activate
```

- **读取**：经 WeKnora 版本化 REST 读取发现库的页面与分块（`/knowledgebase/<kb>/wiki/pages`、`/chunks/by-id/<id>`）。发现库是不受管库，不经过 S1b 的拦截；读取用 `HARNESS_WEKNORA_API_KEY`。
- **出处来源**：用与字段发布相同的 `load_trusted_pages`，读取该产品在 Space 原始材料中的页文本。费率表按材料角色排除。
- **候选包**：
  - 以 Active 为 base，只含 `wiki_page` 成员；
  - Active 中该产品已有、但本次没有导出的 `wiki/<E>/…` 成员，列入 `removals`；
  - 人工决定，理由由 `--reason` 写明；
  - 不调用模型。
- **输出**：一行 JSON，包含 `pages`、`with_evidence`、`evidence`、`removed`、`release_id`、`epoch`；失败时输出 `{"stopped": <code>}`，退出码 2。
- `bundle/assemble.py` 增加 `wiki_pages` 参数，`_member("wiki_page", f"wiki/{entity}/{key}", page, refs)`。

## 4. 验收（RED，Claude 编写，受保护）

- `tests/contracts/test_wiki_page.py`：
  - 最小合法页面；
  - `origin` 只能是 `MODEL_GENERATED`；
  - `entity_refs` 不能为空；
  - 出处最多 3 条；
  - `page_type` 只能是两种之一；
  - 不允许多余字段。
- `tests/compilers/wiki_pages/test_members.py`：
  - 跳过摘要页与索引页；
  - 链接改写的四种情形；
  - 出处按分块顺序取第一个未用分段、不足 8 字的分段不算、同一分段不重复、上限 3 条、找不到就为空；
  - 出处的 `source_ref` 与页码正确；
  - `assemble` 生成的成员：`kind`、`logical_slug`、`evidence_refs`。

发布命令的 REST 读取与候选包组装，由实现方用假客户端测试。

## 5. 改动范围

- `harness/src/insurance_harness/contracts/`：
  - `knowledge.py`；
  - `export.py`；
  - `__init__.py`。
- `contracts/wiki_page.schema.json`：只由导出命令生成。
- `harness/src/insurance_harness/compilers/wiki_pages/`：新增。
- `harness/src/insurance_harness/bundle/assemble.py`。
- `harness/tests/`：测试。

## 6. 试点运行（#253 预算内，0 次模型调用）

三款产品各发布一次：

| 产品 | 发现库 |
|---|---|
| 1828 | `S6A-VALIDATE-1828` |
| 平安盛世金越（尊享版26）终身寿险 | `C2-1824` |
| 2650 | `S6C-DISCOVERY-2650-20261020` |

发布后，核对以下各项并记入 #253：

- 成员数；
- 出处定位率（有出处的页面比例）；
- 平台回验通过；
- 除 `wiki_page` 以外的其他成员摘要不变。
