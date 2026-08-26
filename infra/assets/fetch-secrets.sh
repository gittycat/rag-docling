#!/usr/bin/env bash
#
# Writes each Secrets Manager value to secrets/<NAME>, which compose mounts at
# /run/secrets/<NAME>.
#
# This shim exists because the application deliberately ignores environment
# variables: settings.py and services/evals/infrastructure/settings.py both
# override settings_customise_sources() to return (file_secret_settings,) only,
# on the OWASP rationale recorded in secrets/README.md. So the usual "inject
# secrets as env vars" pattern does not work here — they must be files.
#
# Required environment: AWS_REGION, SECRET_PREFIX (e.g. ragbench/demo)
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ragbench}"
cd "$APP_DIR"

# Generated into the bundle from SECRET_NAMES in infra/lib/config.ts, which is
# also what creates the secrets and grants the instance role read on them. A
# second copy of the list here would drift, and the drift would only show up as
# a compose bind-mount failure at boot, on an AMI that is already baked.
NAMES_FILE="scripts/secret-names"
if [[ ! -s "$NAMES_FILE" ]]; then
  echo "Missing or empty ${APP_DIR}/${NAMES_FILE} — the bundle is incomplete" >&2
  exit 1
fi
# Read up front: the aws calls below inherit stdin and would eat the list.
mapfile -t SECRET_NAMES < "$NAMES_FILE"

install -d -m 700 secrets

for name in "${SECRET_NAMES[@]}"; do
  [[ -n "$name" ]] || continue
  aws secretsmanager get-secret-value \
    --region "$AWS_REGION" \
    --secret-id "${SECRET_PREFIX}/${name}" \
    --query SecretString --output text > "secrets/${name}"
  # Compose bind-mounts these straight into the containers, which read them as
  # three different uids: the postgres entrypoint re-execs as uid 999 (gosu
  # postgres) before it reads POSTGRES_*_FILE and runs 00-roles.sh, rag-server
  # and task-worker run as 1000, webapp as its own node user. No single owner
  # satisfies all three, so the files are world-readable and the root-owned
  # 0700 directory above is what keeps other host users out. A 0600 file here
  # fails silently-ish: 00-roles.sh dies on "Permission denied", the container
  # restarts, postgres finds a populated PGDATA, skips initialisation and comes
  # up healthy with no rag_server role at all.
  chmod 644 "secrets/${name}"
done
