# Load the secrets/.env file
set dotenv-path := "./secrets/.env"

# Suppress command echoing globally
set quiet

alias test := test-unit

default:
    just --list --list-heading "Usage: just <recipe>"

# ============================================================================
# Core — build, start, stop
# ============================================================================

# Build all docker images
[group('core')]
build:
    docker compose build

# Check host dependencies (Docker daemon) and fail early with a clear message
[group('core')]
preflight:
    #!/usr/bin/env bash
    set -euo pipefail
    if ! docker info > /dev/null 2>&1; then
        echo "ERROR: Docker daemon is not running. Start OrbStack or Docker Desktop." >&2
        exit 1
    fi
    # Embedding inference (tei) and any self-hosted vllm model run as compose
    # services now, health-checked via depends_on — nothing to preflight on the host.
    echo "Preflight OK: Docker daemon running"

# Start all services (rag-server, task-worker, webapp, evals, postgres)
[group('core')]
up: preflight
    docker compose up -d

# Stop all services
[group('core')]
down:
    docker compose down

# Tail logs from all services
[group('core')]
logs:
    docker compose logs -f

# A dead embedder does NOT look like an outage: a query whose embedding call
# fails is caught in vector_retriever._aretrieve, which logs and returns [], so
# hybrid search silently degrades to BM25-only and the demo still answers — just
# worse. Reading /metrics/system alone doesn't catch it either: get_vector_health()
# reports "unknown" until a search has actually run in that process, and "unknown"
# is not "unhealthy". So this issues a real query first to force an embedding
# round-trip, THEN reads the health surface.

# Fail loudly if the vector path is silently degrading to BM25-only (run before demoing)
[group('core')]
demo-check:
    #!/usr/bin/env bash
    set -euo pipefail
    BASE="${RAG_SERVER_URL:-http://localhost:8001}"
    TOKEN="$(cat secrets/RAG_SERVER_AUTH_TOKEN 2>/dev/null || echo "")"
    # Array, not a bare ${TOKEN:+...} expansion — the header value has a space in
    # it and word-splitting would send it as three broken arguments.
    AUTH=()
    [ -n "$TOKEN" ] && AUTH=(-H "Authorization: Bearer $TOKEN")

    echo "1/3 tei /health"
    docker compose exec -T tei curl -fsS http://localhost:80/health > /dev/null
    echo "    ok"

    echo "2/3 forcing a real query (so vector health stops being 'unknown')"
    # is_temporary keeps this probe out of the session table.
    curl -fsS -X POST "$BASE/query" \
        -H "Content-Type: application/json" \
        "${AUTH[@]}" \
        -d '{"query": "demo-check vector path probe", "is_temporary": true}' \
        > /dev/null
    echo "    ok"

    echo "3/3 asserting vector_store is healthy, not silently degraded"
    STATUS="$(curl -fsS "$BASE/metrics/system" "${AUTH[@]}" \
        | python3 -c 'import json,sys; print(json.load(sys.stdin)["component_status"]["vector_store"])')"
    if [ "$STATUS" != "healthy" ]; then
        echo "ERROR: vector_store is '$STATUS' — queries are degrading to BM25-only." >&2
        echo "       Check the tei service before demoing: docker compose logs tei" >&2
        exit 1
    fi
    echo "    vector_store: healthy"
    echo "Demo check passed."

# ============================================================================
# Setup
# ============================================================================

# Install rag_server dev dependencies into a local venv (uv)
[group('setup')]
setup:
    cd services/rag_server && \
    uv sync --group dev --python 3.13

# Pre-download the reranker model and warm the TEI/Qwen3 embedding weights
[group('setup')]
init MODEL="cross-encoder/ms-marco-MiniLM-L-6-v2":
    # Created host-side so the bind mounts are owned by the invoking user, not root
    mkdir -p .cache/huggingface .cache/datasets data/eval_runs data/calibration
    docker compose run --rm --no-deps --build rag-server \
      .venv/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download('{{MODEL}}')"
    docker compose pull tei
    docker compose up -d tei
    # 420s, not 120s: this recipe exists precisely to warm a cold tei_data volume,
    # which downloads ~1.2GB of safetensors before warmup starts. Measured at 204s
    # to healthy on a fast connection — 120s would time out on the very case this
    # recipe is for.
    timeout 420 bash -c 'until docker compose exec -T tei curl -sf http://localhost:80/health > /dev/null 2>&1; do sleep 3; done'

