# Testing the Develop Branch

This guide explains how to test new features from the `develop` branch while **preserving your existing configuration and settings**.

## Overview

The `develop` branch contains the latest features and fixes before they're merged to `main`. Testing these helps us catch issues early and get community feedback.

**What gets preserved:**

- Your `config/ai-agent.yaml` settings
- Your `config/ai-agent.local.yaml` operator overrides (if present)
- Your `.env` file (API keys, secrets)
- Your context configurations
- Your tool configurations
- Your dialplan settings (in Asterisk/FreePBX)

---

## Quick Method (Recommended)

### Step 1: Backup Your Configs

```bash
cd /path/to/Asterisk-AI-Voice-Agent

# Create a backup directory with timestamp
BACKUP_DIR="config_backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

# Backup essential files
cp config/ai-agent.yaml "$BACKUP_DIR/"
cp config/ai-agent.local.yaml "$BACKUP_DIR/" 2>/dev/null || true
cp .env "$BACKUP_DIR/" 2>/dev/null || true
cp -r config/contexts "$BACKUP_DIR/" 2>/dev/null || true

echo "Backup saved to: $BACKUP_DIR"
```

### Step 2: Switch to Develop Branch

```bash
# Fetch latest changes
git fetch origin

# Stash any local changes (optional safety)
git stash

# Switch to develop branch
git checkout develop

# Pull latest updates
git pull origin develop
```

### Step 3: Restore Your Configs

```bash
# Restore your configs from backup
cp "$BACKUP_DIR/ai-agent.yaml" config/
cp "$BACKUP_DIR/ai-agent.local.yaml" config/ 2>/dev/null || true
cp "$BACKUP_DIR/.env" . 2>/dev/null || true
cp -r "$BACKUP_DIR/contexts" config/ 2>/dev/null || true
```

### Step 4: Rebuild and Test

```bash
# Rebuild containers with new code
docker compose down
docker compose up -d --build

# Watch logs for issues
docker logs -f ai_engine
```

### Step 5: Revert to Main (When Done Testing)

```bash
# Switch back to main/stable
git checkout main

# Restore your configs again
cp "$BACKUP_DIR/ai-agent.yaml" config/
cp "$BACKUP_DIR/ai-agent.local.yaml" config/ 2>/dev/null || true
cp "$BACKUP_DIR/.env" . 2>/dev/null || true

# Rebuild with stable code
docker compose down
docker compose up -d --build
```

---

## Alternative: Side-by-Side Installation

If you want to keep both versions available simultaneously:

### Step 1: Clone Develop to a Separate Directory

```bash
# Clone to a new directory
git clone -b develop https://github.com/hkjarral/Asterisk-AI-Voice-Agent.git AVA-develop
cd AVA-develop
```

### Step 2: Copy Your Configs

```bash
# Copy from your existing installation
cp /path/to/existing/Asterisk-AI-Voice-Agent/config/ai-agent.yaml config/
cp /path/to/existing/Asterisk-AI-Voice-Agent/config/ai-agent.local.yaml config/ 2>/dev/null || true
cp /path/to/existing/Asterisk-AI-Voice-Agent/.env .
cp -r /path/to/existing/Asterisk-AI-Voice-Agent/config/contexts config/ 2>/dev/null || true
```

### Step 3: Use Different Ports (Optional)

If running both simultaneously, edit `docker-compose.yml` to use different ports:

```yaml
services:
  ai_engine:
    ports:
      - "8088:8080"  # Changed from 8080
      - "18180-18199:18080-18099/udp"  # Changed RTP range
```

### Step 4: Run Develop Version

```bash
docker compose up -d --build
```

---

## Config Migration Notes

### New Settings in Develop

The develop branch may have new configuration options. Check for:

1. **New YAML fields**: Compare `config/ai-agent.example.yaml` with your config
2. **New environment variables**: Check `.env.example` for additions
3. **Schema changes**: Read the relevant milestone docs in `docs/contributing/milestones/`

### Merging New Options

```bash
# View differences between your config and the example
diff config/ai-agent.yaml config/ai-agent.example.yaml

# Or use a merge tool
# vimdiff config/ai-agent.yaml config/ai-agent.example.yaml
```

---

## Reporting Issues

When testing develop, please report any issues:

1. **Join Discord**: [https://discord.gg/ysg8fphxUe](https://discord.gg/ysg8fphxUe)
2. **Collect diagnostics**:
   ```bash
   ./scripts/rca_collect.sh
   ```
3. **Include**:
   - Branch/commit: `git rev-parse --short HEAD`
   - Error logs: `docker logs ai_engine 2>&1 | tail -100`
   - Your provider (Deepgram, OpenAI, Google, Local, etc.)
   - Steps to reproduce

---

## One-Liner Scripts

### Backup, Switch to Develop, and Restore

```bash
# All-in-one: backup → switch → restore → rebuild
BACKUP="config_backup_$(date +%Y%m%d_%H%M%S)" && \
mkdir -p "$BACKUP" && \
cp config/ai-agent.yaml config/ai-agent.local.yaml .env "$BACKUP" 2>/dev/null; \
cp -r config/contexts "$BACKUP" 2>/dev/null; \
git fetch origin && git checkout develop && git pull origin develop && \
cp "$BACKUP/ai-agent.yaml" config/ && \
cp "$BACKUP/ai-agent.local.yaml" config/ 2>/dev/null; \
cp "$BACKUP/.env" . 2>/dev/null; \
cp -r "$BACKUP/contexts" config/ 2>/dev/null; \
docker compose down && docker compose up -d --build
```

### Revert to Main

```bash
# Switch back to main with your configs
git checkout main && \
cp "$BACKUP/ai-agent.yaml" config/ && \
cp "$BACKUP/ai-agent.local.yaml" config/ 2>/dev/null; \
cp "$BACKUP/.env" . 2>/dev/null; \
docker compose down && docker compose up -d --build
```

---

## FAQ

**Q: Will my dialplan break?**  
A: Usually no. Dialplan changes are rare and documented in release notes.

**Q: What if develop has breaking config changes?**  
A: Check `docs/contributing/milestones/` for migration notes. Most changes are additive.

**Q: Can I contribute fixes while testing?**  
A: Yes! Create a branch from develop: `git checkout -b fix/my-fix develop`

**Q: How do I know what's new in develop?**  
A: Check `CHANGELOG.md` or run:

```bash
git log main..develop --oneline
```

---

## See Also

- [Quick Start Guide](quickstart.md) - Development environment setup

- [Testing Guide](testing-guide.md) - Testing your changes
- [Debugging Guide](debugging-guide.md) - Troubleshooting issues
