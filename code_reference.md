# CellScope Code Reference (Exhaustive)

This document is the end-to-end map of the CellScope codebase. It explains
modules, data contracts, control flow, and configuration so another engineer
(or thesis author) can reconstruct how the system works without reading code.

Scope covered:
- Capture (Python and R) -> cross-kernel inference -> RO-Crate build
- Indexing to SPARQL, graph naming/versioning, dedup rules
- Visualization (PyVis + GraphML) and the JupyterLab extension flows
- Personalization hooks, metadata vocabularies, env/config packaging
- CLI utilities and parity/testing tools

All paths are repository-relative unless noted.

---

## 1) Architecture at a Glance

Pipeline steps (shared by CLI and JupyterLab):
1. **Capture**: `cellscope.ast_capture.parse_notebook(nb_path, collect_materialized=True)` parses notebook code cells, extracts defs/uses, function defs/calls, and file I/O (Python AST + R static parser).
2. **Cross-cell/file inference**: `cellscope.cross_kernel.infer_cross_kernel_edges(capture)` adds edges for file hand-offs across cells.
3. **Build RO-Crate**: `cellscope.rocrate_io.build_rocrate(capture, out_dir, xkernel_edges, hints, sidecars, config_files)` writes `ro-crate-metadata.json`, copies cells/files/env configs, emits GraphML and PyVis HTML.
4. **Index**: `cellscope.indexer.index_crate(crate_dir, endpoint=..., ...)` renders a SPARQL UPDATE (schema.org + PROV + OntoDT/OntoFlow + cellscope terms) and optionally POSTs to a triplestore.
5. **Visualize**: `cellscope.visualize.visualize_rocrate` (CLI) or `cellscope_server/handlers.py` (UI) renders HTML graphs; list/filters come from the same graph summary.

Storage layout per export: `out-lab/<ts>/ro-crate/` (cells, files, env, graphml/html, metadata) plus `out-lab/<ts>/index/last_update.sparql` (SPARQL delta). SPARQL pulls write to `out-lab/sparql_<ts>/ro-crate/cell_graph.html`.

Minimal end-to-end (CLI-equivalent) call flow:

```python
from pathlib import Path
from cellscope import ast_capture, cross_kernel, rocrate_io, indexer

nb = Path("examples/multi_kernel_demo.ipynb")
capture = ast_capture.parse_notebook(nb, collect_materialized=True)
xedges = cross_kernel.infer_cross_kernel_edges(capture)
crate_dir = rocrate_io.build_rocrate(
    capture,
    Path("out-lab/preview/ro-crate"),
    xedges,
    hints={},               # user hints (roles, domains, file overrides)
    sidecars=[],            # optional extra entities
    config_files=[],        # env/config files to package
)
indexer.index_crate(crate_dir, endpoint="http://localhost:3030/cellscope/update")
```

---

## 2) Data Model and Vocabularies

CellScope uses RO-Crate JSON-LD with these namespaces:
- `schema:` schema.org (name, description, encodingFormat, keywords, accessURL, text, version, position, isPartOf)
- `prov:` W3C PROV (used, wasGeneratedBy, generatedAtTime)
- `dcat:` DCAT (accessURL for datasets)
- `oflow:` OntoFlow (Activity, hasInput, hasOutput)
- `ontodt:` OntoDT (Data, Symbol)
- `cellscope:` https://cellscope.dev/terms/ (funcCalls, fileHints, localPath)

Entity mapping (in `ro-crate-metadata.json`):
- **Notebook cell**: `cells/cell_<idx>.<ext>` (`.py` or `.R`), `@type`: `["File", oflow:Activity]`, props: `name` (label), `kernel`, `programmingLanguage`, `position`, `version`, `codeSnippet`, optional `roles[]`, `fileHints[]`, `funcCalls[]`.
- **Variable / function**: `#var-<name>`, `@type`: `ontodt:Symbol` (functions) or `ontodt:Data` (others), `name`, `version`. Linked via `oflow:hasOutput`/`prov:wasGeneratedBy` (defs) and `oflow:hasInput`/`prov:used` (uses). Functions also carry `category=function`.
- **File artifact**: `files/<name>`, `@type`: `["File", ontodt:Data]`, `name`, optional `contentHash`, `encodingFormat`, `keywords`, `accessURL`, `etag` (identifier), `retrievedAt` (prov:generatedAtTime), `dateModified`. Added to root dataset `hasPart`.
- **Root Dataset (`./`)**: `name` (notebook filename), `description`, `license`, `softwareRequirements` (dependency list), `hasPart` (cells, files, graphml/html).
- **Graph files**: `cell_graph.graphml` and `cell_graph.html` entities, `@type`: `["File", graph:Graph]`.

