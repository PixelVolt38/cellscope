# CellScope Code Reference (Deep)

This document is the definitive, code-accurate map of the CellScope system.
It is written so another engineer (or thesis author) can reconstruct the
architecture, data flow, and control logic without reading the source.

All paths are repository-relative unless noted.

---

## 0) Repository map and module responsibilities

Core Python package:
- `cellscope/ast_capture.py`: parse notebooks, extract defs/uses, I/O, labels.
- `cellscope/containerizer_adapter.py`: internal static R parser (no external service).
- `cellscope/cross_kernel.py`: infer file handoff edges across cells.
- `cellscope/serialization.py`: convert capture to JSON for API/UI.
- `cellscope/rocrate_io.py`: build RO-Crate, copy artifacts, GraphML/HTML.
- `cellscope/indexer.py`: map RO-Crate JSON-LD to SPARQL INSERT DATA.
- `cellscope/visualize.py`: PyVis graph generation + HTML panel injection.
- `cellscope/personalization.py`: metadata mapping config (file field predicates).
- `cellscope/utils.py`: YAML/sidecar helpers.
- `cellscope/validate_crate.py`: minimal RO-Crate structural validation.

Server extension:
- `cellscope_server/handlers.py`: Jupyter Server endpoints (`/cellscope/*`).

JupyterLab extension:
- `labextension/src/index.ts`: analyzer panel, filters, settings, dialogs.
- `labextension/style/index.css`: UI styling.

CLI:
- `cellscope_cli/__main__.py`: `build`, `vis`, `validate` subcommands.

Evaluation assets:
- `evaluation/`: O1/O2/O3 validation material and results.
- `exports/`: representative RO-Crates generated from evaluation notebooks.

---

## 1) End-to-end pipeline (shared across CLI and UI)

High-level steps:
1) Capture notebook cells -> defs/uses/file I/O.
2) Infer cross-cell file handoffs (read-after-write).
3) Build RO-Crate with PROV + domain hints + config files.
4) Generate GraphML + PyVis HTML for visualization.
5) Render SPARQL UPDATE (optional POST to endpoint).

Reference entry points:
- CLI: `cellscope_cli/__main__.py` -> `parse_notebook` -> `build_rocrate` -> `index_crate`.
- Server: `cellscope_server/handlers.py` -> `/cellscope/analyze` and `/cellscope/export`.
- UI: `labextension/src/index.ts` -> `_runAnalysis()` + `_requestExport()`.

Minimal CLI flow:

```python
from cellscope.ast_capture import parse_notebook
from cellscope.cross_kernel import infer_cross_kernel_edges
from cellscope.rocrate_io import build_rocrate
from cellscope.indexer import index_crate

capture = parse_notebook("examples/multi_kernel_demo.ipynb", collect_materialized=True)
xedges = infer_cross_kernel_edges(capture)
crate_dir = build_rocrate(capture, "out-lab/demo", xedges, hints={}, sidecars=[], config_files=[])
index_crate(crate_dir, endpoint="http://localhost:3030/cellscope/update")
```

---

## 2) Data contracts

### 2.1 CellInfo (in-memory capture object)
Defined in `cellscope/ast_capture.py`.

Fields:
- `idx`: zero-based index among code cells.
- `position`: index in full notebook cell list (includes markdown).
- `kernel`: kernel name (from cell metadata or notebook kernelspec).
- `source`: raw cell source.
- `label`: slugified first comment line (auto-deduped).
- `funcs`: set of function names defined in cell.
- `func_calls`: set of function names called.
- `var_defs`: set of variable symbols defined.
- `var_uses`: set of variable symbols used.
- `file_writes`, `file_reads`: sets of file paths detected.

### 2.2 Capture dict
Returned by `parse_notebook()`.

```python
{
  "nb_path": "path/to/notebook.ipynb",
  "cells": [CellInfo, ...],
  "graph": {
    "edges": [ (u, v, {"type": "uses", "vars": {"x"}, "via": "ast"}), ... ]
  }
}
```

### 2.3 Graph JSON (API/UI shape)
Produced by `cellscope.serialization.capture_to_json()`.

