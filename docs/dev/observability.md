# Observability & Troubleshooting

## Metrics API

Comprehensive visibility into system configuration and performance.

**System Endpoints**:
- `/metrics/system`: Complete system overview + health status
- `/metrics/models`: Model details with references
- `/metrics/retrieval`: Pipeline configuration

**Evaluation Endpoints**: See [eval-framework.md](eval-framework.md) for complete evaluation API documentation.

## Health Monitoring

Component health via `/metrics/system`:
- PostgreSQL: Vector store + BM25 + queue connectivity
- Ollama: LLM availability

## Key Metrics

**Retrieval**: Contextual Precision, Contextual Recall, MRR, Hit Rate

**Generation**: Faithfulness, Answer Relevancy, Hallucination Rate

**Operational**: Latency (P50, P95), Tokens per query, Cost

## Troubleshooting

### Common Issues

- **Ollama not accessible**: Check host binding with `curl http://localhost:11434/api/tags`
- **PostgreSQL connection fails**: Verify `DATABASE_HOST`/`DATABASE_PORT`/`DATABASE_NAME` env vars, DB secrets, and `private` network connectivity
- **Docker build fails**: Ensure `--index-strategy unsafe-best-match` in Dockerfile
- **Tests fail**: Use `.venv/bin/pytest` not `uv run pytest`
- **Reranker slow first query**: Model downloads ~80MB on first use
- **BM25 not initializing**: Requires documents at startup or initializes after first upload
- **Contextual retrieval not working**: Check `enable_contextual_retrieval: true` in config

### Service Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f rag-server
docker compose logs -f task-worker
docker compose logs -f postgres
```

### Database Reset

```bash
docker compose down -v
docker compose up -d
```

### Backup & Restore

```bash
# Manual backup (PostgreSQL) — superuser name comes from secrets/POSTGRES_SUPERUSER
docker compose exec postgres pg_dump -U "$(cat secrets/POSTGRES_SUPERUSER)" ragbench > backups/ragbench.sql

# Restore
cat backups/ragbench.sql | docker compose exec -T postgres psql -U "$(cat secrets/POSTGRES_SUPERUSER)" -d ragbench
```
