#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2025 Savoir-faire Linux, Inc.

"""
docker-compose YAML parser helper script to determine volume properties.
"""

import sys
import yaml


def safe_load_yaml(file_path):
    """Safely load YAML file and return parsed content."""
    try:
        with open(file_path, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"Error loading YAML file: {e}", file=sys.stderr)
        return None


def get_volume_names(yaml_data):
    """Extract volume names from YAML data."""
    volumes = yaml_data.get('volumes', {})
    if isinstance(volumes, dict):
        return list(volumes.keys())
    return []


def get_volume_property(yaml_data, volume_name, property_name):
    """Get a specific property of a volume."""
    volumes = yaml_data.get('volumes', {})
    if isinstance(volumes, dict) and volume_name in volumes:
        volume_config = volumes[volume_name]
        if isinstance(volume_config, dict):
            value = volume_config.get(property_name)
            # Handle null/None values like yq does
            if value is None:
                return "null"
            # Handle boolean values - convert to lowercase string like yq
            if isinstance(value, bool):
                return str(value).lower()
            return str(value)
    return "null"


def get_driver_opts_keys(yaml_data, volume_name):
    """Get driver_opts keys for a volume."""
    volumes = yaml_data.get('volumes', {})
    if isinstance(volumes, dict) and volume_name in volumes:
        volume_config = volumes[volume_name]
        if isinstance(volume_config, dict):
            driver_opts = volume_config.get('driver_opts', {})
            if isinstance(driver_opts, dict):
                return list(driver_opts.keys())
    return []


def get_driver_opt_value(yaml_data, volume_name, opt_key):
    """Get a specific driver_opts value for a volume."""
    volumes = yaml_data.get('volumes', {})
    if isinstance(volumes, dict) and volume_name in volumes:
        volume_config = volumes[volume_name]
        if isinstance(volume_config, dict):
            driver_opts = volume_config.get('driver_opts', {})
            if isinstance(driver_opts, dict):
                value = driver_opts.get(opt_key)
                if value is None:
                    return "null"
                return str(value)
    return "null"


def main():
    if len(sys.argv) < 3:
        print("Usage: yaml_parser.py <yaml_file> <operation> [args...]", file=sys.stderr)
        sys.exit(1)

    yaml_file = sys.argv[1]
    operation = sys.argv[2]

    yaml_data = safe_load_yaml(yaml_file)
    if yaml_data is None:
        sys.exit(1)

    if operation == "volume_names":
        # Equivalent to: yq e '.volumes | keys | .[]'
        names = get_volume_names(yaml_data)
        for name in names:
            print(name)

    elif operation == "volume_property":
        # Equivalent to: yq e ".volumes.$vname.$property"
        if len(sys.argv) < 5:
            print("Usage: yaml_parser.py <yaml_file> volume_property <volume_name> <property>", file=sys.stderr)
            sys.exit(1)
        volume_name = sys.argv[3]
        property_name = sys.argv[4]
        value = get_volume_property(yaml_data, volume_name, property_name)
        print(value)

    elif operation == "driver_opts_keys":
        # Equivalent to: yq e ".volumes.$vname.driver_opts | keys | .[]"
        if len(sys.argv) < 4:
            print("Usage: yaml_parser.py <yaml_file> driver_opts_keys <volume_name>", file=sys.stderr)
            sys.exit(1)
        volume_name = sys.argv[3]
        keys = get_driver_opts_keys(yaml_data, volume_name)
        for key in keys:
            print(key)

    elif operation == "driver_opt_value":
        # Equivalent to: yq e ".volumes.$vname.driver_opts.$opt"
        if len(sys.argv) < 5:
            print("Usage: yaml_parser.py <yaml_file> driver_opt_value <volume_name> <opt_key>", file=sys.stderr)
            sys.exit(1)
        volume_name = sys.argv[3]
        opt_key = sys.argv[4]
        value = get_driver_opt_value(yaml_data, volume_name, opt_key)
        print(value)

    else:
        print(f"Unknown operation: {operation}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
