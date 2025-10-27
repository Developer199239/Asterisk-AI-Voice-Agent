#!/usr/bin/env python3
"""
Config Migration Script - v3 to v4

Migrates configuration from v3 (mixed production + diagnostic settings)
to v4 (clean production config + diagnostic env vars).

Usage:
    python scripts/migrate_config_v4.py --dry-run    # Preview changes
    python scripts/migrate_config_v4.py --apply      # Apply migration
"""

import argparse
import os
import sys
import yaml
from pathlib import Path
from datetime import datetime


# Settings to extract into environment variables
DIAGNOSTIC_SETTINGS = {
    # streaming section
    'egress_swap_mode': {
        'env_var': 'DIAG_EGRESS_SWAP_MODE',
        'default': 'none',
        'description': 'PCM16 byte order detection (auto|swap|none)'
    },
    'egress_force_mulaw': {
        'env_var': 'DIAG_EGRESS_FORCE_MULAW',
        'default': 'false',
        'description': 'Force mulaw output regardless of detection'
    },
    'attack_ms': {
        'env_var': 'DIAG_ATTACK_MS',
        'default': '0',
        'description': 'Attack envelope ramp duration (diagnostic only)'
    },
    'diag_enable_taps': {
        'env_var': 'DIAG_ENABLE_TAPS',
        'default': 'false',
        'description': 'Enable PCM audio taps for RCA analysis'
    },
    'diag_pre_secs': {
        'env_var': 'DIAG_TAP_PRE_SECS',
        'default': '1',
        'description': 'Pre-companding tap duration (seconds)'
    },
    'diag_post_secs': {
        'env_var': 'DIAG_TAP_POST_SECS',
        'default': '1',
        'description': 'Post-companding tap duration (seconds)'
    },
    'diag_out_dir': {
        'env_var': 'DIAG_TAP_OUTPUT_DIR',
        'default': '/tmp/ai-engine-taps',
        'description': 'Directory for diagnostic audio taps'
    },
    'logging_level': {
        'env_var': 'STREAMING_LOG_LEVEL',
        'default': 'info',
        'description': 'Streaming logger verbosity (debug|info|warning|error)'
    },
}

# Settings to remove entirely (deprecated)
DEPRECATED_SETTINGS = {
    'allow_output_autodetect',  # Replaced by Transport Orchestrator
}


def load_config(config_path):
    """Load YAML configuration file."""
    try:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"❌ Error loading config: {e}")
        sys.exit(1)


def extract_diagnostic_settings(config):
    """Extract diagnostic settings that should become env vars."""
    env_vars = {}
    removed_settings = []
    
    if 'streaming' in config:
        streaming = config['streaming']
        for key, info in DIAGNOSTIC_SETTINGS.items():
            if key in streaming:
                value = streaming[key]
                # Convert Python bool to string for env var
                if isinstance(value, bool):
                    value = 'true' if value else 'false'
                env_vars[info['env_var']] = {
                    'value': str(value),
                    'description': info['description'],
                    'yaml_key': f'streaming.{key}'
                }
                removed_settings.append(f'streaming.{key}')
    
    # Check for deprecated settings in providers
    if 'providers' in config:
        for provider_name, provider_config in config['providers'].items():
            if isinstance(provider_config, dict):
                for deprecated in DEPRECATED_SETTINGS:
                    if deprecated in provider_config:
                        removed_settings.append(f'providers.{provider_name}.{deprecated}')
    
    return env_vars, removed_settings


def clean_config(config):
    """Remove diagnostic and deprecated settings from config."""
    cleaned = config.copy()
    
    # Remove diagnostic settings from streaming section
    if 'streaming' in cleaned:
        streaming = cleaned['streaming']
        for key in DIAGNOSTIC_SETTINGS.keys():
            streaming.pop(key, None)
    
    # Remove deprecated settings from providers
    if 'providers' in cleaned:
        for provider_name, provider_config in cleaned['providers'].items():
            if isinstance(provider_config, dict):
                for deprecated in DEPRECATED_SETTINGS:
                    provider_config.pop(deprecated, None)
    
    # Add config version
    cleaned['config_version'] = 4
    
    return cleaned


