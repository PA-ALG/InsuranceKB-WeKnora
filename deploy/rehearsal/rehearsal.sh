#!/usr/bin/env bash
# I3a fresh-install rehearsal runbook (docs/design/slices/I3-私有化演练.md §1, deploy/rehearsal/README.md).
#
# Installs the stack from images pinned by digest (images.lock) into its own empty colima profile,
# runs the official and enterprise migrations from zero, seeds a minimal tenant/Space, and smoke-tests.
# The live environment is never touched except, with `images --from-live`, a read-only `docker save`
# of the exact live image IDs while CI images are not yet available. Secrets are generated into
# $REHEARSAL_HOME (mode 600, outside any repository) and are never printed.
#
# Usage: deploy/rehearsal/rehearsal.sh <profile|images [--from-live|--from-ghcr]|env|dns|up|ledger|
#        seed|smoke|status|down|destroy>
# Settings (environment): REHEARSAL_DISK_ROOT (required by profile/destroy: a directory on another
# disk for the VM data disk), REHEARSAL_HOME (default ~/weknora-rehearsal), REHEARSAL_PROFILE
# (default rehearsal), REHEARSAL_UI_PORT (default 18495), REHEARSAL_PRODUCT (default 1818),
# LIVE_CONTEXT (default colima). seed/smoke read DEEPSEEK_API_KEY (or HARNESS_SCHEMA_FIELDS_API_KEY)
# and DASHSCOPE_API_KEY.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
LIVE_CONTEXT="${LIVE_CONTEXT:-colima}"
PROFILE="${REHEARSAL_PROFILE:-rehearsal}"
CONTEXT="colima-$PROFILE"
REHEARSAL_HOME="${REHEARSAL_HOME:-$HOME/weknora-rehearsal}"
# A directory on another disk for the VM data disk, so the rehearsal never fills the live disk.
DISK_ROOT="${REHEARSAL_DISK_ROOT:-}"
UI_PORT="${REHEARSAL_UI_PORT:-18495}"
SERVICES=(pg redis docreader app ui)

die() { echo "rehearsal: $*" >&2; exit 1; }
log() { echo "[$(date -u +%H:%M:%S)] $*"; }

guard() {
  [[ "$CONTEXT" != "$LIVE_CONTEXT" ]] || die "rehearsal context must differ from the live context"
  [[ "$PROFILE" != default && "$PROFILE" != staging ]] || die "refusing to use profile $PROFILE"
  mkdir -p "$REHEARSAL_HOME/logs"
  chmod 700 "$REHEARSAL_HOME"
  if git -C "$REHEARSAL_HOME" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    die "REHEARSAL_HOME must not be inside a git work tree (it holds secrets)"
  fi
}
rehearse() { docker --context "$CONTEXT" "$@"; }
compose() {
  REHEARSAL_HOME="$REHEARSAL_HOME" REHEARSAL_DEFAULTS="$HERE/app.defaults.env" \
    REHEARSAL_CONTRACTS_DIR="$REPO/contracts" REHEARSAL_UI_PORT="$UI_PORT" \
    rehearse compose -f "$HERE/compose.yaml" --env-file "$REHEARSAL_HOME/images.env" "$@"
}
live_disk() { colima ssh -p default -- df -h /var/lib/docker | tail -1; }

# profile: create the empty VM with its data disk under REHEARSAL_DISK_ROOT (same layout as staging).
cmd_profile() {
  guard
  if colima list 2>/dev/null | awk '{print $1}' | grep -qx "$PROFILE"; then
    die "profile $PROFILE already exists (run destroy first for a clean rehearsal)"
  fi
  [[ -n "$DISK_ROOT" && -d "$DISK_ROOT" ]] \
    || die "set REHEARSAL_DISK_ROOT to a mounted directory on another disk"
  log "live disk before: $(live_disk)"
  colima start -p "$PROFILE" --cpu 4 --memory 5 --disk 40 --vm-type vz >/dev/null
  colima stop -p "$PROFILE" >/dev/null
  local lima_disk="$HOME/.colima/_lima/_disks/colima-$PROFILE/datadisk"
  local ext="$DISK_ROOT/colima-$PROFILE"
  mkdir -p "$ext"
  [[ -f "$lima_disk" && ! -L "$lima_disk" ]] || die "unexpected data disk layout at $lima_disk"
  cp -c "$lima_disk" "$ext/datadisk" 2>/dev/null || cp "$lima_disk" "$ext/datadisk"
  rm "$lima_disk"
  ln -s "$ext/datadisk" "$lima_disk"
  colima start -p "$PROFILE" >/dev/null
  docker context use "$LIVE_CONTEXT" >/dev/null
  log "profile $PROFILE up; data disk on $ext"
}