# Remove __pycache__, .pytest_cache and *.pyc
[group('setup')]
clean:
    fd -t d -H __pycache__ ./services/rag_server -X rm -rf
    fd -t d -H '\.pytest_cache' ./services/rag_server -X rm -rf
    fd -t f -H -e pyc . ./services/rag_server -X rm

# ============================================================================
# Tests
# ============================================================================

# Unit tests (local venv, no docker needed)
[group('test')]
test-unit: setup
    cd services/rag_server && \
    .venv/bin/pytest tests/ --ignore=tests/integration -v

# Integration tests (fresh container, clean state)
[group('test')]
test-integration: up
    docker compose run --rm -e RAG_SERVER_URL=http://rag-server:8001 rag-server \
      .venv/bin/pytest tests/integration -v --run-integration

# Integration tests including slow ones
[group('test')]
test-integration-full: up
    docker compose run --rm -e RAG_SERVER_URL=http://rag-server:8001 rag-server \
      .venv/bin/pytest tests/integration -v --run-integration --run-slow

# ============================================================================
# Evals
# ============================================================================

# Quick eval smoke test (ragbench end-to-end, 5 samples)
[group('eval')]
test-eval: show-config up
    docker compose exec evals .venv/bin/python -m evals.cli eval --tier end_to_end --datasets ragbench --samples 5

# Full eval suite (all end-to-end datasets, all samples)
[group('eval')]
test-eval-full: show-config up
    docker compose exec evals .venv/bin/python -m evals.cli eval --tier end_to_end --datasets ragbench,qasper,hotpotqa,msmarco

# Custom eval run, e.g. `just eval --tier generation --datasets squad_v2 --samples 5`
[group('eval')]
eval +ARGS: show-config up
    docker compose exec evals .venv/bin/python -m evals.cli eval {{ARGS}}

# List available eval datasets
[group('eval')]
eval-datasets: up
    docker compose exec evals .venv/bin/python -m evals.cli datasets

# Calibrate the LLM judge against RAGBench TRACe ground-truth annotations
[group('eval')]
eval-calibrate SAMPLES="20": up
    docker compose exec evals .venv/bin/python -m evals.cli calibrate --samples {{SAMPLES}}

# Compare runs with paired bootstrap CIs, e.g. `just eval-compare <baseline> <candidate>`
[group('eval')]
eval-compare +ARGS: up
    docker compose exec evals .venv/bin/python -m evals.cli compare {{ARGS}}

# Export a run, e.g. `just eval-export abc123 review-csv`
[group('eval')]
eval-export RUN_ID FORMAT="report": up
    docker compose exec evals .venv/bin/python -m evals.cli export --run-id {{RUN_ID}} --format {{FORMAT}}

# ============================================================================
# Config
# ============================================================================

# Show RAG configuration (compact)
[group('config')]
show-config:
    cd services/rag_server && \
    .venv/bin/python -c "from infrastructure.config.display import print_config_banner; print_config_banner(compact=True)"

# Show full RAG configuration
[group('config')]
show-config-full:
    cd services/rag_server && \
    .venv/bin/python -c "from infrastructure.config.display import print_config_banner; print_config_banner(compact=False)"

# ============================================================================
# Deploy & Release
# ============================================================================

# Deploy with a compose overlay: `just deploy server` or `just deploy cloud`
[group('deploy')]
deploy ENV="server": preflight
    docker compose -f docker-compose.yml -f docker-compose.{{ENV}}.yml up -d --build

# Stop a deployed overlay
[group('deploy')]
deploy-down ENV="server":
    docker compose -f docker-compose.yml -f docker-compose.{{ENV}}.yml down

# Release: tag v{VERSION}, bump service manifests, commit, push
[group('deploy')]
release VERSION:
    git tag -a v{{VERSION}} -m "Release {{VERSION}}"
    sed -i '' 's/^version = .*/version = "{{VERSION}}"/' services/rag_server/pyproject.toml
    cd services/webapp && npm version {{VERSION}} --no-git-tag-version --allow-same-version
    git add services/rag_server/pyproject.toml services/webapp/package.json services/webapp/package-lock.json
    git commit -m "Bump version to {{VERSION}}"
    git push origin main --tags

