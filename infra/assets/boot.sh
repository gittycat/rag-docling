#!/usr/bin/env bash
#
# EC2 user data. The golden AMI already has docker, every image, both model
# caches and an ingested corpus, so this is deliberately thin: fetch secrets,
# point the app at its real origin, start compose.
#
# Required environment (templated in by the demo stack): AWS_REGION,
# SECRET_PREFIX, REGISTRY, VERSION, WEBAPP_ORIGIN
set -euo pipefail

APP_DIR=/opt/ragbench
exec > >(tee -a /var/log/ragbench-boot.log) 2>&1
echo "[boot $(date -u +%FT%TZ)] starting"

cd "$APP_DIR"
systemctl is-active --quiet docker || systemctl start docker

"$APP_DIR/scripts/fetch-secrets.sh"

aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "${REGISTRY%%/*}"

export REGISTRY VERSION WEBAPP_ORIGIN
docker compose -f docker-compose.yml -f docker-compose.aws.yml up -d

# The ALB health check hits the webapp root; fail loudly in the log if it never
# comes up, rather than leaving the target group to time out silently.
if timeout 300 bash -c 'until curl -sf http://localhost:8000 >/dev/null; do sleep 5; done'; then
  echo "[boot $(date -u +%FT%TZ)] webapp is serving"
else
  echo "[boot $(date -u +%FT%TZ)] FAILED: webapp did not come up in 300s"
  docker compose -f docker-compose.yml -f docker-compose.aws.yml logs --tail 200
  exit 1
fi
