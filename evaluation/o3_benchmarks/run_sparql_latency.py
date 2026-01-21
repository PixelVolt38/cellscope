#!/usr/bin/env python3
"""Measure SPARQL query latency against a Fuseki endpoint."""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

PREFIXES = """PREFIX schema: <http://schema.org/>
PREFIX prov: <http://www.w3.org/ns/prov#>
"""

QUERIES = {
    "list_graphs": PREFIXES + "SELECT DISTINCT ?g WHERE { GRAPH ?g { ?s ?p ?o } }",
    "count_triples": PREFIXES + "SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }",
    "datasets_per_graph": PREFIXES + (
        "SELECT ?g (COUNT(DISTINCT ?s) AS ?count) WHERE { GRAPH ?g { ?s a schema:Dataset } } GROUP BY ?g"
    ),
    "producers": PREFIXES + (
        "SELECT ?cell (COUNT(?artifact) AS ?count) WHERE { ?artifact prov:wasGeneratedBy ?cell } GROUP BY ?cell"
    ),
    "consumers": PREFIXES + (
        "SELECT ?cell (COUNT(?artifact) AS ?count) WHERE { ?cell prov:used ?artifact } GROUP BY ?cell"
    ),
}


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    k = (len(values) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return values[int(k)]
    return values[f] + (values[c] - values[f]) * (k - f)


def _summary(times_ms: List[float]) -> Dict[str, Any]:
    return {
        "runs": len(times_ms),
        "p50_ms": round(_percentile(times_ms, 50), 3),
        "p95_ms": round(_percentile(times_ms, 95), 3),
        "min_ms": round(min(times_ms), 3),
        "max_ms": round(max(times_ms), 3),
    }


def _run_query(
    endpoint: str,
    query: str,
    *,
    runs: int,
    headers: Dict[str, str],
    auth: Optional[Tuple[str, str]] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    timings: List[float] = []
    sample_bindings: List[Dict[str, Any]] = []
    for idx in range(runs):
        start = time.perf_counter()
        response = requests.get(
            endpoint,
            params={"query": query},
            headers=headers,
            auth=auth,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        duration_ms = (time.perf_counter() - start) * 1000.0
        timings.append(duration_ms)
        if idx == runs - 1:
            sample_bindings = payload.get("results", {}).get("bindings", [])[:3]
    return {"timing": _summary(timings), "sample": sample_bindings}, sample_bindings


def _write_md(path: str, endpoint: str, results: Dict[str, Any], title: str) -> None:
    lines: List[str] = [title, "", f"Endpoint (query): `{endpoint}`", ""]
    for name, entry in results["queries"].items():
        lines.append(f"## {name}")
        lines.append("")
        lines.append(f"Timing: {entry['timing']}")
        if entry.get("sample"):
            lines.append("")
            lines.append("Sample bindings (first 3):")
            lines.append("```json")
            lines.append(json.dumps(entry["sample"], indent=2))
            lines.append("```")
        lines.append("")
    Path(path).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://localhost:3030/cellscope/sparql")
    parser.add_argument("--update-endpoint", default="http://localhost:3030/cellscope/update")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--token", default="")
    parser.add_argument("--user", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--out-json", default="evaluation/o3_benchmarks/sparql_latency.json")
    parser.add_argument("--out-md", default="evaluation/o3_benchmarks/sparql_latency.md")
    parser.add_argument("--title", default="# SPARQL Latency Results")
    args = parser.parse_args()

    headers = {"Accept": "application/sparql-results+json"}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"
    auth = (args.user, args.password) if args.user or args.password else None

    results: Dict[str, Any] = {
        "endpoint_update": args.update_endpoint,
        "endpoint_query": args.endpoint,
        "queries": {},
    }

    for name, query in QUERIES.items():
        entry, _ = _run_query(args.endpoint, query, runs=args.runs, headers=headers, auth=auth)
        results["queries"][name] = entry

    Path(args.out_json).write_text(json.dumps(results, indent=2), encoding="utf-8")
    _write_md(args.out_md, args.endpoint, results, args.title)


if __name__ == "__main__":
    main()
