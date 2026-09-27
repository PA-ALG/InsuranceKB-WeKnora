#!/usr/bin/env bash
set -euo pipefail

: "${BROWSERSKILL_VERSION:?BROWSERSKILL_VERSION is required}"
: "${BROWSERSKILL_SOURCE_COMMIT:?BROWSERSKILL_SOURCE_COMMIT is required}"
: "${BROWSERSKILL_SOURCE_PLATFORM:?BROWSERSKILL_SOURCE_PLATFORM is required}"
: "${BROWSERSKILL_SOURCE_ORIGIN:?BROWSERSKILL_SOURCE_ORIGIN is required}"
: "${BROWSERSKILL_SOURCE_SHA256:?BROWSERSKILL_SOURCE_SHA256 is required}"
: "${PNPM_VERSION:?PNPM_VERSION is required}"
: "${PNPM_PLATFORM:?PNPM_PLATFORM is required}"
: "${PNPM_ORIGIN:?PNPM_ORIGIN is required}"
: "${PNPM_SHA256:?PNPM_SHA256 is required}"
: "${PNPM_STORE_DIR:?PNPM_STORE_DIR is required}"
: "${CARGO_TARGET_DIR:?CARGO_TARGET_DIR is required}"
: "${RUSTUP_TOOLCHAIN:?RUSTUP_TOOLCHAIN is required}"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="${1:-$repo_root/artifacts/browserskill}"
target_platform="${2:-}"
case "$target_platform" in
  ""|linux/amd64|linux/arm64|darwin/amd64|darwin/arm64) ;;
  *) echo "Unsupported BrowserSkill target: $target_platform" >&2; exit 1 ;;
esac

release_manifest="$repo_root/scripts/browserskill-release.json"
source_commit="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["extension"]["source_commit"])' "$release_manifest")"
daemon_commit="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["daemon"]["source_commit"])' "$release_manifest")"
extension_version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["extension"]["version"])' "$release_manifest")"
release_version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$release_manifest")"
[ "$source_commit" = "$daemon_commit" ] || { echo "BrowserSkill daemon/extension baseline mismatch" >&2; exit 1; }
[ "$source_commit" = "$BROWSERSKILL_SOURCE_COMMIT" ] || { echo "BrowserSkill source lock mismatch" >&2; exit 1; }
[ "$extension_version" = "$release_version" ] || { echo "BrowserSkill release version mismatch" >&2; exit 1; }
[ "$extension_version" = "$BROWSERSKILL_VERSION" ] || { echo "BrowserSkill dependency lock version mismatch" >&2; exit 1; }
[ "$BROWSERSKILL_SOURCE_PLATFORM" = "source" ] || { echo "Unsupported BrowserSkill source platform" >&2; exit 1; }
[ "$PNPM_PLATFORM" = "source" ] || { echo "Unsupported pnpm source platform" >&2; exit 1; }
case "$BROWSERSKILL_SOURCE_ORIGIN" in
  *"$BROWSERSKILL_SOURCE_COMMIT"*) ;;
  *) echo "BrowserSkill source origin does not name the locked commit" >&2; exit 1 ;;
esac

host_os="$(uname -s | tr '[:upper:]' '[:lower:]')"
host_arch="$(uname -m)"
case "$host_arch" in arm64|aarch64) host_arch=arm64 ;; x86_64) host_arch=amd64 ;; esac
if [ -n "$target_platform" ] && [ "$target_platform" != "$host_os/$host_arch" ]; then
  echo "Run the BrowserSkill build on $target_platform (host is $host_os/$host_arch)" >&2
  exit 1
fi
command -v cargo >/dev/null || { echo "Rust/Cargo is required to build BrowserSkill" >&2; exit 1; }

verify_sha256() {
  local expected="$1"
  local path="$2"
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s  %s\n' "$expected" "$path" | sha256sum -c -
  else
    printf '%s  %s\n' "$expected" "$path" | shasum -a 256 -c -
  fi
}

mkdir -p "$output_dir" "$PNPM_STORE_DIR" "$CARGO_TARGET_DIR"
output_dir="$(cd "$output_dir" && pwd)"
build_dir="$(mktemp -d /tmp/weknora-bsk-build.XXXXXX)"
trap 'rm -rf "$build_dir"' EXIT

source_archive="$build_dir/browserskill.tar.gz"
pnpm_archive="$build_dir/pnpm.tgz"
curl -fsSL "$BROWSERSKILL_SOURCE_ORIGIN" -o "$source_archive"
verify_sha256 "$BROWSERSKILL_SOURCE_SHA256" "$source_archive"
curl -fsSL "$PNPM_ORIGIN" -o "$pnpm_archive"
verify_sha256 "$PNPM_SHA256" "$pnpm_archive"

mkdir -p "$build_dir/source" "$build_dir/pnpm"
tar -xzf "$source_archive" -C "$build_dir/source" --strip-components=1
tar -xzf "$pnpm_archive" -C "$build_dir/pnpm"
package_manager="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["packageManager"])' "$build_dir/source/package.json")"
[ "$package_manager" = "pnpm@$PNPM_VERSION" ] || { echo "BrowserSkill pnpm lock mismatch" >&2; exit 1; }

# Lifecycle scripts start child shells, so the verified package manager must be
# an executable on PATH rather than a function visible only to this shell.
mkdir -p "$build_dir/bin"
chmod +x "$build_dir/pnpm/package/bin/pnpm.cjs"
ln -s "$build_dir/pnpm/package/bin/pnpm.cjs" "$build_dir/bin/pnpm"
export PATH="$build_dir/bin:$PATH"
(
  cd "$build_dir/source"
  pnpm install --frozen-lockfile --store-dir "$PNPM_STORE_DIR"
  pnpm ext:build:zip
)
cp "$build_dir/source/apps/extension/dist/browser-skillextension-${extension_version}-chrome.zip" "$output_dir/browser-skill-weknora-${extension_version}.zip"
cp "$build_dir/source/LICENSE" "$output_dir/BrowserSkill-LICENSE"

(
  cd "$build_dir/source"
  cargo build --locked --release -p bsk --target-dir "$CARGO_TARGET_DIR"
)
staged_binary="$(mktemp "$output_dir/.bsk-XXXXXX")"
install -m 755 "$CARGO_TARGET_DIR/release/bsk" "$staged_binary"
mv -f "$staged_binary" "$output_dir/bsk"
echo "BrowserSkill $extension_version extension and daemon: $output_dir"
