# 25 · CanonicalEnvelopeV1 语言中立规范

> 状态：随 OpenSpec 034 冻结（2026-07-26）。权威来源：033 生产架构重置
> 设计 §8.4。本文是跨语言唯一编码规范；Python reference codec 位于
> `harness/src/insurance_harness/canonical/`，冻结向量位于其
> `vectors/canonical_vectors_v1.json`。任何消费者（含未来 W1/P11 的 Go
> adapter）必须通过同一向量验收，不得另立规范。

## 1. 范围

所有跨语言、跨进程、长期保存的 identity/digest（P2a、P5a1、P5a2、P6b
Candidate digest、Release、Schema、AutomationScope、EvidenceFragment、
WeKnora managed-page contract）使用本规范。`template_packages` 的自有
hash 与本规范的对账由 P6a 合同裁决（24 号处置清单）。

## 2. 值模型与编码映射

输出为 RFC 8785（JCS）兼容的 UTF-8 JSON 字节。tagged 形式是唯一合法
编码；裸 JSON `null` 与 JSON 浮点字面量永不出现。

| 抽象类型 | 编码 | 规则 |
|---|---|---|
| text | JSON string | 见 §3 文本约束 |
| bool | `true` / `false` | |
| safe int | JSON 整数字面量 | \|i\| ≤ 2^53−1；超出拒绝（`int_out_of_range`），改用 decimal |
| decimal | `{"$decimal":"<s>"}` | `<s>` 为无指数定点串：负号仅非零负数、整数部无前导零、小数部无尾随零；`-0`/`0E-10` → `"0"`；NaN/±Inf 拒绝（`decimal_not_finite`）；>100 位有效数字或数量级 >10^±100 拒绝（`decimal_out_of_range`） |
| date | `{"$date":"YYYY-MM-DD"}` | 年份四位零填充 |
| datetime | `{"$datetime":"YYYY-MM-DDTHH:MM:SS[.f{1,6}]Z"}` | 必须 tz-aware（否则 `naive_datetime`）；规范化为 UTC；微秒为零不输出小数部，非零去尾随零；UTC 转换溢出拒绝（`datetime_out_of_range`） |
| sentinel | `{"$s":"null"\|"unknown"\|"any"\|"-inf"\|"+inf"}` | 五者互不等价；Python `None` 编码为 `{"$s":"null"}` |
| set | `{"$set":[…]}` | 仅受理显式 `CanonicalSet`；成员按各自 canonical UTF-8 字节升序、按字节相等去重。裸 Python `set`/`frozenset` 拒绝：宿主语言相等性会在编码前折叠成员（`{1, 1.0}` 吞 float、`{True, 1}` 顺序相关） |
| list | JSON array | 保持给定语义顺序，不排序 |
| map | JSON object | 键必须为 text（否则 `non_string_key`）；`$` 前缀键拒绝（`reserved_key`，保留给 tag）；键按 UTF-16 码元升序（= UTF-16BE 字节序，RFC 8785 §3.2.3） |
| 其他类型 | 拒绝 | `unsupported_type`；二进制浮点一律 `float_forbidden`。类型判定为 exact type：子类（IntEnum/StrEnum/自定义 str 子类等）一律拒绝，防止与裸原语同 hash |

嵌套深度按容器层级计数（根容器第 1 层，标量不计层）：第 100 层受理
（valid 向量 `depth_100` 冻结该边界），第 101 层拒绝
（`max_depth_exceeded`）。

**数值身份必须由 Schema 钉死**：`int 1` 与 `Decimal("1")` 是两个不同
identity（`1` vs `{"$decimal":"1"}`）；超过 2^53−1 的整数必须改用
decimal，编码类别随之改变。SchemaVersion 必须为每个数值字段固定唯一
表示（int 或 decimal），不得混用。money/percentage 不新增 tag，由
Schema 层以 `$decimal` + 独立币种/单位字段的 map 表达（向量
`money_as_schema_map`）。

## 3. 文本约束（拒绝而非归一化）

适用于所有 text（含 map 键）：

1. 不含 surrogate 码点 U+D800–U+DFFF（`surrogate_forbidden`）；
2. 已是 Unicode NFC（`non_nfc_text`）；
3. 不含 U+000D（`carriage_return_forbidden`）；
4. 除 U+000A、U+0009 外不含 C0 控制符（`control_char_forbidden`）。

字符串转义按 RFC 8785 §3.2.2.2 最小转义：`\" \\ \b \f \n \r \t` 双字符
形式，其余 C0 控制符 `\u00xx`（小写 hex），其他字符字面输出 UTF-8。
注意：受理文本经 §3 约束后实际只有 `\" \\ \n \t` 四种转义可达；
`\b \f \r \u00xx` 各臂仅为 JCS 完整性而规定，向量不可能覆盖。

规范全文只有两处规范化：datetime → UTC、decimal → 定点串。其余一切可疑
输入 fail closed，防止"静默归一化掩盖语义差异"。

## 4. Hash 框架

```text
digest = SHA-256(
  DOMAIN_SEPARATOR ‖ 0x00 ‖ HASH_SCHEMA_VERSION ‖ 0x00 ‖
  object_type ‖ 0x00 ‖ canonical_bytes )
DOMAIN_SEPARATOR    = "insurancekb.canonical-envelope"（ASCII）
HASH_SCHEMA_VERSION = "1"
object_type         ~ ^[a-z][a-z0-9._-]{0,63}$（否则 invalid_object_type）
```

输出 64 位小写 hex。`object_type` 字符集不含 `0x00`，框架无歧义。同一
canonical 字节在不同 `object_type` 下必然得到不同 digest（域分隔）。

**版本升级规则**：更换 hash 算法、编码规则或转义规则必须递增
`HASH_SCHEMA_VERSION` 并新发 vectors 版本；历史对象的既有 digest 不得
静默重算（033 §8.4）。

## 5. 拒绝原因码（冻结）

`carriage_return_forbidden` `control_char_forbidden`
`datetime_out_of_range` `decimal_not_finite` `decimal_out_of_range`
`float_forbidden` `int_out_of_range` `invalid_object_type`
`max_depth_exceeded` `naive_datetime` `non_nfc_text` `non_string_key`
`reserved_key` `surrogate_forbidden` `unsupported_type`

## 6. 向量合同

`canonical_vectors_v1.json`：`valid[]` 每项含
`name/object_type/canonical_utf8/sha256`；`invalid[]` 每项含
`name/reason`（可选 `level:"hash"` 表示在 hash 层以非法 `object_type`
拒绝，缺省为编码层）。canonical 字符串为按本规范手工编写的 ground truth，
`sha256` 由冻结字符串按 §4 框架独立计算（生成脚本存
`openspec/changes/034-c0-canonical-envelope/artifacts/`），不经由任何实现
生成。每种语言的实现必须：

1. 对全部 valid 用例逐字节复现 `canonical_utf8` 与 `sha256`；
2. 对全部 invalid 用例以 exact reason 拒绝；
3. 测试与向量双向完备（向量名 ↔ 构造器一一对应，不得跳过）。

关键跨语言用例：`map_key_order_utf16`（U+1F600 的 UTF-16 码元 D83D DE00
排在 U+FF01 之前，与码点序相反）——任何按码点或插入序排序的实现都会在
此用例失败。
