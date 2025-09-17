# Deployment Process Guide

## Overview

This document explains the improved deployment process for the Asterisk AI Voice Agent to prevent configuration mismatches and ensure reliable deployments.

## The Problem We Fixed

**Previous Issue**: The deployment process would deploy uncommitted changes, leading to:
- Configuration mismatches between local and server
- Silent failures when `git pull` had nothing to pull
- No verification that deployment was successful
- Difficult debugging when things went wrong

## New Deployment Process

### 1. Safe Deployment (Recommended)

```bash
make deploy-safe
```

**What it does:**
1. ✅ Checks for uncommitted changes
2. ✅ Fails if changes are uncommitted (with helpful error message)
3. ✅ Pushes changes to remote repository
4. ✅ Deploys to server
5. ✅ Verifies deployment was successful

**Use this for**: Normal development workflow

### 2. Force Deployment (Use with Caution)

```bash
make deploy-force
```

**What it does:**
1. ⚠️ Skips uncommitted changes check
2. ✅ Pushes changes to remote repository
3. ✅ Deploys to server
4. ✅ Verifies deployment was successful

**Use this for**: Emergency fixes or when you're sure about uncommitted changes

### 3. Legacy Deployment (Deprecated)

```bash
make deploy
```

**What it does:**
1. ⚠️ Shows warning about uncommitted changes
2. ✅ Deploys to server (may deploy uncommitted changes)
3. ❌ No verification

**Use this for**: Backward compatibility only

## Verification Commands

### Check Deployment Status
```bash
make verify-deployment
```

**What it checks:**
- Container status
- Recent logs for errors
- Configuration loading
- Service health

### Check Configuration
```bash
make verify-config
```

**What it checks:**
- Local configuration validity
- Server configuration validity
- Configuration consistency

### Monitor ExternalMedia Status
```bash
make monitor-externalmedia
```

**What it shows:**
- Real-time ExternalMedia + RTP status
- RTP server statistics
- Provider status
- Active calls

## Best Practices

### 1. Always Use Safe Deployment
```bash
# Good: Safe deployment
make deploy-safe

# Bad: Force deployment (unless necessary)
make deploy-force
```

### 2. Verify After Deployment
```bash
# Deploy and verify
make deploy-safe
make verify-deployment
```

### 3. Check Configuration Before Testing
```bash
# Verify config is correct
make verify-config

# Then test
make test-externalmedia
```

### 4. Monitor During Testing
```bash
# In one terminal: monitor
make monitor-externalmedia

# In another terminal: test
# Place test call
```

## Troubleshooting

### Issue: "You have uncommitted changes!"
**Solution:**
```bash
# Commit your changes
git add .
git commit -m "Your commit message"

# Then deploy safely
make deploy-safe
```

### Issue: "Configuration logs not found"
**Solution:**
```bash
# Check if container is running
make server-status

# Check recent logs
make server-logs-snapshot LINES=50

# Verify configuration
make verify-config
```

### Issue: "No errors found in recent logs" but something's wrong
**Solution:**
```bash
# Check more logs
make server-logs-snapshot LINES=100

# Check specific service
make server-logs SERVICE=ai-engine

# Monitor in real-time
make monitor-externalmedia
```

## Deployment Workflow

### Normal Development
1. Make code changes
2. Test locally: `make test-local`
3. Commit changes: `git add . && git commit -m "Description"`
4. Deploy safely: `make deploy-safe`
5. Verify: `make verify-deployment`
6. Test on server: `make test-externalmedia`

### Emergency Fix
1. Make urgent changes
2. Deploy immediately: `make deploy-force`
3. Verify: `make verify-deployment`
4. Test: `make test-externalmedia`
5. Commit later: `git add . && git commit -m "Emergency fix"`

### Configuration Changes
1. Update `config/ai-agent.yaml`
2. Test locally: `make verify-config`
3. Deploy safely: `make deploy-safe`
4. Verify on server: `make verify-config`
5. Test: `make test-externalmedia`

## Summary

The new deployment process ensures:
- ✅ No silent failures
- ✅ Configuration consistency
- ✅ Automatic verification
- ✅ Clear error messages
- ✅ Reliable deployments

**Always use `make deploy-safe` for normal development!**
