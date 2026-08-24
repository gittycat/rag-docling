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

install -d -m 700 secrets

for name in OPENAI_API_KEY ANTHROPIC_API_KEY POSTGRES_SUPERUSER \
            POSTGRES_SUPERPASSWORD RAG_SERVER_DB_USER \
            RAG_SERVER_DB_PASSWORD RAG_SERVER_AUTH_TOKEN; do
  aws secretsmanager get-secret-value \
    --region "$AWS_REGION" \
    --secret-id "${SECRET_PREFIX}/${name}" \
    --query SecretString --output text > "secrets/${name}"
  chmod 600 "secrets/${name}"
done

# postgres reads its secrets as root inside the container; rag-server reads them
# as uid 1000. Both need to be able to open the files.
chown -R 1000:1000 secrets
