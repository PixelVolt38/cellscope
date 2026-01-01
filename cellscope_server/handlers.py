"""
Jupyter Server extension: exposes CellScope endpoints
 - POST /cellscope/analyze
 - POST /cellscope/export
 - POST /cellscope/index
 - POST /cellscope/workflow/capture
 - POST /cellscope/sparql_summary
 - POST /cellscope/sparql_graph

This is a minimal Tornado-based handler module; integrate by
adding to jupyter_server_config.d.
"""
import os
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from jupyter_server.base.handlers import APIHandler
from jupyter_server.utils import url_path_join

from cellscope import (
    parse_notebook,
    infer_cross_kernel_edges,
    build_rocrate,
    index_crate,
)
from cellscope.serialization import capture_to_json
from cellscope.workflow import capture_workflow, parse_workflow
from pathlib import Path
import importlib
import urllib.parse
import urllib.request
import urllib.error
try:
    from pyvis.network import Network  # type: ignore
except Exception:  # pragma: no cover
    Network = None  # type: ignore


EdgeRecord = Union[Dict[str, Any], Iterable[Any]]

IndexConfig = Dict[str, Any]

DEFAULT_INDEX_SETTINGS: IndexConfig = {
    "endpoint": "http://localhost:3030/cellscope/update",
    "output": None,
    "retries": 2,
    "backoff_seconds": 1.5,
    "timeout": 10.0,
    "auth_token": None,
    "username": None,
    "password": None,
}

PREFIXES = """
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX schema: <http://schema.org/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
"""

PROV = "http://www.w3.org/ns/prov#"
SCHEMA = "http://schema.org/"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"


def _resolve_graph_uri(nb_path: Optional[str]) -> Optional[str]:
    if not nb_path:
        return None
    try:
        return Path(nb_path).resolve().as_uri()
    except Exception:
        return None


class AnalyzeHandler(APIHandler):
    def post(self):
        data = self.get_json_body() or {}
        nb_path = data.get("notebook")
        if not nb_path:
            self.set_status(400)
            self.finish({"error": "missing 'notebook' path"})
            return
        aliases = data.get("aliases") or {}
        alias_map = aliases.get("aliases") if isinstance(aliases, dict) else aliases
        capture = parse_notebook(
            nb_path,
            alias_map=alias_map,
            collect_materialized=True,
        )
        # infer cross-kernel/file edges
        xedges = infer_cross_kernel_edges(capture)
        capture["graph"]["edges"].extend(xedges)
        self.finish({"graph": capture_to_json(capture)})


