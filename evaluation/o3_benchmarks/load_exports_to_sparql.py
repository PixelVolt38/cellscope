#!/usr/bin/env python3
"""Load RO-Crates from exports/ into a SPARQL endpoint."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cellscope import index_crate


def _find_crates(root: Path) -> List[Path]:
    return sorted(path for path in root.rglob("ro-crate") if path.is_dir())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exports", default="exports")
    parser.add_argument("--endpoint", default="http://localhost:3030/cellscope/update")
    parser.add_argument("--token", default="")
    parser.add_argument("--user", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--out", default="evaluation/o3_benchmarks/index_results.json")
    args = parser.parse_args()

    exports_root = Path(args.exports)
    crates = _find_crates(exports_root)
    if not crates:
        raise SystemExit(f"No crates found under {exports_root}")

    headers = {"Authorization": f"Bearer {args.token}"} if args.token else None
    auth = (args.user, args.password) if args.user or args.password else None

    results: List[Dict[str, Any]] = []
    for crate_dir in crates:
        result = index_crate(
            crate_dir=str(crate_dir),
            endpoint=args.endpoint,
            headers=headers,
            auth=auth,
        )
        result["crate"] = str(crate_dir)
        results.append(result)

    Path(args.out).write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
