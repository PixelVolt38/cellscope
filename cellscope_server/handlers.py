"""
Jupyter Server extension: exposes two endpoints
 - POST /cellscope/analyze
 - POST /cellscope/export

This is a minimal Tornado-based handler module; integrate by
adding to jupyter_server_config.d.
"""
from typing import Any, Dict, Iterable, Union

from jupyter_server.base.handlers import APIHandler
from jupyter_server.utils import url_path_join

from cellscope import (
    parse_notebook,
    infer_cross_kernel_edges,
    build_rocrate,
    index_crate,
)

EdgeRecord = Union[Dict[str, Any], Iterable[Any]]


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
        self.finish({"graph": _to_json(capture)})


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

        index_cfg = data.get("index") or {}
        skip_index = index_cfg.get("skip") or data.get("no_index")
        index_result = None
        if not skip_index:
            try:
                index_result = index_crate(
                    crate_dir,
                    endpoint=index_cfg.get("endpoint"),
                    output_path=index_cfg.get("output"),
                )
            except Exception as exc:
                self.set_status(500)
                self.finish({"error": f"indexing failed: {exc}"})
                return

        payload = {"crate": str(crate_dir)}
        if index_result:
            payload["index"] = index_result
        self.finish(payload)


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
            )
        except Exception as exc:
            self.set_status(500)
            self.finish({"error": str(exc)})
            return
        self.finish({"index": result})


def _serialise_edge(edge: EdgeRecord) -> Dict[str, Any]:
    if isinstance(edge, dict):
        items = edge.items()
        source = edge.get("source")
        target = edge.get("target")
        payload: Dict[str, Any] = {}
        for key, value in items:
            if key in {"source", "target"}:
                continue
            payload[key] = sorted(value) if isinstance(value, set) else value
        return {"source": source, "target": target, **payload}
    try:
        u, v, data = edge  # type: ignore[misc]
    except Exception:
        return {"raw": edge}
    payload = {}
    if isinstance(data, dict):
        for key, value in data.items():
            payload[key] = sorted(value) if isinstance(value, set) else value
    return {"source": u, "target": v, **payload}


def _to_json(capture: Dict[str, Any]) -> Dict[str, Any]:
    # Convert to plain jsonable structure
    cells = []
    for c in capture["cells"]:
        cells.append({
            "idx": c.idx,
            "kernel": c.kernel,
            "funcs": sorted(c.funcs),
            "func_calls": sorted(getattr(c, "func_calls", [])),
            "var_defs": sorted(c.var_defs),
            "var_uses": sorted(c.var_uses),
            "file_writes": sorted(c.file_writes),
            "file_reads": sorted(c.file_reads),
            "sos_put": sorted(getattr(c, "sos_put", [])),
            "sos_get": sorted(getattr(c, "sos_get", [])),
        })
    edges = [_serialise_edge(edge) for edge in capture["graph"].get("edges", [])]
    return {"cells": cells, "edges": edges}


def setup_handlers(server_app):
    host_app = server_app.web_app
    base_url = host_app.settings.get("base_url", "/")
    pattern = url_path_join(base_url, "cellscope")
    host_app.add_handlers(".*$", [
        (url_path_join(pattern, "analyze"), AnalyzeHandler),
        (url_path_join(pattern, "export"), ExportHandler),
        (url_path_join(pattern, "index"), IndexHandler),
    ])
