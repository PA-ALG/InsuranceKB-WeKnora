#!/usr/bin/env bash
# I2a local staging runbook (docs/design/slices/I2a-本机测试环境.md).
#
# Copies the live stack (images, database, file volumes, configuration) into a separate colima
# profile and starts it on its own port. The live side is only read: `docker inspect`, `docker save`,
# `pg_dump` and `tar` through `docker exec`. Only an allow-list of non-secret settings is copied from
# live; staging generates its own secrets into mode-600 env files under $STAGING_HOME (never printed).
# Model API keys stored in the database stay encrypted with live's key, so re-enter them in staging.
#
# Usage: deploy/staging/staging.sh <env|images|restore|dns|up|ledger|status|stop>
set -euo pipefail

LIVE_CONTEXT="${LIVE_CONTEXT:-colima}"
STAGING_CONTEXT="${STAGING_CONTEXT:-colima-staging}"
STAGING_PROFILE="${STAGING_PROFILE:-staging}"
LIVE_PREFIX="${LIVE_PREFIX:-upg-final-082-20260928-live}"
STAGING_HOME="${STAGING_HOME:-$HOME/weknora-staging}"
HERE="$(cd "$(dirname "$0")" && pwd)"
SERVICES=(pg redis docreader app ui)

die() { echo "staging: $*" >&2; exit 1; }

guard() {
  [[ "$LIVE_CONTEXT" != "$STAGING_CONTEXT" ]] || die "staging context must differ from the live context"
  mkdir -p "$STAGING_HOME/logs"
  chmod 700 "$STAGING_HOME"
  if git -C "$STAGING_HOME" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    die "STAGING_HOME must not be inside a git work tree (it holds secrets)"
  fi
}

live() { docker --context "$LIVE_CONTEXT" "$@"; }
stage() { docker --context "$STAGING_CONTEXT" "$@"; }
compose() {
  local files=(-f "$HERE/compose.yaml")
  # I5: only a live app on a pre-I5 image mounts contracts/; staging mirrors that mount.
  if [[ -f "$STAGING_HOME/contracts.compose.yaml" ]]; then
    files+=(-f "$STAGING_HOME/contracts.compose.yaml")
  fi
  stage compose "${files[@]}" --env-file "$STAGING_HOME/images.env" "$@"
}

# env: write the per-service env files. Staging gets its OWN freshly generated secrets (kept in
# $STAGING_HOME/secrets.env and reused on later runs); live secrets are never copied. Only the
# allow-listed non-secret settings below are taken from the live containers. Consequence: model API
# keys stored in the restored database are encrypted with live's SYSTEM_AES_KEY and do not decrypt
# here, so they are re-entered in the staging UI (same as the I2 cloud plan).
cmd_env() {
  guard
  python3 -I - "$STAGING_HOME" "$LIVE_CONTEXT" "$LIVE_PREFIX" <<'PY'
import base64, json, os, secrets, subprocess, sys, tempfile
home, context, prefix = sys.argv[1:4]

def ed25519_key():
    # config.go: base64 raw-URL of a 64-byte Go ed25519.PrivateKey (seed || public key).
    with tempfile.TemporaryDirectory() as tmp:
        priv, pub = os.path.join(tmp, "k.der"), os.path.join(tmp, "p.der")
        subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-outform", "DER",
                        "-out", priv], check=True, capture_output=True)
        subprocess.run(["openssl", "pkey", "-inform", "DER", "-in", priv, "-pubout",
                        "-outform", "DER", "-out", pub], check=True, capture_output=True)
        seed, public = open(priv, "rb").read()[-32:], open(pub, "rb").read()[-32:]
    return base64.urlsafe_b64encode(seed + public).rstrip(b"=").decode()

def valid_ed25519(value):
    try:
        return len(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))) == 64
    except ValueError:
        return False
