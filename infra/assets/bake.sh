#!/usr/bin/env bash
#
# Runs once, inside EC2 Image Builder, to produce the golden AMI.
#
# Everything slow happens here so `cdk deploy RagbenchDemoStack` is a boot, not an
# install: docker images, the HuggingFace cache, the Ollama model and an
# already-ingested corpus are all written to the root volume before the snapshot.
#
# Required environment: REGISTRY, AWS_REGION, SECRET_PREFIX, COMPOSE_VERSION
set -euo pipefail

APP_DIR=/opt/ragbench
log() { echo "[bake $(date -u +%H:%M:%S)] $*"; }

# --------------------------------------------------------------- docker engine
log "installing docker"
dnf install -y docker jq unzip
systemctl enable --now docker

log "installing the compose plugin ${COMPOSE_VERSION}"
install -d /usr/libexec/docker/cli-plugins
curl -fsSL -o /usr/libexec/docker/cli-plugins/docker-compose \
  "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-aarch64"
chmod +x /usr/libexec/docker/cli-plugins/docker-compose
docker compose version

# ------------------------------------------------------------------ app bundle
# The bundle is already unpacked into $APP_DIR by the Image Builder component —
# it has to be, since this script ships inside it.
cd "$APP_DIR"

# Bind-mount targets compose expects to exist, owned by uid 1000 to match the
# non-root user inside rag-server / task-worker.
install -d -o 1000 -g 1000 \
  .cache/huggingface .cache/datasets \
  data/indexed_documents data/eval_runs data/calibration \
  services/evals/evals/data
chmod +x services/postgres/*.sh scripts/*.sh

# config.yml pins each Ollama model's base_url to host.docker.internal, which is
# how it reaches the host on a laptop. On the instance Ollama is a compose
# service, so rewrite it once — here, so the corpus is ingested against the same
# endpoint the demo will use.
sed -i 's|http://host\.docker\.internal:11434|http://ollama:11434|g' config.yml

# ---------------------------------------------------------------------- secrets
# Written here only so postgres can create its roles during this bake; deleted
# again below so nothing sensitive lands in the snapshot. User data re-fetches
# them at every boot.
"$APP_DIR/scripts/fetch-secrets.sh"

# ------------------------------------------------------------------ pull images
log "logging into ECR"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "${REGISTRY%%/*}"

export REGISTRY VERSION="${VERSION:-latest}" WEBAPP_ORIGIN="http://localhost:8000"
# docker-compose.bake.yml republishes rag-server's 8001 on the loopback for the
# length of the build; the AWS overlay closes it and boot.sh never applies this
# third file, so the golden AMI boots with the port shut.
compose() { docker compose -f docker-compose.yml -f docker-compose.aws.yml -f docker-compose.bake.yml "$@"; }

# Image Builder terminates the build instance on failure, so whatever a container
# printed before dying is the only evidence there will ever be. Dump it into the
# component log rather than leaving "is unhealthy" as the whole diagnosis.
dump_on_failure() {
  local code=$?
  [[ $code -eq 0 ]] && return 0
  log "FAILED (exit ${code}) - dumping compose state"
  compose ps -a || true
  for c in $(docker ps -aq); do
    printf '=== %s health ===\n' "$c"
    docker inspect --format '{{.Name}} {{.State.Status}} {{if .State.Health}}{{json .State.Health}}{{end}}' "$c" || true
  done
  compose logs --tail 200 || true
  return "$code"
}
trap dump_on_failure EXIT

log "pulling images"
compose pull

# --------------------------------------------------------------- model caches
# Not optional: compose sets USE_CACHED_RERANKER=true, which sets HF_HUB_OFFLINE=1
# at startup, and ensure_reranker_model_cached() hard-fails the boot if the
# reranker is absent. The Docling models fail the first ingestion the same way.
log "seeding the HuggingFace cache (reranker + docling)"
compose run --rm --no-deps --user 1000:1000 rag-server .venv/bin/python - <<'PY'
from huggingface_hub import snapshot_download

for repo in (
    "cross-encoder/ms-marco-MiniLM-L-6-v2",
    "docling-project/docling-models",
    "docling-project/docling-layout-heron",
):
    print(f"downloading {repo}", flush=True)
    snapshot_download(repo)
PY

log "pulling the ollama embedding model"
compose up -d ollama
timeout 120 bash -c 'until docker compose -f docker-compose.yml -f docker-compose.aws.yml -f docker-compose.bake.yml exec -T ollama ollama list >/dev/null 2>&1; do sleep 3; done'
compose exec -T ollama ollama pull nomic-embed-text

# ----------------------------------------------------------- bake the corpus
log "starting the full stack"
compose up -d
timeout 300 bash -c 'until curl -sf http://localhost:8000 >/dev/null; do sleep 5; done'

log "ingesting sample_documents"
args=()
for f in sample_documents/*; do args+=(-F "files=@${f}"); done
batch_id=$(curl -sf -X POST "${args[@]}" \
  -H "Authorization: Bearer $(cat secrets/RAG_SERVER_AUTH_TOKEN)" \
  http://localhost:8001/upload | jq -r .batch_id)
log "batch ${batch_id}"

# Ingestion is asynchronous — task-worker picks the batch up via SKIP LOCKED — so
# poll rather than assume. This deliberately checks ingestion, not generation:
# it proves the Ollama embeddings and both model caches work without depending on
# a real OpenAI key being present at bake time.
log "waiting for ingestion to finish"
for _ in $(seq 1 90); do
  status=$(curl -sf "http://localhost:8001/tasks/${batch_id}/status" \
    -H "Authorization: Bearer $(cat secrets/RAG_SERVER_AUTH_TOKEN)")
  total=$(jq -r .total <<<"$status")
  completed=$(jq -r .completed <<<"$status")
  log "  ${completed}/${total}"
  [[ "$completed" == "$total" && "$total" -gt 0 ]] && break
  sleep 10
done
[[ "${completed:-0}" == "${total:-1}" && "${total:-0}" -gt 0 ]] || {
  log "FAILED: ingestion did not complete (${completed:-0}/${total:-0})"
  compose logs --tail 200
  exit 1
}

# The documents endpoint reads back through the same schema the demo queries use,
# so a non-empty list confirms the Postgres volume really holds the corpus.
doc_count=$(curl -sf http://localhost:8001/documents \
  -H "Authorization: Bearer $(cat secrets/RAG_SERVER_AUTH_TOKEN)" | jq '.documents | length')
[[ "${doc_count:-0}" -gt 0 ]] || { log "FAILED: no documents readable after ingestion"; exit 1; }
log "corpus baked: ${doc_count} documents"

# ------------------------------------------------------------------- shut down
log "stopping the stack so the volumes snapshot cleanly"
compose stop
sleep 5

rm -rf "$APP_DIR/secrets"
docker logout "${REGISTRY%%/*}" || true
log "done"
