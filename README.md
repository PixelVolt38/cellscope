# CellScope

CellScope makes the execution flow inside a Jupyter notebook observable and portable.  
It inspects every code cell, captures symbol definitions/uses and file hand‑offs,
and emits a cell-level graph as an RO‑Crate bundle enriched with PROV metadata.
The accompanying JupyterLab extension surfaces the capture in an interactive analyzer
panel and can push the resulting provenance graph to a SPARQL endpoint.

---

## Features

- **Notebook analysis**: track code cell functions, variables, file reads/writes,
  and file hand-offs inferred across cells.
- **Confirm-first export**: review and edit variable roles or per-file metadata before
  building an RO‑Crate. Edits persist for the current session and flow into the export.
- **RO‑Crate + PROV output**: write `ro-crate-metadata.json`, GraphML,
  and an offline PyVis HTML graph under `out-lab/<timestamp>/ro-crate/`.
- **SPARQL delta generation**: create an `INSERT DATA` update capturing crate contents.
  Optional push with configurable endpoint/auth, retries, and backoff.
- **JupyterLab analyzer panel**:
  - One-click Analyze / Export / Open Graph actions.
  - Searchable, faceted cell list (kernel, roles, file metadata).
  - Filters are presented in a dropdown popover (stays clear of the cell list), and
    the panel auto-refreshes after notebook saves/executions with a “pending” indicator.
- **CLI utilities**: `cellscope build` for headless crate generation and
  `cellscope vis` to rehydrate the PyVis HTML for an existing crate.

---

## Repository layout

- `cellscope/`: core capture, RO‑Crate builder, SPARQL indexer.
- `cellscope_server/`: Jupyter Server extension (`/cellscope/*` endpoints).
- `labextension/`: JupyterLab UI source and build assets.
- `examples/`: notebooks used for development and evaluation.
- `evaluation/`: validation artifacts (gold labels, user study, benchmarks).
- `exports/`: representative RO‑Crates (one per evaluation notebook).

---

## Prerequisites

- Python 3.9+ (use 64‑bit on Windows).
- Node.js + npm (required to build the JupyterLab extension).
  - Windows: `winget install OpenJS.NodeJS.LTS` (restart shell).
  - Debian/Ubuntu: `sudo apt-get install -y nodejs npm` (or NodeSource).

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

If you want the extension config written inside the virtualenv, set:
`$env:JUPYTER_CONFIG_DIR = "$env:VIRTUAL_ENV\\etc\\jupyter"` before enabling/listing.

## Quick Start (Linux/macOS)

```bash
cd /path/to/cellscope_platform
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .

# Enable the server extension once per virtualenv
export JUPYTER_CONFIG_DIR="$VIRTUAL_ENV/etc/jupyter"
python -m jupyter server extension enable cellscope_server

# Build/stage the labextension
cd labextension
npm install
npm run stage
cd ..

# Launch JupyterLab
python -m jupyterlab
```

Inside JupyterLab open the **CellScope Analyzer** panel (left sidebar) and run
`Analyze` / `Export Crate`. The export summary reports the crate folder and, if a
SPARQL endpoint is configured, the push status (HTTP result, attempts, duration).
Use **Settings** to set the SPARQL endpoint/auth and to add environment/config
files (e.g., `requirements.txt`, `pyproject.toml`, `environment.yml`); selected
files are bundled into the RO-Crate and parsed for dependency versions.

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

### Quick setup via helper scripts

- Edit `config/sparql.env` with your endpoint, auth token/credentials, and retry
  preferences. The file ships with local Fuseki defaults.
- **Windows**: `powershell -ExecutionPolicy Bypass -File scripts/jupyter_lab_with_sparql.ps1`
- **Linux/macOS**: `bash scripts/jupyter_lab_with_sparql.sh [optional-config-path]`

The scripts load the env file (if present), fall back to sane defaults, export
the `CELLSCOPE_*` variables, and run `jupyter lab` using the repository’s
virtual environment. Any extra arguments after the config path are forwarded to
JupyterLab.

---

## CLI Usage

```powershell
# Build a full crate for a notebook
.\.venv\Scripts\python.exe -m cellscope_cli build examples/test_notebook.ipynb --out out-lab

# Regenerate cell_graph.html for an existing crate
.\.venv\Scripts\python.exe -m cellscope_cli vis out-lab/<timestamp>/ro-crate

# Validate a crate (JSON-LD structure + required entities)
.\.venv\Scripts\python.exe -m cellscope_cli validate out-lab/<timestamp>/ro-crate
```

Each export creates a versioned directory under `out-lab/` containing the RO‑Crate,
GraphML, PyVis HTML, and the SPARQL delta.

## Testing

Automated backend/CLI smoke tests (run from repo root):

```bash
.venv_linux/bin/python scripts/run_full_test.py --clean
```

Manual UI checklist: see `docs/testing.md`.

### R analysis
CellScope uses an internal static analyzer for R cells; no external services are required for R capture.

### SPARQL graph naming
Indexing uses notebook-based graph URIs (slug + version) and issues a drop+insert so re-exports replace the same graph instead of creating duplicates.

---

## Development Notes

- **Labextension bundling**: run `npm run stage` after modifying files under
  `labextension/src/`. The command rebuilds the TS bundle and stages it into the
  active virtualenv so the next JupyterLab session picks it up.
- **Analyzer filters**: the filter dropdown is rendered via the Lumino widget tree.
  The button label reflects the number of active filters, and the popover closes on
  outside clicks. When adjusting UI code keep these behaviors intact.
- **Cell labels**: each cell inherits the slugified text of its first top-of-cell
  comment (e.g., `# climate data input` → `climate_data_input`). The label propagates
  through the analyzer UI, the RO-Crate activities, and SPARQL triples so downstream
  consumers see stable names instead of `Cell 0`, `Cell 1`, etc.
- **Metadata serialization**: the indexer now emits `schema:roles` on activities
  and `schema:roleName` on variables in addition to file MIME/tags.
  (confirm-first persistence, manual refresh controls, richer SPARQL telemetry,
  sidecar metadata editing, and improved non-Python analyzers).

---

## Troubleshooting

- **Node shim on Windows**: ensure `where node` resolves to `C:\Program Files\nodejs\node.exe`
  (avoid `WindowsApps\node.exe`) before running `npm run stage`.
- **Server extension not found**: verify the module import with
  `python -c "import importlib.util; print(importlib.util.find_spec('cellscope_server'))"`,
  and reinstall with `pip install -e .` if needed.
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

---

## License

Apache License 2.0. See `LICENSE`.
