#!/usr/bin/env python
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, Optional

from cellscope.ast_capture import parse_notebook
from cellscope.cross_kernel import infer_cross_kernel_edges
from cellscope.rocrate_io import build_rocrate
from cellscope.visualize import visualize_rocrate
from cellscope.validate_crate import validate_crate
from cellscope.indexer import index_crate
from cellscope.utils import load_yaml, load_sidecars


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


def main():
    parser = argparse.ArgumentParser(
        description="Build/visualize/validate RO-Crates from notebooks",
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

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
