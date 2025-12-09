# Forgejo CI/CD Setup Guide

This guide walks you through setting up Forgejo as a self-hosted CI/CD system for the RAG-Docling project.

## What is Forgejo?

Forgejo is a lightweight, self-hosted Git service with integrated CI/CD (Actions). It's a community-driven fork of Gitea with:
- GitHub-compatible CI/CD (Actions syntax)
- Lightweight footprint (~512MB RAM)
- Single binary deployment
- Full Git hosting with web UI

## Architecture

```
┌─────────────────────────────────────────┐
│ Forgejo Server (localhost:3000)        │
│  - Git hosting                          │
│  - Web UI                               │
│  - Actions (CI/CD) controller           │
└─────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│ Forgejo Runner                          │
│  - Executes CI/CD jobs                  │
│  - Uses Docker to run containers        │
└─────────────────────────────────────────┘
```

## Quick Start

### 1. Start Forgejo Server

```bash
# Start Forgejo and runner
docker compose -f docker-compose.ci.yml up -d

# Check logs
docker compose -f docker-compose.ci.yml logs -f forgejo
```

### 2. Initial Setup (First Time Only)

1. **Open Forgejo Web UI**: http://localhost:3000

2. **Complete installation wizard**:
   - Database: SQLite (default, already configured)
   - Site Title: `RAG-Docling`
   - Administrator Account:
     - Username: `admin` (or your choice)
     - Password: (choose a strong password)
     - Email: your email
   - Click **Install Forgejo**

3. **Login** with your admin credentials

### 3. Register the Runner

The runner needs to be registered with your Forgejo instance:

```bash
# Step 1: Get registration token from Forgejo Web UI
# Go to: http://localhost:3000/admin/actions/runners
# Click "Create new runner" and copy the registration token

# Step 2: Register the runner (replace TOKEN with your actual token)
docker exec -it forgejo-runner \
  forgejo-runner register \
  --instance http://forgejo:3000 \
  --token <YOUR_REGISTRATION_TOKEN> \
  --name docker-runner \
  --labels docker:docker://node:20,docker:docker://python:3.13

# Step 3: Restart the runner to activate
docker compose -f docker-compose.ci.yml restart forgejo-runner

# Verify runner is connected
# Go back to: http://localhost:3000/admin/actions/runners
# You should see "docker-runner" with status "Idle"
```

### 4. Create Your First Repository

1. **In Forgejo Web UI**, click **+** → **New Repository**
2. **Repository name**: `rag-docling`
3. **Visibility**: Private (or Public)
4. Click **Create Repository**

### 5. Push Your Code to Forgejo

```bash
# Add Forgejo as a remote (if you have existing repo)
git remote add forgejo http://localhost:3000/admin/rag-docling.git

# Or set it as origin (if starting fresh)
git remote set-url origin http://localhost:3000/admin/rag-docling.git

# Push your code
git push forgejo main
# Or: git push origin main
```

### 6. Configure Secrets for Eval Tests

To run evaluation tests, add your Anthropic API key:

1. Go to repository **Settings** → **Secrets and Variables** → **Actions**
2. Click **New secret**
3. Name: `ANTHROPIC_API_KEY`
4. Value: Your Anthropic API key (starts with `sk-ant-`)
5. Click **Add secret**

## Using the CI/CD Pipeline

### Automatic Triggers

The CI pipeline runs automatically on:
- **Every push** to any branch → Runs core tests + Docker build
- **Pull requests** → Runs core tests + Docker build

### Running Evaluation Tests

Eval tests are **OFF by default** to save API costs. Enable them via:

#### Method 1: Commit Message Flag
```bash
git commit -m "feat: improve retrieval [eval]"
git push
```

#### Method 2: Manual Workflow Dispatch
1. Go to **Actions** tab in Forgejo
2. Select the **CI** workflow
3. Click **Run workflow**
4. Check **Run evaluation tests**
5. Click **Run**

### Viewing CI Results

1. Go to your repository in Forgejo
2. Click **Actions** tab
3. Click on any workflow run to see:
   - Job status (✓ passed, ✗ failed)
   - Detailed logs
   - Test results

## CI Pipeline Jobs

The `.forgejo/workflows/ci.yml` defines 3 jobs:

### 1. Core Tests (Always Runs)
- **Duration**: ~30 seconds
- **Tests**: 33 core unit/integration tests
- **Container**: `ghcr.io/astral-sh/uv:python3.13-bookworm-slim`
- **Command**: `pytest tests/ --ignore=tests/evaluation --ignore=tests/test_rag_eval.py`

### 2. Evaluation Tests (Optional)
- **Duration**: ~2-5 minutes
- **Tests**: 27 evaluation tests (DeepEval)
- **Requires**: `ANTHROPIC_API_KEY` secret
- **Triggers**: Manual dispatch or `[eval]` in commit message
- **Command**: `pytest tests/test_rag_eval.py --run-eval --eval-samples=5`

### 3. Docker Build (Always Runs)
- **Duration**: ~5-10 minutes
- **Builds**: `rag-server` + `webapp` images
- **Verifies**: Both images build without errors

## Customizing the CI Pipeline

Edit `.forgejo/workflows/ci.yml` to:

