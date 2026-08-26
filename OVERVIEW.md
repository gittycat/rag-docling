# RAGBench

**A private, self-hostable RAG assistant that answers questions from your own trusted content — with the observability to prove the answers are good.**

RAGBench turns your organisation's documents into an AI assistant that gives accurate, grounded answers instead of the confident guesses you get from a generic chatbot. It runs entirely on your infrastructure, keeps sensitive data private even when using frontier cloud models, and ships with a built-in evaluation service so you can measure answer quality rather than hope for it.

---

## Why RAGBench

Retrieval-Augmented Generation (RAG) has become the most common way enterprises put AI to work: instead of relying on a model's training data, answers are grounded in *your* content. But most RAG deployments have two blind spots — **privacy** (your documents leave the building) and **quality** (nobody actually measures whether the answers are correct). RAGBench is built around closing both gaps.

- **Grounded answers, not hallucinations.** Every response is retrieved from and cited against your own corpus.
- **Privacy by design.** Run 100% on-premises, or use cloud models with automatic PII redaction on every outbound request.
- **Measured, not guessed.** A dedicated evaluation service scores retrieval and answer quality against public and custom benchmarks.
- **Own your stack.** Docker Compose, open-source components, no per-seat SaaS lock-in.

---

## Key Features

### 🔒 Data Privacy
- **Fully on-premises option** — run every component locally with open-source models; no request ever leaves your network.
- **Safe cloud-model usage** — when you opt for frontier models (OpenAI, Anthropic, Google, DeepSeek, Moonshot), sensitive data is anonymised before it leaves the perimeter and restored in the response.
- **Reversible PII masking** — Microsoft Presidio + spaCy detect and token-mask names, emails, and other identifiers across the query, retrieved context, chat history, and session titles, with a corpus-local guardrail and audit logging.
- **Secrets handled correctly** — API keys and DB credentials via Docker secrets mounted as files, following OWASP guidance (no secrets in environment variables or logs).

