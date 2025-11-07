# Agent CLI Tools

Go-based command-line interface for Asterisk AI Voice Agent operations.

## Overview

The `agent` CLI provides a comprehensive set of tools for setup, diagnostics, and troubleshooting. All commands are built as a single Go binary for easy distribution.

**Current Status**: ✅ Binary builds available for v4.1+

## Available Commands

- **`agent init`** - Interactive setup wizard
- **`agent doctor`** - System health check and diagnostics
- **`agent demo`** - Audio pipeline validation
- **`agent troubleshoot`** - Post-call analysis and RCA
- **`agent version`** - Show version information

## Installation

### Quick Install (Recommended)

**Linux/macOS:**
```bash
curl -sSL https://raw.githubusercontent.com/hkjarral/Asterisk-AI-Voice-Agent/main/scripts/install-cli.sh | bash
```

This will:
- Detect your platform automatically
- Download the latest binary
- Verify checksums
- Install to `/usr/local/bin`
- Test the installation

### Manual Download

Download pre-built binaries from [GitHub Releases](https://github.com/hkjarral/Asterisk-AI-Voice-Agent/releases):

**Linux:**
```bash
# AMD64 (most Linux servers)
curl -L -o agent https://github.com/hkjarral/Asterisk-AI-Voice-Agent/releases/latest/download/agent-linux-amd64
chmod +x agent
sudo mv agent /usr/local/bin/

# ARM64 (Raspberry Pi, AWS Graviton)
curl -L -o agent https://github.com/hkjarral/Asterisk-AI-Voice-Agent/releases/latest/download/agent-linux-arm64
chmod +x agent
sudo mv agent /usr/local/bin/
```

**macOS:**
```bash
# Intel Macs
curl -L -o agent https://github.com/hkjarral/Asterisk-AI-Voice-Agent/releases/latest/download/agent-darwin-amd64
chmod +x agent
sudo mv agent /usr/local/bin/

# Apple Silicon (M1/M2/M3)
curl -L -o agent https://github.com/hkjarral/Asterisk-AI-Voice-Agent/releases/latest/download/agent-darwin-arm64
chmod +x agent
sudo mv agent /usr/local/bin/
```

**Windows:**
Download `agent-windows-amd64.exe` from releases and add to your PATH.

### Verify Installation

```bash
agent version
```

## Building from Source

### Prerequisites

- Go 1.21 or newer
- Linux/macOS/Windows

### Build Instructions

```bash
# From project root
make cli-build

# Or build manually
cd cli
go build -o ../bin/agent ./cmd/agent
```

### Build for All Platforms

```bash
# Creates binaries for Linux, macOS, Windows (AMD64 & ARM64)
make cli-build-all

# Generate checksums
make cli-checksums

# Complete release build
make cli-release
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