# ============================================================================
# AWS — build/push images, bake the golden AMI, stand up/tear down the demo
# ============================================================================

# Build all images for arm64 and push to ECR, tagged with the git SHA and latest
[group('aws')]
ecr-push TAG="":
    #!/usr/bin/env bash
    set -euo pipefail

    AWS_REGION="${AWS_REGION:-ap-southeast-2}"

    # Every physical name is env-qualified, so a recipe that guesses would
    # touch the wrong environment's registry, parameters or stack.
    ENV_NAME="${AWS_ENV:-}"
    if [ -z "$ENV_NAME" ]; then
        echo "ERROR: no environment selected. Run 'setenv <dev|staging|demo|prod>'." >&2
        exit 1
    fi

    # Derived from the active credentials, never from the environment: an
    # AWS_ACCOUNT_ID that disagrees with AWS_PROFILE would push into one
    # account's registry using another account's credentials.
    if ! AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null); then
        echo "ERROR: no valid AWS credentials. Run 'aws sso login --sso-session kiluna'." >&2
        exit 1
    fi

    # Two different things: the host you authenticate against, and the repository
    # namespace you push into. `docker login` takes the host only — passing it a
    # path silently authenticates the wrong thing.
    REGISTRY_HOST="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
    # Mirrors repoNamespace() in infra/lib/config.ts: demo kept the unqualified
    # names it was first pushed under, every other environment is qualified.
    NAMESPACE="ragbench"
    [ "$ENV_NAME" = "demo" ] || NAMESPACE="ragbench/${ENV_NAME}"
    REGISTRY="${REGISTRY_HOST}/${NAMESPACE}"

    TAG="{{TAG}}"
    if [ -z "$TAG" ]; then
        TAG=$(git rev-parse --short HEAD)
        # An image built from uncommitted work should not claim to be that commit.
        git diff --quiet && git diff --cached --quiet || TAG="${TAG}-dirty"
    fi

    IMAGES="webapp rag-server postgres evals"

    # ECR never creates repositories on push — it fails with "repository does not
    # exist". They are owned by RagbenchBaseStack, so check before spending ten
    # minutes on builds that cannot be pushed.
    missing=""
    for name in $IMAGES; do
        aws ecr describe-repositories --region "$AWS_REGION" \
            --repository-names "${NAMESPACE}/${name}" > /dev/null 2>&1 || missing="${missing} ${NAMESPACE}/${name}"
    done
    if [ -n "$missing" ]; then
        echo "ERROR: missing ECR repositories:${missing}" >&2
        echo "Deploy them first: cd infra && npx cdk deploy RagbenchBaseStack" >&2
        exit 1
    fi

    aws ecr get-login-password --region "$AWS_REGION" \
        | docker login --username AWS --password-stdin "$REGISTRY_HOST"
    trap 'docker logout "$REGISTRY_HOST" > /dev/null 2>&1 || true' EXIT

    # Built on the default builder rather than a docker-container one so the
    # daemon's existing layer cache is reused. On an arm64 host --platform is a
    # no-op guard; on x86 it would emulate, which is why this is explicit.
    build_push() {
        local name="$1" context="$2" dockerfile="$3"
        echo "==> ${name}"
        docker build --platform linux/arm64 \
            -f "$dockerfile" \
            -t "${REGISTRY}/${name}:${TAG}" \
            -t "${REGISTRY}/${name}:latest" \
            "$context"
        docker push "${REGISTRY}/${name}:${TAG}"
        docker push "${REGISTRY}/${name}:latest"
    }

    build_push webapp     services/webapp    services/webapp/Dockerfile
    build_push rag-server .                  services/rag_server/Dockerfile
    build_push postgres   services/postgres  services/postgres/Dockerfile
    build_push evals      .                  services/evals/Dockerfile

    echo
    echo "Pushed to ${REGISTRY} as :${TAG} and :latest"
    for name in $IMAGES; do
        digest=$(aws ecr describe-images --region "$AWS_REGION" \
            --repository-name "${NAMESPACE}/${name}" --image-ids imageTag="$TAG" \
            --query 'imageDetails[0].imageDigest' --output text)
        printf '  %-12s %s\n' "$name" "$digest"
    done
    echo
    echo "Next: just aws-bake"

