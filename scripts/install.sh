#!/usr/bin/env bash
# InsuranceKB Harness 一键安装
# 用法：./scripts/install.sh [--no-db] [--no-test]
#   --no-db    跳过启动 Harness Postgres（无 docker 环境时）
#   --no-test  跳过安装后自检（ruff/pytest）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NO_DB=0; NO_TEST=0
for a in "$@"; do case "$a" in --no-db) NO_DB=1;; --no-test) NO_TEST=1;; esac; done

info(){ printf '\033[1;32m[install]\033[0m %s\n' "$*"; }
warn(){ printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
die(){ printf '\033[1;31m[error]\033[0m %s\n' "$*"; exit 1; }

# 0) 代理坑提示（HANDOFF 坑 #9：SOCKS 代理变量会干扰 httpx/git）
if [ -n "${ALL_PROXY:-}${all_proxy:-}" ]; then
  warn "检测到 ALL_PROXY 代理变量——harness 的 HTTP 客户端已用 trust_env=False 规避；"
  warn "但本脚本的下载步骤将临时绕开代理（如需代理下载请自行调整）。"
fi

# 1) 依赖检查
info "检查依赖……"
command -v git >/dev/null || die "缺少 git"
if ! command -v docker >/dev/null && [ "$NO_DB" = 0 ]; then
  warn "未找到 docker——将跳过数据库启动（等价于 --no-db；DB 相关功能需自备 Postgres）"
  NO_DB=1
fi

# 2) uv（Python 包管理器；官方安装脚本，幂等）
if ! command -v uv >/dev/null && [ ! -x "$HOME/.local/bin/uv" ]; then
  info "安装 uv……"
  env -u ALL_PROXY -u all_proxy curl -LsSf https://astral.sh/uv/install.sh | sh || die "uv 安装失败（网络？）"
fi
export PATH="$HOME/.local/bin:$PATH"
info "uv $(uv --version | head -1)"

# 3) Python 3.12+（uv 自动管理）
uv python install 3.12 >/dev/null 2>&1 || true

# 4) 安装 harness 依赖（uv.lock 锁定版本）
info "安装 harness 依赖……"
cd "$ROOT/harness"
uv sync || { warn "uv sync 失败，重试一次（网络抖动常见）"; sleep 3; uv sync; }

# 5) 配置模板
if [ ! -f .env ]; then
  cp .env.example .env
  warn "已生成 harness/.env（从模板）——请填入 WeKnora 与模型网关的真实密钥后再跑联调"
else
  info "harness/.env 已存在，跳过"
fi

# 6) Harness Postgres + 迁移
if [ "$NO_DB" = 0 ]; then
  info "启动 Harness Postgres（docker-compose.harness.yml）……"
  docker compose -f "$ROOT/docker-compose.harness.yml" up -d
  info "执行数据库迁移……"
  uv run alembic upgrade head
else
  warn "跳过数据库：需要时执行 docker compose -f docker-compose.harness.yml up -d && (cd harness && uv run alembic upgrade head)"
fi

# 7) 自检
if [ "$NO_TEST" = 0 ]; then
  info "自检：ruff + 单元测试（不含 live 用例）……"
  uv run ruff check . >/dev/null && info "ruff ✅"
  uv run pytest -m "not live" -q | tail -1
fi

cat <<'EOF'

✅ 安装完成。下一步：
  1. 填 harness/.env（WeKnora API Key、模型网关 Key）
  2. 启动 WeKnora 平台并初始化双知识库：docs/insurance-kb/14-deployment-runbook.md §2
  3. 注册样本产品：cd harness && uv run python -m insurance_harness.product.cli register-products ../dataset/shouxian_product
  4. 联调验收 L1~L6：14 号文档 §4
接手开发请读：HANDOFF.md（AI 会话会自动加载根目录 CLAUDE.md 的项目约定）
EOF