```json
{
  "nb_path": "...",
  "cells": [
    {
      "idx": 0,
      "position": 3,
      "notebook": "...",
      "label": "climate_input",
      "name": "climate_input",
      "kernel": "python3",
      "funcs": ["compute_stats"],
      "func_calls": ["read_csv"],
      "var_defs": ["df"],
      "var_uses": ["threshold"],
      "file_writes": ["out/summary.json"],
      "file_reads": ["data/input.csv"]
    }
  ],
  "edges": [
    {"source": 0, "target": 1, "type": "uses", "vars": ["df"], "via": "ast"}
  ]
}
```

### 2.4 Review hints (export metadata)
Produced by the UI review dialog and sent to `/cellscope/export`.

```json
{
  "roles": {
    "threshold": "parameter",
    "df": "dataset"
  },
  "domains": {
    "climate_readings.csv": {
      "encodingFormat": "text/csv",
      "keywords": ["climate", "sensor"],
      "accessURL": "https://example.org/...",
      "etag": "W/\"abc\"",
      "retrievedAt": "2025-01-20T10:00:00Z",
      "dateModified": "2025-01-15T12:00:00Z"
    }
  }
}
```

### 2.5 UI configuration (localStorage)
Stored under `cellscope:config` in the JupyterLab extension.

```json
{
  "endpoint": "http://localhost:3030/cellscope/update",
  "token": "...",
  "username": "...",
  "password": "...",
  "retries": 2,
  "backoffSeconds": 1.5,
  "outputPath": "",
  "dataSource": "local" | "sparql",
  "configFiles": ["requirements.txt", "pyproject.toml"]
}
```

---

## 3) Capture subsystem

### 3.1 Python capture (`cellscope/ast_capture.py`)
Key steps in `parse_notebook()`:
- Reads the notebook with `nbformat.read(..., as_version=4)`.
- Kernel for a cell is `cell.metadata.kernel` if available, else notebook kernelspec name.
- Labels are derived from the first non-empty comment in the cell; duplicates are
  disambiguated by suffixing `_2`, `_3`, etc.
- Python AST parsing removes magics and shell escapes before `ast.parse`.

Def/Use heuristics:
- Definitions include assignment targets, augmented assigns, annotated assigns,
  `for` and `with` targets, exception handler names, walrus assignments, and
  comprehension targets.
- Uses are `ast.Name` nodes in Load context minus defs in the same cell.

File I/O heuristics:
- Maintains a mini env map for literal path assignments in the same cell.
- Resolves paths from literals, simple string concatenation, `os.path.join`,
  and `Path(...)`.
- Recognizes reads and writes by common method names (`read_csv`, `to_parquet`,
  `open_dataset`, `open`, etc.).

Alias normalization:
- Optional `alias_map` (YAML or dict) rewrites variable/function names so
  equivalent symbols unify in the graph.

Edge creation:
- Uses a `last_def` mapping. For each use of `v`, if a prior definition exists,
  add edge `(last_def[v] -> current_cell)` with `vars={v}`.

### 3.2 R capture (`cellscope/containerizer_adapter.py`)
A built-in R parser replaces any external containerizer dependency.
It is regex-based and static (no execution):
- Definitions from `<-`, `<<-`, `=`, and right assignment (`->`, `->>`).
- Uses from identifier tokens minus defs, keywords, member access, and
  package prefix (`pkg::fun`).
- Function defs: `name <- function(...)`.
- Function calls: `name(...)` minus defs/keywords, intersected with uses.
- File I/O: common read/write calls (`read.csv`, `readRDS`, `write.csv`,
  `saveRDS`, `download.file`, etc.) and named args like `file`, `path`, `url`.

### 3.3 Cross-kernel file handoff (`cellscope/cross_kernel.py`)
`infer_cross_kernel_edges()` links cells when a later cell reads a file that
an earlier cell wrote.
- Edge data: `{type: "uses", vars: {basename}, via: "file", file: full_path}`.

### 3.4 JSON serialization (`cellscope/serialization.py`)
`capture_to_json()` flattens `CellInfo` into the UI/API contract, ensuring
set fields are sorted and edges are JSON-safe.

