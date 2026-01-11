#!/usr/bin/env python
from __future__ import annotations

import argparse
import os
import os
from pathlib import Path
from typing import Any, Dict, Optional

from cellscope.ast_capture import parse_notebook
from cellscope.cross_kernel import infer_cross_kernel_edges
from cellscope.rocrate_io import build_rocrate
from cellscope.visualize import visualize_rocrate
from cellscope.validate_crate import validate_crate
from cellscope.indexer import index_crate
from cellscope.utils import load_yaml, load_sidecars
from cellscope.workflow import capture_workflow, load_workflow_manifest, parse_workflow

ENABLE_WORKFLOWS = os.environ.get("CELLSCOPE_ENABLE_WORKFLOWS") == "1"

ENABLE_WORKFLOWS = os.environ.get("CELLSCOPE_ENABLE_WORKFLOWS") == "1"


def _load_alias_map(path: Optional[str]) -> Optional[Dict[str, str]]:
    data = load_yaml(path) if path else None
    if not data:
        return None
    if not isinstance(data, dict):
        raise SystemExit("--aliases must point to a YAML mapping")
    aliases = data.get("aliases") if "aliases" in data else data
    if aliases is None:
        return None
    if not isinstance(aliases, dict):
        raise SystemExit("aliases mapping must contain key/value pairs")
    return aliases


def _load_dict(path: Optional[str], label: str) -> Dict[str, Any]:
    data = load_yaml(path) if path else None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise SystemExit(f"{label} must be a YAML mapping")
    return data


def _load_overrides(path: Optional[str]) -> Dict[str, str]:
    data = load_yaml(path) if path else None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise SystemExit("--notebook-map must be a YAML mapping of key -> path")
    return {str(k): str(v) for k, v in data.items()}


def _resolve_manifest_path(base: Path, value: Optional[str]) -> Optional[Path]:
    if not value:
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return (base / candidate).resolve()


def _format_index_output(template: Optional[str], node_id: str) -> Optional[str]:
    if not template:
        return None
    if "{node}" in template:
        return template.replace("{node}", node_id)
    return template


def _notebook_graph_uri(nb_path: Optional[str]) -> Optional[str]:
    if not nb_path:
        return None
    try:
        return Path(nb_path).resolve().as_uri()
    except Exception:
        return None


def cmd_build(args):
    alias_map = _load_alias_map(args.aliases)
    hints = _load_dict(args.hints, "--hints")
    sidecars = load_sidecars(args.sidecars) if args.sidecars else []
    config_files = args.config_files or []

    capture = parse_notebook(
        args.notebook,
        alias_map=alias_map,
        collect_materialized=True,
    )
    xk_edges = infer_cross_kernel_edges(capture)
    crate_dir = build_rocrate(
        capture,
        output_dir=args.out,
        xkernel_edges=xk_edges,
        hints=hints,
        sidecars=sidecars,
        config_files=config_files,
    )
    print(f"RO-Crate written to {crate_dir}")

    if not args.no_index:
        index_result = index_crate(
            crate_dir,
            endpoint=args.index_endpoint,
            output_path=args.index_output,
            graph_uri=_notebook_graph_uri(args.notebook),
        )
        _print_index_result(index_result)


def _print_index_result(result):
    endpoint = result.get("endpoint")
    status = result.get("status")
    triples = result.get("triples")
    output = result.get("output")
    if endpoint and status is not None:
        print(f"Index delta ({triples} triples) posted to {endpoint} (status {status})")
    else:
        print(f"Index delta ({triples} triples) written to {output}")


def cmd_vis(args):
    visualize_rocrate(
        args.crate,
        snippet_lines=args.lines,
        html_tooltips=args.html_tooltips,
        panel=not args.no_panel,
    )


def cmd_validate(args):
    ok = validate_crate(args.crate, verbose=True)
    if not ok:
        raise SystemExit(2)


def cmd_workflow_capture(args):
    plan = parse_workflow(args.workflow)
    alias_map = _load_alias_map(args.aliases)
    hints = _load_dict(args.hints, "--hints")
    overrides = _load_overrides(args.notebook_map)
    sidecars = load_sidecars(args.sidecars) if args.sidecars else []

    result = capture_workflow(
        plan,
        output_dir=args.out,
        notebook_roots=args.notebook_roots,
        notebook_overrides=overrides,
        alias_map=alias_map,
        hints=hints,
        sidecars=sidecars,
        build_crates=not args.skip_crates,
        default_notebook=args.default_notebook,
    )
    captured = sum(1 for record in result.records if record.status == "captured")
    total = len(result.records)
    print(
        f"Workflow '{plan.workflow_id}' captured {captured}/{total} nodes. Manifest: {result.manifest_path}"
    )