COPY = {
    "app": ["AUTO_MIGRATE", "AUTO_RECOVER_DIRTY", "BATCH_EMBED_SIZE", "BROWSERSKILL_BINARY",
            "BROWSERSKILL_EXTENSION_PATH", "DB_DRIVER", "DB_NAME", "DB_PORT", "DB_USER",
            "DISABLE_REGISTRATION", "DOCREADER_TRANSPORT", "DOCUMENT_STORAGE_MIN_FREE_BYTES",
            "ENTERPRISE_CONTRACTS_DIR", "ENTERPRISE_SPACES", "GIN_MODE", "GODEBUG", "GOMEMLIMIT",
            "KNOWLEDGE_REVISION_SOURCE_BACKFILL_ENABLED", "LOCAL_STORAGE_BASE_DIR",
            "MAX_FILE_SIZE_MB", "PORT", "REDIS_DB", "RETRIEVE_DRIVER", "SSRF_WHITELIST",
            "SSRF_WHITELIST_EXTRA", "STORAGE_TYPE", "WEKNORA_HOUSEKEEPING_ENABLED",
            "WEKNORA_SCHEMA_WIKI_C5_INPUT_MANIFEST", "WEKNORA_TENANT_ENABLE_CROSS_TENANT_ACCESS"],
    "pg": ["POSTGRES_USER", "POSTGRES_DB"],
    "redis": [],
    "docreader": ["DOCREADER_GRPC_PORT", "DOCREADER_GRPC_MAX_FILE_SIZE_MB", "DOCREADER_ODL_HYBRID",
                  "DOCREADER_ODL_HYBRID_URL"],
    "ui": ["MAX_FILE_SIZE_MB"],
}
SECRET_NAMES = ["STAGING_DB_PASSWORD", "STAGING_REDIS_PASSWORD", "JWT_SECRET", "SYSTEM_AES_KEY",
                "E2E_CITATION_SIGNING_KEY"]

def write(name, pairs):
    fd = os.open(os.path.join(home, name), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:
        for key, value in pairs:
            if "'" in value or "\n" in value:
                sys.exit(f"staging: {name} {key} has a quote or newline; set it by hand")
            out.write(f"{key}='{value}'\n")

secret_path = os.path.join(home, "secrets.env")
generated = {}
if os.path.exists(secret_path):
    for line in open(secret_path):
        key, _, value = line.rstrip("\n").partition("=")
        generated[key] = value.strip("'")
for name in SECRET_NAMES:
    if name == "E2E_CITATION_SIGNING_KEY":
        if not valid_ed25519(generated.get(name, "")):
            generated[name] = ed25519_key()
    elif not generated.get(name):
        # SYSTEM_AES_KEY must be exactly 32 bytes (internal/utils/crypto.go GetAESKey).
        generated[name] = secrets.token_hex(16)
write("secrets.env", [(k, generated[k]) for k in SECRET_NAMES])

for svc, keys in COPY.items():
    raw = subprocess.run(["docker", "--context", context, "inspect", f"{prefix}-{svc}"],
                         check=True, capture_output=True).stdout
    env = dict(item.partition("=")[::2] for item in json.loads(raw)[0]["Config"]["Env"] or [])
    pairs = [(k, env[k]) for k in keys if k in env]
    copied = len(pairs)
    if svc == "app":
        pairs += [("DB_PASSWORD", generated["STAGING_DB_PASSWORD"]),
                  ("REDIS_PASSWORD", generated["STAGING_REDIS_PASSWORD"]),
                  ("JWT_SECRET", generated["JWT_SECRET"]),
                  ("SYSTEM_AES_KEY", generated["SYSTEM_AES_KEY"]),
                  ("E2E_CITATION_SIGNING_KEY", generated["E2E_CITATION_SIGNING_KEY"])]
    if svc == "pg":
        pairs.append(("POSTGRES_PASSWORD", generated["STAGING_DB_PASSWORD"]))
    if svc == "redis":
        pairs.append(("REDIS_PASSWORD", generated["STAGING_REDIS_PASSWORD"]))
    write(f"{svc}.env", pairs)
    print(f"{svc}.env: {copied} copied, {len(pairs) - copied} generated")
PY
}