### Add More Test Steps
```yaml
- name: Run integration tests
  run: |
    docker compose up -d
    pytest tests/integration/ -v
    docker compose down
```

### Add Code Quality Checks
```yaml
- name: Lint with ruff
  run: |
    uv run ruff check .

- name: Format check
  run: |
    uv run ruff format --check .
```

### Add Deployment
```yaml
deploy:
  name: Deploy to Production
  runs-on: ubuntu-latest
  needs: [test, docker-build]
  if: github.ref == 'refs/heads/main'
  steps:
    - name: Deploy via SSH
      run: |
        # Your deployment commands
```

## Troubleshooting

### Runner Not Connecting

**Symptom**: Runner shows as offline in Forgejo UI

**Solution**:
```bash
# Check runner logs
docker compose -f docker-compose.ci.yml logs forgejo-runner

# Re-register runner
docker exec -it forgejo-runner forgejo-runner register --instance http://forgejo:3000 --token <TOKEN> --name docker-runner

# Restart
docker compose -f docker-compose.ci.yml restart forgejo-runner
```

### CI Jobs Failing to Start

**Symptom**: Jobs stuck in "Waiting" state

**Possible causes**:
1. **No runner available**: Check runner status at `/admin/actions/runners`
2. **Wrong labels**: Ensure workflow uses `runs-on: ubuntu-latest` or `runs-on: docker`
3. **Runner token expired**: Re-register runner

### Docker Build Fails in CI

**Symptom**: `docker: command not found`

**Solution**: Ensure runner has access to Docker socket:
```yaml
# In docker-compose.ci.yml
forgejo-runner:
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock
```

### Eval Tests Fail with "Missing ANTHROPIC_API_KEY"

**Solution**:
1. Verify secret is added: Repository → Settings → Secrets → Actions
2. Secret name must be exactly: `ANTHROPIC_API_KEY`
3. Check workflow references it correctly:
   ```yaml
   env:
     ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
   ```

## Maintenance

### Backup Forgejo Data

```bash
# Create backup
docker exec forgejo forgejo dump -c /data/gitea/conf/app.ini

# Backup is saved in container at /data/gitea-dump-*.zip
# Copy to host
docker cp forgejo:/data/gitea-dump-*.zip ./backups/
```

### Update Forgejo

```bash
# Pull latest image
docker compose -f docker-compose.ci.yml pull forgejo

# Restart with new image
docker compose -f docker-compose.ci.yml up -d forgejo
```

### View Logs

```bash
# Forgejo server logs
docker compose -f docker-compose.ci.yml logs -f forgejo

# Runner logs
docker compose -f docker-compose.ci.yml logs -f forgejo-runner

# Both
docker compose -f docker-compose.ci.yml logs -f
```

### Stop Forgejo

```bash
# Stop services (keeps data)
docker compose -f docker-compose.ci.yml down

# Stop and remove data (WARNING: deletes everything)
docker compose -f docker-compose.ci.yml down -v
```

## Advanced Configuration

### Enable SSH Access

If you want to use SSH for Git operations:

1. **Generate SSH key** (if you don't have one):
   ```bash
   ssh-keygen -t ed25519 -C "your_email@example.com"
   ```

2. **Add public key to Forgejo**:
   - Go to Settings → SSH / GPG Keys → Add Key
   - Paste contents of `~/.ssh/id_ed25519.pub`

3. **Clone/push via SSH**:
   ```bash
   git remote add forgejo ssh://git@localhost:222/admin/rag-docling.git
   git push forgejo main
   ```

### Connect to External Git Provider

You can mirror your repository to/from GitHub, GitLab, etc.:

1. Go to repository **Settings** → **Repository**
2. Scroll to **Mirrors**
3. Add mirror URL and credentials

### Use with GitHub Actions (Hybrid Approach)

You can keep both GitHub Actions and Forgejo CI:
- GitHub Actions: For cloud-based CI
- Forgejo Actions: For local/private CI

Both use the same workflow syntax (mostly compatible).

## Comparison: Forgejo vs GitHub Actions

| Feature | Forgejo | GitHub Actions |
|---------|---------|----------------|
| **Hosting** | Self-hosted | Cloud |
| **Cost** | Free | Free (2,000 min/month) |
| **Privacy** | Full control | GitHub has access |
| **Syntax** | GitHub Actions compatible | Native |
| **Runner** | Your hardware | GitHub's servers |
| **Speed** | Depends on hardware | Generally fast |
| **Maintenance** | You maintain | None |

## Resources

- **Forgejo Documentation**: https://forgejo.org/docs/latest/
- **Forgejo Actions Guide**: https://forgejo.org/docs/latest/user/actions/
- **GitHub Actions Syntax**: https://docs.github.com/en/actions (mostly compatible)
- **Codeberg** (Hosted Forgejo): https://codeberg.org

## Next Steps

1. ✅ Set up Forgejo (this guide)
2. 📝 Add more test coverage
3. 🔧 Customize CI workflow for your needs
4. 🚀 Add deployment automation
5. 📊 Set up notifications (email, webhooks)

For questions or issues, see the main [DEVELOPMENT.md](../DEVELOPMENT.md) guide.