---

## 4) RO-Crate build (`cellscope/rocrate_io.py`)

### 4.1 Output layout
Each export builds:

```
<out_dir>/ro-crate/
  ro-crate-metadata.json
  cell_graph.graphml
  cell_graph.html        # if pyvis is installed
  cells/
    cell_0.py
    cell_1.R
    ...
  files/
    <data artifacts>
  env/
    requirements.txt
    pyproject.toml
  index/
    last_update.sparql
```

### 4.2 Cells as Activities
Each code cell is written to `cells/cell_<idx>.<ext>`:
- Extension rules: `.R` for R kernels (`ir`, `r-`, `r`), `.py` for Python,
  otherwise `.txt`.
- RO-Crate entity: `@type = ["File", "ontoflow:Activity"]`.
- Properties include: `name`, `kernel`, `programmingLanguage`, `position`,
  `version`, `codeSnippet` (first `CELLSCOPE_SNIPPET_LINES`, default 25).
- Optional properties populated from hints: `roles`, `fileHints`, `funcCalls`.

### 4.3 Variables and functions
Variables become `#var-<name>` context entities:
- `@type = ontodt:Data` for data symbols.
- `@type = ontodt:Symbol` if the symbol is in the set of function defs.

Edges are added both ways:
- Definitions: Activity -> `oflow:hasOutput` and Variable -> `prov:wasGeneratedBy`.
- Uses: Activity -> `oflow:hasInput` and Activity -> `prov:used`.

### 4.4 File artifacts and packaging
For each `file_writes` or `file_reads` entry:
- Resolve to a local path relative to the notebook if possible.
- If the path is a URL, create a `File` entity with `accessURL` and optional
  metadata from HEAD requests.
- If a local file exists, copy into `files/` and compute blake2b hash.
- If the local file does not exist, still create a logical `File` entity and
  attach the original path via `cellscope:localPath`.

Environment/config files follow the same strategy and are stored under `env/`.

Remote file support (opt-in):
- `CELLSCOPE_FETCH_REMOTE_METADATA=1` enables HEAD requests to fill `etag` and
  `dateModified` (no download).
- `CELLSCOPE_FETCH_REMOTE_ARTIFACTS=1` downloads remote artifacts into the crate.
- `CELLSCOPE_REMOTE_MAX_BYTES` caps download size.

### 4.5 Environment/config parsing
Config files are parsed into `softwareRequirements` entries:
- `requirements.txt` / `requirements.in` (pip format).
- `environment.yml` / `.yaml` (conda dependencies).
- `pyproject.toml` (PEP 621 dependencies).
- `Pipfile.lock` (JSON lockfile).

Each dependency becomes a `SoftwareApplication` entity linked to the root dataset.

### 4.6 GraphML + PyVis
- GraphML is generated with NetworkX; nodes are cells, edges carry
  `label` (vars), `via`, and `type`.
- If PyVis is available, `visualize_rocrate()` generates HTML and injects
  the hover/click panel (`_inject_roshow_panel`).

---

## 5) SPARQL indexer (`cellscope/indexer.py`)

### 5.1 Graph URIs and dedup
- Default graph URI: `https://cellscope.local/graph/<slug>?v=<n>`.
- `<slug>` is derived from notebook stem; `<n>` is counted from sibling crates.
- Indexing drops the graph before re-inserting to avoid duplicates.

### 5.2 Triple mapping
The indexer walks `ro-crate-metadata.json` and emits:
- `rdf:type` for each entity type.
- `schema:name`, `schema:version`, `schema:position`, `schema:programmingLanguage`.
- `prov:used`, `prov:wasGeneratedBy`, `prov:wasDerivedFrom`, `prov:wasRevisionOf`.
- File metadata: `schema:encodingFormat`, `schema:keywords`, `schema:identifier` (etag),
  `schema:dateModified`, `prov:generatedAtTime`, `dcat:accessURL`.
