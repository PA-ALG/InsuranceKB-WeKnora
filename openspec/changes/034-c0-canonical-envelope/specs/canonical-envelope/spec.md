# 034 C0 Canonical Envelope 验收规格

## ADDED Requirements

### Requirement: C0.1 唯一 canonical 字节编码

系统 SHALL 提供 `canonical_bytes(value) -> bytes`，把受支持的值编码为
RFC 8785（JCS）兼容的 UTF-8 JSON 字节；同一抽象值的编码 SHALL 与调用次数、
进程、平台无关地逐字节相等。受支持的输入 SHALL 且仅为：`str`、`bool`、
安全范围内的 `int`（|i| ≤ 2^53−1）、`decimal.Decimal`（有限值）、
`datetime.date`、tz-aware `datetime.datetime`、五个显式 sentinel、
`CanonicalSet`/`set`/`frozenset`、`list`/`tuple`、键为 `str` 的 `dict`，以及
`None`（编码为 NULL sentinel）。其余类型 SHALL 以 typed error 拒绝。

#### Scenario: 确定性

- **WHEN** 对同一嵌套值调用 `canonical_bytes` 两次
- **THEN** 两次输出逐字节相等

#### Scenario: 不支持类型 fail closed

- **WHEN** 输入包含 `float`、`bytes` 或任意未列举类型（任意嵌套深度）
- **THEN** 编码以 `CanonicalEncodingError` 拒绝并携带确定的 reason code，
  不产生部分输出

### Requirement: C0.2 文本约束——UTF-8/NFC/LF，拒绝而非归一化

文本（含 map 键）SHALL 满足：不含 surrogate 码点；已是 Unicode NFC；除
`\n`（U+000A）与 `\t`（U+0009）外不含 C0 控制符；不含 `\r`（U+000D）。
违反任一约束 SHALL 拒绝（reason 分别为 `surrogate_forbidden`、
`non_nfc_text`、`control_char_forbidden`、`carriage_return_forbidden`），
SHALL NOT 静默归一化。字符串转义 SHALL 按 RFC 8785 §3.2.2.2 最小转义。

#### Scenario: 非 NFC 文本拒绝

- **WHEN** 输入含 NFD 组合序列（如 `e` + U+0301）
- **THEN** 编码拒绝且 reason 为 `non_nfc_text`

#### Scenario: CRLF 拒绝

- **WHEN** 输入文本含 `\r`
- **THEN** 编码拒绝且 reason 为 `carriage_return_forbidden`

### Requirement: C0.3 数值——禁止二进制浮点，decimal 定点规范化

`float`（含 NaN/±Inf）SHALL 在任何位置拒绝（`float_forbidden`）。`int`
超出 ±(2^53−1) SHALL 拒绝（`int_out_of_range`），大数 SHALL 改用
`Decimal`。`Decimal` SHALL 编码为 tagged `{"$decimal":"<s>"}`，其中 `<s>`
为无指数定点串：负号仅在非零负数出现、整数部无前导零、小数部无尾随零、
`-0` 与 `0E-10` 规范化为 `"0"`；NaN/±Inf 的 Decimal SHALL 拒绝
（`decimal_not_finite`）。

#### Scenario: decimal 规范化

- **WHEN** 输入 `Decimal("1.0")`、`Decimal("-0")`、`Decimal("1E+2")`
- **THEN** 编码分别为 `{"$decimal":"1"}`、`{"$decimal":"0"}`、
  `{"$decimal":"100"}`

#### Scenario: 超范围 int 拒绝

- **WHEN** 输入 `2**53`
- **THEN** 编码拒绝且 reason 为 `int_out_of_range`

### Requirement: C0.4 日期/时间 tagged ISO 8601

`date` SHALL 编码为 `{"$date":"YYYY-MM-DD"}`。`datetime` SHALL 要求
tz-aware（naive 拒绝，`naive_datetime`），规范化为 UTC 并编码为
`{"$datetime":"YYYY-MM-DDTHH:MM:SS[.f{1,6}]Z"}`，微秒为零不输出小数部，
非零时去除尾随零。

#### Scenario: 时区归一

- **WHEN** 输入 `2026-07-26T20:00:00+08:00`
- **THEN** 编码为 `{"$datetime":"2026-07-26T12:00:00Z"}`

#### Scenario: naive datetime 拒绝

- **WHEN** 输入无 tzinfo 的 datetime
- **THEN** 编码拒绝且 reason 为 `naive_datetime`

### Requirement: C0.5 显式 sentinel 且互不等价

