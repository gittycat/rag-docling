# Secrets Template

This directory contains template files for secrets used by the RAG system.

## Setup

1. Create a `secrets` directory at the project root:
   ```bash
   mkdir ../secrets
   ```

2. Copy template files to the secrets directory:
   ```bash
   cp ollama_config.env ../secrets/ollama_config.env
   ```

3. Edit the files in `../secrets/` with your actual configuration values.

## Security Notes

- The `secrets/` directory is in `.gitignore` and should never be committed
- Docker Secrets will mount these files into containers at runtime
- Never hardcode sensitive values in source code or Docker images
