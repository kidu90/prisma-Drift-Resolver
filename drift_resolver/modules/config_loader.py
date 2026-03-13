"""Helpers for loading drift-resolver configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_config(path: str = "drift_resolver/config.yaml") -> dict[str, Any]:
    """Load the YAML configuration file from disk."""

    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as config_file:
        loaded_config = yaml.safe_load(config_file) or {}

    return loaded_config