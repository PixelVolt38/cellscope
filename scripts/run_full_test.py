#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from cellscope import (
    parse_notebook,
    infer_cross_kernel_edges,
    build_rocrate,
    index_crate,
    validate_crate,
)


EXAMPLE_CASES = [
    {
        "name": "multi_kernel_demo",
        "path": Path("examples/multi_kernel_demo.ipynb"),
        "expect_remote": False,
        "config_files": ["pyproject.toml"],
    },
    {
        "name": "exhaustive_python",
        "path": Path("examples/exhaustive_python.ipynb"),
        "expect_remote": False,
        "config_files": ["pyproject.toml"],
    },
    {
        "name": "exhaustive_r",
        "path": Path("examples/exhaustive_r.ipynb"),
        "expect_remote": True,
        "config_files": [],
    },
    {
        "name": "file_handoff_a",
        "path": Path("examples/file_handoff_a.ipynb"),
        "expect_remote": False,
        "config_files": [],
    },
    {
        "name": "file_handoff_b",
        "path": Path("examples/file_handoff_b.ipynb"),
        "expect_remote": False,
        "config_files": [],
    },
    {
        "name": "test_http_dataset",
        "path": Path("examples/test_http_dataset.ipynb"),
        "expect_remote": True,
        "config_files": [],
    },
]

LOCAL_PATH_IRI = "https://cellscope.dev/terms/localPath"


def log(message: str) -> None:
    print(message, flush=True)


def is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def expected_cell_extension(kernel: str) -> str:
    k = (kernel or "").lower()
    if k == "r" or k.startswith(("ir", "r-")) or k.startswith("r "):
        return ".R"
    if "python" in k or k.startswith("py"):
        return ".py"
    return ".txt"


