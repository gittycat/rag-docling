## About

This project implements a RAG AI assistant that searches your organisation’s trusted content and answers questions using it. It delivers more accurate, relevant responses grounded in your data than what is obtained by simple LLM apps like ChatGPT.

RAGs have become the most common application of AI in enterprise environments.
This specific RAG focuses on two core features: data privacy and observability.

## Data Privacy

- Confidential-corpus privacy is supported in AWS private mode: the demo Compose
stack uses a separate VPC-private vLLM L40S instance for inference and judging.
Laptop Compose uses cloud models, so its data-policy gate correctly refuses a
confidential-corpus evaluation. See [the private AWS demo guide](docs/guide/12-private-aws-demo.md).
- Frontier cloud models can also be used. Privacy is then ensured by performing data anonymization on any request to the cloud and inserting back the redacted data on responses. This PII masking is opt-in (`pii.enabled` in `config.yml`) and covers queries, chat history, retrieved context, session titles, and document ingestion.

## Observability

This covers both measures of the **quality** of the data (accuracy, completeness, groundedness / hallucination rate, relevance) and **Operational metrics** values like cost, latency and speed.

The system includes an **Evaluation Service** that runs automated quality assessments against multiple datasets. Results are distilled into 5 dashboard metrics:

- **Retrieval Relevance** — Are we finding the right content?
- **Faithfulness** — Is the answer grounded in retrieved context?
- **Answer Completeness** — Does the answer cover all key points?
- **Answer Relevance** — Does the answer address the question asked?
- **Response Latency** — Is the system fast enough?

These metrics allow admins to determine the best combinations of LLM models and settings for their data and organisation constraints.

## Tech Stack

- **Backend**: Python, FastAPI, PostgreSQL (pg_textsearch for BM25)
- **Frontend**: SvelteKit, Tailwind CSS, DaisyUI
- **RAG Pipeline**: Docling, LlamaIndex
- **Vector store**: pgvector + pgvectorscale StreamingDiskANN, inside the same PostgreSQL
- **Search**: Hybrid (BM25 + Vector + RRF)
- **LLM**: OpenAI or Anthropic in laptop mode; private vLLM in AWS private mode
- **Embeddings**: self-hosted HuggingFace Text Embeddings Inference (TEI), runs as a Docker Compose service
- **Infrastructure**: Docker compose

## Requirements

- **Docker** - Docker Desktop, OrbStack, or Podman
- **4GB RAM** - For local development with slow inference.
- **2GB disk** - For models and data for development.

Embeddings run locally out of the box via the `tei` Compose service — no separate
install. On the very first boot it downloads the embedding model's weights
(~1.2GB), which takes a few minutes on a fast connection; `just init` pre-warms
this so `docker compose up` isn't the first time it happens.

## Status

This is a development/research project, not production-ready software. It lacks authentication, enterprise security, monitoring, high availability features to name some main ones.

## AI Development

This project is developed using **Claude Code** (Anthropic) as the primary coding assistant. OpenAI GPT and Google Gemini models are also used to explore alternative implementations.

All code is reviewed, tested (TDD), and validated for correctness and security.

## Quick Start

### 1. Install Prerequisites

**macOS:**
```bash
# Install Docker
brew install orbstack            # or Docker Desktop if you prefer
```

**Linux:** install Docker via your distribution's usual method.

Embedding inference (TEI, serving `Qwen/Qwen3-Embedding-0.6B`) runs as a Docker
Compose service — nothing to install on the host beyond Docker itself. Laptop
Compose uses cloud generation. For private inference and judging, deploy the
separate AWS mode described in [the private AWS demo guide](docs/guide/12-private-aws-demo.md).

### 2. Download ragbench source

```bash
# Clone the repository
git clone https://github.com/gittycat/ragbench.git
cd ragbench
```

### 3. Configure

**Select the LLM Models to use** (`config.yml`):

The `config.yml` file defines available models and RAG settings. The `active` section controls which models are used:

```yaml
active:
  inference: gpt5-mini    # LLM for answering questions
  embedding: qwen3-embed  # Model for document embeddings
  eval: gpt5-2            # Model for evaluation metrics
  reranker: minilm-l6     # Model for result reranking
```

To switch models, change the active model name to any model defined in the `models` section. `qwen3-embed` (self-hosted TEI) works out of the box — it's a Docker Compose service, not a host install. Cloud models require API keys.

> Note: the checked-in `config.yml`'s embedding model already runs locally via TEI; `active.inference` and `active.eval` default to cloud models and need matching API key files under `secrets/`. The `qwen35-9b` inference and `qwen38-27b-judge` eval entries are for the separate AWS private mode, configured by `just llm-up`.
>
> **Breaking change note:** the active embedding model determines `vector_store.dimension` and the `document_chunks.embedding` column type. Switching embedding models always invalidates every stored vector — see [getting-running](docs/guide/02-getting-running.md) before changing it on a database that already has documents in it.

**Secrets**:

API keys are provided via Docker Compose secrets mounted as files under `/run/secrets` and loaded at startup via Pydantic Settings (no environment variables). This follows OWASP best practices for secrets handling and storage guidance:

```
https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html?utm_source=chatgpt.com
https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html
```

Database access also uses secrets per service. Create the required files under `secrets/` before starting containers.

### 4. Start the Application

```bash
# Pre-fetch the re-ranking model and warm the TEI embedding weights.
# This significantly speeds up the rag-server and tei container startup.
just init

# Start RAG Bench
docker compose up -d
```

Open **http://localhost:8000** in your browser. The eval service API is available at **http://localhost:8002**.

### 5. Stop the Application

```bash
docker compose down
```

### Delete all persistent stores (database, document storage)

```bash
docker compose down -v
```

## Documentation

- **[Operator guide](docs/guide/INDEX.md)** — running, configuring, and tuning
  RAGBench. Built around the tuning loop: measure a baseline, change one thing,
  re-measure, decide whether it helped. Covers building an evaluation set from your
  own documents, an experiment cookbook, privacy verification, and the limits of
  what the evaluations prove.
- **[Internal documentation](docs/internal/INDEX.md)** — engineering reference:
  architecture, RAG pipeline, retrieval, APIs, database, configuration, testing,
  CI/CD, and the reasoning behind key design decisions.
- **[Suggestions](docs/suggestions.md)** — known defects and improvement proposals.

New here? Start with [what this does](docs/guide/01-overview.md), then
[getting running](docs/guide/02-getting-running.md).

## Development

Prerequisites, local setup, `just` recipes, and testing:
[docs/internal/development.md](docs/internal/development.md).

## License

Built on the shoulder of a multitude of great open source software.
[MIT License](./LICENSE.md)