Edge semantics:
- AST edges: `prov:used` + `oflow:hasInput` (uses), `prov:wasGeneratedBy` + `oflow:hasOutput` (defs).
- File edges are stored only in GraphML/HTML for visualization; the SPARQL summary reconstructs cross-notebook edges by shared basenames.

Graph URIs (SPARQL):
- Graph name: `https://cellscope.local/graph/<slug>?v=<n>` where `<slug>` is the notebook stem, `<n>` is an export counter. Each export drops and rewrites that graph to avoid duplicates.

---

## 3) Capture Subsystem

### 3.1 `cellscope/ast_capture.py`
- Reads `.ipynb` (nbformat v4) and iterates code cells.
- Kernel detection: `cell.metadata.kernel` (if provided) else notebook `kernelspec.name`; defaults to `python3`.
- Labels: first non-empty comment slugged (`# climate step` -> `climate_step`), used as `cell.name/label`.
- Python parsing:
  - Sanitizes magics/shell (`%`, `!`, `?`) before `ast.parse`.
  - Collects definitions from assignments, augassign, annotated assigns, for/with targets, exception handlers, walrus, comprehensions, imports, class/func names (incl. async).
  - Uses: all `ast.Name` loads minus defs.
  - Function defs: `FunctionDef` / `AsyncFunctionDef`; calls: any `Call` with `Name` func id, minus defs, intersect with uses.
  - File I/O: resolves literal paths from constants, names (using env map), `os.path.join`, pathlib, string concat (`+`) and path join (`/`), then inspects `open`, pandas/xarray/numpy `read_*`, `to_*`, `write_*`, `Path.write_*`, `Path.read_*`.
- R parsing (`ir`, `r-`, `r` kernels) via `containerizer_adapter.analyze_r_cell`:
  - Strips comments while preserving strings; handles `<-`, `<<-`, `=`, `->`, `>>=` assignments.
  - Collects defs, uses (skips package prefixes `pkg::fn` and member access `$`/`@`), function defs (`name <- function(...)`), calls, common read/write calls (read.csv/readRDS/read_feather/read_parquet/fread, write.csv/write_parquet/fwrite/saveRDS/download.file, etc.) using named or positional args (`file`, `path`, `destfile`, `url`).
- Edges: for each use, if `last_def[var]` exists, emit `(def_idx, use_idx, {'type': 'uses', 'vars': {var}})`.
- Output: `capture = {'nb_path', 'cells': [CellInfo], 'graph': {'edges': [...]}}`.

Key capture loop (Python) in practice:

```python
def parse_notebook(nb_path: Path, collect_materialized: bool = True) -> Capture:
    nb = nbformat.read(nb_path, as_version=4)
    for idx, cell in enumerate(code_cells(nb)):
        code = sanitize_magics(cell.source)
        tree = ast.parse(code)
        defs = collect_defs(tree)
        uses = collect_uses(tree) - defs
        files = detect_file_io(tree, code, env_map(build_env(nb_path)))
        yield CellInfo(
            idx=idx,
            kernel=kernel_for(cell),
            label=label_for(cell),
            var_defs=sorted(defs),
            var_uses=sorted(uses),
            file_reads=files.reads,
            file_writes=files.writes,
            func_defs=functions_from(tree),
            func_calls=function_calls_from(tree, uses),
        )
```

### 3.2 `cellscope/containerizer_adapter.py`
- In-process static R parser (no external service). Tokenizes R code to extract
  defs/uses/file I/O/function defs/calls. The legacy external containerizer URL
  is no longer used; the module name is kept for compatibility.

### 3.3 `cellscope/cross_kernel.py`
- Adds inferred edges beyond AST:
  - File hand-off: if cell A writes a normalized path also read by cell B, add `(A, B, {'type': 'file', 'vars': {basename}, 'via': 'file'})`.

