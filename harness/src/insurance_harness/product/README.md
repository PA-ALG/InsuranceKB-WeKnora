# product — 产品主数据、文档分类与路由（change 003）

解决 01 §2#1"多产品文档实体对齐"：一切事实归属先过产品主数据。

- `meta.py`：product_meta.json/.txt 解析（planCode→product_code 等对照见 db/models.py 注释）
- `aliases.py`：确定性别名生成（去括号/去"平安"前缀/剥险种后缀）
- `register.py`：`register_products()` 幂等注册产品/版本/文档/别名（spec P2）
- `classify.py`：文档类型分类（确定性特征优先，LLM 仅兜底，spec P3）
- `routing.py`：产品路由（exact/alias 自动归属；fuzzy 与别名歧义一律进 unassigned，spec P4）
- `cli.py`：`register-products` / `classify`（自动评分报告）

关联文档：docs/insurance-kb/03 §2.2/§8（表结构权威）、04 §7（与抽取管道的衔接）。
依赖：`db/`（迁移见 harness/migrations）、`schemas/`（险种 line_key）。
