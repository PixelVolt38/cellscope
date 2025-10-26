#!/usr/bin/env python
import argparse
from roshow.ast_capture import parse_notebook
from roshow.cross_kernel import infer_cross_kernel_edges
from roshow.rocrate_io import build_rocrate
from roshow.visualize import visualize_rocrate
from roshow.validate_crate import validate_crate
from roshow.utils import load_yaml, load_sidecars

def cmd_build(args):
    aliases = load_yaml(args.aliases) if args.aliases else {}
    hints = load_yaml(args.hints) if args.hints else {}
    sidecars = load_sidecars(args.sidecars) if args.sidecars else []

    capture = parse_notebook(
        args.notebook,
        alias_map=aliases.get('aliases') if aliases else None,
        collect_materialized=True
    )
    # infer cross-kernel edges (SoS %get/%put) + file hand-offs
    xk_edges = infer_cross_kernel_edges(capture)
    # build RO-Crate (cells/variables/files; roles & domain hints; hashes)
    crate_dir = build_rocrate(
        capture,
        output_dir=args.out,
        xkernel_edges=xk_edges,
        hints=hints,
        sidecars=sidecars
    )
    print(f"RO-Crate written to {crate_dir}")

def cmd_vis(args):
    visualize_rocrate(
        args.crate,
        snippet_lines=args.lines,
        html_tooltips=args.html_tooltips,
        panel=not args.no_panel
    )

def cmd_validate(args):
    ok = validate_crate(args.crate, verbose=True)
    if not ok:
        raise SystemExit(2)

def main():
    parser = argparse.ArgumentParser(
        description='Build/visualize/validate RO-Crates from notebooks with cell-level provenance'
    )
    sub = parser.add_subparsers(dest='cmd', required=True)

    pb = sub.add_parser('build', help='Create RO-Crate from a notebook')
    pb.add_argument('notebook', help='Path to notebook.ipynb')
    pb.add_argument('--out', default='output', help='Output directory (crate will be <out>/ro-crate)')
    pb.add_argument('--aliases', help='YAML file mapping equivalent variable names')
    pb.add_argument('--hints', help='YAML file with roles and domain hints (units, cfStandardName, crs)')
    pb.add_argument('--sidecars', nargs='*', help='One or more JSON sidecar files with bridge hints')
    pb.set_defaults(func=cmd_build)

    pv = sub.add_parser('vis', help='Visualize an existing RO-Crate')
    pv.add_argument('crate', help='Directory of RO-Crate')
    pv.add_argument('--lines', type=int, default=25, help='Number of code lines to show in panel')
    pv.add_argument('--html-tooltips', action='store_true', help='Render HTML tooltips (pyvis titles)')
    pv.add_argument('--no-panel', action='store_true', help='Do not inject custom hover panel (use default tooltips only)')
    pv.set_defaults(func=cmd_vis)

    pval = sub.add_parser('validate', help='Validate an existing RO-Crate')
    pval.add_argument('crate', help='Directory of RO-Crate')
    pval.set_defaults(func=cmd_validate)

    args = parser.parse_args()
    args.func(args)

if __name__ == '__main__':
    main()
