# Internal Documentation Index

Engineering reference for RAGBench. Audience: developers working on the system
itself, including AI coding assistants. Load a single topic rather than reading
everything — the `dev-docs` skill uses the Topic column below to pick files.

Operator-facing procedure lives in [`docs/guide/`](../guide/INDEX.md). Known
defects and improvement proposals live in [`docs/suggestions.md`](../suggestions.md).

| File | Topic | Description |
|------|-------|-------------|
| [architecture.md](architecture.md) | architecture, services, docker, topology, networks, data flow, tech stack | Service inventory, Docker topology, public/private network split, request and ingestion paths, technology versions |
| [rag-pipeline.md](rag-pipeline.md) | ingestion, docling, chunking, embedding, contextual retrieval, task worker, upload | Document ingestion end to end: parsing, chunking, contextual prefixes, embeddings, the `SKIP LOCKED` task queue |
| [retrieval.md](retrieval.md) | retrieval, search, bm25, vector, pgvector, hybrid, rrf, fusion, reranker, cross-encoder, top_k | Hybrid BM25 + vector retrieval, RRF fusion, cross-encoder reranking, retrieval knobs and failure modes |
| [chat-and-memory.md](chat-and-memory.md) | chat, sessions, memory, condense, history, cache, ttl, lru | Session model, `condense_plus_context`, chat memory caches and their bounds, token budget |
| [eval-framework.md](eval-framework.md) | eval, evaluation, metrics, judge, calibration, datasets, scorecard, weighted score | Eval design, tiers, dataset adapters, metric catalogue, LLM judge, calibration, persistence, known gaps |
| [eval-service-api.md](eval-service-api.md) | eval api, port 8002, job manager, dashboard endpoints, runs, compare | Eval service REST API, job manager semantics, dashboard endpoints |
| [rag-api.md](rag-api.md) | api, rest, endpoints, query, documents, sessions, upload, streaming, sse, port 8001 | RAG server REST API reference — documents, query, sessions, settings, health and metrics, SSE contract |
| [frontend.md](frontend.md) | frontend, webapp, svelte, sveltekit, ui, components, routes, analytics, dashboard | SvelteKit app structure, routes, the analytics subsystem, stores, theming, known rough edges |
| [database.md](database.md) | database, postgres, schema, tables, pgvector, pgvectorscale, diskann, connection pool, sqlalchemy, queries, skip locked | Schema, indexes, connection pooling, query patterns, the task queue |
| [configuration-reference.md](configuration-reference.md) | config, configuration, yaml, config.yml, secrets, env vars, precedence, dead config | Exhaustive `config.yml` reference, environment variables, Docker secrets, compose overlays, precedence, dead keys |
| [pii-masking.md](pii-masking.md) | pii, masking, privacy, presidio, spacy, gliner, gdpr, anonymization | PII detection and masking, threat model, coverage boundary, validation, guardrails, audit logging, boot-time refusals |
| [observability.md](observability.md) | observability, metrics, health, monitoring, cost, latency, logging, logs | Health and metrics endpoints, cost and latency trackers, logging setup |
| [testing.md](testing.md) | testing, tests, pytest, integration, unit, markers, fixtures | Test categories, markers, commands, integration test design, known stale tests |
| [cicd-deployment.md](cicd-deployment.md) | ci, cd, forgejo, deployment, compose, versioning, release, deploy | Forgejo CI, compose environments, deploy recipes, versioning and release flow |
| [development.md](development.md) | setup, development, prerequisites, just, make, local, getting started | Prerequisites, local setup, `just` recipe reference, config inspection, development loops |
| [design-decisions.md](design-decisions.md) | why, decisions, rationale, postmortem, nullpool, history, tradeoffs | The reasoning behind key choices: in-house evals, the async/NullPool incident, Docling constraints, cache bounds, the PII tier boundary |