- Custom fields from `CELLSCOPE_METADATA_CONFIG` (file fields only).
- `cellscope:localPath`, `cellscope:fileHints`, `cellscope:funcCalls`.
- Roles: activity `schema:roles` plus variable `schema:roleName` when role strings
  are `"var: role"`.

### 5.3 Configuration and env vars
Indexing supports:
- `CELLSCOPE_SPARQL_ENDPOINT`
- `CELLSCOPE_SPARQL_TOKEN`
- `CELLSCOPE_SPARQL_USER` / `CELLSCOPE_SPARQL_PASSWORD`
- `CELLSCOPE_SPARQL_OUTPUT`
- `CELLSCOPE_SPARQL_RETRIES`, `CELLSCOPE_SPARQL_BACKOFF`, `CELLSCOPE_SPARQL_TIMEOUT`

---

## 6) Visualization (`cellscope/visualize.py`)

- Uses PyVis with ForceAtlas2 physics.
- Adds a group node for the notebook (dot) and box nodes for cells.
- Each node stores `snippet` and `meta` fields used by the panel injection.
- `_inject_roshow_panel()` appends a floating HTML panel that shows:
  - Code snippet
  - Metadata list
  - Edge relation and `via` on edge click

The SPARQL graph handler (`/cellscope/sparql_graph`) uses the same panel injection
so local and SPARQL graph views match.

---

## 7) Jupyter Server extension (`cellscope_server/handlers.py`)

Endpoints:
- `POST /cellscope/analyze`
- `POST /cellscope/export`
- `POST /cellscope/export_cached`
- `POST /cellscope/index`
- `POST /cellscope/sparql_summary`
- `POST /cellscope/sparql_graph`

### 7.1 Analyze
Request:
```json
{"notebook": "path/to/notebook.ipynb", "aliases": {"aliases": {"a":"b"}}}
```
Response:
```json
{"graph": {"nb_path": "...", "cells": [...], "edges": [...]}}
```

### 7.2 Export
Request:
```json
{
  "notebook": "...",
  "out_dir": "out-lab/123",
  "hints": {"roles": {...}, "domains": {...}},
  "config_files": ["requirements.txt"],
  "index": {"endpoint": "http://...", "retries": 2}
}
```
Response:
```json
{
  "crate": "out-lab/123/ro-crate",
  "index": {"triples": 123, "status": 200, "attempts": 1}
}
```

### 7.3 Export cached
`/cellscope/export_cached` copies a previously built crate to a new output
folder. The UI uses this when a single-notebook analysis already generated
a crate in `out-lab/.analysis-cache`.

### 7.4 SPARQL summary
`/cellscope/sparql_summary` runs a SPARQL query to list graphs and pull only
a small predicate subset, then rebuilds a graph summary for the UI.
The handler normalizes:
- cell names, kernel, position, version
- defs/uses, file reads/writes, roles
- file metadata tokens (encodingFormat, keywords, accessURL, localPath)

Cross-notebook edges are inferred by shared file basenames.

### 7.5 SPARQL graph
`/cellscope/sparql_graph` renders a PyVis HTML graph from the SPARQL summary.
The HTML is written under `out-lab/sparql_<ts>/ro-crate/cell_graph.html`.

---

## 8) JupyterLab extension (`labextension/src/index.ts`)

### 8.1 Plugin wiring
The plugin registers commands:
- `cellscope:open-list` (analyzer panel)
- `cellscope:open-graph` (graph view)

The panel lives in the left sidebar and contains:
- header with Analyze / Export / Open Graph
- status and pending banners
- filter + results sections
- export summary

### 8.2 Analyze flow
`_analyze()` -> `_promptNotebookSelection()` -> `_runAnalysis("manual", notebooks)`.

Notebook selection is two-stage:
1) Folder picker: select root or specific folders to scan.
2) Notebook picker: choose notebooks from recursive scan.

Notebook scanning uses `contents.get(path, {content: true})` and skips:
`.git`, `.venv`, `node_modules`, `__pycache__`, `.ipynb_checkpoints`.

### 8.3 Manual vs auto analysis
- Manual: combines selected notebooks, shows review dialog, and (optionally)
  writes analysis crates to `out-lab/.analysis-cache` for export reuse.
