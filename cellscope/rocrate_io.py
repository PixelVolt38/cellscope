import os
import json
import hashlib
import networkx as nx
from typing import Dict, Any, List, Optional, Tuple, Set

from rocrate.rocrate import ROCrate
from rocrate.model.contextentity import ContextEntity

OFLOW = "https://example.org/ontology/ontoflow#"
ONTODT = "https://example.org/ontology/ontodt#"
PROV = "http://www.w3.org/ns/prov#"

try:
    from .visualize import visualize_rocrate
except Exception:  # visualization is optional
    visualize_rocrate = None


def _b2_hash(path: str) -> Optional[str]:
    try:
        h = hashlib.blake2b(digest_size=32)
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _ensure_dirs(crate_root: str) -> Tuple[str, str]:
    crate_dir = os.path.join(crate_root)
    cells_dir = os.path.join(crate_root, 'cells')
    os.makedirs(cells_dir, exist_ok=True)
    return crate_dir, cells_dir


def _role_for_input(varname: str, hints: Dict[str, Any]) -> Optional[str]:
    if not hints:
        return None
    roles = hints.get('roles') or {}
    return roles.get(varname)


def _domain_hints_for(name: str, hints: Dict[str, Any]) -> Dict[str, Any]:
    dom = (hints or {}).get('domains') or {}
    return dom.get(name, {})


def _add_usage_with_role(crate: ROCrate, activity, data_entity, role: Optional[str]):
    if not role:
        return
    usage_id = f"#usage-{activity.id}-{data_entity.id}".replace('/', '_')
    usage = ContextEntity(crate, usage_id, properties={
        '@type': f'{PROV}Usage',
        f'{PROV}entity': data_entity,
        f'{PROV}hadRole': role
    })
    crate.add(usage)
    activity.append_to(f'{PROV}qualifiedUsage', usage)


