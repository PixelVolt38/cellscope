from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple


def _serialise_mapping_items(items: Iterable[Tuple[str, Any]]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for key, value in items:
        payload[key] = sorted(value) if isinstance(value, set) else value
    return payload


def serialise_edge(edge: Any) -> Dict[str, Any]:
    """Convert a NetworkX edge (tuple or mapping) into a JSON-serialisable dict."""
    if isinstance(edge, dict):
        payload = _serialise_mapping_items(edge.items())
        source = payload.pop("source", payload.pop("from", None))
        target = payload.pop("target", payload.pop("to", None))
        result: Dict[str, Any] = {}
        if source is not None:
            result["source"] = source
        if target is not None:
            result["target"] = target
        result.update(payload)
        return result

    try:
        u, v, data = edge  # type: ignore[misc]
    except Exception:
        return {"raw": edge}

    payload = _serialise_mapping_items(data.items()) if isinstance(data, dict) else {}
    return {"source": u, "target": v, **payload}


def capture_to_json(capture: Dict[str, Any]) -> Dict[str, Any]:
    """Convert the parse_notebook capture output into a JSON-ready structure."""
    cells_json: List[Dict[str, Any]] = []
    for cell in capture.get("cells", []):
        label = getattr(cell, "label", f"cell_{cell.idx}")
        cells_json.append(
            {
                "idx": cell.idx,
                "position": getattr(cell, "position", None),
                "notebook": capture.get("nb_path"),
                "label": label,
                "name": label,
                "kernel": getattr(cell, "kernel", "python"),
                "funcs": sorted(getattr(cell, "funcs", [])),
                "func_calls": sorted(getattr(cell, "func_calls", [])),
                "var_defs": sorted(getattr(cell, "var_defs", [])),
                "var_uses": sorted(getattr(cell, "var_uses", [])),
                "file_writes": sorted(getattr(cell, "file_writes", [])),
                "file_reads": sorted(getattr(cell, "file_reads", [])),
            }
        )

    edges = capture.get("graph", {}).get("edges", [])
    edges_json = [serialise_edge(edge) for edge in edges]

    return {
        "nb_path": capture.get("nb_path"),
        "cells": cells_json,
        "edges": edges_json,
    }
