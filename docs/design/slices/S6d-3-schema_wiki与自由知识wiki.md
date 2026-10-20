# S6d-3 · 产品导航分为 schema_wiki 与 自由知识wiki

> 状态：用户 2026-10-20 要求（"不叫这个，叫 自由知识wiki，另外上面增加大的节点，schema_wiki，把相关的节点收拢到这里面去"）｜ 作者：Claude Code
> 实现方：Codex（前端）｜ 审核方：Claude ｜ 真实模型调用：0

## 1. 目标

左侧知识导航中，每个产品展开后的内容分为两个大节点，顺序固定：

```
▾ 产品名
  ▾ schema_wiki                  ← 新的大节点，默认展开
    ▾ 合同与交费                 ← 原来的字段分组，原样收进来
        犹豫期 …
    ▾ 保障责任 …
    （没有字段时，原"暂无字段"提示也放在这里）
  ▸ 自由知识wiki  86             ← 原"延伸阅读（模型整理）"，改名
      页面 …
```

- **schema_wiki**：
  - 一个 `<details data-nav-schema open>`，摘要文字为 `schema_wiki`，5 种语言都用这个文字，不翻译；
  - 里面是原来的全部字段分组与字段链接（顺序、链接目标都不变），以及没有字段时的提示；
  - 默认展开；读者折叠后，在同一页面内保留，切换产品或版本时恢复展开。
- **自由知识wiki**：原 `[data-nav-wiki]` 分组只改名，其他行为不变（默认折叠、页数、打开某页时自动展开并标出当前页、读者的展开状态保留）。
  - zh-CN 为"自由知识wiki"；
  - 其他语言：en-US "Free knowledge wiki"，ja-JP "自由知識wiki"，ko-KR "자유 지식 wiki"，ru-RU "Свободная вики знаний"。
- 产品没有 Wiki 页面时只有 schema_wiki 一个节点。
- 字段内容容器保留 `class="ek-nav-fields"`，两个大节点都是它的直接子元素，顺序为先 schema_wiki、后自由知识wiki。
- 页面上的"模型整理，未逐条审核"标签和对话中的来源标签"模型整理（未逐条审核）"不改。它们说明内容的来源性质，与导航分组的名字无关。

## 2. 验收（RED，Claude 编写，受保护）

- 新增 `frontend/src/enterprise/navigationSchemaWiki.spec.ts`：
  - 两个大节点的顺序与文字；
  - schema_wiki 默认展开，并且包含全部字段分组；
  - 自由知识wiki 带页数、默认折叠；
  - 没有 Wiki 页面的产品只有 schema_wiki。
- 修改 S6d 的受保护测试 `frontend/src/enterprise/navigationWiki.spec.ts`：期望文字从"延伸阅读（模型整理）"改为"自由知识wiki"（用户改名），其他断言不变。
- 实现方另补：schema_wiki 的折叠状态保留与恢复。

## 3. 改动范围

- `frontend/src/enterprise/NavigationEntry.vue`、`enterpriseNavigation.css`；
- 语言包 5 种（已登记的上游文件，修改已有键并新增 1 个键）；
- 实现方测试。
