# Secrets Directory

This directory contains sensitive API keys and credentials.

## Setup

### 1. API Keys (.env)

Create `secrets/.env` from the example:

```bash
cp .env.example .env
```

Edit `.env` and add your API keys:

```bash
# For cloud LLM providers (not needed for Ollama)
LLM_API_KEY=sk-...

# For DeepEval evaluations (required)
ANTHROPIC_API_KEY=sk-ant-...
```

### 2. Ollama Configuration (ollama_config.env)

Create `secrets/ollama_config.env` from the example:

```bash
cp ollama_config.env.example ollama_config.env
```

Default configuration should work for most users:

```bash
OLLAMA_URL=http://host.docker.internal:11434
OLLAMA_KEEP_ALIVE=10m
```

## Getting API Keys

### Anthropic (Required for Evaluations)
1. Sign up at https://console.anthropic.com/
2. Navigate to API Keys section
3. Create new key
4. Add to `ANTHROPIC_API_KEY` in `.env`

### OpenAI
1. Sign up at https://platform.openai.com/
2. Navigate to API Keys
3. Create new key
4. Add to `LLM_API_KEY` in `.env`
5. Update `config/models.yml` to use OpenAI provider

### Other Providers
- **Google Gemini**: https://ai.google.dev/
- **DeepSeek**: https://platform.deepseek.com/
- **Moonshot (Kimi)**: https://platform.moonshot.cn/

## Security Notes

- **Never commit `.env` files to git** - they're in `.gitignore`
- Store production keys securely (use secret managers in production)
- Rotate keys regularly
- Use different keys for development and production
- The `.env.example` files are safe to commit (no secrets)

## Docker Integration

### Environment Variables (.env)
Loaded by `docker-compose.yml` as environment variables:
```yaml
environment:
  - LLM_API_KEY=${LLM_API_KEY:-}
  - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}
```

### Docker Secrets (ollama_config.env)
Mounted as Docker secret:
```yaml
secrets:
  ollama_config:
    file: ./secrets/ollama_config.env
```

## Troubleshooting

### "API key required" Error
- Verify API key is set in `.env`
- Restart services: `docker compose down && docker compose up -d`
- Check key format matches provider requirements

### Ollama Connection Failed
- Ensure Ollama is running on host: `ollama list`
- Verify `OLLAMA_URL` in `ollama_config.env`
- Check Docker can reach host: `docker compose exec rag-server curl http://host.docker.internal:11434/api/tags`

### Environment Variables Not Loading
- Ensure `.env` file exists in `secrets/` directory
- Check file permissions (should be readable)
- Restart Docker Compose to reload environment
