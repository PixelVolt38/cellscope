import os
import json
from typing import Any, Dict, List, Optional

def load_yaml(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    try:
        import yaml
    except ImportError:
        raise RuntimeError("Please install pyyaml to use --aliases/--hints")
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}

def load_sidecars(paths: Optional[List[str]]) -> List[Dict[str, Any]]:
    out = []
    for p in (paths or []):
        if not os.path.exists(p):
            continue
        try:
            with open(p, 'r', encoding='utf-8') as f:
                out.append(json.load(f))
        except Exception:
            pass
    return out
