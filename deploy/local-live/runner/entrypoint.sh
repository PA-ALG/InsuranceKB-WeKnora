#!/usr/bin/env bash
set -euo pipefail

required=(
  RUNNER_REPOSITORY_URL
  RUNNER_NAME
  RUNNER_LABEL
)
for name in "${required[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    printf 'runner configuration is incomplete: %s\n' "$name" >&2
    exit 2
  fi
done

token_pipe=/run/insurancekb/registration-token
cleanup_token_pipe() {
  rm -f "$token_pipe"
}
trap cleanup_token_pipe EXIT
mkfifo -m 0600 "$token_pipe"
RUNNER_REGISTRATION_TOKEN="$(cat "$token_pipe")"
cleanup_token_pipe
trap - EXIT
if [[ -z "$RUNNER_REGISTRATION_TOKEN" ]]; then
  printf 'runner registration token is empty\n' >&2
  exit 2
fi

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
