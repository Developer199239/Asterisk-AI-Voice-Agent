"""
Configuration file loaders and path resolution.

This module handles:
- Path resolution (relative to absolute)
- YAML file loading
- Environment variable expansion in YAML with default value support
"""

import os
import re
import yaml
from pathlib import Path


# Project root directory (parent of src/)
_PROJ_DIR = Path(__file__).parent.parent.parent.resolve()

# Pattern to match ${VAR:-default} or ${VAR:=default} shell-style syntax
_ENV_VAR_PATTERN = re.compile(r'\$\{([^}:]+)(:-|:=)?([^}]*)?\}')


def _expand_env_vars_with_defaults(text: str) -> str:
    """
    Expand environment variables with support for shell-style defaults.
    
    Supports:
    - ${VAR} - Basic expansion
    - ${VAR:-default} - Use default if VAR is unset or empty
    - ${VAR:=default} - Use default if VAR is unset or empty (same as :- for our purposes)
    - $VAR - Simple expansion (handled by os.path.expandvars)
    
    Args:
        text: String containing environment variable references
        
    Returns:
        String with environment variables expanded
    """
    def replace_match(match):
        var_name = match.group(1)
        operator = match.group(2)  # :- or := or None
        default_value = match.group(3) or ""
        
        env_value = os.environ.get(var_name)
        
        if operator in (":-", ":="):
            # Use default if env var is unset or empty
            if env_value is None or env_value == "":
                return default_value
            return env_value
        else:
            # No default operator, just expand ${VAR}
            return env_value if env_value is not None else match.group(0)
    
    # First handle ${VAR:-default} and ${VAR:=default} patterns
    result = _ENV_VAR_PATTERN.sub(replace_match, text)
    
    # Then handle any remaining simple $VAR patterns
    result = os.path.expandvars(result)
    
    return result


def resolve_config_path(path: str) -> str:
    """
    Resolve configuration file path to absolute path.
    
    If the provided path is not absolute, it is resolved relative to the project root.
    
    Args:
        path: Configuration file path (absolute or relative)
        
    Returns:
        Absolute path to configuration file
        
    Complexity: 2
    """
    if not os.path.isabs(path):
        return os.path.join(_PROJ_DIR, path)
    return path


def load_yaml_with_env_expansion(path: str) -> dict:
    """
    Load YAML file with environment variable expansion.
    
    Reads the YAML file, expands environment variable references with shell-style
    default value support, then parses the YAML content.
    
    Supports:
    - ${VAR} - Basic expansion
    - ${VAR:-default} - Use default if VAR is unset or empty  
    - ${VAR:=default} - Use default if VAR is unset or empty
    - $VAR - Simple expansion
    
    Args:
        path: Absolute path to YAML configuration file
        
    Returns:
        Parsed configuration dictionary
        
    Raises:
        FileNotFoundError: If configuration file doesn't exist
        yaml.YAMLError: If YAML parsing fails
        
    Complexity: 3
    """
    try:
        with open(path, 'r') as f:
            config_str = f.read()
        
        # Substitute environment variables with shell-style default support
        config_str_expanded = _expand_env_vars_with_defaults(config_str)
        
        # Parse YAML
        config_data = yaml.safe_load(config_str_expanded)
        
        return config_data if config_data is not None else {}
        
    except FileNotFoundError:
        raise FileNotFoundError(f"Configuration file not found at: {path}")
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"Error parsing YAML configuration: {e}")