# Start the EC2 Image Builder pipeline and wait for the golden AMI
[group('aws')]
aws-bake:
    #!/usr/bin/env bash
    set -euo pipefail
    AWS_REGION="${AWS_REGION:-ap-southeast-2}"
    # Every physical name is env-qualified, so a recipe that guesses would
    # touch the wrong environment's registry, parameters or stack.
    ENV_NAME="${AWS_ENV:-}"
    if [ -z "$ENV_NAME" ]; then
        echo "ERROR: no environment selected. Run 'setenv <dev|staging|demo|prod>'." >&2
        exit 1
    fi
    START=$(date +%s)

    PIPELINE_ARN=$(aws ssm get-parameter --region "$AWS_REGION" \
        --name "/ragbench/${ENV_NAME}/image-pipeline-arn" --query 'Parameter.Value' --output text)

    IMAGE_BUILD_VERSION_ARN=$(aws imagebuilder start-image-pipeline-execution \
        --region "$AWS_REGION" --image-pipeline-arn "$PIPELINE_ARN" \
        --query imageBuildVersionArn --output text)
    echo "Started image build: ${IMAGE_BUILD_VERSION_ARN}"

    while true; do
        STATUS=$(aws imagebuilder get-image --region "$AWS_REGION" \
            --image-build-version-arn "$IMAGE_BUILD_VERSION_ARN" \
            --query 'image.state.status' --output text)
        echo "Status: ${STATUS}"
        case "$STATUS" in
            AVAILABLE)
                break
                ;;
            FAILED|CANCELLED|DEPRECATED)
                echo "ERROR: image build ended in status ${STATUS}" >&2
                exit 1
                ;;
        esac
        sleep 30
    done

    AMI_ID=$(aws imagebuilder get-image --region "$AWS_REGION" \
        --image-build-version-arn "$IMAGE_BUILD_VERSION_ARN" \
        --query 'image.outputResources.amis[0].image' --output text)
    # The parameter is written here, not by CloudFormation: if the base stack
    # owned it, every `cdk deploy` would reset it and the demo would boot a
    # stale AMI. RagbenchDemoStack reads it at deploy time.
    aws ssm put-parameter --region "$AWS_REGION" \
        --name "/ragbench/${ENV_NAME}/golden-ami-id" --type String --overwrite \
        --description "Golden AMI baked by the ragbench-${ENV_NAME} image pipeline" \
        --value "$AMI_ID" > /dev/null

    ELAPSED=$(( $(date +%s) - START ))
    echo "AMI: ${AMI_ID}"
    echo "Wrote /ragbench/${ENV_NAME}/golden-ami-id = ${AMI_ID}"
    echo "Elapsed: ${ELAPSED}s"

# Deploy the demo CDK stack and print its URL
[group('aws')]
aws-up:
    #!/usr/bin/env bash
    set -euo pipefail
    # Every physical name is env-qualified, so a recipe that guesses would
    # touch the wrong environment's registry, parameters or stack.
    ENV_NAME="${AWS_ENV:-}"
    if [ -z "$ENV_NAME" ]; then
        echo "ERROR: no environment selected. Run 'setenv <dev|staging|demo|prod>'." >&2
        exit 1
    fi

    # Construct id stays bare in every environment; the deployed stack name does
    # not — stackName() in infra/lib/config.ts suffixes everything but demo.
    STACK=RagbenchDemoStack
    [ "$ENV_NAME" = "demo" ] || STACK="RagbenchDemoStack-${ENV_NAME}"

    cd infra && npx cdk deploy RagbenchDemoStack --require-approval never
    cd - > /dev/null
    URL=$(aws cloudformation describe-stacks --stack-name "$STACK" \
        --query "Stacks[0].Outputs[?OutputKey=='DemoUrl'].OutputValue" --output text)
    echo "Demo URL: ${URL}"

# Tear down the demo CDK stack
[group('aws')]
aws-down:
    cd infra && npx cdk destroy RagbenchDemoStack --force