### 🎯 Retrieval Quality
- **Hybrid search** — combines sparse keyword search (BM25) and dense vector search, fused with Reciprocal Rank Fusion (RRF), so rare literal terms and semantic matches are both retrievable.
- **Contextual retrieval** — an LLM prepends document-level context to each chunk before embedding, at ingestion time rather than query time. Anthropic, who published the technique, [measured a 49% reduction in retrieval failures](https://www.anthropic.com/engineering/contextual-retrieval) for contextual embeddings combined with contextual BM25, and 67% with reranking added, on their own corpus.
- **Cross-encoder reranking** — a second-stage reranker (ms-marco-MiniLM) reorders candidates so the most relevant passages reach the model.
- **Broad document support** — PDF, DOCX, PPTX, XLSX, HTML, Markdown, AsciiDoc, and plain text, parsed with Docling.

### 📊 Observability & Evaluation
- **Built-in evaluation service** — a standalone API that runs automated quality assessments against multiple datasets (RAGBench, SQuAD 2.0, QASPER, HotpotQA, MS MARCO) plus your own golden Q&A.
- **Five headline metrics** — Retrieval Relevance, Faithfulness, Answer Completeness, Answer Relevance, and Response Latency, distilled for at-a-glance dashboards.
- **LLM-as-judge scoring** — a configurable judge model (OpenAI or Anthropic, selected by `active.eval`) scores faithfulness, answer correctness, and answer relevancy. Retrieval, citation, and abstention metrics are computed without a judge, so they are deterministic and free.
- **Run comparison & trends** — compare configurations side-by-side to find the best model/setting mix for your data and cost constraints. See [the tuning workflow](docs/guide/06-tuning-workflow.md) for how to tell a real difference from noise.

### 💬 Conversational RAG
- **Persistent, session-based chat** — PostgreSQL-backed conversation history so context survives restarts.
- **Context-aware follow-ups** — `condense_plus_context` mode rewrites follow-up questions into standalone queries before retrieval.

### ⚙️ Operations
- **Async document processing** — an isolated worker claims ingestion jobs via PostgreSQL `SKIP LOCKED`, with live progress tracking.
- **Multi-provider flexibility** — swap LLM, embedding, reranker, and eval models through a single `config.yml`, no code changes.
- **Network-isolated services** — internal services run on a private Docker network; only the web app and API are exposed.

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| **API & Backend** | Python 3.13, FastAPI |
| **RAG Pipeline** | LlamaIndex, Docling (document parsing) |
| **Vector Search** | PostgreSQL 17 + pgvector, indexed with pgvectorscale StreamingDiskANN |
| **Keyword Search** | PostgreSQL 17 + pg_textsearch (BM25) |
| **Fusion & Rerank** | Reciprocal Rank Fusion (RRF) + SentenceTransformers cross-encoder |
| **Async Processing** | PostgreSQL `SKIP LOCKED` work queue |
| **Chat & Persistence** | PostgreSQL (sessions, history, metadata) |
| **Privacy** | Microsoft Presidio + spaCy (PII detection & masking) |
| **Evaluation** | In-house metrics, LLM-as-judge (configurable — OpenAI by default) |
| **Frontend** | SvelteKit, Tailwind CSS, DaisyUI |
| **Embedding Inference** | Self-hosted HuggingFace Text Embeddings Inference (TEI), a Docker Compose service |
| **LLM Inference** | OpenAI / Anthropic / Google / DeepSeek / Moonshot (cloud) or a self-hosted vLLM endpoint |
| **Deployment** | Docker Compose |

### Running fully local

| Purpose | Model | Runs on |
|---------|-------|---------|
| Answer generation | your choice | self-hosted vLLM endpoint (not a Compose service — see `config.yml`'s commented `qwen-vllm` example) |
| Embeddings | Qwen3-Embedding-0.6B | TEI, a Docker Compose service (`tei`) |
| Reranking | ms-marco-MiniLM-L-6-v2 | HuggingFace (local) |

Embeddings run locally out of the box — the checked-in `config.yml`'s active
embedding model (`qwen3-embed`) already points at the in-Compose `tei` service,
no setup required. Generation defaults to a cloud model; to keep it on-prem too,
point `active.inference` at a vLLM endpoint you run yourself and no request
leaves your network. See
[the getting-running guide](docs/guide/02-getting-running.md) before first boot.

Evaluation uses an LLM-as-judge, and the shipped judge is a vendor-hosted model.
Because judge prompts carry retrieved chunks and answers verbatim and are never
masked, whether corpus content may reach it is a policy decision rather than a
side effect: each model definition declares an `execution_boundary`
(`customer_managed`, `aws_managed`, or `third_party`) and `data_policy` names the
boundaries a confidential corpus is allowed to be judged in. A judge outside that
allow-list — or one that declares no boundary — stops the run. See
[privacy and PII](docs/guide/08-privacy-and-pii.md). All model choices are
swappable in `config.yml`.

---

## Deployment at a Glance

RAGBench ships as a set of Docker Compose services:

- **Web app** (SvelteKit) — upload, chat, and dashboards
- **RAG server** (FastAPI) — retrieval and answer generation
- **Task worker** — async document ingestion
- **Evaluation service** (FastAPI) — automated quality scoring
- **PostgreSQL 17** — vector search, BM25 search, chat, queue, and metadata
- **TEI** (Compose service) — self-hosted embedding inference

Minimum footprint for local development: Docker, ~4 GB RAM, ~2 GB disk. The
`tei` service's first cold start downloads its embedding model's weights from
HuggingFace (a few minutes on a fast connection); `just init` pre-warms this
so it isn't paid on first `docker compose up`. Production on-prem deployments
benefit from a GPU server sized for larger open-source models, including for
self-hosted generation via vLLM.

---

## Documentation

Two purpose-built sets:

- **[Operator guide](docs/guide/INDEX.md)** — for running and tuning RAGBench on
  your own infrastructure. Its spine is the tuning loop: measure a baseline, change
  one thing, re-measure, decide whether it was worth it. Includes building an
  evaluation set from your own documents, an experiment cookbook, and an honest
  account of what the measurements can and cannot prove.
- **[Internal documentation](docs/internal/INDEX.md)** — the engineering reference.
  Architecture, the RAG pipeline, APIs, configuration, and the reasoning behind key
  design decisions.

[`docs/suggestions.md`](docs/suggestions.md) tracks known defects and improvement
proposals.

---

## Project Status

RAGBench is an actively developed research/reference implementation focused on **privacy** and **observability** in RAG. It is not yet hardened for production — authentication, multi-tenancy, and high-availability features are on the roadmap. It is ideal for teams evaluating self-hosted RAG architectures, benchmarking model/retrieval trade-offs, or building a privacy-first internal knowledge assistant.

*Built on the shoulders of great open-source software. Licensed under the MIT License.*