def cmd_workflow_import(args):
    manifest_path = Path(args.manifest).resolve()
    manifest = load_workflow_manifest(str(manifest_path))
    nodes = manifest.get("nodes", [])
    captured = [node for node in nodes if node.get("status") == "captured"]
    print(
        f"Workflow '{manifest.get('workflow', {}).get('id', '?')}' loaded: "
        f"{len(captured)}/{len(nodes)} nodes ready"
    )
    if not args.index:
        return

    base_dir = manifest_path.parent
    for node in captured:
        crate_ref = node.get("crate")
        if not crate_ref:
            continue
        crate_path = _resolve_manifest_path(base_dir, crate_ref)
        if not crate_path or not crate_path.exists():
            print(f"- {node.get('title')}: crate not found ({crate_path})")
            continue
        output_path = _format_index_output(args.index_output, node.get('id', 'node'))
        result = index_crate(
            str(crate_path),
            endpoint=args.index_endpoint,
            output_path=output_path,
        )
        prefix = f"- {node.get('title')}: "
        endpoint = result.get("endpoint")
        status = result.get("status")
        if endpoint and status is not None:
            print(f"{prefix}posted to {endpoint} (status {status})")
        else:
            print(f"{prefix}written to {result.get('output')}")


def main():
    parser = argparse.ArgumentParser(
        description="Build/visualize/validate RO-Crates from notebooks and workflows",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    pb = sub.add_parser("build", help="Create RO-Crate from a notebook")
    pb.add_argument("notebook", help="Path to notebook.ipynb")
    pb.add_argument("--out", default="output", help="Output directory (crate lives under <out>/ro-crate)")
    pb.add_argument("--aliases", help="YAML file mapping equivalent variable names")
    pb.add_argument("--hints", help="YAML file with roles/domain hints")
    pb.add_argument("--sidecars", nargs="*", help="JSON sidecar files with bridge hints")
    pb.add_argument("--config-file", dest="config_files", action="append", help="Environment/config file to include (repeatable)")
    pb.add_argument("--no-index", action="store_true", help="Skip index delta generation")
    pb.add_argument("--index-endpoint", help="SPARQL endpoint URL")
    pb.add_argument("--index-output", help="Override path for SPARQL update payload")
    pb.set_defaults(func=cmd_build)

    pv = sub.add_parser("vis", help="Visualize an existing RO-Crate")
    pv.add_argument("crate", help="Directory of RO-Crate")
    pv.add_argument("--lines", type=int, default=25, help="Number of code lines to show in panel")
    pv.add_argument("--html-tooltips", action="store_true", help="Render HTML tooltips (pyvis titles)")
    pv.add_argument("--no-panel", action="store_true", help="Skip custom hover panel")
    pv.set_defaults(func=cmd_vis)

    pval = sub.add_parser("validate", help="Validate an existing RO-Crate")
    pval.add_argument("crate", help="Directory of RO-Crate")
    pval.set_defaults(func=cmd_validate)

    if ENABLE_WORKFLOWS:
        pw = sub.add_parser("workflow", help="Workflow capture/import helpers (set CELLSCOPE_ENABLE_WORKFLOWS=1 to enable)")
        pw_sub = pw.add_subparsers(dest="workflow_cmd", required=True)

        pwc = pw_sub.add_parser("capture", help="Capture a multi-notebook workflow from a .naavrewf file")
        pwc.add_argument("workflow", help="Path to workflow .naavrewf file")
        pwc.add_argument("--out", default="out-lab/workflows", help="Directory where workflow assets are stored")
        pwc.add_argument("--notebook-root", dest="notebook_roots", action="append", help="Directory to search for node notebooks by title/source (repeatable)")
        pwc.add_argument("--notebook-map", help="YAML mapping of node ids/titles to explicit notebook paths")
        pwc.add_argument("--default-notebook", help="Fallback notebook path when a node cannot be resolved")
        pwc.add_argument("--aliases", help="YAML file mapping equivalent variable names")
        pwc.add_argument("--hints", help="YAML file with roles/domain hints")
        pwc.add_argument("--sidecars", nargs="*", help="JSON sidecar files with bridge hints")
        pwc.add_argument("--skip-crates", action="store_true", help="Capture metadata only (skip per-node crate build)")
        pwc.set_defaults(func=cmd_workflow_capture)

        pwi = pw_sub.add_parser("import", help="Load a stored workflow manifest and optionally index crates")
        pwi.add_argument("manifest", help="Path to workflow_manifest.json")
        pwi.add_argument("--index", action="store_true", help="Generate SPARQL deltas for captured nodes")
        pwi.add_argument("--index-endpoint", help="SPARQL endpoint URL")
        pwi.add_argument("--index-output", help="Output path or template (supports '{node}') for SPARQL payloads")
        pwi.set_defaults(func=cmd_workflow_import)

    args = parser.parse_args()
    if hasattr(args, "workflow_cmd") and not getattr(args, "workflow_cmd"):
        parser.error("workflow command requires a subcommand")
    args.func(args)


if __name__ == "__main__":
    main()
