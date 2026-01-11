import os
import json
import hashlib
import networkx as nx
import re
from typing import Dict, Any, List, Optional, Tuple, Set
from urllib.parse import urlsplit
from datetime import datetime
import os
try:
    import tomllib  # type: ignore
except Exception:  # pragma: no cover - python < 3.11
    tomllib = None
try:
    import yaml  # type: ignore
except Exception:  # optional
    yaml = None

try:
    import requests  # type: ignore
except Exception:  # requests is optional
    requests = None

from rocrate.rocrate import ROCrate
from rocrate.model.contextentity import ContextEntity

OFLOW = "https://example.org/ontology/ontoflow#"
ONTODT = "https://example.org/ontology/ontodt#"
PROV = "http://www.w3.org/ns/prov#"
LOCAL_PATH_IRI = "https://cellscope.dev/terms/localPath"

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


def _is_url(path: str) -> bool:
    return isinstance(path, str) and (path.startswith("http://") or path.startswith("https://"))


def _basename_for_path(path: str) -> str:
    if _is_url(path):
        parsed = urlsplit(path)
        # fallback to entire path if no trailing segment
        return os.path.basename(parsed.path) or path
    return os.path.basename(path)


def _remote_metadata(url: str) -> Dict[str, Any]:
    """
    Best-effort metadata fetch for remote artifacts.
    Only runs when CELLSCOPE_FETCH_REMOTE_METADATA is truthy and requests is available.
    """
    if not os.environ.get("CELLSCOPE_FETCH_REMOTE_METADATA"):
        return {}
    if requests is None:
        return {}
    try:
        resp = requests.head(url, timeout=5)
    except Exception:
        return {}
    if resp is None or resp.status_code >= 400:
        return {}
    props: Dict[str, Any] = {}
    etag = resp.headers.get("ETag")
    if etag:
        props["etag"] = etag
    last_modified = resp.headers.get("Last-Modified")
    if last_modified:
        props["dateModified"] = last_modified
    props["retrievedAt"] = datetime.utcnow().isoformat() + "Z"
    return props


def _should_fetch_remote_artifacts() -> bool:
    return bool(os.environ.get("CELLSCOPE_FETCH_REMOTE_ARTIFACTS")) and requests is not None


def _download_remote_artifact(url: str, dest_path: str) -> bool:
    if not _should_fetch_remote_artifacts():
        return False
    if requests is None:
        return False
    max_bytes_raw = os.environ.get("CELLSCOPE_REMOTE_MAX_BYTES")
    max_bytes = int(max_bytes_raw) if max_bytes_raw and max_bytes_raw.isdigit() else None
    try:
        resp = requests.get(url, stream=True, timeout=10)
    except Exception:
        return False
    if resp is None or resp.status_code >= 400:
        return False
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    total = 0
    try:
        with open(dest_path, "wb") as handle:
            for chunk in resp.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                total += len(chunk)
                if max_bytes is not None and total > max_bytes:
                    raise RuntimeError("remote artifact exceeds size limit")
                handle.write(chunk)
    except Exception:
        try:
            if os.path.exists(dest_path):
                os.remove(dest_path)
        except Exception:
            pass
        return False
    return True


def _split_requirement(line: str) -> Optional[Dict[str, str]]:
    raw = line.strip()
    if not raw or raw.startswith("#"):
        return None
    lowered = raw.lower()
    if lowered.startswith(("-r ", "--requirement", "-c ", "--constraint")):
        return None
    if lowered.startswith(("-e ", "--editable")):
        parts = raw.split(None, 1)
        raw = parts[1] if len(parts) > 1 else ""
    if lowered.startswith(("--index-url", "--extra-index-url", "--find-links", "--trusted-host")):
        return None
    raw = raw.split(";", 1)[0].strip()
    if not raw:
        return None
    if "://" in raw and raw.startswith(("http://", "https://", "git+")):
        name = None
        if "#egg=" in raw:
            name = raw.split("#egg=")[-1].strip() or None
        return {"name": name or raw, "version": raw}
    if "@" in raw and "://" in raw:
        name, uri = raw.split("@", 1)
        name = name.strip()
        uri = uri.strip()
        if "#egg=" in uri and not name:
            name = uri.split("#egg=")[-1].strip()
        return {"name": name or uri, "version": uri}
    parts = re.split(r"(==|~=|!=|<=|>=|<|>)", raw, maxsplit=1)
    if len(parts) >= 3:
        name = parts[0].strip()
        spec = "".join(parts[1:]).strip()
    else:
        name = raw.strip()
        spec = ""
    if not name:
        return None
    return {"name": name, "version": spec} if spec else {"name": name}


