#!/usr/bin/env python3
"""Run local latency benchmarks for CellScope analysis/export."""
from __future__ import annotations

import argparse
import json
import math
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from cellscope import build_rocrate, index_crate, infer_cross_kernel_edges, parse_notebook
from cellscope.serialization import capture_to_json


SYNTHETIC_CASES: List[Tuple[str, Path]] = [
    ("synth_10.ipynb", Path("evaluation/o3_benchmarks/notebooks/synth_10.ipynb")),
    ("synth_50.ipynb", Path("evaluation/o3_benchmarks/notebooks/synth_50.ipynb")),
    ("synth_100.ipynb", Path("evaluation/o3_benchmarks/notebooks/synth_100.ipynb")),
]

EXAMPLE_CASES: List[Tuple[str, Path]] = [
    ("RAVL", Path("examples/RAVL/RAVL.ipynb")),
    ("RAVL_R_source", Path("examples/RAVL/RAVL_R_source.ipynb")),
    ("SecretsProvider_demo", Path("examples/RAVL/SecretsProvider_demo.ipynb")),
    ("migrate_secrets", Path("examples/RAVL/migrate_secrets.ipynb")),
    ("exhaustive_python", Path("examples/exhaustive_python.ipynb")),
    ("exhaustive_r", Path("examples/exhaustive_r.ipynb")),
    ("multi_kernel_demo", Path("examples/multi_kernel_demo.ipynb")),
]


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


def _summary(times: List[float]) -> Dict[str, Any]:
    return {
        "runs": len(times),
        "p50_s": round(_percentile(times, 50), 6),
        "p95_s": round(_percentile(times, 95), 6),
        "min_s": round(min(times), 6),
        "max_s": round(max(times), 6),
    }


def _count_code_cells(path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    return sum(1 for cell in data.get("cells", []) if cell.get("cell_type") == "code")


def _analyze_once(path: Path) -> float:
    start = time.perf_counter()
    capture = parse_notebook(str(path), collect_materialized=True)
    capture["graph"]["edges"].extend(infer_cross_kernel_edges(capture))
    capture_to_json(capture)
    return time.perf_counter() - start


def _export_index_once(path: Path) -> float:
    start = time.perf_counter()
    capture = parse_notebook(str(path), collect_materialized=True)
    xkernel_edges = infer_cross_kernel_edges(capture)
    capture["graph"]["edges"].extend(xkernel_edges)
    tmp_root = Path(tempfile.mkdtemp(prefix="cellscope-bench-"))
    try:
        crate_dir = build_rocrate(
            capture,
            output_dir=str(tmp_root),
            xkernel_edges=xkernel_edges,
            hints=None,
            sidecars=None,
            config_files=None,
        )
        index_crate(crate_dir=crate_dir, endpoint=None)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
    return time.perf_counter() - start


def _run_cases(
    cases: Sequence[Tuple[str, Path]],
    analyze_runs: int,
    export_runs: int,
    include_code_cells: bool,
) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    for name, path in cases:
        if not path.exists():
            raise FileNotFoundError(path)
        analyze_times = [_analyze_once(path) for _ in range(analyze_runs)]
        export_times = [_export_index_once(path) for _ in range(export_runs)]
        entry: Dict[str, Any] = {
            "analyze": _summary(analyze_times),
            "export_index": _summary(export_times),
        }
        if include_code_cells:
            entry["code_cells"] = _count_code_cells(path)
        else:
            entry["notebook"] = str(path)
        results[name] = entry
    return results


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_md(path: Path, payload: Dict[str, Any], *, title: str, include_notebook: bool) -> None:
    lines: List[str] = [title, "", "Analyze = parse_notebook + infer_cross_kernel_edges + capture_to_json.",
                        "Export+index = parse_notebook + build_rocrate + index_crate (no endpoint).", ""]
    for name, entry in payload.items():
        lines.append(f"## {name}")
        if include_notebook:
            lines.append(f"Notebook: `{entry['notebook']}`")
        elif "code_cells" in entry:
            lines[-1] = f"## {name} ({entry['code_cells']} code cells)"
        lines.append(f"Analyze: {entry['analyze']}")
        lines.append(f"Export+index: {entry['export_index']}")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthetic-only", action="store_true")
    parser.add_argument("--examples-only", action="store_true")
    parser.add_argument("--out-dir", default="evaluation/o3_benchmarks")
    parser.add_argument("--synthetic-analyze-runs", type=int, default=10)
    parser.add_argument("--synthetic-export-runs", type=int, default=5)
    parser.add_argument("--example-analyze-runs", type=int, default=5)
    parser.add_argument("--example-export-runs", type=int, default=3)
    args = parser.parse_args()

    run_synth = not args.examples_only
    run_examples = not args.synthetic_only
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if run_synth:
        synth_results = _run_cases(
            SYNTHETIC_CASES,
            analyze_runs=args.synthetic_analyze_runs,
            export_runs=args.synthetic_export_runs,
            include_code_cells=True,
        )
        _write_json(out_dir / "benchmark_results.json", synth_results)
        _write_md(out_dir / "benchmark_results.md", synth_results,
                  title="# Local Benchmark Results", include_notebook=False)

    if run_examples:
        example_results = _run_cases(
            EXAMPLE_CASES,
            analyze_runs=args.example_analyze_runs,
            export_runs=args.example_export_runs,
            include_code_cells=False,
        )
        _write_json(out_dir / "benchmark_results_examples.json", example_results)
        _write_md(
            out_dir / "benchmark_results_examples.md",
            example_results,
            title="# Local Benchmark Results (examples)",
            include_notebook=True,
        )


if __name__ == "__main__":
    main()