- Auto: triggered on save/execution; debounced (400-1000ms) and uses the
  currently open notebook only.

When `dataSource = "sparql"`, auto analysis pulls from the SPARQL endpoint
instead of local parsing.

### 8.4 Review dialog
The review dialog builds a draft from the combined graph:
- Variables: from `var_defs` across all cells.
- Files: union of `file_reads` + `file_writes` basenames.

Users can edit:
- Variable roles (string labels).
- File metadata fields: encodingFormat, keywords, accessURL, etag,
  retrievedAt, dateModified.

Hints are stored in localStorage per notebook:
- `cellscope:hints:<encoded notebook path>`.

### 8.5 Export flow
- Export uses the *last analysis* + *last review*; if missing, export is blocked.
- For single-notebook analysis with cached crate, `/export_cached` is used.
- For multiple notebooks, each is exported to `out-lab/<ts>-<slug>`.
- When dataSource is `sparql` and endpoint configured, indexing is enabled.

### 8.6 Filters and search
- Filter state is stored globally: `cellscope:filters:global`.
- Filter dropdown includes kernel, roles, file metadata tokens, edge via,
  and read/write toggles.
- Search terms are highlighted in list results; exact object matches are
  pinned at the top with a summary of defs/uses and file paths.
- Filter changes emit `cellscope:filters-changed` with the serialized filter
  state plus `filteredCells` and `filteredEdges` counts.

### 8.7 Settings dialog
Settings are stored in `cellscope:config`:
- endpoint, auth token or basic auth, retries, backoff, output path
- data source (local vs sparql)
- env/config files to bundle (requirements.txt, pyproject.toml, etc.)

---

## 9) CLI (`cellscope_cli/__main__.py`)

Commands:
- `build <notebook>`: parse, build crate, optionally index.
- `vis <crate>`: generate HTML graph for existing crate.
- `validate <crate>`: run structural checks on RO-Crate JSON-LD.

Key flags for `build`:
- `--aliases`: YAML map of equivalent variable names.
- `--hints`: YAML file for roles/domains.
- `--sidecars`: JSON sidecar entities.
- `--config-file`: env/config file to include (repeatable).
- `--no-index`: skip SPARQL delta.

---

## 10) Configuration knobs

Environment variables:
- `CELLSCOPE_SPARQL_ENDPOINT`, `CELLSCOPE_SPARQL_TOKEN`, `CELLSCOPE_SPARQL_USER`, `CELLSCOPE_SPARQL_PASSWORD`
- `CELLSCOPE_SPARQL_OUTPUT`, `CELLSCOPE_SPARQL_RETRIES`, `CELLSCOPE_SPARQL_BACKOFF`, `CELLSCOPE_SPARQL_TIMEOUT`
- `CELLSCOPE_METADATA_CONFIG` (JSON config for file field -> predicate mapping)
- `CELLSCOPE_SNIPPET_LINES` (code snippet length)
- `CELLSCOPE_FETCH_REMOTE_METADATA` (HEAD remote artifacts)
- `CELLSCOPE_FETCH_REMOTE_ARTIFACTS` + `CELLSCOPE_REMOTE_MAX_BYTES`

---

## 11) Known limitations (code-level)

- Static analysis only; dynamic runtime behavior is not captured.
- Variable-driven file paths are under-approximated (unless literals
  or simple joins are used in a single cell).
- R parsing is regex-based and best-effort; unusual constructs may be missed.
- Cross-notebook links in SPARQL mode are inferred by basename, not by full path.
- File metadata hints in the review dialog apply to basenames, not full paths.

---

## 12) Where to extend

For full extension recipes, see `PERSONALIZATION.md`. Key extension points:
- Capture rules: `cellscope/ast_capture.py`, `cellscope/containerizer_adapter.py`.
- Metadata fields: review dialog + `cellscope/rocrate_io.py` + `cellscope/indexer.py`.
- SPARQL projection: `cellscope/indexer.py`.
- UI filters: `labextension/src/index.ts`.
- Graph styling: `cellscope/visualize.py`.