class SparqlSummaryHandler(APIHandler):
    def post(self):
        data = self.get_json_body() or {}
        endpoint = data.get("endpoint") or DEFAULT_INDEX_SETTINGS.get("endpoint")
        token = data.get("auth_token") or data.get("token")
        username = data.get("username")
        password = data.get("password")
        if not endpoint:
            self.set_status(400)
            self.finish({"error": "missing endpoint"})
            return

        try:
            graphs = self._list_graphs(endpoint, token, username, password)
            latest_graphs = self._latest_per_notebook(graphs)
            triples = self._fetch_triples(endpoint, latest_graphs, token, username, password)
            summary = self._build_graph_summary(triples)
            self.finish({"graph": summary, "graphs": latest_graphs})
        except Exception as exc:  # pragma: no cover - network failures
            self.log.error("CellScope SPARQL summary failed: %s", exc)
            self.set_status(500)
            self.finish({"error": f"sparql summary failed: {exc}"})

    def _build_headers(self, token: Optional[str], username: Optional[str], password: Optional[str]) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/sparql-results+json"
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif username and password:
            import base64
            encoded = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {encoded}"
        return headers

    def _post(self, endpoint: str, query: str, token: Optional[str], username: Optional[str], password: Optional[str]) -> Dict[str, Any]:
        # Use stdlib to avoid handler/header clashes; fall back from /update to /sparql on 400
        data = urllib.parse.urlencode({"query": query}).encode("utf-8")
        headers = self._build_headers(token, username, password)

        def _do(url: str) -> Dict[str, Any]:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = resp.read()
            try:
                import json
                return json.loads(payload.decode("utf-8"))
            except Exception:
                return {}

        # Prefer the query endpoint when the user points us at /update
        primary = endpoint.replace("/update", "/sparql") if endpoint.endswith("/update") else endpoint
        fallback = endpoint if primary != endpoint else None

        try:
            return _do(primary)
        except urllib.error.HTTPError as err:
            if fallback:
                try:
                    return _do(fallback)
                except Exception:
                    pass
            raise

    def _list_graphs(self, endpoint: str, token: Optional[str], username: Optional[str], password: Optional[str]) -> List[str]:
        query = PREFIXES + "SELECT DISTINCT ?g WHERE { GRAPH ?g { ?s ?p ?o } }"
        data = self._post(endpoint, query, token, username, password)
        graphs: List[str] = []
        for b in data.get("results", {}).get("bindings", []):
            gval = b.get("g", {}).get("value")
            if isinstance(gval, str):
                graphs.append(gval)
        return graphs

    def _latest_per_notebook(self, graphs: List[str]) -> List[str]:
        by_base: Dict[str, Tuple[int, str]] = {}
        for g in graphs:
            if "?v=" in g:
                base, ver = g.split("?v=", 1)
                try:
                    vnum = int(ver)
                except Exception:
                    vnum = -1
            else:
                base, vnum = g, -1
            prev = by_base.get(base)
            if prev is None or vnum > prev[0]:
                by_base[base] = (vnum, g)
        return [item[1] for item in by_base.values()]

    def _fetch_triples(self, endpoint: str, graphs: List[str], token: Optional[str], username: Optional[str], password: Optional[str]) -> List[tuple]:
        if not graphs:
            return []
        values = " ".join(f"<{g}>" for g in graphs)
        query = PREFIXES + f"""
SELECT ?g ?s ?p ?o WHERE {{
  VALUES ?g {{ {values} }}
  GRAPH ?g {{
    ?s ?p ?o .
    FILTER (?p IN (
      prov:used,
      prov:wasGeneratedBy,
      rdf:type,
      schema:name,
      schema:programmingLanguage,
      schema:position,
      schema:isPartOf,
      schema:checksum
    ))
  }}
}}
"""
        data = self._post(endpoint, query, token, username, password)
        triples = []
        for b in data.get("results", {}).get("bindings", []):
            g = b.get("g", {}).get("value")
            s = b.get("s", {}).get("value")
            p = b.get("p", {}).get("value")
            o_obj = b.get("o", {})
            if not all(isinstance(x, str) for x in (g, s, p)):
                continue
            o_type = o_obj.get("type")
            o_val = o_obj.get("value")
            triples.append((g, s, p, o_val, o_type))
        return triples

    def _build_graph_summary(self, triples: List[tuple]) -> Dict[str, Any]:
        activities: Dict[str, Dict[str, Any]] = {}
        data_entities: Dict[str, Dict[str, Any]] = {}
        name_map: Dict[str, str] = {}
        kernel_map: Dict[str, str] = {}
        position_map: Dict[str, int] = {}
        is_part_of: Dict[str, str] = {}
        hash_map: Dict[str, str] = {}

        for g, s, p, o, otype in triples:
            if p == "http://www.w3.org/1999/02/22-rdf-syntax-ns#type":
                if o == PROV + "Activity" or o.endswith("ontoflow#Activity"):
                    activities.setdefault(s, {"id": s, "graph": g})
                else:
                    data_entities.setdefault(s, {"id": s, "graph": g})
            if p == "http://schema.org/name" and isinstance(o, str):
                name_map[s] = o
            if p == "http://schema.org/programmingLanguage" and isinstance(o, str):
                kernel_map[s] = o
            if p == "http://schema.org/position":
                try:
                    position_map[s] = int(o)
                except Exception:
                    pass
            if p == "http://schema.org/isPartOf" and isinstance(o, str):
                is_part_of[s] = o
            if p == "http://schema.org/checksum" and isinstance(o, str):
                hash_map[s] = o

        # build producer/consumers
        produced_by: Dict[str, str] = {}
        consumed_by: Dict[str, List[str]] = {}
        base_producers: Dict[str, str] = {}
        for g, s, p, o, otype in triples:
            if p == PROV + "wasGeneratedBy" and isinstance(o, str):
                produced_by[s] = o
                base = os.path.basename(name_map.get(s, s))
                if base:
                    base_producers.setdefault(base, o)
            if p == PROV + "used" and isinstance(o, str):
                consumed_by.setdefault(o, []).append(s)

        cells = []
        idx_map: Dict[str, int] = {}
        for idx, (aid, info) in enumerate(activities.items()):
            idx_map[aid] = idx
            produced_names = []
            for data_id, producer in produced_by.items():
                if producer == aid:
                    produced_names.append(name_map.get(data_id, data_id))
            consumed_names = []
            for data_id, consumers in consumed_by.items():
                if aid in consumers:
                    consumed_names.append(name_map.get(data_id, data_id))

            def _split_files(values: List[str]) -> Tuple[List[str], List[str]]:
                files: List[str] = []
                others: List[str] = []
                for v in values:
                    if any(ch in v for ch in ("/", "\\")) or v.lower().startswith("http"):
                        files.append(v)
                    else:
                        others.append(v)
                return files, others

            writes_files, writes_vars = _split_files(produced_names)
            reads_files, reads_vars = _split_files(consumed_names)

            cells.append(
                {
                    "idx": idx,
                    "name": name_map.get(aid) or aid,
                    "kernel": kernel_map.get(aid) or "sparql",
                    "graph": self._label_for_graph(info.get("graph"), is_part_of.get(aid)),
                    "funcs": [],
                    "var_defs": writes_vars,
                    "var_uses": reads_vars,
                    "file_writes": writes_files,
                    "file_reads": reads_files,
                }
            )

        edges = []
        for data_id, prod in produced_by.items():
            consumers = consumed_by.get(data_id, [])
            if prod not in idx_map:
                continue
            for cons in consumers:
                if cons not in idx_map:
                    continue
                edges.append(
                    {
                        "source": idx_map[prod],
                        "target": idx_map[cons],
                        "type": "uses",
                        "via": "sparql",
                        "vars": [name_map.get(data_id) or data_id],
                    }
                )

        # Cross-notebook heuristic: link by shared basename when producer known
        for data_id, consumers in consumed_by.items():
            base = os.path.basename(name_map.get(data_id, data_id))
            prod = base_producers.get(base)
            if not prod or prod not in idx_map:
                continue
            for cons in consumers:
                if cons not in idx_map:
                    continue
                edges.append(
                    {
                        "source": idx_map[prod],
                        "target": idx_map[cons],
                        "type": "uses",
                        "via": "sparql",
                        "vars": [base],
                    }
                )

        return {"cells": cells, "edges": edges}

    def _label_for_graph(self, graph_uri: Optional[str], is_part: Optional[str]) -> str:
        if is_part:
            base = os.path.basename(is_part)
            if base:
                return base
        if graph_uri:
            cleaned = graph_uri.split("?")[0]
            base = os.path.basename(cleaned)
            if base:
                return base
            return graph_uri
        return "notebook"