def build_rocrate(capture: Dict[str, Any],
                  output_dir: str,
                  xkernel_edges: List[tuple],
                  hints: Optional[Dict[str, Any]] = None,
                  sidecars: Optional[List[Dict[str, Any]]] = None) -> str:
    crate_root = os.path.join(output_dir, 'ro-crate')
    os.makedirs(crate_root, exist_ok=True)
    _, cells_dir = _ensure_dirs(crate_root)

    cells = capture['cells']
    crate = ROCrate()
    try:
        nb_name = os.path.basename(capture.get('nb_path', 'notebook'))
        crate.root_dataset['name'] = nb_name
        crate.root_dataset['description'] = f"CellScope export for {nb_name}"
        # Simple default license to satisfy RO-Crate root requirements; callers can override via hints.
        if 'license' not in crate.root_dataset.properties():
            crate.root_dataset['license'] = "https://creativecommons.org/publicdomain/zero/1.0/"
    except Exception:
        pass
    function_symbols = {fn for cell in cells for fn in getattr(cell, 'funcs', [])}

    activities = {}
    for c in cells:
        rel_path = f'cells/cell_{c.idx}.py'
        abs_path = os.path.join(crate_root, rel_path)
        with open(abs_path, 'w', encoding='utf-8') as f:
            f.write(c.source)
        roles_for_cell = []
        role_map = ((hints or {}).get('roles') or {})
        for var in sorted(getattr(c, 'var_defs', [])):
            role_val = role_map.get(var)
            if role_val:
                roles_for_cell.append(f"{var}: {role_val}")

        file_hints_for_cell = []
        domain_map = ((hints or {}).get('domains') or {})
        file_candidates = sorted(set(getattr(c, 'file_writes', set())) | set(getattr(c, 'file_reads', set())))
        for fpath in file_candidates:
            base = os.path.basename(fpath)
            domain_info = domain_map.get(base)
            if not domain_info:
                continue
            parts = []
            for key, value in domain_info.items():
                if isinstance(value, (list, tuple)):
                    parts.append(f"{key}: {', '.join(map(str, value))}")
                else:
                    parts.append(f"{key}: {value}")
            if parts:
                file_hints_for_cell.append(f"{base} ({'; '.join(parts)})")

        cell_name = getattr(c, 'label', f'cell_{c.idx}')
        props = {
            '@type': ['File', f'{OFLOW}Activity'],
            'name': cell_name,
            'kernel': c.kernel,
            'version': '1',
        }
        if roles_for_cell:
            props['roles'] = roles_for_cell
        if file_hints_for_cell:
            props['fileHints'] = file_hints_for_cell
        act = crate.add_file(abs_path, dest_path=rel_path, properties=props)
        activities[c.idx] = act

    data_entities: Dict[str, ContextEntity] = {}

    def _ensure_var_entity(var: str, kind: str = 'data') -> ContextEntity:
        vid = f'#var-{var}'
        existing = data_entities.get(vid)
        if existing:
            if kind == 'symbol':
                props = existing.properties() if hasattr(existing, 'properties') else getattr(existing, '_jsonld', {})
                if isinstance(props, dict):
                    current = props.get('@type')
                    if current and current != f'{ONTODT}Symbol':
                        props['@type'] = f'{ONTODT}Symbol'
            return existing
        dtype = f'{ONTODT}Symbol' if kind == 'symbol' else f'{ONTODT}Data'
        props = {'@type': dtype, 'name': var, 'version': '1'}
        de = ContextEntity(crate, vid, properties=props)
        crate.add(de)
        data_entities[vid] = de
        return de

    for c in cells:
        for v in c.var_defs:
            kind = 'symbol' if v in function_symbols else 'data'
            de = _ensure_var_entity(v, kind=kind)
            activities[c.idx].append_to(f'{OFLOW}hasOutput', de)
            de.append_to(f'{PROV}wasGeneratedBy', activities[c.idx])
            if kind == 'symbol':
                de.append_to('category', 'function')

    for (u, v, d) in capture['graph']['edges']:
        if d.get('type') == 'uses':
            ov = d.get('vars') or set()
            for var in ov:
                kind = 'symbol' if var in function_symbols else 'data'
                de = _ensure_var_entity(var, kind=kind)
                activities[v].append_to(f'{OFLOW}hasInput', de)
                activities[v].append_to(f'{PROV}used', de)
                role = _role_for_input(var, hints or {})
                _add_usage_with_role(crate, activities[v], de, role)

    for (u, v, d) in xkernel_edges:
        if d.get('type') == 'uses':
            label_vars = d.get('vars') or set()
            for var in label_vars:
                kind = 'symbol' if var in function_symbols else 'data'
                de = _ensure_var_entity(var, kind=kind)
                activities[v].append_to(f'{OFLOW}hasInput', de)
                activities[v].append_to(f'{PROV}used', de)
                activities[v].append_to('via', d.get('via', 'xkernel'))

    file_entities: Dict[str, ContextEntity] = {}
    used_dest_names: Set[str] = set()

    def _unique_dest(base: str) -> str:
        candidate = base
        counter = 2
        while candidate in used_dest_names:
            candidate = f"{base}_{counter}"
            counter += 1
        used_dest_names.add(candidate)
        return candidate

    for c in cells:
        for fpath in c.file_writes:
            absf = fpath if os.path.isabs(fpath) else os.path.normpath(os.path.join(os.path.dirname(capture['nb_path']), fpath))
            base = os.path.basename(absf)
            dest_rel = f"files/{_unique_dest(base)}"
            props = {
                '@type': ['File', f'{ONTODT}Data'],
                'name': base,
                'version': '1',
            }
            if os.path.exists(absf):
                h = _b2_hash(absf)
                if h:
                    props['contentHash'] = f'blake2b-256:{h}'
                fe = crate.add_file(absf, dest_path=dest_rel, properties=props)
            else:
                fe = ContextEntity(crate, dest_rel, properties=props)
                crate.add(fe)
            file_entities[absf] = fe
            crate.root_dataset.append_to("hasPart", fe)
            activities[c.idx].append_to(f'{OFLOW}hasOutput', fe)
            fe.append_to(f'{PROV}wasGeneratedBy', activities[c.idx])
            dh = _domain_hints_for(base, hints or {})
            for k, v in dh.items():
                fe.append_to(k, v)

        for fpath in c.file_reads:
            absf = fpath if os.path.isabs(fpath) else os.path.normpath(os.path.join(os.path.dirname(capture['nb_path']), fpath))
            fe = file_entities.get(absf)
            if fe is None:
                base = os.path.basename(absf)
                dest_rel = f"files/{_unique_dest(base)}"
                props = {
                    '@type': ['File', f'{ONTODT}Data'],
                    'name': base,
                    'version': '1',
                }
                if os.path.exists(absf):
                    h = _b2_hash(absf)
                    if h:
                        props['contentHash'] = f'blake2b-256:{h}'
                    fe = crate.add_file(absf, dest_path=dest_rel, properties=props)
                else:
                    fe = ContextEntity(crate, dest_rel, properties=props)
                    crate.add(fe)
                file_entities[absf] = fe
            crate.root_dataset.append_to("hasPart", fe)
            activities[c.idx].append_to(f'{OFLOW}hasInput', fe)
            activities[c.idx].append_to(f'{PROV}used', fe)
            role = _role_for_input(os.path.basename(absf), hints or {}) or 'dataset'
            _add_usage_with_role(crate, activities[c.idx], fe, role)

    for sj in (sidecars or []):
        sid = sj.get('id') or f"#sidecar-{abs(hash(json.dumps(sj, sort_keys=True)))}"
        stype = sj.get('type', 'Data')
        stname = sj.get('name', sid)
        props = {'@type': f'{ONTODT}{stype}', 'name': stname, 'version': '1'}
        se = ContextEntity(crate, sid, properties=props)
        crate.add(se)
        prod = sj.get('producer')
        if isinstance(prod, int) and prod in activities:
            activities[prod].append_to(f'{OFLOW}hasOutput', se)
            se.append_to(f'{PROV}wasGeneratedBy', activities[prod])
        for cons in sj.get('consumers', []):
            if isinstance(cons, int) and cons in activities:
                activities[cons].append_to(f'{OFLOW}hasInput', se)
                activities[cons].append_to(f'{PROV}used', se)
                _add_usage_with_role(crate, activities[cons], se, sj.get('role'))

    G = nx.DiGraph()
    for c in cells:
        G.add_node(c.idx, kernel=c.kernel, funcs=json.dumps(sorted(c.funcs)),
                   func_calls=json.dumps(sorted(getattr(c, 'func_calls', []))),
                   var_defs=json.dumps(sorted(c.var_defs)),
                   var_uses=json.dumps(sorted(c.var_uses)))
    edge_accum: Dict[tuple, Set[str]] = {}
    for (u, v, d) in capture['graph']['edges']:
        via = d.get('via', 'ast')
        key = (u, v, via)
        edge_accum.setdefault(key, set()).update(set(d.get('vars', [])))
    for (u, v, d) in xkernel_edges:
        via = d.get('via', 'xkernel')
        key = (u, v, via)
        edge_accum.setdefault(key, set()).update(set(d.get('vars', [])))
    for (u, v, via), vars_set in edge_accum.items():
        label = ",".join(sorted(vars_set))
        G.add_edge(u, v, type='uses', via=via, label=label)
    graph_path = os.path.join(crate_root, 'cell_graph.graphml')
    nx.write_graphml(G, graph_path)

    crate.add_file(graph_path, dest_path='cell_graph.graphml',
                   properties={'@type': ['File', 'https://example.org/ontology/graph#Graph'], 'name': 'cell_graph'})

    crate.write(crate_root)

    if visualize_rocrate is not None:
        try:
            visualize_rocrate(crate_root, panel=True)
        except Exception as exc:
            print(f"[cellscope] Failed to generate PyVis HTML: {exc}")
    else:
        print("[cellscope] PyVis not available; skipping HTML graph export")

    return crate_root