# images: copy the exact live image IDs into the staging VM and tag them locally.
cmd_images() {
  guard
  local out="$STAGING_HOME/images.env.tmp"
  : >"$out"
  for svc in "${SERVICES[@]}"; do
    local id tag
    id="$(live inspect -f '{{.Image}}' "$LIVE_PREFIX-$svc")"
    tag="insurancekb-staging/$svc:${id:7:12}"
    if ! stage image inspect "$id" >/dev/null 2>&1; then
      echo "copying $svc image ${id:0:19}"
      live save "$id" | stage load >/dev/null
    fi
    stage tag "$id" "$tag"
    echo "STAGING_$(echo "$svc" | tr '[:lower:]' '[:upper:]')_IMAGE=$tag" >>"$out"
  done
  local cfg contracts
  cfg="$(live inspect -f '{{range .Mounts}}{{if eq .Destination "/app/config/config.yaml"}}{{.Source}}{{end}}{{end}}' "$LIVE_PREFIX-app")"
  # The trailing `x` keeps trailing newlines of the source from being dropped by `$(...)` (I5).
  contracts="$(live inspect -f '{{range .Mounts}}{{if eq .Destination "/app/contracts"}}{{.Source}}{{end}}{{end}}x' "$LIVE_PREFIX-app")"
  contracts="${contracts%x}"
  [[ -n "$cfg" ]] || die "live app config mount not found"
  # I5: images built after I5 ship contracts/ (no mount); a pre-I5 live app mounts them.
  if [[ -n "$contracts" ]]; then
    # The path goes into a YAML double-quoted short-syntax entry: refuse what would change it there
    # (line folding, escapes, Compose `$` interpolation, the `:` separator) instead of escaping.
    [[ "$contracts" != *[[:cntrl:]\"\\\$:]* ]] \
      || die "live contracts mount path has a control character, quote, backslash, \$ or :"
    printf 'services:\n  app:\n    volumes:\n      - "%s:/app/contracts:ro"\n' "$contracts" \
      >"$STAGING_HOME/contracts.compose.yaml"
  else
    rm -f "$STAGING_HOME/contracts.compose.yaml"
  fi
  {
    echo "STAGING_HOME=$STAGING_HOME"
    echo "STAGING_CONFIG_YAML=$cfg"
    echo "STAGING_UI_PORT=${STAGING_UI_PORT:-18395}"
  } >>"$out"
  mv "$out" "$STAGING_HOME/images.env"
  chmod 600 "$STAGING_HOME/images.env"
}

db_setting() {  # print a non-secret app setting (DB_NAME or DB_USER) from the live app
  live inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$LIVE_PREFIX-app" | sed -n "s/^$1=//p"
}

# restore: database (pg_dump custom format, streamed) and the two file volumes.
cmd_restore() {
  guard
  local db user started log
  db="$(db_setting DB_NAME)"; user="$(db_setting DB_USER)"
  [[ -n "$db" && -n "$user" ]] || die "DB_NAME/DB_USER not found on the live app"
  compose up -d pg
  for _ in $(seq 1 60); do
    [[ "$(stage inspect -f '{{.State.Health.Status}}' insurancekb-staging-pg-1)" == healthy ]] && break
    sleep 2
  done
  if [[ "$(compose exec -T pg psql -U "$user" -d postgres -Atc "select 1 from pg_database where datname='$db'")" == 1 ]]; then
    die "database $db already exists in staging; remove the staging stack and its volumes to restore again"
  fi
  compose exec -T pg psql -U "$user" -d postgres -c "create database \"$db\" owner \"$user\"" >/dev/null
  started=$(date +%s); log="$STAGING_HOME/logs/pg_restore-$(date +%Y%m%d-%H%M%S).log"
  # pg_restore exits non-zero for ignorable warnings (e.g. grants to roles that only exist on live);
  # the dump side must succeed.
  set +e
  live exec "$LIVE_PREFIX-pg" pg_dump -U "$user" -Fc "$db" \
    | compose exec -T pg pg_restore -U "$user" -d "$db" 2>"$log"
  local codes=("${PIPESTATUS[@]}")
  set -e
  [[ "${codes[0]}" == 0 ]] || die "pg_dump failed (exit ${codes[0]})"
  echo "database restored in $(( $(date +%s) - started ))s; pg_restore exit ${codes[1]}, messages: $(grep -c . "$log" || true) (log: $log)"
  local app_tag
  app_tag="$(sed -n 's/^STAGING_APP_IMAGE=//p' "$STAGING_HOME/images.env")"
  for pair in "files:/data/files" "c5:/run/insurancekb/c5"; do
    local vol="${pair%%:*}" src="${pair#*:}"
    stage volume create "insurancekb-staging_$vol" >/dev/null
    started=$(date +%s)
    live exec "$LIVE_PREFIX-app" tar -C "$src" -cf - . \
      | stage run --rm -i --user 0 --network none --entrypoint tar \
          -v "insurancekb-staging_$vol:/dst" "$app_tag" -C /dst --numeric-owner -xpf -
    echo "volume $vol restored in $(( $(date +%s) - started ))s"
  done
}

# dns: a fresh colima profile can boot with /etc/resolv.conf still linked to systemd-resolved's
# stub while that service is inactive, so nothing resolves (seen 2026-10-30). Point the staging VM at
# its own user-network gateway, never at the live VM.
cmd_dns() {
  guard
  if colima ssh -p "$STAGING_PROFILE" -- getent hosts api.deepseek.com >/dev/null 2>&1; then
    echo "staging VM resolves names"; return
  fi
  local gw
  gw="$(colima ssh -p "$STAGING_PROFILE" -- ip route | awk '/^default/ {print $3; exit}')"
  [[ -n "$gw" ]] || die "no default route in the staging VM"
  colima ssh -p "$STAGING_PROFILE" -- sh -c \
    "sudo rm -f /etc/resolv.conf && printf 'nameserver %s\n' '$gw' | sudo tee /etc/resolv.conf >/dev/null"
  colima ssh -p "$STAGING_PROFILE" -- getent hosts api.deepseek.com >/dev/null || die "still no DNS"
  echo "staging VM now resolves via $gw; recreate running containers (staging.sh up)"
}

cmd_up() { guard; compose up -d --force-recreate; compose ps --format '{{.Service}} {{.Status}}'; }

# ledger: both migration ledgers must equal live; nothing may have migrated.
cmd_ledger() {
  guard
  local db user q
  db="$(db_setting DB_NAME)"; user="$(db_setting DB_USER)"
  q="select 'official', version, dirty from schema_migrations union all select 'enterprise', version, dirty from enterprise_schema_migrations"
  echo "live:    $(live exec "$LIVE_PREFIX-pg" psql -U "$user" -d "$db" -Atc "$q" | tr '\n' ' ')"
  echo "staging: $(compose exec -T pg psql -U "$user" -d "$db" -Atc "$q" | tr '\n' ' ')"
}

cmd_status() {
  guard
  compose ps --format '{{.Service}} {{.Status}}' || true
  colima ssh -p "$STAGING_PROFILE" -- df -h /var/lib/docker | tail -1
  colima ssh -p default -- df -h /var/lib/docker | tail -1
}

# stop: stop the stack and the staging VM; live is not touched.
cmd_stop() { guard; compose stop || true; colima stop -p "$STAGING_PROFILE"; docker context use "$LIVE_CONTEXT" >/dev/null; }

case "${1:-}" in
  env) cmd_env ;;
  images) cmd_images ;;
  restore) cmd_restore ;;
  dns) cmd_dns ;;
  up) cmd_up ;;
  ledger) cmd_ledger ;;
  status) cmd_status ;;
  stop) cmd_stop ;;
  *) die "usage: $0 <env|images|restore|dns|up|ledger|status|stop>" ;;
esac
