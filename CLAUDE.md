## Library and Tool documentation
Use the Svelte MCP server for any Svelte related coding, question or documentation.

Otherwise, use context7 when I need code generation, setup or configuration steps, or
library/API documentation. This means you should automatically use the Context7 MCP
tools to resolve library id when it is not known, and get library docs without me having to explicitly ask.

### Context7 IDs
For tailwind 4, use context7 with id: websites/tailwindcss
For DaisyUI doc, use context7 with id: websites/daisyui

## Development Documentation

Architecture, API reference, database patterns, configuration, eval framework, testing,
observability, PII masking, CI/CD: see `docs/dev/INDEX.md` — load a topic with the
`dev-docs` skill rather than reading everything.

## Python

### Prefer Functions Over Classes
- Use module-level functions instead of classes for stateless operations
- Avoid singleton pattern (`_instance = None` + `get_instance()`) - just use functions
- Classes are appropriate for: stateful objects, resource lifecycle management, framework integration

### Documentation
- Skip docstrings on private helpers - use inline comments if non-obvious
- Type hints replace parameter/return documentation
- Keep public API docstrings to one line when possible

## Gotchas

### Docling + LlamaIndex
- **CRITICAL**: Must use `DoclingReader(export_type=DoclingReader.ExportType.JSON)` — DoclingNodeParser requires JSON

### Docker Build
- Dockerfile uses `--index-strategy unsafe-best-match` for PyTorch CPU index resolution
- Includes gcc, g++, make for pystemmer compilation (sentence-transformers dep)

### Integration Tests
- **No separate test-runner service** — tests reuse the `rag-server` service definition to avoid config drift (env, secrets, volumes, networks)

## Common Issues

- **Docker build fails:** ensure `--index-strategy unsafe-best-match` in Dockerfile
- **Reranker slow on first query:** downloads model (~80MB), adds ~100-300ms
- **task-worker issues:** `docker compose logs task-worker` — auto-restarts, stuck tasks reset after 1 hour
- **Slow processing:** contextual retrieval takes ~85% of time (LLM calls per chunk)