class SparqlGraphHandler(APIHandler):
    def post(self):
        data = self.get_json_body() or {}
        endpoint = data.get("endpoint") or DEFAULT_INDEX_SETTINGS.get("endpoint")
        token = data.get("auth_token") or data.get("token")
        username = data.get("username")
        password = data.get("password")
        if not endpoint:
            self.set_status(400)
            self.finish({"error": "missing endpoint"})
            return
        try:
            helper = SparqlSummaryHandler(self.application, self.request)
            graphs = helper._list_graphs(endpoint, token, username, password)
            latest_graphs = helper._latest_per_notebook(graphs)
            triples = helper._fetch_triples(endpoint, latest_graphs, token, username, password)
            summary = helper._build_graph_summary(triples)
            graph_url = self._render_pyvis(summary)
            self.finish({"graph": summary, "graph_url": graph_url, "graphs": latest_graphs})
        except Exception as exc:  # pragma: no cover - network failures
            self.log.error("CellScope SPARQL graph failed: %s", exc)
            self.set_status(500)
            self.finish({"error": f"sparql graph failed: {exc}"})

    def _render_pyvis(self, summary: Dict[str, Any]) -> Optional[str]:
        if Network is None:
            return None
        ts = str(int(time.time() * 1000))
        out_dir = os.path.join("out-lab", f"sparql_{ts}", "ro-crate")
        os.makedirs(out_dir, exist_ok=True)
        net = Network(height="600px", width="100%", directed=True)
        net.set_options(
            """
            {
              "physics": {
                "solver": "forceAtlas2Based",
                "forceAtlas2Based": { "gravitationalConstant": -60, "springLength": 140, "springConstant": 0.08 },
                "minVelocity": 0.75
              },
              "interaction": { "hover": true, "tooltipDelay": 80 },
              "layout": { "improvedLayout": true }
            }
            """
        )
        group_nodes: Dict[str, str] = {}
        group_idx = 10000
        for cell in summary.get("cells", []):
            label = cell.get("name") or f"cell {cell.get('idx')}"
            group = cell.get("graph") or "notebook"
            meta_parts = []
            if cell.get("kernel"):
                meta_parts.append(f"Kernel: {cell.get('kernel')}")
            if cell.get("var_defs"):
                meta_parts.append("Defines: " + ", ".join(cell["var_defs"]))
            if cell.get("var_uses"):
                meta_parts.append("Uses: " + ", ".join(cell["var_uses"]))
            if cell.get("file_writes"):
                meta_parts.append("Writes: " + ", ".join(cell["file_writes"]))
            if cell.get("file_reads"):
                meta_parts.append("Reads: " + ", ".join(cell["file_reads"]))
            title = "<b>" + group + "</b><br/>" + "<br/>".join(meta_parts) if meta_parts else group
            # add a soft group parent to keep cells together
            if group not in group_nodes:
                group_nodes[group] = str(group_idx)
                net.add_node(
                    group_nodes[group],
                    label=group,
                    shape="dot",
                    size=60,
                    opacity=0.15,
                    color="rgba(180,180,180,0.25)",
                    font={"size": 14, "color": "#444"},
                    physics=True,
                )
                group_idx += 1
            net.add_node(
                str(cell.get("idx")),
                label=label,
                shape="box",
                group=group,
                title=title,
            )
            net.add_edge(group_nodes[group], str(cell.get("idx")), hidden=False, color="rgba(0,0,0,0.05)")
        for edge in summary.get("edges", []):
            src = edge.get("source")
            tgt = edge.get("target")
            if src is None or tgt is None:
                continue
            label = ",".join(edge.get("vars") or [])
            net.add_edge(str(src), str(tgt), label=label, title=edge.get("via") or "sparql")
        html_path = os.path.join(out_dir, "cell_graph.html")
        net.write_html(html_path, notebook=False)
        return f"/files/{html_path}"