def generate_env_file(env_vars):
    """Generate .env file content."""
    lines = [
        "# Diagnostic Settings (migrated from config/ai-agent.yaml)",
        "# These settings are for troubleshooting only - not needed in production",
        f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]
    
    for env_name, info in sorted(env_vars.items()):
        lines.append(f"# {info['description']}")
        lines.append(f"# Migrated from: {info['yaml_key']}")
        lines.append(f"{env_name}={info['value']}")
        lines.append("")
    
    return "\n".join(lines)


def write_files(config_path, cleaned_config, env_content, dry_run=True):
    """Write cleaned config and env file."""
    config_dir = Path(config_path).parent
    new_config_path = config_dir / "ai-agent-v4.yaml"
    env_path = config_dir / "diagnostic.env"
    
    if dry_run:
        print("\n" + "="*60)
        print("DRY RUN - Files would be written to:")
        print("="*60)
        print(f"\n📄 {new_config_path}")
        print(f"📄 {env_path}")
        print("\nTo apply changes, run with --apply flag")
        return
    
    # Write cleaned config
    try:
        with open(new_config_path, 'w') as f:
            yaml.dump(cleaned_config, f, default_flow_style=False)
        print(f"✅ Written: {new_config_path}")
    except Exception as e:
        print(f"❌ Error writing config: {e}")
        sys.exit(1)
    
    # Write env file
    try:
        with open(env_path, 'w') as f:
            f.write(env_content)
        print(f"✅ Written: {env_path}")
    except Exception as e:
        print(f"❌ Error writing env file: {e}")
        sys.exit(1)


def print_summary(env_vars, removed_settings):
    """Print migration summary."""
    print("\n" + "="*60)
    print("MIGRATION SUMMARY")
    print("="*60)
    
    print(f"\n📦 Settings moved to environment variables: {len(env_vars)}")
    for env_name, info in sorted(env_vars.items()):
        print(f"  • {env_name}={info['value']}")
        print(f"    ↳ Was: {info['yaml_key']}")
    
    print(f"\n🗑️  Deprecated settings removed: {len(removed_settings)}")
    for setting in sorted(removed_settings):
        print(f"  • {setting}")
    
    print(f"\n📝 Config version: 4")


def main():
    parser = argparse.ArgumentParser(
        description='Migrate config from v3 to v4',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        '--config',
        default='config/ai-agent.yaml',
        help='Path to config file (default: config/ai-agent.yaml)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without writing files'
    )
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Apply migration and write new files'
    )
    
    args = parser.parse_args()
    
    if not args.dry_run and not args.apply:
        print("❌ Must specify either --dry-run or --apply")
        sys.exit(1)
    
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"❌ Config file not found: {config_path}")
        sys.exit(1)
    
    print("🔍 Loading configuration...")
    config = load_config(config_path)
    
    print("🔧 Extracting diagnostic settings...")
    env_vars, removed_settings = extract_diagnostic_settings(config)
    
    print("🧹 Cleaning configuration...")
    cleaned_config = clean_config(config)
    
    print("📝 Generating environment file...")
    env_content = generate_env_file(env_vars)
    
    # Print summary
    print_summary(env_vars, removed_settings)
    
    # Write files
    write_files(config_path, cleaned_config, env_content, dry_run=args.dry_run)
    
    if args.apply:
        print("\n" + "="*60)
        print("✅ MIGRATION COMPLETE")
        print("="*60)
        print("\nNext steps:")
        print("1. Review generated files:")
        print(f"   • config/ai-agent-v4.yaml")
        print(f"   • config/diagnostic.env")
        print("2. Test with: docker-compose config")
        print("3. Apply: mv config/ai-agent-v4.yaml config/ai-agent.yaml")
        print("4. Source env vars: docker-compose --env-file config/diagnostic.env up -d")
        print("5. Verify: ./bin/agent doctor")


if __name__ == '__main__':
    main()