NULL、UNKNOWN、ANY、负无穷、正无穷 SHALL 编码为
`{"$s":"null"|"unknown"|"any"|"-inf"|"+inf"}` 五个互不相等的 tagged
sentinel；Python `None` SHALL 编码为 NULL sentinel；裸 JSON `null`
SHALL NOT 出现在 canonical 字节中。

#### Scenario: sentinel 互异

- **WHEN** 分别编码五个 sentinel 并对同一 `object_type` 求 hash
- **THEN** 五个 canonical 字节串与五个 hash 两两不同

### Requirement: C0.6 set 排序去重，list 保序，map 键 UTF-16 码元排序

`CanonicalSet`/`set`/`frozenset` SHALL 编码为 `{"$set":[...]}`，成员按各自
canonical 字节升序排序并按字节相等去重。`list`/`tuple` SHALL 保持给定顺序。
`dict` SHALL 仅接受 `str` 键（否则 `non_string_key`）；以 `$` 开头的键
SHALL 拒绝（`reserved_key`，保留给 tag）；键序 SHALL 按 RFC 8785 的
UTF-16 码元升序（等价于 UTF-16BE 字节序），SHALL NOT 使用码点序或插入序。

#### Scenario: UTF-16 键序与码点序不同

- **WHEN** 编码 `{"！": 2, "😀": 1}`（U+FF01 与 U+1F600）
- **THEN** canonical 字节中 `"😀"`（UTF-16 D83D DE00）在 `"！"`（FF01）之前

#### Scenario: set 排序去重

- **WHEN** 编码 `CanonicalSet([3, 1, 2, 1])`
- **THEN** 结果为 `{"$set":[1,2,3]}`

### Requirement: C0.7 domain-separated hash

系统 SHALL 提供 `canonical_hash(object_type, value) -> str`（64 位小写
hex），其 SHA-256 输入 SHALL 为
`DOMAIN_SEPARATOR ‖ 0x00 ‖ HASH_SCHEMA_VERSION ‖ 0x00 ‖ object_type ‖ 0x00 ‖ canonical_bytes`，
其中 `DOMAIN_SEPARATOR = "insurancekb.canonical-envelope"`、
`HASH_SCHEMA_VERSION = "1"`。`object_type` SHALL 匹配
`^[a-z][a-z0-9._-]{0,63}$`，否则拒绝（`invalid_object_type`）。同一
canonical 字节在不同 `object_type` 下 SHALL 得到不同 hash。更换算法或编码
规则 SHALL 升 `hash_schema_version`，SHALL NOT 静默重算历史对象。

#### Scenario: 域分隔

- **WHEN** 同一值分别以 `object_type="claim-revision"` 与
  `object_type="wiki-release"` 求 hash
- **THEN** 两个 hash 不同

#### Scenario: 非法 object_type 拒绝

- **WHEN** `object_type` 为空、含大写或含 `\x00`
- **THEN** 拒绝且 reason 为 `invalid_object_type`

### Requirement: C0.8 语言中立向量冻结与双向完备

变更 SHALL 交付 `canonical_vectors_v1.json`：每个合法用例含
`name/object_type/canonical_utf8/sha256`，每个非法用例含 `name/reason`。
向量的 `canonical_utf8` SHALL 由规范手工编写、`sha256` SHALL 由该冻结字符
串按 C0.7 框架独立计算（不经由被测实现生成）。Python reference codec
SHALL 对全部合法用例逐字节复现 `canonical_utf8` 与 `sha256`，对全部非法
用例以 exact reason 拒绝。测试 SHALL 双向完备：向量中每个 name 必须有
对应构造器，构造器集合不得包含向量之外的 name。后续任何语言的实现
（Go adapter 于 W1/P11）SHALL 通过同一向量文件验收，SHALL NOT 另立规范。

#### Scenario: 向量全等

- **WHEN** 对每个合法向量用构造器生成输入并编码、求 hash
- **THEN** 字节与 hash 与向量文件逐项相等，无跳过

#### Scenario: 非法向量 exact 拒绝

- **WHEN** 对每个非法向量用构造器生成输入并编码
- **THEN** 均以 `CanonicalEncodingError` 拒绝且 reason 与向量记录相等

### Requirement: C0.9 纯度与嵌套上限

canonical 包 SHALL 零 `insurance_harness` 内部依赖、无 I/O、无全局可变
状态。嵌套深度超过 100 SHALL 拒绝（`max_depth_exceeded`），不得栈溢出。

#### Scenario: 深度上限

- **WHEN** 编码嵌套深度 101 的列表
- **THEN** 以 `max_depth_exceeded` 拒绝而非 RecursionError
