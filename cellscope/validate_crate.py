import os
import json
from typing import Dict, Any

def _load_crate_meta(crate_dir: str) -> Dict[str, Any]:
    meta_path = os.path.join(crate_dir, 'ro-crate-metadata.json')
    with open(meta_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def validate_crate(crate_dir: str, verbose: bool = False) -> bool:
    """
    Minimal validation:
      - ro-crate-metadata.json exists
      - each Activity has @type ontoflow:Activity and name
      - each hasInput/hasOutput points at an entity present in graph
      - qualifiedUsage (if any) has prov:entity and prov:hadRole
    """
    ok = True
    meta = _load_crate_meta(crate_dir)
    graph = meta.get('@graph', [])
    by_id = {e.get('@id'): e for e in graph}

    # find activities
    acts = [e for e in graph if e.get('@type') == 'https://example.org/ontology/ontoflow#Activity'
            or (isinstance(e.get('@type'), list) and 'https://example.org/ontology/ontoflow#Activity' in e.get('@type'))]
    if verbose:
        print(f"Found {len(acts)} activities")

    for a in acts:
        if 'name' not in a:
            ok = False
            if verbose: print(f"[ERR] Activity {a.get('@id')} missing name")
        for rel in ('https://example.org/ontology/ontoflow#hasInput', 'https://example.org/ontology/ontoflow#hasOutput'):
            if rel in a:
                vals = a[rel] if isinstance(a[rel], list) else [a[rel]]
                for v in vals:
                    vid = v.get('@id') if isinstance(v, dict) else v
                    if vid not in by_id:
                        ok = False
                        if verbose: print(f"[ERR] Activity {a.get('@id')} references missing entity {vid} via {rel}")
        # qualifiedUsage
        q = a.get('http://www.w3.org/ns/prov#qualifiedUsage')
        if q:
            vals = q if isinstance(q, list) else [q]
            for u in vals:
                uid = u.get('@id') if isinstance(u, dict) else u
                ue = by_id.get(uid)
                if not ue:
                    ok = False
                    if verbose: print(f"[ERR] Missing Usage entity {uid}")
                else:
                    if 'http://www.w3.org/ns/prov#entity' not in ue or 'http://www.w3.org/ns/prov#hadRole' not in ue:
                        ok = False
                        if verbose: print(f"[ERR] Usage {uid} missing prov:entity or prov:hadRole")

    if verbose:
        print("Validation:", "OK" if ok else "FAILED")
    return ok
