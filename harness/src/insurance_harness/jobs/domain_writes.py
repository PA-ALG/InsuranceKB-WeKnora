"""P1.5 领域写通道（S7f-2c 自 store.py 拆出）：完成事务内的声明式领域写与目标表、列值校验。"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import MetaData, Table
from sqlalchemy import insert as sa_insert
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.orm import Session

from insurance_harness.jobs.errors import DomainWriteViolationError, InvalidJobInputError
from insurance_harness.jobs.models import DomainWriteSpec
from insurance_harness.jobs.store_rules import validated_text

#: P1 自有的两张表（P1.5 领域写通道合同，D-2026-07-27-16）。**精确枚举**，
#: 不按 `wiki_` 前缀封杀：其他 `wiki_` 前缀表属别的交付项所有（如 P6a 的
#: `wiki_page_revisions`、P2b 的 `wiki_releases`），误拦它们会让那些窗口
#: 无法写自己的领域表（第二轮评审 N2）。
OWNED_TABLES: frozenset[str] = frozenset({"wiki_jobs", "wiki_outbox_events"})

MAX_TABLE_NAME_LENGTH = 63  # PostgreSQL 标识符上限

#: 领域写目标表只接受**裸标识符**（P1.5，D-2026-07-27-16 第三轮自攻修订）。
#: 形状收窄使"规范化后等于自有表"的各种变体无从构造：不允许点号（schema
#: 限定）、引号、空白、注释标记、非 ASCII（Unicode 同形/大小写折叠）。
_BARE_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


#: 领域写列值只接受**纯标量**（P1.5「收数据不收代码」，D-2026-07-27-16
#: 第三轮独立评审 A3 修订）。SQLAlchemy 表达式对象会被编译进 INSERT——实测
#: `select(...).select_from(table("wiki_jobs")).scalar_subquery()` 能把 P1
#: 自有表的行读出来写进领域表（跨已声明边界的信息泄漏），`func.current_database()`
#: 与 `literal_column("current_user")` 能拿环境信息。写侧虽被方言挡住，但
#: "收数据不收代码"这条冻结条款在 values 侧必须同样成立。
_SCALAR_VALUE_TYPES: tuple[type, ...] = (str, bytes, bool, int, float, datetime, date, Decimal)


def _validated_domain_value(key: str, value: Any) -> Any:
    """校验单个列值是纯数据：拒绝任何可编译成 SQL 的对象（P1.5）。"""
    if value is None or isinstance(value, _SCALAR_VALUE_TYPES):
        return value
    if isinstance(value, Mapping | list | tuple):
        # JSON 容器：递归确认其中不夹带表达式对象。
        items = value.values() if isinstance(value, Mapping) else value
        for item in items:
            _validated_domain_value(key, item)
        return value
    raise InvalidJobInputError(
        f"domain write value for {key!r} must be plain data, got "
        f"{type(value).__module__}.{type(value).__name__}; SQL expression objects are refused"
    )


def _validated_domain_values(values: Mapping[str, Any]) -> dict[str, Any]:
    """校验列名是裸标识符、列值是纯标量（P1.5）。列名同样是安全比较点。"""
    validated: dict[str, Any] = {}
    for key, value in values.items():
        if not isinstance(key, str):
            raise InvalidJobInputError("domain write value keys must be strings")
        column = key.strip().casefold()
        if not _BARE_IDENTIFIER.fullmatch(column):
            raise InvalidJobInputError(
                f"domain write column must be a bare lowercase identifier (got {key!r})"
            )
        validated[column] = _validated_domain_value(key, value)
    return validated


def _canonical_table(raw: str) -> str:
    """把表标识规范化为安全比较用的 canonical 形式（P1.5）。

    第三轮自攻的 BLOCKER：原实现用**原样字符串**比对 `OWNED_TABLES`，而
    `autoload_with` 在 SQLite 上大小写不敏感地解析——`table="WIKI_JOBS"` 过了
    校验却真的写进 `wiki_jobs`（伪造别的 Space 的行、任意 state 与
    `lease_generation`）。同一输入在 PostgreSQL 上是 `NoSuchTableError`，
    即护栏的正确性取决于方言，这不是护栏。安全比较点必须自己规范化，不能
    依赖底层解析恰好宽或恰好严（019 教训第 10 条）。
    """
    name = validated_text(raw, "domain write table", max_length=MAX_TABLE_NAME_LENGTH)
    canonical = name.strip().casefold()
    if not _BARE_IDENTIFIER.fullmatch(canonical):
        raise InvalidJobInputError(
            "domain write table must be a bare lowercase identifier "
            f"(got {raw!r}); schema-qualified, quoted, padded or non-ASCII forms are refused"
        )
    return canonical


def execute_domain_writes(
    session: Session, specs: Sequence[DomainWriteSpec], *, job_id: str
) -> None:
    """在完成事务内执行声明式领域写（P1.5 领域写通道合同，D-2026-07-27-16）。

    存储层自己执行，调用方从不持有 Session/Connection/语句结果——因此
    "回调提交外层事务使领域行落库而任务仍 running" 在接口层面无法构造。

    目标表校验在**数据**上进行（比对表标识），不扫描 SQL 文本：后者既可被
    绕过（公共属性即可拿到活连接），又会误杀合法负载（同前缀的其他域自有表、
    含事务控制关键字的字符串字面量）。全部规格先校验、后执行：任一非法即在
    执行任何领域语句之前 typed 拒绝。
    """
    if not specs:
        return
    canonical_tables: list[str] = []
    canonical_values: list[dict[str, Any]] = []
    for spec in specs:
        table = _canonical_table(spec.table)
        if table in OWNED_TABLES:
            raise DomainWriteViolationError(
                f"domain write may not target P1-owned table {table!r}", job_id=job_id
            )
        if not spec.values:
            raise InvalidJobInputError("domain write values must not be empty")
        canonical_tables.append(table)
        canonical_values.append(_validated_domain_values(spec.values))
    metadata = MetaData()
    bind = session.get_bind()
    for table, values in zip(canonical_tables, canonical_values, strict=True):
        # 只用 canonical 名反射与执行：校验看到的名与实际打到的表必须是同一个。
        try:
            table_obj = Table(table, metadata, autoload_with=bind)
        except NoSuchTableError as error:
            raise InvalidJobInputError(f"domain write target table not found: {table!r}") from error
        # 列必须真实存在：未知列 typed 拒绝，而不是留给编译期抛
        # `CompileError`（P1.5 读路径/输入合同一致性）。
        unknown = sorted(set(values) - {column.name.casefold() for column in table_obj.columns})
        if unknown:
            raise InvalidJobInputError(
                f"domain write references unknown columns on {table!r}: {unknown}"
            )
        session.execute(sa_insert(table_obj).values(**values))