def load_metadata(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def graph_index(metadata: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    graph = metadata.get("@graph") or []
    index: Dict[str, Dict[str, Any]] = {}
    for entity in graph:
        if isinstance(entity, dict) and "@id" in entity:
            index[str(entity["@id"])] = entity
    return index


def find_root_dataset(graph: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if "./" in graph:
        return graph["./"]
    for entity in graph.values():
        types = entity.get("@type")
        if isinstance(types, list) and "Dataset" in types:
            return entity
        if types == "Dataset":
            return entity
    return None


def entity_names(graph: Dict[str, Dict[str, Any]], prefix: str) -> Set[str]:
    names: Set[str] = set()
    for entity_id, entity in graph.items():
        if not entity_id.startswith(prefix):
            continue
        name = entity.get("name")
        if isinstance(name, str):
            names.add(name)
    return names


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def verify_crate(
    crate_dir: Path,
    capture: Dict[str, Any],
    config_files: List[str],
    expect_remote: bool,
) -> None:
    metadata_path = crate_dir / "ro-crate-metadata.json"
    graphml_path = crate_dir / "cell_graph.graphml"
    assert_true(metadata_path.exists(), f"Missing {metadata_path}")
    assert_true(graphml_path.exists(), f"Missing {graphml_path}")

    cells_dir = crate_dir / "cells"
    assert_true(cells_dir.is_dir(), "Missing cells directory")
    for cell in capture.get("cells", []):
        ext = expected_cell_extension(getattr(cell, "kernel", ""))
        cell_path = cells_dir / f"cell_{cell.idx}{ext}"
        assert_true(cell_path.exists(), f"Missing cell file {cell_path}")

    metadata = load_metadata(metadata_path)
    graph = graph_index(metadata)
    root = find_root_dataset(graph)
    assert_true(root is not None, "Root dataset missing")

    has_part = root.get("hasPart") or []
    has_part_ids = {part.get("@id") for part in has_part if isinstance(part, dict)}
    assert_true("cell_graph.graphml" in has_part_ids, "GraphML missing from hasPart")

    file_names = set()
    remote_urls = set()
    existing_local_files: Set[str] = set()
    nb_path = capture.get("nb_path")
    nb_dir = os.path.dirname(nb_path) if nb_path else ""
    for cell in capture.get("cells", []):
        for path in list(getattr(cell, "file_reads", [])) + list(getattr(cell, "file_writes", [])):
            if is_url(path):
                remote_urls.add(path)
            else:
                file_names.add(os.path.basename(path))
                abs_path = path if os.path.isabs(path) else os.path.normpath(os.path.join(nb_dir, path))
                if abs_path and os.path.exists(abs_path):
                    existing_local_files.add(os.path.basename(abs_path))

    crate_file_names = entity_names(graph, "files/")
    for name in file_names:
        assert_true(name in crate_file_names, f"File artifact missing from crate: {name}")

    files_dir = crate_dir / "files"
    if existing_local_files:
        assert_true(files_dir.exists(), "files/ directory missing for local artifacts")
        stored_files = {path.name for path in files_dir.iterdir() if path.is_file()}
        for name in existing_local_files:
            has_match = name in stored_files or any(entry.startswith(f"{name}_") for entry in stored_files)
            assert_true(has_match, f"Local file not copied into crate: {name}")

    if expect_remote:
        access_urls = {
            entity.get("accessURL")
            for entity in graph.values()
            if isinstance(entity, dict) and entity.get("accessURL")
        }
        assert_true(bool(access_urls), "Expected at least one accessURL entry")
        assert_true(any(url in access_urls for url in remote_urls), "Remote URL missing from crate")

    env_dir = crate_dir / "env"
    if config_files:
        assert_true(env_dir.exists(), "Config files were provided but env/ directory is missing")
        config_names = {Path(path).name for path in config_files}
        env_names = entity_names(graph, "env/")
        assert_true(config_names.issubset(env_names), "Config file entities missing from crate")
        software_reqs = root.get("softwareRequirements") or []
        assert_true(len(software_reqs) > 0, "softwareRequirements missing from root dataset")
    else:
        assert_true(not env_dir.exists() or not any(env_dir.iterdir()), "env/ directory should be empty")

    for entity in graph.values():
        if entity.get("@id", "").startswith(("files/", "env/")) and LOCAL_PATH_IRI in entity:
            assert_true(
                isinstance(entity.get(LOCAL_PATH_IRI), str),
                f"localPath should be string for {entity.get('@id')}"
            )


def run_case(
    name: str,
    notebook: Path,
    out_root: Path,
    config_files: List[str],
    expect_remote: bool,
) -> Path:
    log(f"[case] {name} -> {notebook}")
    capture = parse_notebook(str(notebook), collect_materialized=True)
    xedges = infer_cross_kernel_edges(capture)
    out_dir = out_root / name
    out_dir.mkdir(parents=True, exist_ok=True)
    crate_dir = Path(build_rocrate(
        capture,
        output_dir=str(out_dir),
        xkernel_edges=xedges,
        hints={},
        sidecars=[],
        config_files=config_files,
    ))
    verify_crate(crate_dir, capture, config_files, expect_remote=expect_remote)

    index_out = out_dir / "index" / "last_update.sparql"
    index_out.parent.mkdir(parents=True, exist_ok=True)
    index_result = index_crate(str(crate_dir), output_path=str(index_out))
    assert_true(index_out.exists(), f"Index output missing: {index_out}")
    assert_true(index_result.get("triples", 0) > 0, "Indexer returned zero triples")

    assert_true(validate_crate(str(crate_dir)), "RO-Crate validation failed")
    return crate_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Run CellScope full-stack smoke tests")
    parser.add_argument("--out", default="out-test", help="Output directory for test crates")
    parser.add_argument("--clean", action="store_true", help="Remove existing output directory before running")
    parser.add_argument("--skip-http", action="store_true", help="Skip HTTP dataset notebook")
    args = parser.parse_args()

    out_root = Path(args.out)
    if out_root.exists() and args.clean:
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    start = time.time()
    log("CellScope test run starting...")

    for case in EXAMPLE_CASES:
        name = case["name"]
        nb_path = case["path"]
        expect_remote = bool(case.get("expect_remote"))
        config_files = list(case.get("config_files") or [])
        if not nb_path.exists():
            log(f"[skip] {nb_path} not found")
            continue
        if args.skip_http and expect_remote:
            log(f"[skip] {name} (remote)")
            continue
        run_case(
            name,
            nb_path,
            out_root,
            config_files,
            expect_remote=expect_remote,
        )

    duration = time.time() - start
    log(f"CellScope tests completed in {duration:.1f}s.")
    log(f"Artifacts written to {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
