# RAGBench

A self-hostable RAG assistant that answers questions from your organisation's own
content, plus an evaluation service that measures whether those answers are any
good. Built around two things most RAG deployments skip: **data privacy** and
**observability**.

> Development/research project, not production software. No authentication in the
> laptop stack, no HA, no enterprise monitoring.

---

## Pick your deployment first

The two deployments are separate. Nothing bridges them — there is no tunnel, VPN,
or route from a laptop to the AWS models, and that is deliberate.

| | **Local (laptop)** | **AWS private** |
|---|---|---|
| Runs on | Docker Compose on your machine | EC2 demo instance + opt-in GPU instance |
| Answer model | OpenAI `gpt-5-mini` (cloud API) | `Qwen/Qwen3.5-9B` on vLLM, in your VPC |
| Judge model | OpenAI `gpt-5.2` (cloud API) | `Qwen/Qwen3.8-27B-FP8` on vLLM, in your VPC |
| Embeddings | self-hosted TEI container | self-hosted TEI container |
| Confidential corpus | **refused** by the data-policy gate | allowed |
| Cost when idle | free | roughly a coffee/month; GPU billed only while up |
| Start here | [Local quick start](#local-quick-start) | [AWS private deployment](#aws-private-deployment) |

**A privacy demo requires the AWS deployment.** The laptop stack has no local LLM
option, so its only generation path is a vendor API — the policy gate correctly
refuses a confidential corpus there. Full rationale:
[private model slate plan](docs/private-model-slate-plan.md).

---

## Local quick start

### 1. Install prerequisites

```bash
# macOS
brew install orbstack   # or Docker Desktop / Podman
brew install just uv    # task runner + Python env manager
```

Linux: install Docker your distribution's usual way, then `just` and `uv`.

Nothing else is installed on the host. Embedding inference (TEI serving
`Qwen/Qwen3-Embedding-0.6B`) is a Compose service.

**Needs:** Docker, ~4GB RAM, ~2GB disk for models and data.

### 2. Get the source

```bash
git clone https://github.com/gittycat/ragbench.git
cd ragbench
just setup      # local venv used by `just show-config` and the eval recipes
```

### 3. Create secrets

Credentials are **files** under `secrets/`, mounted at `/run/secrets/<NAME>` by
Compose and read at startup by Pydantic Settings. Environment variables with the
same names are ignored — this follows
[OWASP secrets-management guidance](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html).

```bash
mkdir -p secrets
echo -n "ragbench_admin"          > secrets/POSTGRES_SUPERUSER
echo -n "$(openssl rand -hex 24)" > secrets/POSTGRES_SUPERPASSWORD
echo -n "ragbench_app"            > secrets/RAG_SERVER_DB_USER
echo -n "$(openssl rand -hex 24)" > secrets/RAG_SERVER_DB_PASSWORD
echo -n "sk-..."                  > secrets/OPENAI_API_KEY   # default active models
```

Add `secrets/ANTHROPIC_API_KEY` only if you switch an active model to Anthropic.

### 4. Choose models (optional)

`config.yml` defines every available model; the `active` block picks which are
used. The checked-in defaults work as-is once an OpenAI key exists:

```yaml
active:
  inference: gpt5-mini    # OpenAI — answers questions
  embedding: qwen3-embed  # self-hosted TEI, no host install
  eval: gpt5-2            # OpenAI — evaluation judge
  reranker: minilm-l6     # local cross-encoder
```

Swap in any name from the `models` section. The `qwen35-9b` and `qwen38-27b-judge`
entries are AWS-only — they point at a non-routable placeholder until `just llm-up`
writes the real VPC address on the demo instance.

> **Breaking change:** the active embedding model fixes `vector_store.dimension`
> and the `document_chunks.embedding` column type. Changing it invalidates every
> stored vector, and there are no migrations for it — you must
> `docker compose down -v` and re-ingest. Read
> [getting running](docs/guide/02-getting-running.md) first.

### 5. Build and start

```bash
just init    # pre-fetch the reranker + warm TEI weights (~1.2GB, few minutes, once)
just up      # start webapp, rag-server, task-worker, evals, postgres, tei
```

- Web app: **http://localhost:8000**
- RAG API: **http://localhost:8001**
- Eval API: **http://localhost:8002**

Skipping `just init` is safe but the first `just up` spends ~200s downloading
embedding weights before `tei` reports healthy.

### 6. Stop

```bash
just down                # stop containers, keep data
docker compose down -v   # stop and DELETE the database and document store
```

---

## AWS private deployment

Full procedure, pricing and teardown:
**[docs/guide/12-private-aws-demo.md](docs/guide/12-private-aws-demo.md)**.
Infrastructure detail: [infra/README.md](infra/README.md).

Prerequisites: an AWS account per [infra/README.md](infra/README.md), Node.js for
CDK, and a selected environment — every recipe refuses to run without one:

```bash
setenv demo    # selects AWS_ENV + AWS_PROFILE together; `setenv none` clears it
```

### Bring it up

```bash
just ecr-push    # 1. build arm64 images, push to ECR
just aws-bake    # 2. bake the golden AMI (polls until AVAILABLE, prints elapsed)
just aws-up      # 3. deploy RagbenchDemoStack, prints the demo URL
```

That gives you a CPU-only demo instance still calling cloud models. For **private
inference and judging**, add the opt-in GPU stack:

```bash
just llm-up      # 4. spot g6e.xlarge (L40S), both vLLM servers, up to 30 min cold
```

`just llm-up` waits for both private `/health` endpoints, then rewrites only the
two `base_url` values in the demo instance's `config.yml` over SSM Run Command.
The GPU has no public ingress and no laptop-reachable route. Then set
`active.inference: qwen35-9b` and `active.eval: qwen38-27b-judge` for the run.

Self-hosted is not free, and an unpriced model is dropped from cost scoring rather
than counted as $0 — which silently reweights the headline score. Measure
throughput and publish an explicit rate:

```bash
just llm-price <instance-usd-per-hour> <inference-tok/s> <judge-tok/s>
```

Export the printed `MODEL_PRICE_OVERRIDES` in the shell that starts `rag-server`
and `evals`.

### Tear it down

Tear down in reverse — the GPU is the expensive part, so kill it first.

```bash
just llm-down    # restores the placeholder base_urls, destroys RagbenchLlmStack
just aws-down    # destroys RagbenchDemoStack
```

Confirm both CloudFormation stacks are gone before calling the demo complete.

### Other deployment targets

```bash
just deploy server        # base stack + Caddy TLS reverse proxy + bearer auth
just deploy cloud         # base stack, pulling pre-built registry images
just deploy-down server   # tear the same combination down
```

---

## Everyday commands

| Command | What it does |
|---|---|
| `just` | list every recipe, grouped |
| `just up` / `just down` / `just logs` | start, stop, tail the local stack |
| `just build` | rebuild all images |
| `just show-config` | print the resolved active configuration |
| `just eval <args>` | run an evaluation |
| `just eval-compare <args>` | compare two runs |
| `just demo-check` | fail loudly if vector search has silently degraded to BM25-only |
| `just test-unit` / `just test-integration` | run tests |

---

## What it does

### Data privacy

- **AWS private mode** keeps a confidential corpus inside a VPC you control: both
  the answer model and the judge run on your own vLLM instance, so no corpus text
  reaches a vendor API.
- **PII masking** for cloud models — opt-in via `pii.enabled` in `config.yml`,
  covering queries, chat history, retrieved context, session titles, and document
  ingestion. Identifiers are token-masked on the way out and restored on the way
  back.
- **A data-policy gate** refuses to evaluate a confidential corpus with a judge
  outside the allowed execution boundary, and fails closed on a missing boundary.

### Observability

Quality (accuracy, groundedness, relevance) and operations (cost, latency) are
both measured. The built-in evaluation service runs automated assessments against
public datasets and your own golden Q&A, distilled into five dashboard metrics:

- **Retrieval Recall** — did the evidence reach the model, and if not, where was it lost?
- **Faithfulness** — is the answer grounded in retrieved context?
- **Answer Completeness** — does it cover all key points?
- **Answer Relevance** — does it address the question asked?
- **Response Latency** — is it fast enough?

These let you pick the model and setting combination that fits your data and
constraints, instead of guessing.

---

## Tech stack

- **Backend:** Python, FastAPI, PostgreSQL (pg_textsearch for BM25)
- **Frontend:** SvelteKit, Tailwind CSS, DaisyUI
- **RAG pipeline:** Docling, LlamaIndex
- **Vector store:** pgvector + pgvectorscale StreamingDiskANN, in the same PostgreSQL
- **Search:** hybrid BM25 + vector, fused with RRF
- **LLM:** OpenAI or Anthropic locally; private vLLM (Qwen3.5-9B / Qwen3.8-27B-FP8) on AWS
- **Embeddings:** self-hosted HuggingFace Text Embeddings Inference (TEI)
- **Infrastructure:** Docker Compose locally, AWS CDK for the demo stacks

---

## Documentation

- **[Operator guide](docs/guide/INDEX.md)** — running, configuring, and tuning.
  Built around the tuning loop: measure a baseline, change one thing, re-measure,
  decide whether it helped. Covers building an evaluation set from your own
  documents, an experiment cookbook, privacy verification, and what the
  evaluations do and don't prove.
- **[Private AWS demo](docs/guide/12-private-aws-demo.md)** — start, price, and
  tear down the GPU.
- **[Internal documentation](docs/internal/INDEX.md)** — architecture, RAG
  pipeline, retrieval, APIs, database, configuration, testing, CI/CD, and design
  rationale.
- **[Suggestions](docs/suggestions.md)** — known defects and improvement proposals.

New here? Read [what this does](docs/guide/01-overview.md), then
[getting running](docs/guide/02-getting-running.md).

Developing on it? Prerequisites, `just` recipes, and testing are in
[docs/internal/development.md](docs/internal/development.md).

---

## AI development

Developed using **Claude Code** (Anthropic) as the primary coding assistant.
OpenAI GPT and Google Gemini models are also used to explore alternative
implementations. All code is reviewed, tested (TDD), and validated for
correctness and security.

## License

Built on the shoulders of a multitude of great open source software.
[MIT License](./LICENSE.md)
