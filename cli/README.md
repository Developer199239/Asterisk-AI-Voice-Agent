# Agent CLI Tools

Go-based command-line interface for Asterisk AI Voice Agent operations.

## Overview

The `agent` CLI provides a comprehensive set of tools for setup, diagnostics, and troubleshooting. All commands are built as a single Go binary for easy distribution.

**Current Status**: Source code available in Go, binary builds planned for v4.1

## Available Commands

- **`agent init`** - Interactive setup wizard
- **`agent doctor`** - System health check and diagnostics
- **`agent demo`** - Audio pipeline validation
- **`agent troubleshoot`** - Post-call analysis and RCA
- **`agent version`** - Show version information

## Building from Source

### Prerequisites

- Go 1.21 or newer
- Linux/macOS (Windows support planned)

### Build Instructions

```bash
# From project root
cd cli
go build -o ../bin/agent ./cmd/agent

# Or use the Makefile (from project root)
make cli-build
```

### Install System-Wide (Optional)

```bash
# Copy to system path
sudo cp bin/agent /usr/local/bin/

# Verify installation
agent version
```

## Quick Start

### 1. Run Setup Wizard

```bash
./bin/agent init
```

Guides you through:
- Asterisk ARI credentials
- Audio transport selection (AudioSocket/ExternalMedia)
- AI provider selection (OpenAI, Deepgram, Local)
- Configuration validation

### 2. Validate Environment

```bash
./bin/agent doctor
```

Checks:
- Docker containers running
- Asterisk ARI connectivity
- AudioSocket/RTP ports available
- Configuration validity
- Provider API connectivity

### 3. Test Audio Pipeline

```bash
./bin/agent demo
```

Validates audio without making real calls.

### 4. Troubleshoot Issues

```bash
# Analyze most recent call
./bin/agent troubleshoot

# Analyze specific call
./bin/agent troubleshoot <call_id>
```

## Documentation

For detailed usage examples and command reference, see:
- **[CLI Tools Guide](../docs/CLI_TOOLS_GUIDE.md)** - Complete usage documentation
- **[CHANGELOG.md](../CHANGELOG.md)** - CLI tools features and updates

## Development

### Project Structure

```
cli/
├── cmd/agent/           # Main CLI commands
│   ├── main.go          # Root command and app entry
│   ├── init.go          # Setup wizard
│   ├── doctor.go        # Health checks
│   ├── demo.go          # Audio validation
│   ├── troubleshoot.go  # Post-call analysis
│   └── version.go       # Version command
└── internal/            # Internal packages
    ├── wizard/          # Interactive setup wizard
    ├── health/          # Health check system
    ├── audio/           # Audio test utilities
    └── rca/             # Root cause analysis
```

### Dependencies

```bash
# Install dependencies
go mod download

# Update dependencies
go get -u ./...
go mod tidy
```

### Testing

```bash
# Run tests
go test ./...

# Run with coverage
go test -cover ./...
```

## Planned Features (v4.1)

- [ ] Automated binary builds (Makefile target)
- [ ] `agent config validate` - Pre-flight config validation
- [ ] `agent test` - Automated test call execution
- [ ] Windows support
- [ ] Shell completion (bash, zsh, fish)
- [ ] Package managers (apt, yum, brew)

## Exit Codes

Commands follow standard Unix exit code conventions:

- **0** - Success
- **1** - Warning (non-critical issues detected)
- **2** - Failure (critical issues detected)

Use in scripts:

```bash
#!/bin/bash
if ! ./bin/agent doctor; then
    echo "Health check failed - see output above"
    exit 1
fi
```

## Support

- **Documentation**: [docs/CLI_TOOLS_GUIDE.md](../docs/CLI_TOOLS_GUIDE.md)
- **Issues**: https://github.com/hkjarral/Asterisk-AI-Voice-Agent/issues
- **Discussions**: https://github.com/hkjarral/Asterisk-AI-Voice-Agent/discussions

## License

Same as parent project - see [LICENSE](../LICENSE)