class ExportHandler(APIHandler):
    def post(self):
        data = self.get_json_body() or {}
        nb_path = data.get("notebook")
        out_dir = data.get("out_dir") or "output"
        aliases = data.get("aliases") or {}
        hints = data.get("hints") or {}
        sidecars = data.get("sidecars") or []
        alias_map = aliases.get("aliases") if isinstance(aliases, dict) else aliases

        capture = parse_notebook(
            nb_path,
            alias_map=alias_map,
            collect_materialized=True,
        )
        crate_dir = build_rocrate(
            capture,
            out_dir,
            infer_cross_kernel_edges(capture),
            hints=hints,
            sidecars=sidecars,
        )

        request_index_cfg = data.get("index") or {}
        skip_index = request_index_cfg.get("skip") or data.get("no_index")
        index_result: Optional[Dict[str, Any]] = None
        if not skip_index:
            index_cfg = _merge_index_configs(
                self._default_index_config(),
                request_index_cfg,
            )
            if index_cfg.get("endpoint"):
                try:
                    index_result = self._index_with_retry(crate_dir, index_cfg)
                except Exception as exc:  # pragma: no cover - network failures
                    self.log.error("CellScope indexing failed: %s", exc)
                    self.set_status(500)
                    self.finish({"error": f"indexing failed: {exc}"})
                    return
            else:
                try:
                    index_result = index_crate(
                        crate_dir,
                        output_path=index_cfg.get("output"),
                        graph_uri=_resolve_graph_uri(nb_path),
                    )
                    index_result["attempts"] = 1
                    index_result["duration_seconds"] = 0.0
                    index_result["endpoint"] = None
                    index_result["retries"] = 0
                except Exception as exc:  # pragma: no cover - filesystem failures
                    self.log.error("CellScope indexing failed: %s", exc)
                    self.set_status(500)
                    self.finish({"error": f"indexing failed: {exc}"})
                    return

        payload: Dict[str, Any] = {"crate": str(crate_dir)}
        if index_result is not None:
            payload["index"] = index_result
        self.finish(payload)

    def _default_index_config(self) -> IndexConfig:
        config = self.settings.get("cellscope_index_config", DEFAULT_INDEX_SETTINGS)
        return dict(config or {})

    def _index_with_retry(self, crate_dir: str, config: IndexConfig) -> Dict[str, Any]:
        retries = int(config.get("retries") or 0)
        backoff = float(config.get("backoff_seconds") or 1.5)
        timeout = config.get("timeout")
        if timeout is not None:
            try:
                timeout = float(timeout)
            except (TypeError, ValueError):
                timeout = None
        endpoint = config.get("endpoint")
        output = config.get("output")
        token = config.get("auth_token")
        username = config.get("username")
        password = config.get("password")

        headers = dict(config.get("headers") or {})
        auth: Optional[Tuple[str, str]] = None
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if username and password:
            auth = (username, password)

        attempts = 0
        last_exc: Optional[Exception] = None
        start_time = time.monotonic()
        while attempts <= retries:
            attempts += 1
            try:
                result = index_crate(
                    crate_dir,
                    endpoint=endpoint,
                    output_path=output,
                    auth=auth,
                    headers=headers,
                    timeout=timeout,
                )
                duration = time.monotonic() - start_time
                result["attempts"] = attempts
                result["duration_seconds"] = duration
                result["endpoint"] = endpoint
                result["retries"] = retries
                return result
            except Exception as exc:  # pragma: no cover - network failures
                last_exc = exc
                if attempts > retries:
                    raise
                sleep_for = backoff * (2 ** (attempts - 1))
                self.log.warning(
                    "CellScope indexing attempt %s/%s failed: %s. Retrying in %.2fs",
                    attempts,
                    retries + 1,
                    exc,
                    sleep_for,
                )
                time.sleep(sleep_for)
        # this point only reached if retries < 0, which should not happen.
        if last_exc:
            raise last_exc
        raise RuntimeError("Unknown indexing failure")


