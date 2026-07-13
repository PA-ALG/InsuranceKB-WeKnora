# T8 交接文档：gs-v0.1 金标标注（进行到 11/13，已搁置待接手）

> 写给零上下文的新会话/其他模型。背景：金标标注消耗 token 过大，业务方决定搁置，由其他模型接手完成。**现场已全部固化在 `dataset/goldenset/wip-gs-v0.1/`，本文按步骤执行即可完成 T8。**

## 一、任务是什么

对 `dataset/shouxian_product/` 的 13 个产品，按 schema（v1.1+b31a411c621c）逐字段产出金标标注（最强模型直读文档），最后打包成不可变 release `dataset/goldenset/gs-v0.1/`。规则与格式详见同目录 `annotation-runbook.md` 与 `specs/goldenset.md`；设计背景见 `docs/insurance-kb/05-golden-set-eval.md`。

## 二、已完成（保持现状，不要重做）

`dataset/goldenset/wip-gs-v0.1/<产品名>/` 下已有 **11 个产品的 golden.jsonl**（agent 标注原始输出）+ 每产品 `fields.json`（字段工单）+ `manifest.json`（工单清单）+ `assemble_release.py`（汇总管线脚本）。

dry-run 验证结论（2026-07-12）：11 份全部结构合规，程序化引文回验 disputed 率 3%~5%（≤5% 阈值，无需退回重标）；报告里的 `missing_fields`（7~11 个/产品）是 **extractable=false 的字段，本就不在文档标注范围**，属预期而非缺漏。

## 三、待完成（两个产品 + 打包）

**缺标注的 2 个产品**：`平安爱满分（2026）两全保险`（endowment，61 字段）、`平安附加（2026）意外伤害保险`（accident，55 字段）。

### 步骤 1：重新生成这两个产品的分页文本（page texts 未入库，可再生）

```bash
cd harness && uv run python - << 'EOF'
from pathlib import Path
from insurance_harness.goldenset.pdf import extract_pages
ROOT = Path('..').resolve()
for name in ['平安爱满分（2026）两全保险', '平安附加（2026）意外伤害保险']:
    src = ROOT/'dataset/shouxian_product'/name
    out = ROOT/'dataset/goldenset/wip-gs-v0.1'/name
    for pdf in sorted(src.glob('*.pdf')):
        pages = extract_pages(pdf)
        txt = '\n'.join(f'===== 第{p.page_no}页 =====\n{p.text}' for p in pages)
        (out/(pdf.stem + '.pages.txt')).write_text(txt)
        print(name, pdf.name, len(pages))
EOF
```

### 步骤 2：标注（每产品一个标注任务，用可用的最强模型）

输入：该产品目录下 `fields.json`（字段清单）+ 三个 `*.pages.txt`。输出：同目录 `golden.jsonl`，每字段一行：

```json
{"field_id":"…","field_name":"…","doc":"保险条款.pdf|产品说明书.pdf|费率表.pdf","value":"…或null","tri_state":"present|absent_explicitly|unknown","evidence":[{"page":N,"quote":"逐字摘录"}],"reasoning":"一句话"}
```

标注铁律（必须原样传达给标注模型）：
1. 只依据文档内容，禁止用保险常识补值；
2. quote 必须与原文逐字一致（程序会做字符串回验），present 至少 1 条 evidence，quote ≤120 字；
3. doc = 证据所在文档；多文档支持时优先 保险条款 > 产品说明书 > 费率表；
4. 三态：明确写了值=present；明确"无/不含/不承担"=absent_explicitly（也要给 quote）；通篇无线索=unknown（value=null，evidence=[]）；
5. "未明确/详见条款"等占位语不算值；
6. **"文档没写"≠"没有"**——这是三态设计的核心，宁 unknown 勿妄断。

### 步骤 3：汇总打包

```bash
cd harness
# 先把 assemble_release.py 里的 WORK 路径改为 ../dataset/goldenset/wip-gs-v0.1（脚本原写的是旧会话 scratchpad 路径）
uv run python ../dataset/goldenset/wip-gs-v0.1/assemble_release.py --dry-run   # 看 13 产品 disputed 率
# 任一产品 disputed_rate > 0.05 → 按失败明细退回该产品重标
uv run python ../dataset/goldenset/wip-gs-v0.1/assemble_release.py            # 正式写 dataset/goldenset/gs-v0.1/
# 自洽性检查（金标 vs 金标应满分）：
uv run python -m insurance_harness.goldenset.eval --golden ../dataset/goldenset/gs-v0.1 --pred <由金标转的pred.jsonl> --report /tmp/self.md
```

### 步骤 4：收尾

- 勾掉 `tasks.md` 的 T8/T9；更新根目录 `HANDOFF.md`；
- release 后 `wip-gs-v0.1/` 可保留为工作底稿（含 agent 原始输出，便于追溯）；
- git 提交（分支 `feature/insurance-kb-foundation`，注意：**push 需等 GitHub 账号写权限，当前只能本地提交**）。

## 四、已知坑

- 汇总脚本的 `ANNOTATOR` 常量记录标注模型名——接手模型不同时改成实际模型标识，混合标注就 per-record 记；
- `平安福满分…养老年金保险` 的 meta 是 `product_meta.txt`（内容仍是 JSON），`load_product_meta` 已兼容；
- 分红型 vs 传统型："有分红"字段在传统型产品文档中通常无"无分红"明示，正确标法是 unknown（已有 11 份中如此处理，保持一致）；
- 本机 shell 有代理环境变量，HTTP 客户端一律 `trust_env=False`（详见根 HANDOFF 坑清单）。
