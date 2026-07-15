#!/usr/bin/env bash
set -euo pipefail

required=(
  RUNNER_REPOSITORY_URL
  RUNNER_REGISTRATION_TOKEN
  RUNNER_NAME
  RUNNER_LABEL
)
for name in "${required[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    printf 'runner configuration is incomplete: %s\n' "$name" >&2
    exit 2
  fi
done

./config.sh \
  --unattended \
  --ephemeral \
  --disableupdate \
  --url "$RUNNER_REPOSITORY_URL" \
  --token "$RUNNER_REGISTRATION_TOKEN" \
  --name "$RUNNER_NAME" \
  --labels "$RUNNER_LABEL" \
  --work _work

unset RUNNER_REGISTRATION_TOKEN
exec ./run.sh --once