# images: product images by digest from GHCR (default) or, while CI images are missing, the exact
# live image IDs copied read-only from the live VM; base services by digest from their registries.
cmd_images() {
  guard
  local mode="${1:---from-ghcr}"
  # shellcheck disable=SC1091
  source "$HERE/images.lock"
  local out="$REHEARSAL_HOME/images.env.tmp"
  : >"$out"
  for svc in pg redis; do
    local ref var
    var="REHEARSAL_$(echo "$svc" | tr '[:lower:]' '[:upper:]')_IMAGE"
    ref="${!var}"
    rehearse image inspect "$ref" >/dev/null 2>&1 || rehearse pull -q "$ref" >/dev/null
    echo "$var=$ref" >>"$out"
  done
  for svc in app ui docreader; do
    local upper ref
    upper="$(echo "$svc" | tr '[:lower:]' '[:upper:]')"
    if [[ "$mode" == "--from-live" ]]; then
      local var="REHEARSAL_${upper}_IMAGE_LIVE"
      ref="${!var}"
      if ! rehearse image inspect "$ref" >/dev/null 2>&1; then
        log "copying $svc ${ref:0:19} from the live VM (read-only docker save)"
        docker --context "$LIVE_CONTEXT" save "$ref" | rehearse load >/dev/null
      fi
    else
      local var="REHEARSAL_${upper}_IMAGE_CI"
      ref="${!var}"
      [[ -n "$ref" ]] || die "no CI digest for $svc in images.lock (use --from-live until I1 publishes)"
      rehearse image inspect "$ref" >/dev/null 2>&1 || rehearse pull -q "$ref" >/dev/null
    fi
    echo "REHEARSAL_${upper}_IMAGE=$ref" >>"$out"
  done
  mv "$out" "$REHEARSAL_HOME/images.env"
  chmod 600 "$REHEARSAL_HOME/images.env"
  write_config
  log "images ready ($mode); live disk: $(live_disk)"
}

# The App image's config.yaml has no artifact signing ring, which publishing requires once
# ENTERPRISE_SPACES is set (releasestore.LoadSpaces) and which cannot be given through env alone
# (rehearsal finding F3). Take the image's own file and append the ring; the key stays a
# ${E2E_CITATION_SIGNING_KEY} placeholder the App expands at start, so the file holds no secret.
write_config() {
  local app container
  app="$(grep '^REHEARSAL_APP_IMAGE=' "$REHEARSAL_HOME/images.env" | cut -d= -f2-)"
  container="$(rehearse create "$app")"
  rehearse cp "$container:/app/config/config.yaml" "$REHEARSAL_HOME/config.yaml" >/dev/null
  rehearse rm "$container" >/dev/null
  if grep -q '^schema_wiki_signing:' "$REHEARSAL_HOME/config.yaml"; then
    log "image config already carries a signing ring; left unchanged"; return
  fi
  cat >>"$REHEARSAL_HOME/config.yaml" <<'YAML'

# Added by deploy/rehearsal/rehearsal.sh: the capture/citation signing ring (Ed25519, RawURL base64).
schema_wiki_signing:
  citation_token_signing_keys:
    - key_id: rehearsal-citation-1
      private_key_base64: ${E2E_CITATION_SIGNING_KEY}
  active_citation_token_key_id: rehearsal-citation-1
YAML
}

# env: generated secrets only; nothing copied from live.
cmd_env() {
  guard
  python3 -I - "$REHEARSAL_HOME" <<'PY'
import base64, os, secrets, subprocess, sys, tempfile
home = sys.argv[1]

def ed25519_key():
    with tempfile.TemporaryDirectory() as tmp:
        priv, pub = os.path.join(tmp, "k.der"), os.path.join(tmp, "p.der")
        subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-outform", "DER",
                        "-out", priv], check=True, capture_output=True)
        subprocess.run(["openssl", "pkey", "-inform", "DER", "-in", priv, "-pubout",
                        "-outform", "DER", "-out", pub], check=True, capture_output=True)
        seed, public = open(priv, "rb").read()[-32:], open(pub, "rb").read()[-32:]
    return base64.urlsafe_b64encode(seed + public).rstrip(b"=").decode()

def write(name, pairs):
    fd = os.open(os.path.join(home, name), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:
        for key, value in pairs:
            out.write(f"{key}={value}\n")

path = os.path.join(home, "secrets.env")
known = {}
if os.path.exists(path):
    for line in open(path):
        key, _, value = line.rstrip("\n").partition("=")
        known[key] = value
for name in ("DB_PASSWORD", "REDIS_PASSWORD", "JWT_SECRET", "SYSTEM_AES_KEY"):
    known.setdefault(name, secrets.token_hex(16))
known.setdefault("E2E_CITATION_SIGNING_KEY", ed25519_key())
write("secrets.env", sorted(known.items()))
write("app.env", [(k, known[k]) for k in ("DB_PASSWORD", "REDIS_PASSWORD", "JWT_SECRET",
                                          "SYSTEM_AES_KEY", "E2E_CITATION_SIGNING_KEY")])
write("pg.env", [("POSTGRES_USER", "weknora"), ("POSTGRES_DB", "weknora"),
                 ("POSTGRES_PASSWORD", known["DB_PASSWORD"])])
write("redis.env", [("REDIS_PASSWORD", known["REDIS_PASSWORD"])])
if not os.path.exists(os.path.join(home, "spaces.env")):
    write("spaces.env", [])  # filled by `seed` once the knowledge bases exist
print("env files written (secrets generated locally, never printed)")
PY
}

