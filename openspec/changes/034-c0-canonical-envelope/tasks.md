# 034 · Tasks

## Contract Card

1. **单一职责**：CanonicalEnvelopeV1 语言中立规范 + expected bytes/hash
   vectors + Python reference codec。**非目标**：Go/fork 改动、领域表、
   迁移、Candidate/Release、template_packages hash 迁移、宽松模式。
2. **读写权威/事务/幂等**：纯函数库，无 DB、无 I/O、无状态；幂等性即
   确定性（同值同字节）。
3. **状态机**：无。
4. **威胁矩阵**：
   - hash 注入/歧义 → 定长常量 + `0x00` 分隔 + `object_type` 字符集禁 NUL；
   - 跨语言不一致 → 禁 float、UTF-16 键序显式向量用例、NFC/控制符拒绝；
   - 静默归一化掩盖差异 → 除 tz→UTC 与 decimal 定点规范化（规范明文）外
     一律拒绝；
   - 向量漂移/循环验证 → canonical 字符串手工按规范编写，sha256 由冻结
     字符串独立计算，不经由实现生成；
   - 恶意深嵌套 → 深度 100 上限，typed 拒绝。
5. **验收测试清单**：见 spec C0.1–C0.9 全部 Scenario；向量双向完备；
   focused + Ruff + mypy strict + OpenSpec strict；PG/live lane 不适用
   （NOT RUN，无 DB 面）。
6. **路径预算**：≈13 个逻辑文件（包 5 + 向量 1 + 测试 2 + 文档 1 +
   OpenSpec 3 + 台账 1），生产代码 ≤ 650 行，无迁移。

## Tasks

- [x] T1（RED）：手工编写 `canonical_vectors_v1.json`（合法 ≥ 24、非法
  ≥ 12），sha256 用独立一次性脚本从冻结 canonical 字符串计算；写
  `test_canonical_vectors_034.py`（构造器注册表 + 双向完备断言）与
  `test_canonical_envelope_034.py`（C0.1–C0.9 单元红测）；此时包不存在，
  两个文件全 RED。
- [x] T2（GREEN）：实现 `canonical` 包（errors/values/encoder/hashing +
  向量资源打包），使 T1 全绿。
- [x] T3：文档 `docs/insurance-kb/25-canonical-envelope-v1.md`（语言中立
  规范：类型映射表、转义规则、键序、hash 框架、版本升级规则）+ README
  台账占号 034/035。
- [x] T4：门禁：focused 两文件、`ruff check`、`mypy`（strict）、
  `openspec validate 034-c0-canonical-envelope --strict`；validation-report
  记录证据与 NOT RUN 项。
- [x] T5（评审闭合）：双独立评审 4 项 Important + 5 项 Minor 全部 RED→GREEN 闭合；向量 40+19，focused 99 passed。