class IndexHandler(APIHandler):
    def post(self):
        data = self.get_json_body() or {}
        crate_dir = data.get("crate")
        crate_json = data.get("crate_json")
        if not crate_dir and not crate_json:
            self.set_status(400)
            self.finish({"error": "provide 'crate' or 'crate_json'"})
            return
        try:
            result = index_crate(
                crate_dir,
                crate_metadata=crate_json,
                endpoint=data.get("endpoint"),
                output_path=data.get("output"),
                base_uri=data.get("base_uri"),
                auth=_resolve_basic_auth(data),
                headers=_resolve_headers(data),
            )
        except Exception as exc:
            self.set_status(500)
            self.finish({"error": str(exc)})
            return
        self.finish({"index": result})


def _resolve_headers(config: Dict[str, Any]) -> Optional[Dict[str, str]]:
    headers = config.get("headers")
    if headers and isinstance(headers, dict):
        return {str(k): str(v) for k, v in headers.items()}
    token = config.get("auth_token")
    if token:
        return {"Authorization": f"Bearer {token}"}
    return None


def _resolve_basic_auth(config: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    username = config.get("username")
    password = config.get("password")
    if username and password:
        return str(username), str(password)
    return None


def _merge_index_configs(defaults: IndexConfig, override: IndexConfig) -> IndexConfig:
    merged = dict(defaults or {})
    for key, value in (override or {}).items():
        if value is not None:
            merged[key] = value
    return merged

class WorkflowCaptureHandler(APIHandler):
    def post(self):
        data = self.get_json_body() or {}
        workflow_path = data.get("workflow")
        if not workflow_path:
            self.set_status(400)
            self.finish({"error": "missing 'workflow' path"})
            return
        out_dir = data.get("out_dir") or "out-lab/workflows"
        notebook_roots = _normalise_string_list(data.get("notebook_roots"))
        notebook_map_raw = data.get("notebook_map") or {}
        if notebook_map_raw and not isinstance(notebook_map_raw, dict):
            self.set_status(400)
            self.finish({"error": "'notebook_map' must be an object"})
            return
        notebook_map = {str(k): str(v) for k, v in notebook_map_raw.items()}
        default_notebook = data.get("default_notebook")
        aliases = data.get("aliases") or {}
        alias_map = aliases.get("aliases") if isinstance(aliases, dict) else aliases
        hints = data.get("hints") or {}
        sidecars = data.get("sidecars") or []
        skip_crates = bool(data.get("skip_crates"))

        try:
            plan = parse_workflow(workflow_path)
        except Exception as exc:
            self.set_status(400)
            self.finish({"error": f"failed to parse workflow: {exc}"})
            return

        try:
            result = capture_workflow(
                plan,
                output_dir=out_dir,
                notebook_roots=notebook_roots,
                notebook_overrides=notebook_map,
                alias_map=alias_map,
                hints=hints,
                sidecars=sidecars,
                build_crates=not skip_crates,
                default_notebook=default_notebook,
            )
        except Exception as exc:
            self.log.error("Workflow capture failed: %s", exc)
            self.set_status(500)
            self.finish({"error": f"workflow capture failed: {exc}"})
            return

        nodes_summary: List[Dict[str, Any]] = []
        captured = 0
        for record in result.records:
            if record.status == "captured":
                captured += 1
            nodes_summary.append({
                "id": record.node_id,
                "title": record.title,
                "status": record.status,
                "notebook": record.notebook_path,
                "capture": record.capture_path,
                "crate": record.crate_dir,
                "error": record.error,
            })

        self.finish({
            "workflow_id": result.plan.workflow_id,
            "manifest": str(result.manifest_path),
            "captured": captured,
            "total": len(result.records),
            "nodes": nodes_summary,
        })





def setup_handlers(server_app):
    host_app = server_app.web_app
    base_url = host_app.settings.get("base_url", "/")
    pattern = url_path_join(base_url, "cellscope")
    host_app.settings["cellscope_index_config"] = _load_index_config(server_app)
    host_app.add_handlers(".*$", [
        (url_path_join(pattern, "analyze"), AnalyzeHandler),
        (url_path_join(pattern, "export"), ExportHandler),
        (url_path_join(pattern, "index"), IndexHandler),
        (url_path_join(pattern, "workflow", "capture"), WorkflowCaptureHandler),
        (url_path_join(pattern, "sparql_summary"), SparqlSummaryHandler),
        (url_path_join(pattern, "sparql_graph"), SparqlGraphHandler),
    ])


def _normalise_string_list(value: Any) -> Optional[List[str]]:
    if value is None:
        return None
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, Iterable):
        items = list(value)
    else:
        items = [value]
    result: List[str] = []
    for item in items:
        if item is None:
            continue
        text_value = str(item).strip()
        if text_value:
            result.append(text_value)
    return result if result else None