### 3.4 `cellscope/serialization.py`
- Normalizes capture to JSON for API/UI: cells get `idx`, `label/name`, `kernel`, `funcs`, `func_calls`, `var_defs`, `var_uses`, `file_reads`, `file_writes`. Edges are flattened with `source/target`.

### 3.5 Workflow capture (`cellscope/workflow.py`)
- Parses `.naavrewf` (or JSON) describing nodes + edges.
- Notebook resolution order: explicit map overrides > declared notebook roots > best-effort search by stem/title.
- `capture_workflow` runs the same per-notebook pipeline, writing `out-lab/<ts>/workflow/<id>/nodes/<slug>/capture.json` and optional crates. Produces `workflow_manifest.json` with node statuses and crate paths.

---

## 4) RO-Crate Build (`cellscope/rocrate_io.py`)

Inputs: capture, inferred edges, user hints (roles/domains), sidecars, config files.

Behaviors:
- **Cells**: copy each cell to `cells/cell_<idx>.<ext>` (`.py` for Python, `.R` for R). Add as `File` + `oflow:Activity` with props: `name`, `kernel`, `programmingLanguage`, `position`, `version` (1), `codeSnippet` (first N lines, env `CELLSCOPE_SNIPPET_LINES`), optional `roles[]`, `fileHints[]`, `funcCalls[]`.
- **Variables/Functions**: `ContextEntity` `#var-<name>`, type `ontodt:Symbol` if it is in `function_symbols`, else `ontodt:Data`. Link: defs -> `oflow:hasOutput` + `prov:wasGeneratedBy`; uses -> `oflow:hasInput` + `prov:used`. Functions also set `category=function`.
- **Files**: For every read/write, create `File` entity with `name`, optional hash, and any domain hints. Copy existing local files into `files/` (unique names to avoid clashes). Add to root `hasPart`. Nonexistent paths still get logical `File` entities for provenance.
- **Edges for graph files**: accumulate AST + xkernel edges, merge duplicate `(u,v,via)` vars, emit GraphML with `label` (vars) and `via`. HTML graph uses same data.
- **Root dataset**: set `name` (notebook basename), `description`, `license` (CC0 default), `hasPart` (cells, files, graphml/html), `softwareRequirements` (parsed from env/config files). Env/config files are copied to `env/` and added as `File` entities; dependencies parsed from pyproject/requirements/lockfiles into `SoftwareApplication` items.
- **Sidecars**: optional ad-hoc entities (type/name) linked to producers/consumers with optional roles.
- **Output tree**: `ro-crate-metadata.json`, `cell_graph.graphml`, `cell_graph.html` (if PyVis), `cells/`, `files/`, `env/`, `index/last_update.sparql` (after indexing).

---

## 5) Indexing to SPARQL (`cellscope/indexer.py`)

Function: `index_crate(crate_dir, endpoint=None, output_path=None, base_uri=None, graph_uri=None, drop_legacy_graphs=True, ...)`

