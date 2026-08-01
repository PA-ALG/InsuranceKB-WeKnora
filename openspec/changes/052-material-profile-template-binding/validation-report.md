# 052 · Validation report

## Candidate identity

- authoritative base: `ad99ca9a3e658e7d0fd768164f7aab247fe92933`
- verified `origin/main`: `ad99ca9a3e658e7d0fd768164f7aab247fe92933`
- branch: `codex/052-material-profile-template-binding`
- state: `IMPLEMENTED / VERIFIED LOCALLY / UNCOMMITTED`
- candidate tree: 由最终只读 owner handoff 记录 exact Git tree；不在本制品
  内自嵌，避免递归改变自身 identity

## RED / GREEN evidence

- focused RED 1：能力存在性用例 `1 failed in 0.08s`，失败为
  `OpenSpec 052 MaterialProfile binding is missing`。
- focused RED 2：完整验收用例 `15 failed in 0.26s`，15 项全部在同一
  缺失能力断言处失败；未调用 template、Golden、provider 或外部系统。
- minimal GREEN：只新增 `material_profiles.py` 后，focused
  `15 passed in 0.38s`；最终 fresh 复验见 Gates。

## Gates

- focused tests: `15 passed in 0.36s`
- relevant regressions: `142 passed in 19.45s`，覆盖 TemplatePackage 028、
  ProductVersion 041、Schema loader 与 frozen Golden 049
- Ruff: `All checks passed!`（implementation + focused test）
- strict mypy: `Success: no issues found in 2 source files`
- OpenSpec 052 strict: `Change '052-material-profile-template-binding' is valid`
- diff/scope/private/secret: exact 8 paths，UTF-8/LF `8/8`，private/absolute-path 与
  high-signal secret 扫描零命中；all `100644` 与 temp-index tree 在最终 handoff
  记录
- provider/model/PostgreSQL/WeKnora live: `NOT RUN / OUT OF SCOPE`

## Frozen slice evidence

- Product / ProductVersion: exact `596` / `596-1`
- Schema: exact `v1.1+b31a411c621c`，medical extractable field-id 与 authority
  union 均为 60/60 exact bijection
- source identities: terms `1047811` / `88b784c…`，brochure `492101` /
  `5e2aef32…`，rate table `51961` / `7b35fa3b…`，本地 exact bytes 复算一致
- Golden identity: release `fca06f98…`，artifact `83032da0…`，approval
  `6feb2acf…`；fixture/resolver input 不包含 Golden answer path 或 records
- C0 catalog hash:
  `fb7faa3f526a13fff5a75fae04ee973b0943075c48288d1fdd177d8c9a119a5e`
- full/fallback receipts: 既有 4-level chain 和缺 product-family 时的 exact
  3-level broader chain 均由未修改的 resolver 生成，薄层只记录 missing layer

## Review classification

- `BLOCKER`: `0`
- `BACKLOG`: `0` within 052；051 中 B 的 parsed-artifact/quality contract 是下一个
  独立 Mission，不是本 PR 漏项
- `MAINLINE DRIFT`: `NONE`；最后核对时 `HEAD == origin/main == ad99ca9a…`
- `DETAIL TRAP`: 052 只冻结 fixture catalog/binding；Golden hash 不是答案输入或
  source authority，MaterialProfile 不是三 PDF parsed admission，fallback receipt 也
  不授予缺失 product-family template 以外的猜测权

本报告只能在 fresh 命令完成后更新；不得将 fixture 或单测通过
写成 ParsedDocument admission、S0-Q PASS、Golden 变更、Release ready 或生产完成。
