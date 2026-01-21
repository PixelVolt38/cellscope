# CellScope Personalization Guide (Deep)

This guide explains how to tailor CellScope for a specific domain or VRE
without rewriting the core. It follows the actual code paths and data
contracts in this repository.

If you only do one thing: use the review dialog (roles + file metadata) and
optionally a metadata config file (`CELLSCOPE_METADATA_CONFIG`). That covers
most domain adaptation needs.

---

## 0) Mental model: where metadata flows

```
UI review dialog / CLI hints
        ↓
RO-Crate entities (rocrate_io)
        ↓
SPARQL triples (indexer)
        ↓
Analyzer list + graph (labextension / sparql_summary)
```

Personalization is additive: you can add metadata without breaking existing
parsers or consumers as long as you map it consistently across the pipeline.

---

## 1) No-code personalization (recommended start)

### 1.1 Review dialog (roles + file metadata)
In the JupyterLab UI, `Analyze` opens a review dialog before export.
Users can edit:
- Variable roles (free text): e.g., `parameter`, `feature`, `dataset`.
- File metadata:
  - `encodingFormat` (MIME type)
  - `keywords` (comma-separated)
  - `accessURL` (source URL for remote data)
  - `etag` (version tag)
  - `retrievedAt` (ISO 8601 timestamp)

These fields are stored under `hints` and then embedded in the RO-Crate and
SPARQL projection.

### 1.2 Settings dialog (SPARQL + config files)
Settings are stored in localStorage under `cellscope:config`:
- SPARQL endpoint and auth (token or basic auth)
- retry/backoff
- data source (`local` or `sparql`)
- environment/config files to package

Config files (e.g., `requirements.txt`, `pyproject.toml`, `environment.yml`)
are copied into `env/` and parsed into `softwareRequirements` entries.

---

## 2) Low-code personalization (config + hints files)

### 2.1 Hints file (CLI or programmatic export)
The CLI `build` command accepts a YAML/JSON hints file:

```yaml
roles:
  threshold: parameter
  df: dataset

domains:
  climate_readings.csv:
    encodingFormat: text/csv
    keywords: [climate, sensor]
    accessURL: https://example.org/data/climate_readings.csv
    etag: "W/\"abc123\""
    retrievedAt: "2025-01-20T10:00:00Z"
```

This structure matches what the UI generates.

### 2.2 Metadata mapping config (`CELLSCOPE_METADATA_CONFIG`)
`cellscope/personalization.py` loads a JSON file if the env var is set:

```bash
export CELLSCOPE_METADATA_CONFIG=/path/to/metadata_config.json
```

Current behavior:
- `file_fields` are mapped to RDF predicates in `cellscope/indexer.py`.
- `variable_fields` is parsed but **not used by default** (see below).

Example config:

```json
{
  "file_fields": [
    {"key": "encodingFormat", "predicate": "schema:encodingFormat"},
    {"key": "accessURL", "predicate": "dcat:accessURL"},
    {"key": "localPath", "predicate": "https://cellscope.dev/terms/localPath"},
    {"key": "sensitivity", "predicate": "https://example.org/vocab#sensitivity"}
  ],
  "variable_fields": [
    {"key": "unit", "predicate": "https://qudt.org/schema/qudt/unit"}
  ]
}
```

Important:
- File fields are read directly from file entities (`ro-crate-metadata.json`).
- Variable fields are **reserved**; to project them you must extend
  `cellscope/indexer.py` to read those fields from `#var-*` entities.

---

## 3) Code-level personalization (deep customization)

### 3.1 Add new metadata fields end-to-end
To add a new field that appears everywhere (RO-Crate, SPARQL, UI):

1) Add the field to the UI review dialog (optional):
   - `labextension/src/index.ts` in `_showReviewDialog()`.
2) Store it in hints (roles/domains or a new hints section).
3) Attach it to RO-Crate entities in `cellscope/rocrate_io.py`.
4) Project it in `cellscope/indexer.py` (or via `CELLSCOPE_METADATA_CONFIG`).
5) Surface it in the UI list/filters in `labextension/src/index.ts`.

This ensures parity between local mode and SPARQL mode.

### 3.2 Add a new object type (sidecars)
Use sidecar JSON entities for domain objects that are not code cells
(e.g., instruments, protocols, external registry entries).

Example sidecar:

```json
{
  "id": "https://example.org/instrument/CTD-42",
  "type": "Instrument",
  "name": "CTD-42",
  "producer": 3,
  "consumers": [5],
  "role": "instrument"
}
```

How it flows:
- Added by `rocrate_io.build_rocrate()`.
- Stored as a `ContextEntity`.
- Linked via `prov:wasGeneratedBy` or `prov:used`.
- Indexed by the SPARQL generator like any other entity.

### 3.3 Extend Python capture
Add new patterns in `cellscope/ast_capture.py`:
- Extend `_collect_file_io()` with new read/write APIs.
- Extend `_collect_python_defs()` for new definition patterns.
- Update label extraction in `_extract_cell_label()` if your notebooks
  use a different convention.

### 3.4 Extend R capture
`cellscope/containerizer_adapter.py` is regex-based:
- Add read/write functions to `READ_CALLS` and `WRITE_CALLS`.
- Add path argument names in `FILE_ARG_NAMES`.
- Update `KEYWORDS` if you see false positives.

---

## 4) Personalize graph and UI behavior

### 4.1 Graph style
`cellscope/visualize.py` controls the offline graph style:
- Node shapes and sizes
- Physics layout
- Popup panel HTML

The SPARQL graph handler (`/cellscope/sparql_graph`) injects the same
hover/click panel so local and SPARQL graphs stay consistent.

### 4.2 Analyzer list and filters
`labextension/src/index.ts` controls:
- Search highlighting and pinned exact matches
- Filter facets (kernel, roles, file metadata, edge via)
- Grouping by notebook label

Filter persistence is global:
- Key: `cellscope:filters:global`

Hints persistence is per notebook:
- Key: `cellscope:hints:<encoded notebook path>`

If you want per-notebook filters, modify `_filterStorageKey()`.

---

## 5) Storage and packaging knobs

### 5.1 Local path and file packaging
Files referenced by the notebook are handled in `rocrate_io.py`:
- Local file exists -> copied into `files/` and hashed.
- Local file missing -> entity still created with `cellscope:localPath`.
- Remote file URL -> `accessURL` stored; optional metadata retrieval.

### 5.2 Remote metadata and artifact downloads
These are opt-in:
- `CELLSCOPE_FETCH_REMOTE_METADATA=1` (HEAD request for etag + dateModified)
- `CELLSCOPE_FETCH_REMOTE_ARTIFACTS=1` (download into crate)
- `CELLSCOPE_REMOTE_MAX_BYTES` (size cap)

---

## 6) VRE customization example (VRE-agnostic)

Scenario: a virtual lab wants to track dataset sensitivity and instrument IDs.

1) Add fields to the review dialog or hints file:

```yaml
domains:
  readings.csv:
    sensitivity: restricted
```

2) Map that field into SPARQL:

```json
{
  "file_fields": [
    {"key": "sensitivity", "predicate": "https://example.org/vocab#sensitivity"}
  ]
}
```

3) Add an instrument sidecar:

```json
{
  "id": "https://example.org/instrument/CTD-42",
  "type": "Instrument",
  "name": "CTD-42",
  "producer": 2
}
```

This approach remains VRE-agnostic: you do not need any NaaVRE-specific
APIs or schema to integrate.

---

## 7) Testing your personalization changes

Recommended checks:
1) Run CLI export:
   `python -m cellscope_cli build <notebook> --out out-lab`
2) Inspect `ro-crate-metadata.json` for the new fields.
3) Run `cellscope_cli validate` on the crate.
4) If SPARQL indexing is enabled, verify the new predicate appears in the
   `index/last_update.sparql` output.
5) Confirm UI filters and graph panels show the new metadata.

---

## 8) Known limitations to keep in mind

- Static analysis only; dynamic path construction may be missed.
- R parser is heuristic and may miss advanced constructs.
- `variable_fields` in `CELLSCOPE_METADATA_CONFIG` are not projected by
  default; add code in `cellscope/indexer.py` if needed.
- File metadata hints are keyed by basename, not full path.

---

## 9) Quick reference: key files for customization

- Capture logic: `cellscope/ast_capture.py`, `cellscope/containerizer_adapter.py`
- RO-Crate mapping: `cellscope/rocrate_io.py`
- SPARQL mapping: `cellscope/indexer.py`, `cellscope/personalization.py`
- UI review dialog: `labextension/src/index.ts`
- Graph rendering: `cellscope/visualize.py`
