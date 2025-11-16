from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlparse
from collections import defaultdict

from cellscope.ast_capture import parse_notebook
from cellscope.cross_kernel import infer_cross_kernel_edges
from cellscope.rocrate_io import build_rocrate
from cellscope.serialization import capture_to_json, serialise_edge


@dataclass
class WorkflowPort:
    name: str
    port_id: str
    side: str
    properties: Dict[str, Any]


@dataclass
class WorkflowNode:
    node_id: str
    title: str
    description: Optional[str]
    kernel: Optional[str]
    virtual_lab: Optional[str]
    source_url: Optional[str]
    params: List[Dict[str, Any]]
    secrets: List[Dict[str, Any]]
    ports: Dict[str, WorkflowPort]


@dataclass
class WorkflowEdge:
    edge_id: str
    source: Optional[str]
    source_port: Optional[str]
    target: Optional[str]
    target_port: Optional[str]


@dataclass
class WorkflowPlan:
    workflow_id: str
    path: Path
    nodes: Dict[str, WorkflowNode]
    edges: List[WorkflowEdge]


@dataclass
class NodeCaptureRecord:
    node_id: str
    title: str
    status: str
    notebook_path: Optional[str]
    capture_path: Optional[str]
    cross_edges_path: Optional[str]
    crate_dir: Optional[str]
    error: Optional[str]


@dataclass
class WorkflowCaptureResult:
    plan: WorkflowPlan
    records: List[NodeCaptureRecord]
    manifest_path: Path


@dataclass
class NotebookIndex:
    roots: List[Path]
    by_slug: Dict[str, List[Path]]
    by_stem: Dict[str, List[Path]]


def _slugify(value: str) -> str:
    import re

    slug = re.sub(r"[^0-9a-zA-Z]+", "-", value).strip("-")
    return slug or "node"


def _parse_ports(port_map: Dict[str, Any]) -> Dict[str, WorkflowPort]:
    ports: Dict[str, WorkflowPort] = {}
    for name, payload in (port_map or {}).items():
        port_id = payload.get("id") or name
        side = payload.get("type", "")
        ports[name] = WorkflowPort(
            name=name,
            port_id=port_id,
            side=side,
            properties=dict(payload.get("properties") or {}),
        )
    return ports


def parse_workflow(workflow_path: str) -> WorkflowPlan:
    path = Path(workflow_path)
    data = json.loads(path.read_text())
    chart = data.get("chart") or {}

    nodes: Dict[str, WorkflowNode] = {}
    for node_data in (chart.get("nodes") or {}).values():
        cell = (node_data.get("properties") or {}).get("cell") or {}
        node = WorkflowNode(
            node_id=node_data.get("id"),
            title=cell.get("title") or node_data.get("id"),
            description=cell.get("description"),
            kernel=cell.get("kernel"),
            virtual_lab=cell.get("virtual_lab"),
            source_url=cell.get("source_url"),
            params=list(cell.get("params") or []),
            secrets=list(cell.get("secrets") or []),
            ports=_parse_ports(node_data.get("ports") or {}),
        )
        nodes[node.node_id] = node

    edges: List[WorkflowEdge] = []
    for link in (chart.get("links") or {}).values():
        from_block = link.get("from") or {}
        to_block = link.get("to") or {}
        edges.append(
            WorkflowEdge(
                edge_id=link.get("id"),
                source=from_block.get("nodeId"),
                source_port=from_block.get("portId"),
                target=to_block.get("nodeId"),
                target_port=to_block.get("portId"),
            )
        )

    workflow_id = _slugify(path.stem)
    return WorkflowPlan(workflow_id=workflow_id, path=path, nodes=nodes, edges=edges)


def _candidate_notebook_stems(node: WorkflowNode) -> List[str]:
    stems: List[str] = []
    candidates = [node.title, node.node_id]
    if node.source_url:
        parsed = urlparse(node.source_url)
        tail = Path(parsed.path).name
        candidates.append(tail)
    for cand in candidates:
        if not cand:
            continue
        for val in {cand, _slugify(cand)}:
            if val and val not in stems:
                stems.append(val)
    return stems


def resolve_notebook(
    node: WorkflowNode,
    notebook_roots: Sequence[str],
    overrides: Optional[Dict[str, str]] = None,
    index: Optional[NotebookIndex] = None,
    default_notebook: Optional[str] = None,
) -> Optional[Path]:
    overrides = overrides or {}
    for key in (node.node_id, node.title, _slugify(node.title or "")):
        if key and key in overrides:
            return Path(overrides[key]).expanduser()
    if node.source_url:
        parsed = urlparse(node.source_url)
        tail = Path(parsed.path)
        for candidate in (str(tail), tail.name):
            if candidate and candidate in overrides:
                return Path(overrides[candidate]).expanduser()
    if index:
        match = _match_notebook_index(node, index)
        if match:
            return match
    for root in notebook_roots:
        root_path = Path(root).expanduser()
        if not root_path.exists():
            continue
        for stem in _candidate_notebook_stems(node):
            for suffix in (".ipynb", ".py"):
                candidate = root_path / f"{stem}{suffix}"
                if candidate.exists():
                    return candidate
    if default_notebook:
        default_path = Path(default_notebook).expanduser()
        if default_path.exists():
            return default_path
    return None


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


