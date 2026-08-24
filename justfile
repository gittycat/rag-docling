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

# Check host dependencies (Docker daemon, Ollama) and fail early with a clear message
[group('core')]
preflight:
    #!/usr/bin/env bash
    set -euo pipefail
    if ! docker info > /dev/null 2>&1; then
        echo "ERROR: Docker daemon is not running. Start OrbStack or Docker Desktop." >&2
        exit 1
    fi
    # Ollama is only required when an active model in config.yml uses the ollama provider
    needs_ollama=false
    for name in $(awk '/^active:/{f=1;next} f&&/^[^ ]/{exit} f{print $2}' config.yml); do
        provider=$(awk -v m="$name:" '$1==m{f=1;next} f&&$1=="provider:"{print $2; exit}' config.yml)
        [ "$provider" = "ollama" ] && needs_ollama=true
    done
    if $needs_ollama && ! curl -sf --max-time 3 http://localhost:11434/api/version > /dev/null; then
        echo "ERROR: Ollama is not running on localhost:11434, but an active model in config.yml uses the ollama provider." >&2
        echo "Start it by opening the Ollama app or running 'ollama serve'." >&2
        exit 1
    fi
    echo "Preflight OK: Docker daemon running$($needs_ollama && echo ", Ollama reachable" || true)"

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

# ============================================================================
# Setup
# ============================================================================

# Install rag_server dev dependencies into a local venv (uv)
[group('setup')]
setup:
    cd services/rag_server && \
    uv sync --group dev --python 3.13

# Pre-download the reranker model into .cache/huggingface (bind-mounted)
[group('setup')]
init MODEL="cross-encoder/ms-marco-MiniLM-L-6-v2":
    # Created host-side so the bind mounts are owned by the invoking user, not root
    mkdir -p .cache/huggingface .cache/datasets data/eval_runs data/calibration
    docker compose run --rm --no-deps --build rag-server \
      .venv/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download('{{MODEL}}')"

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

    if [ -z "${AWS_ACCOUNT_ID:-}" ]; then
        echo "ERROR: AWS_ACCOUNT_ID is not set. Put it in .envrc (see infra/README.md)." >&2
        exit 1
    fi
    AWS_REGION="${AWS_REGION:-ap-southeast-2}"

    # Two different things: the host you authenticate against, and the repository
    # namespace you push into. `docker login` takes the host only — passing it a
    # path silently authenticates the wrong thing.
    REGISTRY_HOST="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
    REGISTRY="${REGISTRY_HOST}/ragbench"

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
            --repository-names "ragbench/${name}" > /dev/null 2>&1 || missing="${missing} ragbench/${name}"
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
            --repository-name "ragbench/${name}" --image-ids imageTag="$TAG" \
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
    START=$(date +%s)

    PIPELINE_ARN=$(aws ssm get-parameter --region "$AWS_REGION" \
        --name /ragbench/demo/image-pipeline-arn --query 'Parameter.Value' --output text)

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
        --name /ragbench/demo/golden-ami-id --type String --overwrite \
        --description "Golden AMI baked by the ragbench-demo image pipeline" \
        --value "$AMI_ID" > /dev/null

    ELAPSED=$(( $(date +%s) - START ))
    echo "AMI: ${AMI_ID}"
    echo "Wrote /ragbench/demo/golden-ami-id = ${AMI_ID}"
    echo "Elapsed: ${ELAPSED}s"

# Deploy the demo CDK stack and print its URL
[group('aws')]
aws-up:
    #!/usr/bin/env bash
    set -euo pipefail
    cd infra && npx cdk deploy RagbenchDemoStack --require-approval never
    cd - > /dev/null
    URL=$(aws cloudformation describe-stacks --stack-name RagbenchDemoStack \
        --query "Stacks[0].Outputs[?OutputKey=='DemoUrl'].OutputValue" --output text)
    echo "Demo URL: ${URL}"

# Tear down the demo CDK stack
[group('aws')]
aws-down:
    cd infra && npx cdk destroy RagbenchDemoStack --force
