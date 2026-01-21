#!/usr/bin/env python3
"""Generate predictions + coverage metrics for O1 notebooks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from cellscope import infer_cross_kernel_edges, parse_notebook
from cellscope.serialization import capture_to_json


CORE_NOTEBOOKS = ["exhaustive_python", "multi_kernel_demo"]


def _as_list(values: Iterable[Any]) -> List[List[Any]]:
    return [list(item) for item in values]


def _set_from_cells(cells: Sequence[Dict[str, Any]], field: str) -> Set[Tuple[int, str]]:
    result: Set[Tuple[int, str]] = set()
    for cell in cells:
        idx = cell.get("idx")
        if idx is None:
            continue
        for value in cell.get(field, []) or []:
            result.add((int(idx), str(value)))
    return result


def _set_from_edges(edges: Sequence[Dict[str, Any]]) -> Set[Tuple[int, int, str]]:
    result: Set[Tuple[int, int, str]] = set()
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if source is None or target is None:
            continue
        for var in edge.get("vars", []) or []:
            result.add((int(source), int(target), str(var)))
    return result


def _metrics(gold: Set[Tuple[Any, ...]], pred: Set[Tuple[Any, ...]]) -> Dict[str, Any]:
    tp = len(gold & pred)
    fp = len(pred - gold)
    fn = len(gold - pred)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _diff(gold: Set[Tuple[Any, ...]], pred: Set[Tuple[Any, ...]]) -> Dict[str, List[List[Any]]]:
    fp = sorted(pred - gold)
    fn = sorted(gold - pred)
    return {"fp": _as_list(fp), "fn": _as_list(fn)}


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_md(path: Path, payload: Dict[str, Any], title: str) -> None:
    lines: List[str] = ["# Coverage Results (O1)", "", "Gold labels vs. model predictions.", ""]
    for name in payload:
        lines.append(f"## {name}")
        for section in ("defs", "uses", "edges"):
            metrics = payload[name][section]["metrics"]
            lines.append(
                "- {section}: precision {p:.4f}, recall {r:.4f}, F1 {f:.4f} "
                "(tp {tp}, fp {fp}, fn {fn})".format(
                    section=section,
                    p=metrics["precision"],
                    r=metrics["recall"],
                    f=metrics["f1"],
                    tp=metrics["tp"],
                    fp=metrics["fp"],
                    fn=metrics["fn"],
                )
            )
        lines.append("")

        for section in ("defs", "uses", "edges"):
            diff = payload[name][section]["diff"]
            if diff["fp"] or diff["fn"]:
                lines.append(f"### {section} mismatches")
                if diff["fp"]:
                    lines.append("False positives:")
                    lines.append("```json")
                    lines.append(json.dumps(diff["fp"], indent=2))
                    lines.append("```")
                if diff["fn"]:
                    lines.append("False negatives:")
                    lines.append("```json")
                    lines.append(json.dumps(diff["fn"], indent=2))
                    lines.append("```")
                lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def _predict_notebook(notebook_path: Path) -> Dict[str, Any]:
    capture = parse_notebook(str(notebook_path), collect_materialized=True)
    capture["graph"]["edges"].extend(infer_cross_kernel_edges(capture))
    return capture_to_json(capture)


def _score_notebook(gold: Dict[str, Any], pred: Dict[str, Any]) -> Dict[str, Any]:
    gold_cells = gold.get("cells", [])
    pred_cells = pred.get("cells", [])
    gold_edges = gold.get("edges", [])
    pred_edges = pred.get("edges", [])

    gold_defs = _set_from_cells(gold_cells, "defs")
    pred_defs = _set_from_cells(pred_cells, "var_defs")
    gold_uses = _set_from_cells(gold_cells, "uses")
    pred_uses = _set_from_cells(pred_cells, "var_uses")
    gold_edge_set = _set_from_edges(gold_edges)
    pred_edge_set = _set_from_edges(pred_edges)

    return {
        "defs": {"metrics": _metrics(gold_defs, pred_defs), "diff": _diff(gold_defs, pred_defs)},
        "uses": {"metrics": _metrics(gold_uses, pred_uses), "diff": _diff(gold_uses, pred_uses)},
        "edges": {"metrics": _metrics(gold_edge_set, pred_edge_set), "diff": _diff(gold_edge_set, pred_edge_set)},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold-dir", default="evaluation/o1_coverage/gold_templates")
    parser.add_argument("--pred-dir", default="evaluation/o1_coverage/gold_predictions")
    parser.add_argument("--out-all-json", default="evaluation/o1_coverage/coverage_results_all.json")
    parser.add_argument("--out-all-md", default="evaluation/o1_coverage/coverage_results_all.md")
    parser.add_argument("--out-core-json", default="evaluation/o1_coverage/coverage_results.json")
    parser.add_argument("--out-core-md", default="evaluation/o1_coverage/coverage_results.md")
    args = parser.parse_args()

    gold_dir = Path(args.gold_dir)
    pred_dir = Path(args.pred_dir)
    pred_dir.mkdir(parents=True, exist_ok=True)

    results_all: Dict[str, Any] = {}
    results_core: Dict[str, Any] = {}

    for gold_path in sorted(gold_dir.glob("gold_template_*.json")):
        name = gold_path.stem.replace("gold_template_", "")
        gold = _load_json(gold_path)
        notebook_path = Path(gold.get("notebook", ""))
        if not notebook_path.is_file():
            notebook_path = Path(str(notebook_path).replace("/path/to/repo/", ""))
        if not notebook_path.is_file():
            raise FileNotFoundError(f"Notebook not found for {name}: {notebook_path}")

        pred = _predict_notebook(notebook_path)
        pred_path = pred_dir / f"predicted_{name}.json"
        _write_json(pred_path, pred)

        score = _score_notebook(gold, pred)
        results_all[name] = score
        if name in CORE_NOTEBOOKS:
            results_core[name] = score

    _write_json(Path(args.out_all_json), results_all)
    _write_md(Path(args.out_all_md), results_all, "Coverage Results (O1)")
    _write_json(Path(args.out_core_json), results_core)
    _write_md(Path(args.out_core_md), results_core, "Coverage Results (O1)")


if __name__ == "__main__":
    main()