# Deploy the burst embedding stack and point config.yml's TEI base_url at it
[group('aws')]
embed-up:
    #!/usr/bin/env bash
    set -euo pipefail
    AWS_REGION="${AWS_REGION:-ap-southeast-2}"
    # Every physical name is env-qualified, so a recipe that guesses would
    # touch the wrong environment's registry, parameters or stack.
    ENV_NAME="${AWS_ENV:-}"
    if [ -z "$ENV_NAME" ]; then
        echo "ERROR: no environment selected. Run 'setenv <dev|staging|demo|prod>'." >&2
        exit 1
    fi

    # Construct id stays bare in every environment; the deployed stack name does
    # not — stackName() in infra/lib/config.ts suffixes everything but demo.
    STACK=RagbenchEmbedStack
    [ "$ENV_NAME" = "demo" ] || STACK="RagbenchEmbedStack-${ENV_NAME}"

    # -c embedStack=true is mandatory: infra/bin/ragbench.ts leaves this stack out
    # of the app tree entirely without it, so a bare deploy fails with "no such
    # stack". That gate is deliberate — it keeps a bare `cdk deploy --all` from
    # ever standing up a GPU instance.
    cd infra && npx cdk deploy "$STACK" -c embedStack=true --require-approval never
    cd - > /dev/null

    ENDPOINT=$(aws ssm get-parameter --region "$AWS_REGION" \
        --name "/ragbench/${ENV_NAME}/embed-endpoint" --query 'Parameter.Value' --output text)
    if [ -z "$ENDPOINT" ] || [ "$ENDPOINT" = "None" ]; then
        echo "ERROR: ${STACK} deployed but /ragbench/${ENV_NAME}/embed-endpoint is empty." >&2
        exit 1
    fi

    # Address-range-scoped so this only ever touches the qwen3-embed block's
    # base_url, never an unrelated one elsewhere in config.yml. Back up first and
    # verify the rewrite landed — restore on any failure so config.yml is never
    # left half-edited.
    cp config.yml config.yml.bak
    if ! sed -i '' "/model: Qwen\\/Qwen3-Embedding-0.6B/,/embed_batch_size/ s|base_url: .*|base_url: ${ENDPOINT}|" config.yml \
        || ! grep -q "base_url: ${ENDPOINT}" config.yml; then
        echo "ERROR: failed to rewrite config.yml's embedding base_url; restoring backup." >&2
        mv config.yml.bak config.yml
        exit 1
    fi
    rm -f config.yml.bak

    echo "Embed endpoint: ${ENDPOINT}"
    echo "config.yml embedding base_url -> ${ENDPOINT}"

# Point config.yml's TEI base_url back at the in-compose service, then tear down the burst embedding stack
[group('aws')]
embed-down:
    #!/usr/bin/env bash
    set -euo pipefail
    ENV_NAME="${AWS_ENV:-}"
    if [ -z "$ENV_NAME" ]; then
        echo "ERROR: no environment selected. Run 'setenv <dev|staging|demo|prod>'." >&2
        exit 1
    fi
    # Same construct-id vs stack-name split as embed-up.
    STACK=RagbenchEmbedStack
    [ "$ENV_NAME" = "demo" ] || STACK="RagbenchEmbedStack-${ENV_NAME}"

    # Same address-range-scoped rewrite as embed-up, reverted. Done before the
    # destroy call so a failed destroy doesn't leave a half-edited file — the
    # edit itself is verified and rolled back on its own before that call runs.
    cp config.yml config.yml.bak
    if ! sed -i '' "/model: Qwen\\/Qwen3-Embedding-0.6B/,/embed_batch_size/ s|base_url: .*|base_url: http://tei:80|" config.yml \
        || ! grep -q "base_url: http://tei:80" config.yml; then
        echo "ERROR: failed to revert config.yml's embedding base_url; restoring backup." >&2
        mv config.yml.bak config.yml
        exit 1
    fi
    rm -f config.yml.bak
    echo "config.yml embedding base_url -> http://tei:80"

    # -c embedStack=true here too — without it the stack isn't in the app tree
    # and destroy has nothing to match, leaving the GPU instance running.
    cd infra && npx cdk destroy "$STACK" -c embedStack=true --force
