# CLI Tools Guide (`agent`)

Operator-focused reference for the `agent` CLI (setup + diagnostics + post-call RCA + updates).

## What it does

- `agent setup`: interactive onboarding (providers, transport, dialplan hints).
- `agent check`: shareable diagnostics report for support (recommended first step when debugging).
- `agent rca`: post-call RCA using Call History and logs.
- `agent update`: safe pull + rebuild/restart + verify workflow for repo-based installs.
- `agent version`: version/build info (attach to issues).

## Installation

### If you installed the full project

The CLI is included with standard installs (for example via `install.sh` / Admin UI workflows). If `agent` is already on your PATH, skip ahead to Usage.

### CLI-only install (prebuilt binaries)

From a Linux/macOS host:

```bash
curl -sSL https://raw.githubusercontent.com/hkjarral/Asterisk-AI-Voice-Agent/main/scripts/install-cli.sh | bash
```

Verify:

```bash
agent version
```

## Usage

Run these commands on the host that runs Docker Compose for this repo (the CLI shells out to Docker/Compose and reads your local `.env` and `config/ai-agent.yaml`).

### `agent setup`

```bash
agent setup
```

Typically guides:
1) ARI host/credentials validation  
2) transport selection (AudioSocket vs ExternalMedia)  
3) provider selection (OpenAI/Deepgram/Google/Local/etc.)  
4) writes config + restarts services  

### `agent check`

```bash
agent check
```

Useful flags:

```bash
agent check --json
agent check --verbose
agent check --no-color
```

### `agent rca`

```bash
# Most recent call
agent rca

# Specific call ID
agent rca --call <call_id>
```

### `agent update`

```bash
agent update
```

Use this for repo-based installs when you want a conservative “update + rebuild + verify” flow.

## Notes

- CLI details for building from source live in `cli/README.md`.
- For call-level debugging, use **Admin UI → Call History** first, then `agent rca` for a concise root-cause summary.