def _parse_requirements_text(text: str) -> List[Dict[str, str]]:
    deps: List[Dict[str, str]] = []
    for line in text.splitlines():
        entry = _split_requirement(line)
        if entry:
            deps.append(entry)
    return deps


def _parse_requirements_file(path: str) -> List[Dict[str, str]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return _parse_requirements_text(handle.read())
    except Exception:
        return []


def _parse_conda_dependency(entry: str) -> Optional[Dict[str, str]]:
    item = entry.strip()
    if not item or item.startswith("#"):
        return None
    if "::" in item:
        item = item.split("::", 1)[1].strip()
    if not item:
        return None
    if "==" in item or ">=" in item or "<=" in item or "~=" in item or "!=" in item or ">" in item or "<" in item:
        parsed = _split_requirement(item)
        return parsed
    if "=" in item:
        name, version = item.split("=", 1)
        name = name.strip()
        version = version.strip()
        if not name:
            return None
        spec = f"=={version}" if version else ""
        return {"name": name, "version": spec} if spec else {"name": name}
    return {"name": item}


def _parse_env_yaml(path: str) -> List[Dict[str, str]]:
    deps: List[Dict[str, str]] = []
    if yaml is not None:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle)
        except Exception:
            data = None
        if isinstance(data, dict):
            for entry in data.get("dependencies", []) or []:
                if isinstance(entry, str):
                    parsed = _parse_conda_dependency(entry)
                    if parsed:
                        deps.append(parsed)
                elif isinstance(entry, dict):
                    for key, items in entry.items():
                        if key != "pip" or not isinstance(items, list):
                            continue
                        for pip_entry in items:
                            if isinstance(pip_entry, str):
                                parsed = _split_requirement(pip_entry)
                                if parsed:
                                    deps.append(parsed)
        return deps
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except Exception:
        return deps
    in_deps = False
    in_pip = False
    pip_indent: Optional[int] = None
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if stripped.startswith("dependencies:"):
            in_deps = True
            in_pip = False
            pip_indent = None
            continue
        if not in_deps:
            continue
        if stripped.startswith("-"):
            item = stripped[1:].strip()
            if item.startswith("pip:"):
                in_pip = True
                pip_indent = indent
                continue
            if in_pip and pip_indent is not None and indent > pip_indent:
                parsed = _split_requirement(item)
                if parsed:
                    deps.append(parsed)
                continue
            in_pip = False
            parsed = _parse_conda_dependency(item)
            if parsed:
                deps.append(parsed)
    return deps


def _parse_pyproject(path: str) -> List[Dict[str, str]]:
    if tomllib is None:
        return []
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except Exception:
        return []
    deps: List[Dict[str, str]] = []
    project = data.get("project") or {}
    for dep in project.get("dependencies", []) or []:
        if isinstance(dep, str):
            parsed = _split_requirement(dep)
            if parsed:
                deps.append(parsed)
    for opt_list in (project.get("optional-dependencies") or {}).values():
        if isinstance(opt_list, list):
            for dep in opt_list:
                if isinstance(dep, str):
                    parsed = _split_requirement(dep)
                    if parsed:
                        deps.append(parsed)
    poetry = ((data.get("tool") or {}).get("poetry") or {})
    for name, value in (poetry.get("dependencies") or {}).items():
        if name.lower() == "python":
            continue
        spec = ""
        if isinstance(value, str):
            spec = value
        elif isinstance(value, dict):
            spec = value.get("version") or ""
        deps.append({"name": name, "version": spec} if spec else {"name": name})
    return deps


