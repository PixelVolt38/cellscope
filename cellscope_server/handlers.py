"""
Jupyter Server extension: exposes two endpoints
 - POST /cellscope/analyze
 - POST /cellscope/export

This is a minimal Tornado-based handler module; integrate by
adding to jupyter_server_config.d.
"""
import os
import time
from typing import Any, Dict, Iterable, Optional, Tuple, Union

from jupyter_server.base.handlers import APIHandler
from jupyter_server.utils import url_path_join

from cellscope import (
    parse_notebook,
    infer_cross_kernel_edges,
    build_rocrate,
    index_crate,
)

EdgeRecord = Union[Dict[str, Any], Iterable[Any]]

IndexConfig = Dict[str, Any]

DEFAULT_INDEX_SETTINGS: IndexConfig = {
    "endpoint": None,
    "output": None,
    "retries": 2,
    "backoff_seconds": 1.5,
    "timeout": 10.0,
    "auth_token": None,
    "username": None,
    "password": None,
}


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
    host_app.settings["cellscope_index_config"] = _load_index_config(server_app)
    host_app.add_handlers(".*$", [
        (url_path_join(pattern, "analyze"), AnalyzeHandler),
        (url_path_join(pattern, "export"), ExportHandler),
        (url_path_join(pattern, "index"), IndexHandler),
    ])


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