Steps:
1. Load `ro-crate-metadata.json`; determine `base_uri` (file:// of crate dir) and `root_name`.
2. Graph URI: `https://cellscope.local/graph/<slug>?v=<n>` (export counter). Always issues `DROP SILENT` on the graph and base URI to avoid duplicate graphs.
3. `_collect_triples` walks every entity and emits:
   - Types, name, version, checksum, encodingFormat, programmingLanguage, position, dateModified, keywords, accessURL (dcat), generatedAtTime (prov), identifier (etag), isPartOf, roles, roleName on `#var-` entities, funcCalls (cellscope:funcCalls), fileHints (cellscope:fileHints), prov relations (used/wasGeneratedBy/wasDerivedFrom/wasRevisionOf).
   - Custom predicates from `CELLSCOPE_METADATA_CONFIG` are merged.
4. `_render_sparql` renders prefixes (schema/prov/dcat/oflow/ontodt/cellscope) and INSERT DATA into the graph.
5. POST to endpoint if provided, with retries/backoff/timeouts controlled by env vars: `CELLSCOPE_SPARQL_ENDPOINT`, `CELLSCOPE_SPARQL_TOKEN`, `CELLSCOPE_SPARQL_RETRIES`, `CELLSCOPE_SPARQL_BACKOFF`, `CELLSCOPE_SPARQL_TIMEOUT`, `CELLSCOPE_SPARQL_OUTPUT` (write sparql file only).

Example emitted SPARQL (truncated):

```sparql
PREFIX schema: <https://schema.org/>
PREFIX prov:   <http://www.w3.org/ns/prov#>
PREFIX oflow:  <https://example.org/ontology/ontoflow#>
PREFIX ontodt: <https://example.org/ontology/ontodt#>
PREFIX cell:   <https://cellscope.dev/terms/>

DROP SILENT GRAPH <https://cellscope.local/graph/exhaustive_python?v=3>;
INSERT DATA {
  GRAPH <https://cellscope.local/graph/exhaustive_python?v=3> {
    <cells/cell_0.py> a schema:File, oflow:Activity ;
      schema:name "cell_0" ;
      schema:programmingLanguage "python3" ;
      schema:position 0 ;
      cell:funcCalls "compute_stats" .

    <#var-threshold> a ontodt:Data ;
      schema:name "threshold" ;
      prov:wasGeneratedBy <cells/cell_0.py> .

    <cells/cell_1.py> a schema:File, oflow:Activity ;
      prov:used <#var-threshold> .
  }
}
```

---

## 6) Graph Visualization (`cellscope/visualize.py`)

CLI helper used by `cellscope_cli vis` and the server:
- Loads crate; adds a notebook group node (dot) plus one box node per `ontoflow:Activity`.
- Builds snippet from cell file (first N lines), HTML-escapes, stores in `snippet`.
- Metadata panel is injected via `_inject_roshow_panel`: hover/click shows code + metadata; edges show relation + via.
- Edges loaded from GraphML; labels become `dep_label`, `via` is retained.
- Writes `cell_graph.html` and prints path. GraphML is always present for headless use.

---

## 7) Server Extension (`cellscope_server/handlers.py`)

Registered under `/cellscope` (see `.venv_linux/etc/jupyter/jupyter_server_config.d/cellscope_server.json`):

| Endpoint | Purpose |
| --- | --- |
| `POST /cellscope/analyze` | Capture + cross-kernel inference; returns JSON graph (cells, edges, file metadata). |
| `POST /cellscope/export` | Analyze + build crate + index (unless `no_index`). Payload accepts `notebook`, `out_dir`, `hints` (roles/domains), `config_files`, `aliases`. |
| `POST /cellscope/export_cached` | Rebuild crate HTML/graph from an existing crate. |
| `POST /cellscope/index` | Index an existing crate from disk or provided JSON-LD. |
| `POST /cellscope/sparql_summary` | Query triplestore for latest graph per notebook, return graph summary (cells/edges) reconstructed from triples. |
| `POST /cellscope/sparql_graph` | Same as summary but also renders PyVis HTML into `out-lab/sparql_<ts>/ro-crate/cell_graph.html`. |
| `POST /cellscope/workflow/capture` | Workflow orchestrator (optional feature flag). |

SPARQL summary internals:
- Lists graphs, groups by base (before `?v=`), selects the highest version.
- Fetches triples for predicates: type, name, text (snippet), roles, programmingLanguage, position, version, category, encodingFormat, keywords, identifier, dateModified, generatedAtTime, accessURL, fileHints, funcCalls, isPartOf, checksum, prov used/wasGeneratedBy.
- Reconstructs cells: defs/uses split by file-vs-var (checks checksum or file-like name), functions from `ontodt:Symbol`/category=function, func calls from `cellscope:funcCalls`, file metadata tokens from `fileHints` plus file entities' metadata.
- Edges: producer->consumer per data entity, deduped per (src,tgt), accumulate vars; cross-notebook heuristic links by shared basename when producer known.
- Graph labels: prefers dataset `name` in the same graph; else falls back to basename of graph URI.

---

## 8) JupyterLab Extension (`labextension/src/index.ts`)

Key UX commands:
- `cellscope:open-list` - opens the analyzer panel.
- `cellscope:open-graph` - opens the latest HTML graph in a main area widget.
- Settings dialog - endpoint, auth, retries/backoff, data source (local vs SPARQL), config file picker.

Panel flow:
1. **Analyze** (local mode): POST `/cellscope/analyze`. Stores `_lastAnalysis`, populates filters (kernels, via, roles, file hints). Shows list grouped by notebook, with functions, function calls, defs/uses, file reads/writes, roles, file metadata. Filters support search, kernel facet, require file read/write, via facet, roles, file metadata facets.
2. **Review dialog**: Lets user edit roles (`var -> role`) and file metadata (`encodingFormat`, `keywords`, `accessURL`, `etag`, `retrievedAt`) per basename. The result becomes `hints`.
3. **Export Crate**: POST `/cellscope/export` with notebook, out_dir, hints, config_files, index settings. Builds crate + SPARQL update (unless `skip index`). Uses analyze results already computed; export does not re-run analysis.
4. **Open Graph**: Opens `cell_graph.html` from the last export (local) or triggers `/cellscope/sparql_graph` (SPARQL mode). Graph uses the same style in both modes (box nodes + notebook group dot + roshow popup).
5. **SPARQL mode**: Analyzer/list/graph pull from `/cellscope/sparql_summary`/`sparql_graph`, showing latest version of every notebook in the triplestore. Analyze in SPARQL mode still runs local capture to update SPARQL, then reads back from SPARQL to display merged results.
6. **Workflow capture**: Optional (flagged by `cellscopeEnableWorkflows`); allows capturing multiple notebooks per workflow graph and staging crates.

Data source toggle:
- Local: uses `_lastAnalysis` from `/cellscope/analyze`, graph from local crate.
- SPARQL: uses `/cellscope/sparql_summary`/`sparql_graph`; falls back to local if endpoint fails.

Settings persistence: stored in localStorage (`cellscope:config`) and applied to all requests (`index` payload includes endpoint, auth, retries, backoff, output path).

Panel mechanics:
- Filter state is stored per-notebook in localStorage; the filter badge shows active counts.
- Auto-refresh runs on save/execute (debounced) with a pending indicator while results are stale.

Skeleton of the analyze action (TypeScript):

```ts
async function runAnalyze(notebookPath: string) {
  const url = URLExt.join(this._settings.baseUrl, "cellscope/analyze");
  const body = JSON.stringify({ notebook: notebookPath, configFiles: this._configFiles });
  const resp = await ServerConnection.makeRequest(url, {
    method: "POST",
    body,
    headers: { "Content-Type": "application/json" }
  }, this._settings);
  const summary = await resp.json();
  this._lastAnalysis = summary;
  this._renderList(summary);
  this._latestGraphUrl = summary.graph_html ?? null;
}
```

---

## 9) CLI Utilities

- `cellscope_cli build <notebook> --out <dir>`: runs capture + crate build (no UI).
- `cellscope_cli vis <crate>`: renders `cell_graph.html` if missing.
- `cellscope workflow capture ...` / `cellscope workflow import ...`: optional workflow helpers (only if `CELLSCOPE_ENABLE_WORKFLOWS=1`).
- `scripts/run_full_test.py --clean`: automated regression covering all sample notebooks (multi_kernel_demo, exhaustive_python, exhaustive_r, file_handoff_a/b, test_http_dataset), crate structure, env packaging, SPARQL delta generation, localPath correctness, R cell extensions.
- `scripts/check_parity.py`: compares local analyzer graph vs SPARQL summary. Example:
  ```
  .venv_linux/bin/python scripts/check_parity.py \
    --notebook examples/multi_kernel_demo.ipynb \
    --sparql-endpoint http://localhost:3030/cellscope/update
  ```

---

## 10) Personalization / Extensibility

- **Metadata config**: `cellscope/personalization.py` loads `CELLSCOPE_METADATA_CONFIG` (JSON) to add custom file/variable predicates. Defaults include `localPath`, `encodingFormat`, `keywords`, `accessURL`, `etag`, `retrievedAt`, `dateModified`.
- **Adding new fields**: Extend the review dialog (labextension) to collect values, pass them in `hints`, propagate through `build_rocrate` (store on entities, add `@context` if you need RDF), and map to triples in `indexer.py`. Add display/filter tokens in the panel if needed.
- **Graph naming/versioning**: slug is derived from notebook stem; version is an export counter to avoid overwriting historical HTML files while SPARQL drops/replaces the same graph.
- **Data source parity**: local and SPARQL summaries carry the same fields (funcs, func_calls, roles, file hints, snippets, position, kernel, file reads/writes, vars). If you add a new field, update both the crate (and indexer) and the SPARQL summary builder so the UI sees it in both modes.
- **Full guide**: see `PERSONALIZATION.md` for step-by-step recipes and customization checklists.

---

## 11) Testing and Quality

- Automated: `scripts/run_full_test.py --clean` (backend/CLI, no JupyterLab).
- Manual checklist: see `docs/testing.md` (panel flow, settings/env capture, R kernels, HTTP datasets, SPARQL mode, cross-notebook hand-off, error handling).
- Parity: `scripts/check_parity.py` to ensure SPARQL summaries reflect local analysis.

---

## 12) Key Paths and Files

Repository layout (top-level):

```
cellscope_platform/
- cellscope/                 # Python capture/export modules
- cellscope_cli/             # CLI entry point
- cellscope_server/          # Jupyter server extension
- labextension/              # TypeScript + staged labextension assets
- docs/                      # Architecture notes, history, thesis context
- examples/                  # Demo notebooks (ignored in git)
- out-lab/                   # Default output root for crates + workflow manifests
- virtual_labs/              # NaaVRE sample workflows + notebooks
```

Coding conventions:

- Python follows PEP8-ish style with type hints and small helpers.
- TypeScript uses ES2020 modules, Lumino widgets, and the JupyterLab plugin pattern.
- Configuration flows env vars -> CLI/UI flags -> hard-coded defaults.

- Core: `cellscope/ast_capture.py`, `cellscope/cross_kernel.py`, `cellscope/rocrate_io.py`, `cellscope/indexer.py`, `cellscope/visualize.py`, `cellscope_server/handlers.py`
- UI: `labextension/src/index.ts`, `labextension/buildutils/stage-to-venv.js`
- Docs: `docs/architecture/code_reference.md` (this file), `docs/architecture/multi_notebook_exports.md`, `docs/testing.md`
- Examples: `examples/*.ipynb`, `examples/data_outputs/*`
- Outputs: `out-lab/<ts>/ro-crate/*`, `out-lab/sparql_<ts>/ro-crate/cell_graph.html`

---

## 13) Minimal Code Landmarks

Capture entry point:
```python
from cellscope import parse_notebook, infer_cross_kernel_edges

capture = parse_notebook("examples/multi_kernel_demo.ipynb", collect_materialized=True)
capture["graph"]["edges"].extend(infer_cross_kernel_edges(capture))
```

Build + index:
```python
from cellscope import build_rocrate, index_crate

crate_dir = build_rocrate(capture, out_dir="out-lab/1234/ro-crate",
                          xkernel_edges=infer_cross_kernel_edges(capture),
                          hints={"roles": {"threshold": "parameter"}}, config_files=["pyproject.toml"])
index_crate(crate_dir, endpoint="http://localhost:3030/cellscope/update")
```

Server endpoints (see `cellscope_server/handlers.py`):
```python
@web.post("/cellscope/analyze")
def analyze(): parse_notebook(...); infer_cross_kernel_edges(...);

@web.post("/cellscope/export")
def export(): analyze(); build_rocrate(); index_crate();
```

JupyterLab data source toggle (simplified):
```ts
if (config.dataSource === "sparql") {
  const summary = await _requestSparqlSummary(); // POST /cellscope/sparql_summary
  this._render(summary.graph);
} else {
  const local = await _requestAnalysis(notebookPath); // POST /cellscope/analyze
  this._render(local.graph);
}
```

## 14) Key Environment Variables

| Variable | Purpose |
| --- | --- |
| `CELLSCOPE_METADATA_CONFIG` | JSON mapping for custom predicates (see `cellscope/personalization.py`). |
| `CELLSCOPE_SNIPPET_LINES` | Number of code lines stored in `codeSnippet`. |
| `CELLSCOPE_FETCH_REMOTE_METADATA` | If set, attempt HTTP HEAD to capture ETag/Last-Modified for remote URLs. |
| `CELLSCOPE_FETCH_REMOTE_ARTIFACTS` | If set, download remote artifacts into `files/`. |
| `CELLSCOPE_REMOTE_MAX_BYTES` | Max bytes for remote downloads (default is conservative). |
| `CELLSCOPE_SPARQL_ENDPOINT` | SPARQL `update` URL (e.g., `http://localhost:3030/cellscope/update`). |
| `CELLSCOPE_SPARQL_TOKEN` / `CELLSCOPE_SPARQL_USER/PASSWORD` | Authentication for SPARQL pushes. |
| `CELLSCOPE_SPARQL_OUTPUT` | Path to dump the last SPARQL delta (`index/last_update.sparql`). |
| `CELLSCOPE_SPARQL_RETRIES`, `CELLSCOPE_SPARQL_BACKOFF`, `CELLSCOPE_SPARQL_TIMEOUT` | Retry policy for the exporter. |
| `CELLSCOPE_ENABLE_WORKFLOWS` | Enables workflow CLI commands (default off). |
| `JUPYTER_CONFIG_DIR` (server) | Point to the active venv to avoid permission conflicts. |

---

## 15) Workflow Notes (optional)

- Workflow capture/import is optional and gated by `CELLSCOPE_ENABLE_WORKFLOWS=1`
  (CLI) plus the `cellscopeEnableWorkflows` JupyterLab page config (UI).
- `.naavrewf` files reference workflow nodes; capture resolves them to local
  notebooks when possible and writes manifests under
  `out-lab/workflows/<workflow-id>/workflow_manifest.json`.
- Use `--skip-crates` for metadata-only capture, then re-run with crates when
  notebooks are available.

---

## 16) Design Trade-offs (why it looks this way)

- **RO-Crate + PROV + DCAT**: uses standard JSON-LD so crates remain portable,
  queryable, and compatible with triple stores; OntoDT/OntoFlow carry symbols
  and activities.
- **Static analysis only**: avoids executing user notebooks for safety and
  reproducibility; relies on path/value heuristics plus optional user hints.
- **Graph rewrite per version**: each export drops and rewrites the named graph
  `https://cellscope.local/graph/<slug>?v=<n>` to prevent duplicate triples; a
  simple counter keeps ordering without diffing SPARQL.
- **Dual render assets**: PyVis HTML for interactive review in JupyterLab, plus
  GraphML for downstream tooling; both live in the crate for offline use.
- **Local vs SPARQL data sources**: local mode is fast/offline; SPARQL mode
  mirrors the same schema to support multi-notebook aggregation. The UI falls
  back to local on remote errors.
- **In-Python R parsing**: keeps dependencies minimal (no external R runtime or
  containerizer), using a tokenizer to reach parity with Python where possible.
- **Persist cell sources**: saves each cell as `.py`/`.R` inside the crate so
  previews and provenance stay self-contained.

## 17) Known Limitations and Future Work

- **Static parsing gaps**: runtime-computed paths, dynamic imports, or
  download-to-temp flows may be missed; a future guarded tracer could improve
  IO coverage.
- **R coverage**: tidy-eval, NSE-heavy code, and complex data.table chains are
  only partially captured.
- **Mixed kernels**: links rely on shared files; cross-kernel magics are not
  supported. Mixed-kernel links mostly rely on files.
- **Workflow scope**: workflow capture assumes `.naavrewf` inputs and is not a
  general workflow engine; use it when those assets are present.
- **Dataset versioning**: we record hashes/etag/timestamps when available but do
  not cache remote payloads; reproducibility depends on source stability.
- **Graph scale/readability**: dense notebooks/workflows can produce crowded
  PyVis layouts; auto-clustering and filtering in-graph are future work.
- **Triple store availability**: SPARQL mode requires a reachable endpoint;
  fallback to local cannot merge partial remote data.
- **Build toolchain**: Node is required to rebuild the labextension; staging
  copies into the venv is still manual via `npm run stage`.
- **Testing depth**: sample notebooks cover common IO; broader R notebooks and
  exotic Python IO libraries would improve confidence.

---

This reference is intentionally exhaustive. If you keep it nearby while working
on CellScope, you should be able to trace any feature, module, or triple back to
its spot in the repository and extend the system with confidence.