def _parse_pipfile_lock(path: str) -> List[Dict[str, str]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return []
    deps: List[Dict[str, str]] = []
    for section in ("default", "develop"):
        entries = data.get(section) or {}
        if not isinstance(entries, dict):
            continue
        for name, info in entries.items():
            if not isinstance(info, dict):
                continue
            version = info.get("version") or ""
            deps.append({"name": name, "version": version} if version else {"name": name})
    return deps


def _parse_dependencies_from_config(path: str) -> List[Dict[str, str]]:
    base = os.path.basename(path).lower()
    if base in ("requirements.txt", "requirements.in") or "requirements" in base:
        return _parse_requirements_file(path)
    if base in ("environment.yml", "environment.yaml") or base.endswith((".yml", ".yaml")):
        return _parse_env_yaml(path)
    if base == "pyproject.toml" or base.endswith(".toml"):
        return _parse_pyproject(path)
    if base == "pipfile.lock":
        return _parse_pipfile_lock(path)
    return []


def _dependency_id(name: str, version: Optional[str]) -> str:
    safe = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower() or "dependency"
    seed = f"{name}|{version or ''}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]
    return f"#software-{safe}-{digest}"


def _add_software_requirements(crate: ROCrate, deps: List[Dict[str, str]]) -> None:
    seen: Set[str] = set()
    for dep in deps:
        name = dep.get("name") or ""
        if not name:
            continue
        version = dep.get("version") or ""
        sid = _dependency_id(name, version)
        if sid in seen:
            continue
        seen.add(sid)
        props: Dict[str, Any] = {"@type": "SoftwareApplication", "name": name}
        if version:
            props["version"] = version
        entity = ContextEntity(crate, sid, properties=props)
        crate.add(entity)
        crate.root_dataset.append_to("softwareRequirements", entity)


def _resolve_config_path(config_path: str, nb_path: Optional[str]) -> str:
    if not config_path:
        return config_path
    if _is_url(config_path):
        return config_path
    candidate = config_path
    if not os.path.isabs(candidate):
        candidate = os.path.normpath(candidate)
        if os.path.exists(candidate):
            return os.path.abspath(candidate)
        if nb_path:
            candidate = os.path.normpath(os.path.join(os.path.dirname(nb_path), candidate))
    return os.path.abspath(candidate)


def _resolve_local_path(path: str, nb_path: Optional[str]) -> str:
    if not path:
        return path
    if os.path.isabs(path):
        return path
    candidate = os.path.normpath(path)
    nb_dir = os.path.dirname(nb_path) if nb_path else ""
    nb_dir_norm = os.path.normpath(nb_dir) if nb_dir else ""
    nb_dir_base = os.path.basename(nb_dir_norm) if nb_dir_norm else ""
    if nb_dir_norm and candidate.startswith(nb_dir_norm + os.sep):
        return os.path.abspath(candidate)
    if nb_dir_base and candidate.startswith(nb_dir_base + os.sep):
        return os.path.abspath(candidate)
    if os.path.exists(candidate):
        return os.path.abspath(candidate)
    if nb_dir:
        return os.path.abspath(os.path.normpath(os.path.join(nb_dir, path)))
    return os.path.abspath(candidate)


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
                  sidecars: Optional[List[Dict[str, Any]]] = None,
                  config_files: Optional[List[str]] = None) -> str:
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

    def _cell_extension(kernel_name: str) -> str:
        k = (kernel_name or "").lower()
        if k == "r" or k.startswith(("ir", "r-")) or k.startswith("r "):
            return ".R"
        if "python" in k or k.startswith("py"):
            return ".py"
        return ".txt"

    activities = {}
    for c in cells:
        ext = _cell_extension(getattr(c, "kernel", ""))
        rel_path = f'cells/cell_{c.idx}{ext}'
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
        snippet_lines = 25
        try:
            snippet_lines = int(os.environ.get("CELLSCOPE_SNIPPET_LINES", "25") or 25)
        except Exception:
            snippet_lines = 25
        code_lines = c.source.splitlines()
        truncated = len(code_lines) > snippet_lines
        snippet_text = "\n".join(code_lines[:snippet_lines])
        if truncated:
            snippet_text = snippet_text + "\n..."

        func_calls = sorted(getattr(c, "func_calls", []))
        props = {
            '@type': ['File', f'{OFLOW}Activity'],
            'name': cell_name,
            'kernel': c.kernel,
            'programmingLanguage': c.kernel,
            'position': c.idx,
            'isPartOf': './',
            'version': '1',
            'codeSnippet': snippet_text,
        }
        if roles_for_cell:
            props['roles'] = roles_for_cell
        if file_hints_for_cell:
            props['fileHints'] = file_hints_for_cell
        if func_calls:
            props['funcCalls'] = func_calls
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

    has_part_ids: Set[str] = set()
    def _add_has_part(entity: ContextEntity) -> None:
        entity_id = entity.id
        if entity_id in has_part_ids:
            return
        has_part_ids.add(entity_id)
        crate.root_dataset.append_to("hasPart", entity)

    nb_path = capture.get("nb_path")
    if nb_path:
        nb_abs = os.path.abspath(nb_path)
        if os.path.exists(nb_abs):
            nb_base = os.path.basename(nb_abs)
            nb_dest = f"notebook/{_unique_dest(nb_base)}"
            nb_props = {
                "@type": ["File"],
                "name": nb_base,
                "encodingFormat": "application/x-ipynb+json",
                "isPartOf": "./",
                LOCAL_PATH_IRI: nb_abs,
            }
            nb_entity = crate.add_file(nb_abs, dest_path=nb_dest, properties=nb_props)
            _add_has_part(nb_entity)

    dependency_records: List[Dict[str, str]] = []
    for cfg_path in (config_files or []):
        if not cfg_path:
            continue
        resolved = _resolve_config_path(cfg_path, capture.get("nb_path"))
        base = _basename_for_path(resolved)
        dest_rel = f"env/{_unique_dest(base)}"
        props: Dict[str, Any] = {
            "@type": ["File"],
            "name": base,
            "isPartOf": "./",
            "description": "Environment/config file",
            "category": "environment-config",
        }
        if _is_url(resolved):
            props["accessURL"] = resolved
            props.update(_remote_metadata(resolved))
            dest_abs = os.path.join(crate_root, dest_rel)
            if _download_remote_artifact(resolved, dest_abs):
                h = _b2_hash(dest_abs)
                if h:
                    props["contentHash"] = f"blake2b-256:{h}"
            fe = ContextEntity(crate, dest_rel, properties=props)
            crate.add(fe)
        elif os.path.exists(resolved):
            h = _b2_hash(resolved)
            if h:
                props["contentHash"] = f"blake2b-256:{h}"
            props[LOCAL_PATH_IRI] = os.path.abspath(resolved)
            fe = crate.add_file(resolved, dest_path=dest_rel, properties=props)
            dependency_records.extend(_parse_dependencies_from_config(resolved))
        else:
            props[LOCAL_PATH_IRI] = os.path.abspath(resolved)
            fe = ContextEntity(crate, dest_rel, properties=props)
            crate.add(fe)
        _add_has_part(fe)

    for c in cells:
        for fpath in c.file_writes:
            if _is_url(fpath):
                absf = fpath
            else:
                absf = _resolve_local_path(fpath, capture.get("nb_path"))
            base = _basename_for_path(absf)
            dest_rel = f"files/{_unique_dest(base)}"
            props = {
                '@type': ['File', f'{ONTODT}Data'],
                'name': base,
                'isPartOf': './',
                'version': '1',
            }
            if _is_url(absf):
                props['accessURL'] = absf
                props.update(_remote_metadata(absf))
                dest_abs = os.path.join(crate_root, dest_rel)
                if _download_remote_artifact(absf, dest_abs):
                    h = _b2_hash(dest_abs)
                    if h:
                        props['contentHash'] = f'blake2b-256:{h}'
                fe = ContextEntity(crate, dest_rel, properties=props)
                crate.add(fe)
            elif os.path.exists(absf):
                h = _b2_hash(absf)
                if h:
                    props['contentHash'] = f'blake2b-256:{h}'
                props[LOCAL_PATH_IRI] = os.path.abspath(absf)
                fe = crate.add_file(absf, dest_path=dest_rel, properties=props)
            else:
                props[LOCAL_PATH_IRI] = os.path.abspath(absf)
                fe = ContextEntity(crate, dest_rel, properties=props)
                crate.add(fe)
            file_entities[absf] = fe
            _add_has_part(fe)
            activities[c.idx].append_to(f'{OFLOW}hasOutput', fe)
            fe.append_to(f'{PROV}wasGeneratedBy', activities[c.idx])
            dh = _domain_hints_for(base, hints or {})
            for k, v in dh.items():
                fe.append_to(k, v)

        for fpath in c.file_reads:
            if _is_url(fpath):
                absf = fpath
            else:
                absf = _resolve_local_path(fpath, capture.get("nb_path"))
            fe = file_entities.get(absf)
            if fe is None:
                base = _basename_for_path(absf)
                dest_rel = f"files/{_unique_dest(base)}"
                props = {
                    '@type': ['File', f'{ONTODT}Data'],
                    'name': base,
                    'isPartOf': './',
                    'version': '1',
                }
                if _is_url(absf):
                    props['accessURL'] = absf
                    props.update(_remote_metadata(absf))
                    dest_abs = os.path.join(crate_root, dest_rel)
                    if _download_remote_artifact(absf, dest_abs):
                        h = _b2_hash(dest_abs)
                        if h:
                            props['contentHash'] = f'blake2b-256:{h}'
                    fe = ContextEntity(crate, dest_rel, properties=props)
                    crate.add(fe)
                elif os.path.exists(absf):
                    h = _b2_hash(absf)
                    if h:
                        props['contentHash'] = f'blake2b-256:{h}'
                    props[LOCAL_PATH_IRI] = os.path.abspath(absf)
                    fe = crate.add_file(absf, dest_path=dest_rel, properties=props)
                else:
                    props[LOCAL_PATH_IRI] = os.path.abspath(absf)
                    fe = ContextEntity(crate, dest_rel, properties=props)
                    crate.add(fe)
                file_entities[absf] = fe
            _add_has_part(fe)
            activities[c.idx].append_to(f'{OFLOW}hasInput', fe)
            activities[c.idx].append_to(f'{PROV}used', fe)
            role = _role_for_input(_basename_for_path(absf), hints or {}) or 'dataset'
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

    if dependency_records:
        _add_software_requirements(crate, dependency_records)

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

    graph_entity = crate.add_file(
        graph_path,
        dest_path='cell_graph.graphml',
        properties={'@type': ['File', 'https://example.org/ontology/graph#Graph'], 'name': 'cell_graph'}
    )
    _add_has_part(graph_entity)

    crate.write(crate_root)

    if visualize_rocrate is not None:
        try:
            visualize_rocrate(crate_root, panel=True)
            html_path = os.path.join(crate_root, 'cell_graph.html')
            if os.path.exists(html_path):
                html_entity = crate.add_file(
                    html_path,
                    dest_path='cell_graph.html',
                    properties={'@type': ['File', 'https://example.org/ontology/graph#Graph'], 'name': 'cell_graph_html'}
                )
                _add_has_part(html_entity)
        except Exception as exc:
            print(f"[cellscope] Failed to generate PyVis HTML: {exc}")
    else:
        print("[cellscope] PyVis not available; skipping HTML graph export")

    return crate_root
