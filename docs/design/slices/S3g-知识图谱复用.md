# S3g · 关系图：企业知识里的产品—概念关系图（方案 ③）

> 状态：用户 2026-10-18 改选方案 ③（"改用 ③ 自己做"）。方案 ① 经 Codex 评审（#232）发现版本混读、投影失效、需仿造 7 个原生接口格式、不改 WikiBrowser 就无法完善错误处理，已放弃 ｜ 作者：Claude Code
> 实现方：Codex（前端）；审核方：Claude
> 画法参照：`frontend/src/views/knowledge/wiki/WikiBrowser.vue` 中的 SVG 力导向图（WeKnora，MIT 许可）。可以复制并改写到 `frontend/src/enterprise/`，文件头注明出处；原文件不改。

## 1. 目标

- 在企业知识空间里提供"关系图"：产品与概念之间的关系一目了然，点节点可直达产品页或概念页。
- 与产品页、概念页读**同一个固定的发布版本**（`?release=`），不读原生 Wiki、不放开受管库限制，也不需要后端和 Harness 改动。

## 2. 设计

### 2.1 数据（纯函数 `frontend/src/enterprise/graphView.ts`）

`relationGraph(release): { nodes: GraphNode[]; edges: GraphEdge[] }`：

- **产品节点** `{ id: 'entity:<entity_id>', kind: 'product', title: 产品名, group: 导航分组键, groupTitle: 分组名 }`：
  - 产品取 `entity_type` 属于产品域的条目，分组规则同 `navigationTree`；
  - 没有导航成员时，`group` 为空。
- **概念节点** `{ id: 'concept:<field_key>', kind: 'concept', title: 概念标题 }`：
  - 概念集合与顺序同 `conceptKeys`；
  - 标题取 concept 成员的 `title`，没有时用 profile 中的字段标题。
- **连线** `{ source: 产品节点, target: 概念节点 }`：该产品对该字段的 Claim 为 present 或 absent_explicitly。
- 每个节点带 `degree`（连线数），用于决定节点大小。
- 只读 Release 内容，不发请求；结果按产品、概念的固定顺序排列，相同 Release 得到相同结果。

### 2.2 页面（`frontend/src/enterprise/EnterpriseGraph.vue`，路由 `enterpriseGraph`：`enterprise/:spaceId/graph`，query `release`）

- 读取 Release：有 `release` 参数就读该版本，否则读 Active。页面内所有跳转都带读到的那个 Release id。
- **画布**：
  - SVG 力导向布局，产品与概念用两种形状或颜色区分，产品按导航分组着色（使用 TDesign 主题变量，深色模式可用）；
  - 支持拖拽节点、滚轮缩放、拖动画布；
  - 悬停一个节点时，高亮它和它的邻居，其余变淡；
  - 节点标签在缩放较小时只显示连线多的节点，避免重叠。
- **侧边详情**：点击节点后在右侧显示：
  - 产品：产品名、险种、相关概念数，以及按钮"打开产品页"（`enterpriseEntity`，带 `release`）；
  - 概念：标题、定义（有 concept 成员时标"模型补充"）、涉及产品数，以及按钮"打开概念页"（`enterpriseConcept`，带 `release`）。
- **工具栏**：
  - 搜索框：按名称定位并选中节点；
  - 险种筛选：勾选哪些分组的产品参与绘制，概念只保留与可见产品相连的；
  - "适应画布"按钮；
  - 开关"显示全部概念"：默认关闭。关闭时，被当前可见的全部产品都陈述的概念不画（这类概念区分不了产品，真实数据中有 16 个，贡献约一半连线）；统计行写明隐藏了多少个。搜索或定位到被隐藏的概念时，自动显示它。（2026-10-18 审核 PR #237 时补充）
- **状态**：
  - 加载中：`role="status"`；
  - Release 不存在：显示空状态"该空间还没有发布版本"；
  - 读取失败：`role="alert"` 并带重试按钮；
  - 没有产品：显示"该版本中还没有条目"。
- **可访问性**：节点可聚焦，按 Enter 打开侧边详情；侧边详情可关闭，焦点返回原节点。
- **入口**：空间页增加"关系图"链接 `{ name: 'enterpriseGraph', params: { spaceId }, query: { release } }`。

## 3. 验收（RED，Claude 编写，受保护）

- `graphView.spec.ts`：
  - 节点与连线规则（present 与 absent_explicitly 连线，unknown 不连）；
  - 分组；
  - 概念集合与 `conceptKeys` 一致；
  - degree；
  - 结果确定。
- `enterpriseGraph.spec.ts`：
  - 按 `release` 读取并渲染节点数（`[data-graph-node]`）；
  - 点击节点打开侧边详情，跳转带同一个 Release；
  - 搜索选中节点；
  - 险种筛选减少节点；
  - 加载、无发布、失败重试、无条目四种状态；
  - 空间页入口。
- 视觉：实现方附截图，存放在仓库外。

## 4. 上线

与 S3f、S3f-2b、RV4b 一起构建 1 次 UI，届时请用户批准。