def capture_workflow(
    plan: WorkflowPlan,
    output_dir: str,
    notebook_roots: Optional[Sequence[str]] = None,
    notebook_overrides: Optional[Dict[str, str]] = None,
    alias_map: Optional[Dict[str, str]] = None,
    hints: Optional[Dict[str, Any]] = None,
    sidecars: Optional[List[Dict[str, Any]]] = None,
    build_crates: bool = True,
    default_notebook: Optional[str] = None,
) -> WorkflowCaptureResult:
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    workflow_dir = base / plan.workflow_id
    nodes_dir = workflow_dir / "nodes"
    nodes_dir.mkdir(parents=True, exist_ok=True)

    roots: List[str] = []
    if notebook_roots:
        roots.extend(str(Path(root).expanduser()) for root in notebook_roots)
    auto_root = plan.path.resolve().parent.parent / "codebase"
    if not roots and auto_root.exists():
        roots.append(str(auto_root))
    notebook_index = _build_notebook_index(roots)

    records: List[NodeCaptureRecord] = []
    manifest_nodes: List[Dict[str, Any]] = []

    for node in plan.nodes.values():
        nb_path = resolve_notebook(
            node,
            notebook_roots=roots,
            overrides=notebook_overrides,
            index=notebook_index,
            default_notebook=default_notebook,
        )
        node_slug = _slugify(node.title or node.node_id)
        node_dir = nodes_dir / node_slug
        node_dir.mkdir(parents=True, exist_ok=True)

        status = "missing"
        capture_path: Optional[Path] = None
        cross_edges_path: Optional[Path] = None
        crate_dir: Optional[str] = None
        error: Optional[str] = None

        if nb_path and nb_path.exists():
            try:
                capture = parse_notebook(
                    str(nb_path),
                    alias_map=alias_map,
                    collect_materialized=True,
                )
                xedges = infer_cross_kernel_edges(capture)
                capture.setdefault("graph", {}).setdefault("edges", []).extend(xedges)
                capture_json = capture_to_json(capture)
                capture_path = node_dir / "capture.json"
                _write_json(capture_path, capture_json)
                if xedges:
                    cross_edges_path = node_dir / "cross_edges.json"
                    _write_json(cross_edges_path, [serialise_edge(edge) for edge in xedges])
                if build_crates:
                    crate_output = node_dir / "crate"
                    crate_dir = build_rocrate(
                        capture,
                        output_dir=str(crate_output),
                        xkernel_edges=xedges,
                        hints=hints or {},
                        sidecars=sidecars or [],
                    )
                status = "captured"
            except Exception as exc:  # pragma: no cover - defensive
                status = "error"
                error = str(exc)
        else:
            if nb_path:
                error = f"Notebook missing: {nb_path}"
            else:
                error = "Notebook not resolved"

        records.append(
            NodeCaptureRecord(
                node_id=node.node_id,
                title=node.title,
                status=status,
                notebook_path=str(nb_path) if nb_path else None,
                capture_path=str(capture_path) if capture_path else None,
                cross_edges_path=str(cross_edges_path) if cross_edges_path else None,
                crate_dir=str(crate_dir) if crate_dir else None,
                error=error,
            )
        )
        manifest_nodes.append(
            {
                "id": node.node_id,
                "title": node.title,
                "kernel": node.kernel,
                "source_url": node.source_url,
                "status": status,
                "notebook": str(nb_path) if nb_path else None,
                "capture": _relpath(capture_path, workflow_dir),
                "cross_edges": _relpath(cross_edges_path, workflow_dir),
                "crate": _relpath(Path(crate_dir), workflow_dir) if crate_dir else None,
                "error": error,
            }
        )

    manifest = {
        "workflow": {
            "id": plan.workflow_id,
            "source": str(plan.path),
            "node_count": len(plan.nodes),
            "edge_count": len(plan.edges),
        },
        "nodes": manifest_nodes,
        "edges": [asdict(edge) for edge in plan.edges],
    }

    manifest_path = workflow_dir / "workflow_manifest.json"
    _write_json(manifest_path, manifest)
    return WorkflowCaptureResult(plan=plan, records=records, manifest_path=manifest_path)


def _relpath(path: Optional[Path], base: Path) -> Optional[str]:
    if not path:
        return None
    try:
        return os.path.relpath(path, base)
    except Exception:
        return str(path)


def load_workflow_manifest(manifest_path: str) -> Dict[str, Any]:
    path = Path(manifest_path)
    return json.loads(path.read_text())


def _build_notebook_index(roots: Sequence[str]) -> NotebookIndex:
    by_slug: Dict[str, List[Path]] = defaultdict(list)
    by_stem: Dict[str, List[Path]] = defaultdict(list)
    resolved_roots: List[Path] = []
    for root in roots:
        root_path = Path(root).expanduser()
        if not root_path.exists():
            continue
        resolved_roots.append(root_path)
        for path in root_path.rglob("*.ipynb"):
            slug = _slugify(path.stem)
            by_slug[slug].append(path)
            by_stem[path.stem.lower()].append(path)
    return NotebookIndex(roots=resolved_roots, by_slug=dict(by_slug), by_stem=dict(by_stem))


def _match_notebook_index(node: WorkflowNode, index: NotebookIndex) -> Optional[Path]:
    candidates = _candidate_notebook_stems(node)
    if node.source_url:
        parsed = urlparse(node.source_url)
        tail = Path(parsed.path).stem
        if tail:
            candidates.append(tail)
    for cand in candidates:
        slug = _slugify(cand)
        if slug and slug in index.by_slug:
            return index.by_slug[slug][0]
        stem = cand.lower()
        if stem and stem in index.by_stem:
            return index.by_stem[stem][0]
    for slug, paths in index.by_slug.items():
        for cand in candidates:
            cand_slug = _slugify(cand)
            if cand_slug and (cand_slug in slug or slug in cand_slug):
                return paths[0]
    return None
