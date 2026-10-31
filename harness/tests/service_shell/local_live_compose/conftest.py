"""OpenSpec 023 local-live compose and runtime-environment contracts: shared paths and images."""

from __future__ import annotations

import pytest


@pytest.fixture
def compliant_rendered_compose() -> dict[str, object]:
    return {
        "services": {
            "app": {
                "image": "example/app:1.2.3@sha256:" + "a" * 64,
                "ports": [{"host_ip": "127.0.0.1", "published": "8080", "target": 8080}],
                "environment": {
                    "TENANT_AES_KEY": "t" * 32,
                    "SYSTEM_AES_KEY": "s" * 32,
                },
                "healthcheck": {"test": ["CMD", "true"]},
            },
            "frontend": {
                "image": "example/frontend:1.2.3@sha256:" + "b" * 64,
                "ports": [{"host_ip": "127.0.0.1", "published": "8081", "target": 80}],
                "healthcheck": {"test": ["CMD", "true"]},
            },
            "harness-postgres": {
                "image": "postgres:16.4@sha256:" + "c" * 64,
                "ports": [{"host_ip": "127.0.0.1", "published": "5442", "target": 5432}],
                "environment": {"POSTGRES_PASSWORD": "random-local-secret"},
                "healthcheck": {"test": ["CMD-SHELL", "pg_isready"]},
            },
            "redis": {
                "image": "redis:7.0-alpine@sha256:" + "d" * 64,
                "healthcheck": {"test": ["CMD", "redis-cli", "ping"]},
            },
            "postgres": {
                "image": "example/postgres:17@sha256:" + "e" * 64,
                "healthcheck": {"test": ["CMD", "pg_isready"]},
            },
            "docreader": {
                "image": "example/docreader:1.2.3@sha256:" + "f" * 64,
                "healthcheck": {"test": ["CMD", "grpc_health_probe"]},
            },
        }
    }


@pytest.fixture
def compliant_lock() -> dict[str, str]:
    return {
        "app": "example/app:1.2.3@sha256:" + "a" * 64,
        "frontend": "example/frontend:1.2.3@sha256:" + "b" * 64,
        "harness-postgres": "postgres:16.4@sha256:" + "c" * 64,
        "redis": "redis:7.0-alpine@sha256:" + "d" * 64,
        "postgres": "example/postgres:17@sha256:" + "e" * 64,
        "docreader": "example/docreader:1.2.3@sha256:" + "f" * 64,
    }