def _load_index_config(server_app) -> IndexConfig:
    # Priority: explicit config > environment variables > defaults
    config_section = server_app.config.get("CellScope", {})
    env_endpoint = os.getenv("CELLSCOPE_SPARQL_ENDPOINT")
    env_token = os.getenv("CELLSCOPE_SPARQL_TOKEN")
    env_user = os.getenv("CELLSCOPE_SPARQL_USER")
    env_password = os.getenv("CELLSCOPE_SPARQL_PASSWORD")
    env_output = os.getenv("CELLSCOPE_SPARQL_OUTPUT")
    env_retries = os.getenv("CELLSCOPE_SPARQL_RETRIES")
    env_backoff = os.getenv("CELLSCOPE_SPARQL_BACKOFF")
    env_timeout = os.getenv("CELLSCOPE_SPARQL_TIMEOUT")

    cfg = dict(DEFAULT_INDEX_SETTINGS)
    cfg.update({k: v for k, v in config_section.items() if v is not None})

    if env_endpoint:
        cfg["endpoint"] = env_endpoint
    if env_token:
        cfg["auth_token"] = env_token
    if env_user:
        cfg["username"] = env_user
    if env_password:
        cfg["password"] = env_password
    if env_output:
        cfg["output"] = env_output
    if env_retries:
        try:
            cfg["retries"] = int(env_retries)
        except ValueError:
            pass
    if env_backoff:
        try:
            cfg["backoff_seconds"] = float(env_backoff)
        except ValueError:
            pass
    if env_timeout:
        try:
            cfg["timeout"] = float(env_timeout)
        except ValueError:
            pass

    return cfg
