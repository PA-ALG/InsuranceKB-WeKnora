# 052 · Validation report

## Candidate identity

- authoritative base: `ad99ca9a3e658e7d0fd768164f7aab247fe92933`
- local `origin/main`: `ad99ca9a3e658e7d0fd768164f7aab247fe92933`
- PR #80 head before this correction:
  `46b7e6b16e2bf2afb7ce1e450d63cca81e849951`
- branch: `codex/052-material-profile-template-binding`
- state: `PR #80 DRAFT / KCA4 CORRECTION VERIFIED LOCALLY / UNCOMMITTED`
- candidate tree: 由最终只读 owner handoff 记录 exact Git tree；不在本制品
  内自嵌，避免递归改变自身 identity

## RED / GREEN evidence

- focused RED 1：能力存在性用例 `1 failed in 0.08s`，失败为
  `OpenSpec 052 MaterialProfile binding is missing`。
- focused RED 2：完整验收用例 `15 failed in 0.26s`，15 项全部在同一
  缺失能力断言处失败；未调用 template、Golden、provider 或外部系统。
- minimal GREEN：只新增 `material_profiles.py` 后，focused
  `15 passed in 0.38s`；最终 fresh 复验见 Gates。
- KCA4 correction RED 1：缺 approved parse policy 时，原实现错误接受 catalog；
  focused 为 `1 failed in 0.20s`，失败点是 `DID NOT RAISE`。只加入必填门后
  `1 passed in 0.11s`。
- KCA4 correction RED 2：在 parser-neutral fixture 上先加第三次 attempt、upgrade
  无 trigger、缺 privacy/output refs、多值/链式 parser profile、limit 不一致、
  owning profile identity 与 receipt/C0 覆盖用例；得到
  `12 failed, 16 passed in 2.08s`。
- KCA4 minimal GREEN：加入 frozen `ApprovedParsePolicy`、singular bounded path 与
  `ParsePolicyReceipt` 后，首轮 `28 passed in 0.80s`。

## Gates

- focused tests: `29 passed in 1.24s`（含 explicit no-upgrade / one-attempt
  正向用例）
- relevant regressions: `142 passed`；其中 TemplatePackage 028、ProductVersion 041
  与 Schema loader 串行为 `135 passed in 72.78s`，frozen Golden 049 单独串行为
  `7 passed in 189.39s`
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
  `32651266dcef2c6597b35911906b3d64408bc9c0cabe2db52472f836d519d019`
- full/fallback receipts: 既有 4-level chain 和缺 product-family 时的 exact
  3-level broader chain 均由未修改的 resolver 生成，薄层只记录 missing layer
- parse policy receipt: 三个 profile 均冻结 exact versioned parser-neutral default、
  singular bounded upgrade、四类 mechanical triggers、attempt limit `2`、required
  capabilities 与 versioned privacy/output policy refs；完整进入 catalog/binding C0

## Review classification

- `BLOCKER`: `0`
- `BACKLOG`: `0` within 052；053 仍负责 parsed-artifact/quality decision，但所需
  default/upgrade/trigger/policy authorization 已在 052 显式冻结
- `MAINLINE DRIFT`: `NONE`；本 correction 基于 PR #80 head `46b7e6b1…`，local
  `origin/main` 仍为 authoritative base `ad99ca9a…`
- `DETAIL TRAP`: 052 只冻结 fixture catalog/binding；Golden hash 不是答案输入或
  source authority，parse policy 也不是 parser winner 或三 PDF parsed admission；
  052 不执行 attempt/ESCALATE，fallback receipt 也不授予缺失 product-family
  template 以外的猜测权

本报告只能在 fresh 命令完成后更新；不得将 fixture 或单测通过
写成 ParsedDocument admission、S0-Q PASS、Golden 变更、Release ready 或生产完成。