# dns: a fresh colima profile can boot with /etc/resolv.conf linked to an inactive systemd-resolved
# stub (seen on staging 2026-10-30); point the rehearsal VM at its own gateway.
cmd_dns() {
  guard
  if colima ssh -p "$PROFILE" -- getent hosts api.deepseek.com >/dev/null 2>&1; then
    log "rehearsal VM resolves names"; return
  fi
  local gw
  gw="$(colima ssh -p "$PROFILE" -- ip route | awk '/^default/ {print $3; exit}')"
  [[ -n "$gw" ]] || die "no default route in the rehearsal VM"
  colima ssh -p "$PROFILE" -- sh -c \
    "sudo rm -f /etc/resolv.conf && printf 'nameserver %s\n' '$gw' | sudo tee /etc/resolv.conf >/dev/null"
  colima ssh -p "$PROFILE" -- getent hosts api.deepseek.com >/dev/null || die "still no DNS"
  log "rehearsal VM now resolves via $gw"
}

# The App answers through the UI's proxy; /health alone is served by nginx even while the App is down.
wait_app() {
  for _ in $(seq 1 120); do
    [[ "$(curl -s -o /dev/null -m 5 -w '%{http_code}' "http://127.0.0.1:$UI_PORT/api/v1/auth/config")" == 200 ]] \
      && return 0
    sleep 3
  done
  die "the App did not answer through the UI in 6 min"
}

# up: start the stack; the App applies official then enterprise migrations from zero (AUTO_MIGRATE).
cmd_up() {
  guard
  local started=$(date +%s)
  compose up -d
  wait_app
  log "stack healthy in $(( $(date +%s) - started ))s"
  compose ps --format '{{.Service}} {{.Status}}'
}

# ledger: prove the migrations by ledger state (not logs).
cmd_ledger() {
  guard
  compose exec -T pg psql -U weknora -d weknora -Atc \
    "select 'official', version, dirty from schema_migrations
     union all select 'enterprise', version, dirty from enterprise_schema_migrations"
}

cmd_status() {
  guard
  compose ps --format '{{.Service}} {{.Status}}' || true
  colima ssh -p "$PROFILE" -- df -h /var/lib/docker | tail -1
  log "live disk: $(live_disk)"
}

# seed / smoke live in seed.py (API calls; model keys read from the environment, never printed).
seed_py() {
  python3 -I "$HERE/seed.py" "$1" --base "http://127.0.0.1:$UI_PORT" --home "$REHEARSAL_HOME" \
    --repo "$REPO" --product "${REHEARSAL_PRODUCT:-1818}"
}
cmd_seed() {
  guard
  [[ -x "$REPO/harness/.venv/bin/python" ]] || die "run uv sync in $REPO/harness first"
  local step started
  for step in platform materials harness; do
    started=$(date +%s)
    seed_py "$step" | tee -a "$REHEARSAL_HOME/logs/seed.jsonl"
    log "seed $step done in $(( $(date +%s) - started ))s"
    if [[ "$step" == platform ]]; then
      compose up -d app >/dev/null  # recreate: ENTERPRISE_SPACES is read at start
      wait_app
    fi
  done
}
cmd_smoke() { guard; seed_py smoke | tee -a "$REHEARSAL_HOME/logs/smoke.jsonl"; }

# down: stop the stack and the VM (keeps data); destroy: delete the profile and its external disk.
cmd_down() { guard; compose stop || true; colima stop -p "$PROFILE"; docker context use "$LIVE_CONTEXT" >/dev/null; }
cmd_destroy() {
  guard
  colima delete -p "$PROFILE" --force >/dev/null 2>&1 || true
  local ext="$DISK_ROOT/colima-$PROFILE"
  if [[ -n "$DISK_ROOT" && -d "$ext" ]]; then
    rm -f "$ext/datadisk"
    rmdir "$ext"
  fi
  docker context use "$LIVE_CONTEXT" >/dev/null
  log "profile $PROFILE deleted; secrets remain in $REHEARSAL_HOME (remove by hand)"
}

case "${1:-}" in
  profile) cmd_profile ;;
  images) cmd_images "${2:-}" ;;
  env) cmd_env ;;
  dns) cmd_dns ;;
  up) cmd_up ;;
  ledger) cmd_ledger ;;
  seed) cmd_seed ;;
  smoke) cmd_smoke ;;
  status) cmd_status ;;
  down) cmd_down ;;
  destroy) cmd_destroy ;;
  *) die "usage: rehearsal.sh <profile|images [--from-live|--from-ghcr]|env|dns|up|ledger|seed|smoke|status|down|destroy>" ;;
esac
