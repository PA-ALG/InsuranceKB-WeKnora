"""OpenSpec 020 D1.3b/D1.5: durable canary capability ledger."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from multiprocessing import get_context
from pathlib import Path
from threading import Event
from typing import Protocol

import pytest
from pydantic import ValidationError

import insurance_harness.goldenset.admission_budget as admission_budget
from insurance_harness.goldenset.admission_budget import (
    SQLITE_SAFE_INTEGER_MAX,
    AttemptKey,
    BudgetAmounts,
    BudgetContract,
    BudgetLedger,
    BudgetLedgerError,
    ProductReserve,
    ProductSettlementSnapshot,
    ProviderSpendCapAttestation,
    RequestReserve,
    RoleRate,
    SendPermit,
)

_NOW = datetime(2026, 7, 20, 9, 0, tzinfo=UTC)
_ACCOUNT_ID = "a" * 64
_APPROVAL_DIGEST = "b" * 64
_CANARY = ("annotation", "canary-product")
_TARGET = ("annotation", "next-product")


class _ProcessBarrier(Protocol):
    def wait(self, timeout: float | None = None) -> int: ...


def _amounts(
    input_tokens: int = 1_000,
    output_tokens: int = 500,
    cost_minor_units: int = 20,
) -> BudgetAmounts:
    return BudgetAmounts(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_minor_units=cost_minor_units,
    )


def _contract() -> BudgetContract:
    role_rates = {
        role: RoleRate(
            model_role_identity_hash=digest * 64,
            input_cost_per_million_minor_units=10,
            output_cost_per_million_minor_units=20,
        )
        for role, digest in (
            ("annotator", "1"),
            ("weak_extractor", "2"),
            ("judge", "3"),
        )
    }
    products = tuple(
        ProductReserve(
            stage=stage,
            product_id=product_id,
            maximum=_amounts(),
            request_reserves=(
                RequestReserve(
                    request_unit=f"{product_id}-request",
                    role="weak_extractor",
                    maximum=_amounts(100, 50, 10),
                ),
            ),
        )
        for stage, product_id in (_CANARY, _TARGET)
    )
    return BudgetContract(
        currency="CNY",
        price_snapshot_id="price-20260720",
        price_observed_at=_NOW,
        price_expires_at=_NOW + timedelta(hours=1),
        ceiling=_amounts(5_000, 2_500, 100),
        role_rates=role_rates,
        provider_attestation=ProviderSpendCapAttestation(
            provider="bailian",
            workspace_ref="goldenset-production",
            project_ref="sha256:" + "4" * 64,
            credential_ref="sha256:" + "5" * 64,
            max_cost_minor_units=100,
            observed_at=_NOW,
            expires_at=_NOW + timedelta(hours=1),
            evidence_digest="6" * 64,
        ),
        product_reserves=products,
    )


def _seed_settled_canary(
    db_path: Path,
    *,
    clock: Callable[[], datetime] | None = None,
) -> BudgetLedger:
    ledger = BudgetLedger._for_testing(db_path, clock=clock or (lambda: _NOW))
    contract = _contract()
    canary_maximum = contract.product_reserves[0].maximum
    target_maximum = contract.product_reserves[1].maximum
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """INSERT INTO budget_accounts VALUES (
                   ?, 'run-020', 'baseline', 'CNY', 5000, 2500, 100,
                   1, ?, 0
               )""",
            (_ACCOUNT_ID, _APPROVAL_DIGEST),
        )
        connection.execute(
            """INSERT INTO budget_approvals VALUES (
                   ?, 1, ?, NULL, ?, ?, ?, 5000, 2500, 100
               )""",
            (
                _ACCOUNT_ID,
                _APPROVAL_DIGEST,
                "7" * 64,
                "8" * 64,
                contract.model_dump_json().encode("utf-8"),
            ),
        )
        for (stage, product_id), maximum in (
            (_CANARY, canary_maximum),
            (_TARGET, target_maximum),
        ):
            connection.execute(
                "INSERT INTO product_limits VALUES (?, ?, ?, ?, ?, ?)",
                (
                    _ACCOUNT_ID,
                    stage,
                    product_id,
                    maximum.input_tokens,
                    maximum.output_tokens,
                    maximum.cost_minor_units,
                ),
            )
        connection.execute(
            """INSERT INTO product_reservations VALUES (
                   ?, ?, ?, 'settled', 1000, 500, 20, 200, 100, 4
               )""",
            (_ACCOUNT_ID, *_CANARY),
        )
        for request_unit, attempt_no in (("f" * 64, 2), ("e" * 64, 1)):
            connection.execute(
                """INSERT INTO request_limits VALUES (
                       ?, ?, ?, ?, 'weak_extractor', 100, 50, 10
                   )""",
                (_ACCOUNT_ID, *_CANARY, request_unit),
            )
            connection.execute(
                """INSERT INTO request_attempts VALUES (
                       ?, ?, ?, ?, ?, ?, 'weak_extractor', 'exact', 'terminal',
                       100, 50, 10, 100, 50, 2, 100, 50, 2, ?, 1,
                       NULL, NULL, NULL, NULL
                   )""",
                (
                    _ACCOUNT_ID,
                    *_CANARY,
                    request_unit,
                    attempt_no,
                    "9" * 64,
                    ("c" if request_unit.startswith("e") else "d") * 64,
                ),
            )
    return ledger


def _downgrade_legacy_usage_schema(db_path: Path, *, version: int, reservation_state: str) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TABLE infrastructure_provider_cap_evidence")
        connection.execute("DROP TABLE final_topology_receipt_annexes")
        connection.execute("DROP TABLE final_infrastructure_topologies")
        connection.execute("DROP TABLE deployment_role_bindings")
        connection.execute("DROP TABLE infrastructure_reserves")
        connection.execute("DROP TABLE infrastructure_authorizations")
        connection.execute("DROP TABLE canary_capability_claims")
        connection.execute(
            """UPDATE request_attempts
               SET usage_verified=0,actual_input=10,actual_output=5,actual_cost=2,
                   charged_input=10,charged_output=5,charged_cost=2"""
        )
        connection.execute(
            """UPDATE product_reservations
               SET state=?,actual_input=20,actual_output=10,actual_cost=4""",
            (reservation_state,),
        )
        if version != 3:
            role_columns = (
                """role TEXT NOT NULL CHECK (
                       role IN ('annotator','weak_extractor','judge')
                   ),
                   limit_kind TEXT NOT NULL CHECK (limit_kind IN ('exact','pool')),"""
                if version in {0, 2}
                else ""
            )
            role_names = "role,limit_kind," if version in {0, 2} else ""
            connection.execute(
                f"""CREATE TABLE request_attempts_legacy (
                    account_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    request_unit TEXT NOT NULL,
                    attempt_no INTEGER NOT NULL,
                    owner_token_digest TEXT NOT NULL,
                    {role_columns}
                    state TEXT NOT NULL,
                    max_input INTEGER NOT NULL,
                    max_output INTEGER NOT NULL,
                    max_cost INTEGER NOT NULL,
                    actual_input INTEGER NOT NULL,
                    actual_output INTEGER NOT NULL,
                    actual_cost INTEGER NOT NULL,
                    charged_input INTEGER NOT NULL,
                    charged_output INTEGER NOT NULL,
                    charged_cost INTEGER NOT NULL,
                    response_digest TEXT,
                    provider_proof_digest TEXT,
                    provider_request_id TEXT,
                    provider_verifier_policy TEXT,
                    provider_proof_observed_at TEXT,
                    PRIMARY KEY (
                        account_id,stage,product_id,request_unit,attempt_no
                    )
                )"""
            )
            connection.execute(
                f"""INSERT INTO request_attempts_legacy (
                    account_id,stage,product_id,request_unit,attempt_no,
                    owner_token_digest,{role_names}state,
                    max_input,max_output,max_cost,
                    actual_input,actual_output,actual_cost,
                    charged_input,charged_output,charged_cost,response_digest,
                    provider_proof_digest,provider_request_id,
                    provider_verifier_policy,provider_proof_observed_at
                )
                SELECT account_id,stage,product_id,request_unit,attempt_no,
                       owner_token_digest,{role_names}state,
                       max_input,max_output,max_cost,
                       actual_input,actual_output,actual_cost,
                       charged_input,charged_output,charged_cost,response_digest,
                       provider_proof_digest,provider_request_id,
                       provider_verifier_policy,provider_proof_observed_at
                FROM request_attempts"""
            )
            connection.execute("DROP TABLE request_attempts")
            connection.execute("ALTER TABLE request_attempts_legacy RENAME TO request_attempts")
        if version in {0, 1}:
            connection.execute("DROP TABLE request_pool_limits")
        connection.execute(f"PRAGMA user_version = {version}")


def _replace_canary_claim_schema(db_path: Path, *, wrong: str) -> str:
    primary_key = (
        "PRIMARY KEY (account_id, capability_digest)"
        if wrong == "primary-key"
        else """PRIMARY KEY (
            account_id,capability_digest,target_stage,target_product_id
        )"""
    )
    target_foreign_key = (
        ""
        if wrong == "foreign-key"
        else """, FOREIGN KEY (account_id,target_stage,target_product_id)
            REFERENCES product_limits(account_id,stage,product_id)"""
    )
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TABLE canary_capability_claims")
        connection.execute(
            f"""CREATE TABLE canary_capability_claims (
                account_id TEXT NOT NULL REFERENCES budget_accounts(account_id),
                capability_digest TEXT NOT NULL,
                canary_stage TEXT NOT NULL,
                canary_product_id TEXT NOT NULL,
                settlement_digest TEXT NOT NULL,
                budget_revision INTEGER NOT NULL,
                approval_digest TEXT NOT NULL,
                target_stage TEXT NOT NULL,
                target_product_id TEXT NOT NULL,
                target_max_input INTEGER NOT NULL,
                target_max_output INTEGER NOT NULL,
                target_max_cost INTEGER NOT NULL,
                {primary_key},
                FOREIGN KEY (account_id,canary_stage,canary_product_id)
                    REFERENCES product_limits(account_id,stage,product_id)
                {target_foreign_key}
            )"""
        )
        schema = connection.execute(
            """SELECT sql FROM sqlite_master
               WHERE type='table' AND name='canary_capability_claims'"""
        ).fetchone()
    assert schema is not None
    return str(schema[0])


def _mutate_current_canary_claim_schema(db_path: Path, *, defect: str) -> str:
    replacements = {
        "blob-type": (
            "capability_digest TEXT NOT NULL",
            "capability_digest BLOB NOT NULL",
        ),
        "nullable": (
            "target_product_id TEXT NOT NULL",
            "target_product_id TEXT",
        ),
        "missing-check": (
            "target_max_cost INTEGER NOT NULL CHECK (target_max_cost >= 0)",
            "target_max_cost INTEGER NOT NULL",
        ),
    }
    with sqlite3.connect(db_path) as connection:
        schema = connection.execute(
            """SELECT sql FROM sqlite_master
               WHERE type='table' AND name='canary_capability_claims'"""
        ).fetchone()
        assert schema is not None
        original = str(schema[0])
        old, new = replacements[defect]
        assert old in original
        mutated = original.replace(old, new, 1)
        connection.execute("DROP TABLE canary_capability_claims")
        connection.execute(mutated)
    return mutated


def _claim(
    ledger: BudgetLedger,
    *,
    capability_digest: str = "0" * 64,
    settlement_digest: str | None = None,
    target: tuple[str, str] = _TARGET,
    granted_targets: tuple[tuple[str, str], ...] = (_TARGET,),
) -> None:
    snapshot = ledger.product_settlement_snapshot(_ACCOUNT_ID, *_CANARY)
    ledger.claim_canary_capability_and_reserve(
        account_id=_ACCOUNT_ID,
        capability_digest=capability_digest,
        canary_stage=_CANARY[0],
        canary_product_id=_CANARY[1],
        expected_settlement_digest=(
            settlement_digest
            if settlement_digest is not None
            else ledger.product_settlement_snapshot_digest(snapshot)
        ),
        authorization_evaluated_at=_NOW,
        authorization_expires_at=_NOW + timedelta(hours=1),
        target_stage=target[0],
        target_product_id=target[1],
        target_maximum=_amounts(),
        granted_targets=granted_targets,
    )


def _multiprocess_claim_worker(db_path: str, barrier: _ProcessBarrier) -> None:
    ledger = BudgetLedger._for_testing(Path(db_path), clock=lambda: _NOW)
    barrier.wait(timeout=10)
    _claim(ledger)


def _target_reservations(db_path: Path) -> list[tuple[object, ...]]:
    with sqlite3.connect(db_path) as connection:
        return connection.execute(
            """SELECT stage,product_id,state,max_input,max_output,max_cost
               FROM product_reservations WHERE account_id=? AND product_id=?""",
            (_ACCOUNT_ID, _TARGET[1]),
        ).fetchall()


def _prepared_canary(db_path: Path) -> tuple[BudgetLedger, SendPermit]:
    ledger = _seed_settled_canary(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute("DELETE FROM request_attempts")
        connection.execute(
            """UPDATE product_reservations
               SET state='reserved',actual_input=0,actual_output=0,actual_cost=0
               WHERE account_id=? AND stage=? AND product_id=?""",
            (_ACCOUNT_ID, *_CANARY),
        )
        connection.execute(
            """INSERT INTO request_limits VALUES (
                   ?, ?, ?, 'canary-request', 'weak_extractor', 100, 50, 10
               )""",
            (_ACCOUNT_ID, *_CANARY),
        )
    permit = ledger.claim_attempt(
        _ACCOUNT_ID,
        *_CANARY,
        "canary-request",
        1,
        "owner",
        _amounts(100, 50, 10),
    )
    assert permit is not None
    return ledger, permit


def test_d1_5_settlement_snapshot_is_complete_canonical_and_stable(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = _seed_settled_canary(db_path)

    snapshot = ledger.product_settlement_snapshot(_ACCOUNT_ID, *_CANARY)

    assert snapshot.account_id == _ACCOUNT_ID
    assert snapshot.budget_revision == 1
    assert snapshot.approval_digest == _APPROVAL_DIGEST
    assert snapshot.reservation_state == "settled"
    assert snapshot.reservation_maximum == _amounts()
    assert snapshot.reservation_actual == _amounts(200, 100, 4)
    assert [(attempt.request_unit, attempt.attempt_no) for attempt in snapshot.attempts] == [
        ("e" * 64, 1),
        ("f" * 64, 2),
    ]
    first = snapshot.attempts[0]
    assert first.role == "weak_extractor"
    assert first.limit_kind == "exact"
    assert first.state == "terminal"
    assert first.maximum == _amounts(100, 50, 10)
    assert first.actual == _amounts(100, 50, 2)
    assert first.usage_verified is True
    assert first.response_digest == "c" * 64
    assert first.no_usage_proof is None
    assert ledger.product_settlement_snapshot_digest(snapshot) == (
        BudgetLedger(db_path).product_settlement_snapshot_digest(
            BudgetLedger(db_path).product_settlement_snapshot(_ACCOUNT_ID, *_CANARY)
        )
    )


def test_d1_5_claim_rechecks_snapshot_and_atomically_reserves_target(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = _seed_settled_canary(db_path)

    _claim(ledger)
    _claim(BudgetLedger._for_testing(db_path, clock=lambda: _NOW))

    assert _target_reservations(db_path) == [(*_TARGET, "reserved", 1_000, 500, 20)]
    with sqlite3.connect(db_path) as connection:
        claims = connection.execute(
            "SELECT capability_digest,target_stage,target_product_id FROM canary_capability_claims"
        ).fetchall()
    assert claims == [("0" * 64, *_TARGET)]


def test_d1_5_expired_idempotent_capability_recovery_fails_before_existing_claim(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    current = [_NOW]
    ledger = _seed_settled_canary(db_path, clock=lambda: current[0])
    _claim(ledger)
    current[0] = _NOW + timedelta(hours=1)

    with pytest.raises(BudgetLedgerError, match="expired"):
        _claim(ledger)

    assert _target_reservations(db_path) == [(*_TARGET, "reserved", 1_000, 500, 20)]
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM canary_capability_claims"
        ).fetchone() == (1,)


def test_d1_5_claim_rejects_drift_unverified_uncertain_and_overage(
    tmp_path: Path,
) -> None:
    for failure, update in (
        ("drift", "UPDATE request_attempts SET response_digest='" + "a" * 64 + "'"),
        ("unverified", "UPDATE request_attempts SET usage_verified=0"),
        ("uncertain", "UPDATE request_attempts SET state='uncertain'"),
        ("overage", "UPDATE budget_accounts SET overage=1"),
    ):
        db_path = tmp_path / f"{failure}.sqlite3"
        ledger = _seed_settled_canary(db_path)
        snapshot_digest = ledger.product_settlement_snapshot_digest(
            ledger.product_settlement_snapshot(_ACCOUNT_ID, *_CANARY)
        )
        with sqlite3.connect(db_path) as connection:
            connection.execute(update)

        with pytest.raises(BudgetLedgerError):
            _claim(ledger, settlement_digest=snapshot_digest)
        assert _target_reservations(db_path) == []


@pytest.mark.parametrize(
    ("state", "usage_verified"),
    [
        ("prepared", 1),
        ("sent", 1),
        ("uncertain", 1),
        ("no_usage", 0),
        ("terminal", 0),
    ],
)
def test_d1_5_historical_nonterminal_or_unverified_attempt_cannot_unlock(
    tmp_path: Path,
    state: str,
    usage_verified: int,
) -> None:
    db_path = tmp_path / f"{state}-{usage_verified}.sqlite3"
    ledger = _seed_settled_canary(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE request_attempts SET state=?,usage_verified=?",
            (state, usage_verified),
        )

    with pytest.raises(BudgetLedgerError, match="terminal|verified"):
        _claim(ledger)
    assert _target_reservations(db_path) == []


def test_d1_5_empty_or_signed_rate_inconsistent_settlement_cannot_unlock(
    tmp_path: Path,
) -> None:
    empty_path = tmp_path / "empty.sqlite3"
    empty_ledger = _seed_settled_canary(empty_path)
    with sqlite3.connect(empty_path) as connection:
        connection.execute("DELETE FROM request_attempts")
        connection.execute(
            """UPDATE product_reservations
               SET actual_input=0,actual_output=0,actual_cost=0"""
        )
    with pytest.raises(BudgetLedgerError, match="completely settled"):
        _claim(empty_ledger)

    cost_path = tmp_path / "cost.sqlite3"
    cost_ledger = _seed_settled_canary(cost_path)
    with sqlite3.connect(cost_path) as connection:
        connection.execute("UPDATE request_attempts SET actual_cost=3,charged_cost=3")
        connection.execute("UPDATE product_reservations SET actual_cost=6")
    with pytest.raises(BudgetLedgerError, match="signed role rate"):
        _claim(cost_ledger)
    assert _target_reservations(cost_path) == []


def test_d1_5_capability_claims_each_granted_target_but_rejects_ungranted(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = _seed_settled_canary(db_path)
    with sqlite3.connect(db_path) as connection:
        for product_id in ("other-product", "ungranted-product"):
            connection.execute(
                "INSERT INTO product_limits VALUES (?, 'annotation', ?, 1000, 500, 20)",
                (_ACCOUNT_ID, product_id),
            )

    grants = (_TARGET, ("annotation", "other-product"))
    _claim(ledger, granted_targets=grants)
    _claim(
        ledger,
        target=("annotation", "other-product"),
        granted_targets=grants,
    )

    with pytest.raises(BudgetLedgerError, match="grant"):
        _claim(
            ledger,
            target=("annotation", "ungranted-product"),
            granted_targets=grants,
        )
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            """SELECT target_stage,target_product_id
               FROM canary_capability_claims ORDER BY target_product_id"""
        ).fetchall()
        assert rows == [
            ("annotation", "next-product"),
            ("annotation", "other-product"),
        ]
        assert (
            connection.execute(
                """SELECT 1 FROM product_reservations
               WHERE product_id='ungranted-product'"""
            ).fetchone()
            is None
        )


def test_d1_3b_d1_5_two_processes_claim_one_capability_reservation(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    _seed_settled_canary(db_path)

    context = get_context("spawn")
    barrier = context.Barrier(2)
    processes = [
        context.Process(
            target=_multiprocess_claim_worker,
            args=(str(db_path), barrier),
        )
        for _ in range(2)
    ]
    started = []
    try:
        for process in processes:
            process.start()
            started.append(process)
        for process in started:
            process.join(timeout=15)
    finally:
        for process in started:
            if process.is_alive():
                process.terminate()
        for process in started:
            process.join(timeout=5)
        for process in started:
            if process.is_alive():
                process.kill()
        for process in started:
            process.join(timeout=5)

    assert all(not process.is_alive() for process in started)
    assert [process.exitcode for process in processes] == [0, 0]
    assert len(_target_reservations(db_path)) == 1
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM canary_capability_claims").fetchone() == (
            1,
        )


def test_d1_3b_verified_usage_rejects_caller_forged_signed_rate_cost(
    tmp_path: Path,
) -> None:
    ledger, permit = _prepared_canary(tmp_path / "budget.sqlite3")

    with pytest.raises(BudgetLedgerError, match="cost"):
        ledger.record_terminal(
            permit,
            actual=_amounts(100, 50, 9),
            response_digest="c" * 64,
            usage_verified=True,
        )

    assert ledger.attempt_snapshot(permit.key).state == "prepared"


def test_d1_3b_unverified_usage_is_charged_at_full_bound(
    tmp_path: Path,
) -> None:
    ledger, permit = _prepared_canary(tmp_path / "budget.sqlite3")

    ledger.record_terminal(
        permit,
        actual=_amounts(10, 5, 2),
        response_digest="c" * 64,
        usage_verified=False,
    )

    snapshot = ledger.attempt_snapshot(permit.key)
    assert snapshot.actual == permit.maximum
    assert snapshot.charged == permit.maximum
    assert snapshot.usage_verified is False


def test_d1_3b_force_overage_persists_unrepresentable_usage_fail_closed(
    tmp_path: Path,
) -> None:
    ledger, permit = _prepared_canary(tmp_path / "budget.sqlite3")

    ledger.record_terminal(
        permit,
        actual=_amounts(10, 5, 2),
        response_digest="c" * 64,
        usage_verified=False,
        force_overage=True,
    )

    assert ledger.attempt_snapshot(permit.key).actual == permit.maximum
    assert ledger.account_snapshot(_ACCOUNT_ID).overage is True


def test_d1_3b_sqlite_persisted_budget_values_reject_integer_overflow() -> None:
    with pytest.raises(ValidationError):
        _amounts(SQLITE_SAFE_INTEGER_MAX + 1, 0, 0)
    with pytest.raises(ValidationError):
        RoleRate(
            model_role_identity_hash="1" * 64,
            input_cost_per_million_minor_units=SQLITE_SAFE_INTEGER_MAX + 1,
            output_cost_per_million_minor_units=0,
        )


def test_d1_5_public_role_rate_digest_has_stable_domain_separated_vector() -> None:
    rate = RoleRate(
        model_role_identity_hash="1" * 64,
        input_cost_per_million_minor_units=10,
        output_cost_per_million_minor_units=20,
    )

    assert admission_budget.role_rate_digest(rate) == (
        "dfede9356e42f1867beed47ce2c4e80785327a26d070533c4a573f2ca9158f78"
    )


@pytest.mark.parametrize("version", [0, 1, 2, 3])
@pytest.mark.parametrize("reservation_state", ["reserved", "settled"])
def test_d1_3b_d1_5_legacy_unverified_terminal_debits_full_bound_after_v4_migration(
    tmp_path: Path,
    version: int,
    reservation_state: str,
) -> None:
    db_path = tmp_path / f"v{version}-{reservation_state}.sqlite3"
    _seed_settled_canary(db_path)
    _downgrade_legacy_usage_schema(db_path, version=version, reservation_state=reservation_state)

    migrated = BudgetLedger(db_path)
    if reservation_state == "reserved":
        migrated.settle_product(_ACCOUNT_ID, *_CANARY)

    assert migrated.account_snapshot(_ACCOUNT_ID).settled == _amounts(200, 100, 20)
    first = migrated.attempt_snapshot(
        AttemptKey(
            account_id=_ACCOUNT_ID,
            stage=_CANARY[0],
            product_id=_CANARY[1],
            request_unit="e" * 64,
            attempt_no=1,
        )
    )
    assert first.actual == _amounts(10, 5, 2)
    assert first.charged == _amounts(10, 5, 2)
    assert first.usage_verified is False
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (8,)
        assert connection.execute("SELECT COUNT(*) FROM canary_capability_claims").fetchone() == (
            0,
        )


def test_d1_3b_v4_missing_capability_table_fails_closed_without_repair(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    _seed_settled_canary(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TABLE canary_capability_claims")
        attempts_before = connection.execute(
            "SELECT * FROM request_attempts ORDER BY request_unit,attempt_no"
        ).fetchall()

    with pytest.raises(BudgetLedgerError, match="claim table"):
        BudgetLedger(db_path)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (8,)
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name='canary_capability_claims'"
            ).fetchone()
            is None
        )
        assert (
            connection.execute(
                "SELECT * FROM request_attempts ORDER BY request_unit,attempt_no"
            ).fetchall()
            == attempts_before
        )


def test_d1_3b_legacy_settled_reconciliation_restores_durable_overage(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    _seed_settled_canary(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE request_attempts SET request_unit=? WHERE request_unit=?",
            ("e" * 64, "f" * 64),
        )
        connection.execute(
            "DELETE FROM request_limits WHERE request_unit=?",
            ("f" * 64,),
        )
        connection.execute(
            """UPDATE product_limits
               SET max_input=150,max_output=75,max_cost=15
               WHERE account_id=? AND stage=? AND product_id=?""",
            (_ACCOUNT_ID, *_CANARY),
        )
        connection.execute(
            """UPDATE product_reservations
               SET max_input=150,max_output=75,max_cost=15
               WHERE account_id=? AND stage=? AND product_id=?""",
            (_ACCOUNT_ID, *_CANARY),
        )
    _downgrade_legacy_usage_schema(db_path, version=3, reservation_state="settled")

    migrated = BudgetLedger(db_path)

    snapshot = migrated.account_snapshot(_ACCOUNT_ID)
    assert snapshot.settled == _amounts(200, 100, 20)
    assert snapshot.overage is True
    with pytest.raises(BudgetLedgerError, match="overage"):
        migrated.reserve_product(_ACCOUNT_ID, *_TARGET, _amounts())
    assert _target_reservations(db_path) == []


def test_d1_3b_legacy_reconciliation_checks_account_occupied_after_all_products(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    _seed_settled_canary(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE request_attempts SET request_unit=? WHERE request_unit=?",
            ("e" * 64, "f" * 64),
        )
        connection.execute(
            "DELETE FROM request_limits WHERE request_unit=?",
            ("f" * 64,),
        )
        connection.execute(
            """UPDATE product_limits
               SET max_input=250,max_output=125,max_cost=25
               WHERE account_id=?""",
            (_ACCOUNT_ID,),
        )
        connection.execute(
            """UPDATE product_reservations
               SET max_input=250,max_output=125,max_cost=25
               WHERE account_id=?""",
            (_ACCOUNT_ID,),
        )
        connection.execute(
            """UPDATE budget_accounts
               SET ceiling_input=300,ceiling_output=150,ceiling_cost=30
               WHERE account_id=?""",
            (_ACCOUNT_ID,),
        )
        connection.execute(
            """INSERT INTO request_limits VALUES (
                   ?, ?, ?, ?, 'weak_extractor', 100, 50, 10
               )""",
            (_ACCOUNT_ID, *_TARGET, "d" * 64),
        )
        connection.execute(
            """INSERT INTO product_reservations VALUES (
                   ?, ?, ?, 'settled', 250, 125, 25, 20, 10, 4
               )""",
            (_ACCOUNT_ID, *_TARGET),
        )
        for attempt_no in (1, 2):
            connection.execute(
                """INSERT INTO request_attempts VALUES (
                       ?, ?, ?, ?, ?, ?, 'weak_extractor', 'exact', 'terminal',
                       100, 50, 10, 10, 5, 2, 10, 5, 2, ?, 1,
                       NULL, NULL, NULL, NULL
                   )""",
                (
                    _ACCOUNT_ID,
                    *_TARGET,
                    "d" * 64,
                    attempt_no,
                    "9" * 64,
                    "c" * 64,
                ),
            )
    _downgrade_legacy_usage_schema(db_path, version=3, reservation_state="settled")

    migrated = BudgetLedger(db_path)

    snapshot = migrated.account_snapshot(_ACCOUNT_ID)
    assert snapshot.settled == _amounts(400, 200, 40)
    assert snapshot.overage is True
    with pytest.raises(BudgetLedgerError, match="overage"):
        migrated.reserve_product(_ACCOUNT_ID, *_TARGET, _amounts(250, 125, 25))


@pytest.mark.parametrize("wrong", ["primary-key", "foreign-key"])
def test_d1_3b_v4_claim_schema_wrong_pk_or_fk_fails_closed_without_repair(
    tmp_path: Path,
    wrong: str,
) -> None:
    db_path = tmp_path / f"{wrong}.sqlite3"
    _seed_settled_canary(db_path)
    schema_before = _replace_canary_claim_schema(db_path, wrong=wrong)

    with pytest.raises(BudgetLedgerError, match="claim"):
        BudgetLedger(db_path)

    with sqlite3.connect(db_path) as connection:
        schema_after = connection.execute(
            """SELECT sql FROM sqlite_master
               WHERE type='table' AND name='canary_capability_claims'"""
        ).fetchone()
        assert connection.execute("PRAGMA user_version").fetchone() == (8,)
    assert schema_after is not None
    assert str(schema_after[0]) == schema_before


def test_d1_5_public_settlement_snapshot_uses_one_consistent_read_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = _seed_settled_canary(db_path)
    first_read = Event()
    writer_committed = Event()
    original = BudgetLedger._product_settlement_snapshot

    def pause_after_first_read(
        connection: sqlite3.Connection,
        account_id: str,
        stage: str,
        product_id: str,
    ) -> ProductSettlementSnapshot:
        account = connection.execute(
            "SELECT current_revision FROM budget_accounts WHERE account_id=?",
            (account_id,),
        ).fetchone()
        assert account is not None and int(account[0]) == 1
        first_read.set()
        assert writer_committed.wait(timeout=5)
        return original(connection, account_id, stage, product_id)

    monkeypatch.setattr(
        BudgetLedger,
        "_product_settlement_snapshot",
        staticmethod(pause_after_first_read),
    )

    def mutate_after_first_read() -> None:
        assert first_read.wait(timeout=5)
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                "UPDATE request_attempts SET response_digest=? WHERE request_unit=?",
                ("a" * 64, "e" * 64),
            )
        writer_committed.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        writer = executor.submit(mutate_after_first_read)
        snapshot = ledger.product_settlement_snapshot(_ACCOUNT_ID, *_CANARY)
        writer.result(timeout=5)

    assert snapshot.attempts[0].response_digest == "c" * 64
    assert (
        BudgetLedger(db_path)
        .product_settlement_snapshot(_ACCOUNT_ID, *_CANARY)
        .attempts[0]
        .response_digest
        == "a" * 64
    )


def test_d1_3b_account_snapshot_uses_one_consistent_read_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = _seed_settled_canary(db_path)
    first_read = Event()
    writer_committed = Event()
    original = BudgetLedger._require_account

    def pause_after_account_read(
        connection: sqlite3.Connection,
        account_id: str,
    ) -> sqlite3.Row:
        account = original(connection, account_id)
        first_read.set()
        assert writer_committed.wait(timeout=5)
        return account

    monkeypatch.setattr(
        BudgetLedger,
        "_require_account",
        staticmethod(pause_after_account_read),
    )

    def mutate_after_account_read() -> None:
        assert first_read.wait(timeout=5)
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                """UPDATE product_reservations
                   SET actual_input=300,actual_output=150,actual_cost=6
                   WHERE account_id=? AND stage=? AND product_id=?""",
                (_ACCOUNT_ID, *_CANARY),
            )
            connection.execute(
                "UPDATE budget_accounts SET overage=1 WHERE account_id=?",
                (_ACCOUNT_ID,),
            )
        writer_committed.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        writer = executor.submit(mutate_after_account_read)
        snapshot = ledger.account_snapshot(_ACCOUNT_ID)
        writer.result(timeout=5)

    assert snapshot.settled == _amounts(200, 100, 4)
    assert snapshot.overage is False
    fresh = BudgetLedger(db_path).account_snapshot(_ACCOUNT_ID)
    assert fresh.settled == _amounts(300, 150, 6)
    assert fresh.overage is True


@pytest.mark.parametrize("defect", ["blob-type", "nullable", "missing-check"])
def test_d1_3b_v4_claim_schema_exact_shape_drift_fails_closed_without_repair(
    tmp_path: Path,
    defect: str,
) -> None:
    db_path = tmp_path / f"{defect}.sqlite3"
    _seed_settled_canary(db_path)
    schema_before = _mutate_current_canary_claim_schema(db_path, defect=defect)

    with pytest.raises(BudgetLedgerError, match="claim"):
        BudgetLedger(db_path)

    with sqlite3.connect(db_path) as connection:
        schema_after = connection.execute(
            """SELECT sql FROM sqlite_master
               WHERE type='table' AND name='canary_capability_claims'"""
        ).fetchone()
        assert connection.execute("PRAGMA user_version").fetchone() == (8,)
    assert schema_after is not None
    assert str(schema_after[0]) == schema_before
