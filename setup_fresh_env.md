# CellScope fresh install guide (Windows & Linux)

Use these steps on a clean machine to get the server extension and JupyterLab UI running end-to-end.

## Prerequisites
- Python 3.9+ (use 64‑bit on Windows).
- Node.js + npm (needed to build the lab extension).
  - Windows: `winget install OpenJS.NodeJS.LTS` (restart shell).
  - Linux (Debian/Ubuntu): `sudo apt-get install -y nodejs npm` or install from NodeSource.

## Create and activate a virtualenv
```bash
python -m venv .venv
.venv\Scripts\Activate.ps1 # Windows
source .venv/bin/activate # Linux
python -m pip install --upgrade pip
```

## Install CellScope (server + CLI)
```bash
python -m pip install --upgrade setuptools wheel
pip install .
```
Sanity check the server module imports:
```bash
python - <<'PY'
import importlib.util, sys
spec = importlib.util.find_spec("cellscope_server")
print(sys.executable)
print("cellscope_server:", spec.origin if spec else None)
PY
```

## Enable the server extension
Set the config dir to the venv so Jupyter writes configs there:
```bash
$env:JUPYTER_CONFIG_DIR = "$env:VIRTUAL_ENV\etc\jupyter" # Windows
export JUPYTER_CONFIG_DIR="$VIRTUAL_ENV/etc/jupyter" # Linux
python -m jupyter server extension enable cellscope_server
python -m jupyter server extension list --debug  # should show cellscope_server OK
```

## Build and stage the JupyterLab extension
```bash
cd labextension
npm install
npm run stage  # builds and stages into the active venv
cd ..
```

## Launch JupyterLab
```bash
# ensure config dir is set as above
python -m jupyter-lab
```
Terminal should log “CellScope server extension loaded”. In the UI, open a notebook and use the CellScope panel (Analyze/Export).

## Common issues
- “module not found” on enable: ensure `cellscope_server` exists under `<venv>/Lib/site-packages` (Windows) or `<venv>/lib/pythonX.Y/site-packages` and reinstall with `pip install .` if missing.
- No CellScope panel: Node/npm not installed or `npm run stage` not run. Install Node, re-run `npm install` + `npm run stage`, then restart JupyterLab.
- Wrong Jupyter binary: run `python -m jupyter ...` from the same venv or set `JUPYTER_CONFIG_DIR` as above.
