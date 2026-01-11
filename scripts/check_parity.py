#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from cellscope import infer_cross_kernel_edges, parse_notebook
from cellscope.serialization import capture_to_json

try:
    from cellscope_server.handlers import SparqlSummaryHandler
except Exception:  # pragma: no cover - optional dependency
    SparqlSummaryHandler = None  # type: ignore


def load_graph(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "graph" in payload:
        return payload["graph"]
    return payload


def build_local_graph(notebook_path: str) -> Dict[str, Any]:
    capture = parse_notebook(notebook_path, collect_materialized=True)
    capture["graph"]["edges"].extend(infer_cross_kernel_edges(capture))
    summary = capture_to_json(capture)
    return summary.get("graph", {})


def build_sparql_graph(endpoint: str, token: str, username: str, password: str) -> Dict[str, Any]:
    if SparqlSummaryHandler is None:
        raise RuntimeError("cellscope_server is required to fetch SPARQL summaries")
    helper = SparqlSummaryHandler.__new__(SparqlSummaryHandler)
    graphs = helper._list_graphs(endpoint, token or None, username or None, password or None)
    latest_graphs = helper._latest_per_notebook(graphs)
    triples = helper._fetch_triples(endpoint, latest_graphs, token or None, username or None, password or None)
    return helper._build_graph_summary(triples)


def _cell_key(cell: Dict[str, Any], default_graph: str) -> str:
    graph = cell.get("graph") or default_graph
    name = cell.get("name") or cell.get("label") or f"cell_{cell.get('idx')}"
    return f"{graph}::{name}"


def _set(value: Optional[Iterable[Any]]) -> Set[str]:
    if not value:
        return set()
    return {str(v) for v in value if v is not None}


def _compare_cells(
    local_graph: Dict[str, Any],
    sparql_graph: Dict[str, Any],
    local_default_graph: str,
) -> Tuple[Dict[str, Any], Dict[int, str], Dict[int, str]]:
    local_cells = local_graph.get("cells", [])
    sparql_cells = sparql_graph.get("cells", [])
    local_by_key = {_cell_key(cell, local_default_graph): cell for cell in local_cells}
    sparql_by_key = {_cell_key(cell, local_default_graph): cell for cell in sparql_cells}

    local_idx_map = {cell.get("idx"): _cell_key(cell, local_default_graph) for cell in local_cells}
    sparql_idx_map = {cell.get("idx"): _cell_key(cell, local_default_graph) for cell in sparql_cells}

    diffs: Dict[str, Any] = {"missing_in_sparql": [], "missing_in_local": [], "field_mismatches": []}
    for key in sorted(set(local_by_key) | set(sparql_by_key)):
        local_cell = local_by_key.get(key)
        sparql_cell = sparql_by_key.get(key)
        if local_cell is None:
            diffs["missing_in_local"].append(key)
            continue
        if sparql_cell is None:
            diffs["missing_in_sparql"].append(key)
            continue

        mismatch: Dict[str, Any] = {"cell": key, "fields": {}}
        for field in (
            "kernel",
            "position",
            "version",
        ):
            local_val = local_cell.get(field)
            sparql_val = sparql_cell.get(field)
            if field == "position" and local_val is None and local_cell.get("idx") is not None:
                local_val = local_cell.get("idx")
            if local_val != sparql_val:
                mismatch["fields"][field] = {"local": local_val, "sparql": sparql_val}

        set_fields = (
            "funcs",
            "func_calls",
            "var_defs",
            "var_uses",
            "file_reads",
            "file_writes",
            "roles",
            "fileHints",
        )
        for field in set_fields:
            local_set = _set(local_cell.get(field))
            sparql_set = _set(sparql_cell.get(field))
            if local_set != sparql_set:
                mismatch["fields"][field] = {
                    "local": sorted(local_set),
                    "sparql": sorted(sparql_set),
                }

        if mismatch["fields"]:
            diffs["field_mismatches"].append(mismatch)
    return diffs, local_idx_map, sparql_idx_map


def _edge_key(edge: Dict[str, Any], idx_map: Dict[int, str]) -> Optional[Tuple[str, str, str, Tuple[str, ...]]]:
    source = edge.get("source")
    target = edge.get("target")
    if source is None or target is None:
        return None
    source_key = idx_map.get(source, str(source))
    target_key = idx_map.get(target, str(target))
    edge_type = edge.get("type") or "uses"
    vars_key = tuple(sorted(_set(edge.get("vars"))))
    return source_key, target_key, str(edge_type), vars_key


def _compare_edges(
    local_graph: Dict[str, Any],
    sparql_graph: Dict[str, Any],
    local_idx_map: Dict[int, str],
    sparql_idx_map: Dict[int, str],
) -> Dict[str, Any]:
    local_edges = local_graph.get("edges", [])
    sparql_edges = sparql_graph.get("edges", [])
    local_keys = {key for edge in local_edges if (key := _edge_key(edge, local_idx_map))}
    sparql_keys = {key for edge in sparql_edges if (key := _edge_key(edge, sparql_idx_map))}

    return {
        "missing_in_sparql": sorted(local_keys - sparql_keys),
        "missing_in_local": sorted(sparql_keys - local_keys),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare local analysis vs SPARQL summaries.")
    parser.add_argument("--notebook", help="Notebook path for local analysis.")
    parser.add_argument("--local-graph", help="JSON file with local graph summary.")
    parser.add_argument("--sparql-graph", help="JSON file with SPARQL graph summary.")
    parser.add_argument("--sparql-endpoint", help="SPARQL update endpoint (will query /sparql).")
    parser.add_argument("--token", default="", help="SPARQL auth token.")
    parser.add_argument("--username", default="", help="SPARQL basic auth username.")
    parser.add_argument("--password", default="", help="SPARQL basic auth password.")
    parser.add_argument("--dump-local", help="Write local graph summary to this path.")
    parser.add_argument("--dump-sparql", help="Write SPARQL graph summary to this path.")
    parser.add_argument("--out", help="Write parity report JSON to this path.")
    args = parser.parse_args()

    if not args.local_graph and not args.notebook:
        parser.error("Provide --notebook or --local-graph for local analysis.")
    if not args.sparql_graph and not args.sparql_endpoint:
        parser.error("Provide --sparql-graph or --sparql-endpoint for SPARQL analysis.")

    if args.local_graph:
        local_graph = load_graph(Path(args.local_graph))
        local_default_graph = "notebook"
    else:
        local_graph = build_local_graph(args.notebook)
        local_default_graph = os.path.basename(args.notebook)

    if args.sparql_graph:
        sparql_graph = load_graph(Path(args.sparql_graph))
    else:
        sparql_graph = build_sparql_graph(args.sparql_endpoint, args.token, args.username, args.password)

    if args.dump_local:
        Path(args.dump_local).write_text(json.dumps(local_graph, indent=2), encoding="utf-8")
    if args.dump_sparql:
        Path(args.dump_sparql).write_text(json.dumps(sparql_graph, indent=2), encoding="utf-8")

    cell_diffs, local_idx_map, sparql_idx_map = _compare_cells(local_graph, sparql_graph, local_default_graph)
    edge_diffs = _compare_edges(local_graph, sparql_graph, local_idx_map, sparql_idx_map)

    report = {
        "cells": cell_diffs,
        "edges": edge_diffs,
    }

    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
