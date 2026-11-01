"""A synthetic product repository in a temporary git checkout (PV-1 review R2, R3)."""

import json
import subprocess
from pathlib import Path


def git(directory: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(directory), *args], capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


def meta(plan: str, number: int, name: str, code: str, **override: str) -> dict[str, str]:
    data = {
        "planCode": plan,
        "actualPlanCode": plan,
        "versionNo": f"{plan}-{number}",
        "clauseName": name,
        "planSalesStatus": "在售",
        "planPlanType": "普通型",
        "planSalesChannel": "个人代理",
        "startDate": "2025-10-01",
        "sccode": code,
    }
    data.update(override)
    return data


def write_meta(root: Path, tree: str, folder: str, content: dict[str, str] | str) -> Path:
    path = root / tree / folder / "product_meta.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    path.write_text(text, encoding="utf-8")
    return path


def repository(root: Path, *entries: tuple[str, str, dict[str, str] | str]) -> str:
    """A committed repository holding these (tree, folder, meta) entries; its commit SHA."""
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "test")
    git(root, "config", "commit.gpgsign", "false")
    for tree, folder, content in entries:
        write_meta(root, tree, folder, content)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "products")
    return git(root, "rev-parse", "HEAD")
