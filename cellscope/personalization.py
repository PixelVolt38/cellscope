import json
import os
from typing import Dict, Any

DEFAULT_METADATA_CONFIG: Dict[str, Any] = {
    "file_fields": [
        {"key": "https://cellscope.dev/terms/localPath", "predicate": "https://cellscope.dev/terms/localPath"},
        {"key": "encodingFormat", "predicate": "schema:encodingFormat"},
        {"key": "keywords", "predicate": "schema:keywords"},
        {"key": "accessURL", "predicate": "dcat:accessURL"},
        {"key": "etag", "predicate": "schema:identifier"},
        {"key": "retrievedAt", "predicate": "prov:generatedAtTime"},
        {"key": "dateModified", "predicate": "schema:dateModified"},
    ],
    "variable_fields": [
        # Add custom variable-level fields here as needed.
    ],
}


def load_metadata_config() -> Dict[str, Any]:
    """
    Load metadata config from JSON pointed to by CELLSCOPE_METADATA_CONFIG.
    Falls back to DEFAULT_METADATA_CONFIG.
    """
    cfg = dict(DEFAULT_METADATA_CONFIG)
    path = os.environ.get("CELLSCOPE_METADATA_CONFIG")
    if not path:
        return cfg
    try:
        with open(path, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
        # shallow merge lists: if user supplies file_fields/variable_fields, replace defaults
        if isinstance(user_cfg, dict):
            if "file_fields" in user_cfg and isinstance(user_cfg["file_fields"], list):
                cfg["file_fields"] = user_cfg["file_fields"]
            if "variable_fields" in user_cfg and isinstance(user_cfg["variable_fields"], list):
                cfg["variable_fields"] = user_cfg["variable_fields"]
    except Exception:
        # On error, return defaults to avoid breaking pipeline.
        return cfg
    return cfg
