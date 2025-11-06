# CellScope

CellScope makes the execution flow inside a Jupyter notebook observable and portable.  
It inspects every code cell, captures symbol definitions/uses, file hand‑offs, and SoS
exchanges, and emits that graph as an RO‑Crate bundle enriched with PROV metadata.
The accompanying JupyterLab extension surfaces the capture in an interactive analyzer
panel and can push the resulting provenance graph to a SPARQL endpoint.

---

## Features

- **Notebook analysis**: track code cell functions, variables, file reads/writes,
  SoS `put/get`, and inferred cross‑kernel edges.
- **Confirm-first export**: review and edit variable roles or per-file metadata before
  building an RO‑Crate. Edits persist for the current session and flow into the export.
- **RO‑Crate + PROV output**: write `ro-crate-metadata.json`, GraphML,
  and an offline PyVis HTML graph under `out-lab/<timestamp>/ro-crate/`.
- **SPARQL delta generation**: create an `INSERT DATA` update capturing crate contents.
  Optional push with configurable endpoint/auth, retries, and backoff.
- **JupyterLab analyzer panel**:
  - One-click Analyze / Export / Open Graph actions.
  - Searchable, faceted cell list (kernel, roles, file metadata, SoS).
  - Filters are presented in a dropdown popover (stays clear of the cell list), and
    the panel auto-refreshes after notebook saves/executions with a “pending” indicator.
  - Quick action buttons jump to notebook cells.
- **CLI utilities**: `cellscope build` for headless crate generation and
  `cellscope vis` to rehydrate the PyVis HTML for an existing crate.

---

## Quick Start (Windows)

```powershell
# Clone / unpack CellScope (repo root shown as C:\path\to\cellscope_platform)
cd C:\path\to\cellscope_platform
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -e .

# Enable the server extension once per virtualenv
.\.venv\Scripts\python.exe -m jupyter server extension enable cellscope_server

# Build/stage the labextension
cd labextension
npm install
npm run stage       # bundles + stages to .venv/share/jupyter/labextensions/cellscope-lab
cd ..

# Launch JupyterLab with the extension
.\.venv\Scripts\jupyter-lab
```

Inside JupyterLab open the **CellScope Analyzer** panel (left sidebar) and run
`Analyze` / `Export Crate`. The export summary reports the crate folder and, if a
SPARQL endpoint is configured, the push status (HTTP result, attempts, duration).

---

## Optional: SPARQL Push Configuration

Exports always write `index/last_update.sparql`. To also POST the delta:

Set config in `jupyter_server_config.py` or via env vars before launching Lab:

```python
c.CellScope = {
    "endpoint": "http://localhost:3030/cellscope/update",
    "auth_token": "...",          # optional: bearer token
    "username": "...",            # optional: basic auth
    "password": "...",
    "output": "out-lab/index/last_update.sparql",
    "retries": 2,
    "backoff_seconds": 1.5,
    "timeout": 10.0,
}
```

Environment variable equivalents:

```
CELLSCOPE_SPARQL_ENDPOINT, CELLSCOPE_SPARQL_TOKEN,
CELLSCOPE_SPARQL_USER, CELLSCOPE_SPARQL_PASSWORD,
CELLSCOPE_SPARQL_OUTPUT, CELLSCOPE_SPARQL_RETRIES,
CELLSCOPE_SPARQL_BACKOFF, CELLSCOPE_SPARQL_TIMEOUT
```

For local testing, Apache Jena Fuseki can be started with
`java -jar fuseki-server.jar --mem /cellscope` and the endpoint set to
`http://localhost:3030/cellscope/update`.

---

## CLI Usage

```powershell
# Build a full crate for a notebook
.\.venv\Scripts\python.exe -m cellscope_cli build examples/test_notebook.ipynb --out out-lab

# Regenerate cell_graph.html for an existing crate
.\.venv\Scripts\python.exe -m cellscope_cli vis out-lab/<timestamp>/ro-crate
```

Each export creates a versioned directory under `out-lab/` containing the RO‑Crate,
GraphML, PyVis HTML, and the SPARQL delta.

---

## Development Notes

- **Labextension bundling**: run `npm run stage` after modifying files under
  `labextension/src/`. The command rebuilds the TS bundle and stages it into the
  active virtualenv so the next JupyterLab session picks it up.
- **Analyzer filters**: the filter dropdown is rendered via the Lumino widget tree.
  The button label reflects the number of active filters, and the popover closes on
  outside clicks. When adjusting UI code keep these behaviors intact.
- **Metadata serialization**: the indexer now emits `schema:roles` on activities
  and `schema:roleName` on variables in addition to file MIME/tags. Any future
  integrations (e.g., external containerizers) can rely on those triples.
- **Planned work**: see `AGENTS.md` / `docs/history/latest.md` for the current roadmap
  (confirm-first persistence, manual refresh controls, richer SPARQL telemetry,
  sidecar metadata editing, and improved non-Python analyzers).

---

## Troubleshooting

- **Node shim on Windows**: ensure `where node` resolves to `C:\Program Files\nodejs\node.exe`
  (avoid `WindowsApps\node.exe`) before running `npm run stage`.
- **Missing PyVis HTML**: install `pyvis` into the same virtualenv and re-run the export
  or `cellscope vis`.
- **500 errors during export**: check the notebook for unsupported kernels or unparseable
  cells. The server log will include the AST parsing trace.
- **SPARQL errors**: the analyzer status area reports HTTP failures; the export summary
  also captures attempts and duration. The SPARQL payload is still written to disk for
  manual replay.

---

## Roadmap / Future Integrations

- Persist confirm-first edits across sessions and add lightweight validation feedback.
- Provide a user-facing toggle to pause auto-refresh or clear the “pending” state after errors.
- Expose SPARQL configuration in the UI and capture telemetry for pushes.
- Extend sidecar/domain hints surfaced in the dialog and crate.
- Explore integration with external containerizers (e.g., NaaVRE) by publishing
  CellScope analysis artifacts via a shared adapter.
