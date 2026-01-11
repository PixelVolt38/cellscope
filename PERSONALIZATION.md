# CellScope Personalization Guide

CellScope is a skeleton meant to be adapted to your domain. This guide shows
exactly where to plug in your own metadata, vocabularies, UI fields, and
analysis rules. It is written for adopters who want a reliable, repeatable
way to tailor the tool without rewriting the core.

If you only do one thing: use the review dialog and the metadata config file
(`CELLSCOPE_METADATA_CONFIG`). That already covers most customization needs.

---

## 1) Personalization layers (pick your depth)

1. **No-code (user settings + review dialog)**
   - Users enter roles and file metadata at export time.
   - Settings panel lets you switch data source, set SPARQL endpoint, and
     bundle environment config files.

2. **Low-code (config files + hints JSON)**
   - Add new metadata fields by configuration instead of editing code.
   - Provide `hints` JSON/YAML in CLI or server payloads.

3. **Code-level (extend capture + UI + SPARQL mapping)**
   - Add new capture heuristics or fields that do not exist today.
   - Add new UI inputs and list filters.
   - Map new fields into RO-Crate and SPARQL triples.

---

## 2) The metadata flow (where to hook in)

```
User input (review dialog or hints)  ->  RO-Crate entities  ->  SPARQL triples
            (labextension)                (rocrate_io)           (indexer)
```

- **UI inputs** go into `hints` on export.
- `cellscope/rocrate_io.py` attaches `hints` to crate entities.
- `cellscope/indexer.py` converts those fields into RDF predicates.

This flow is intentionally additive. You can add new fields without breaking
existing consumers.

---

## 3) No-code personalization (recommended starting point)

### 3.1 Review dialog (roles and file metadata)

When you click Export, the review dialog lets users set:
- **Variable roles**: `roles[var] = "feature"` or `"parameter"`.
- **File metadata**: `encodingFormat`, `keywords`, `accessURL`, `etag`,
  `retrievedAt`, `dateModified` (all stored on file entities).

These values become `hints` and are stored in the RO-Crate and SPARQL.

### 3.2 Settings panel

The settings dialog lets users configure:
- SPARQL endpoint + auth (token or basic)
- retries/backoff, output path for SPARQL deltas
- data source (local or SPARQL)
- environment/config files to include in the crate

Those config files are copied into `env/` and parsed for dependency
names/versions. This is how you include `requirements.txt`, `pyproject.toml`,
`environment.yml`, `Pipfile.lock`, etc.

### 3.3 Environment variables

Common knobs (all optional):
- `CELLSCOPE_METADATA_CONFIG` -> JSON mapping for custom predicates
- `CELLSCOPE_SPARQL_ENDPOINT`, `CELLSCOPE_SPARQL_TOKEN`, `CELLSCOPE_SPARQL_USER`,
  `CELLSCOPE_SPARQL_PASSWORD`
- `CELLSCOPE_SPARQL_RETRIES`, `CELLSCOPE_SPARQL_BACKOFF`, `CELLSCOPE_SPARQL_TIMEOUT`
- `CELLSCOPE_SPARQL_OUTPUT` (write delta to file)
- `CELLSCOPE_SNIPPET_LINES` (how many lines in code snippets)

---

## 4) Low-code personalization (config files + hints)

### 4.1 Add fields with `CELLSCOPE_METADATA_CONFIG`

Create a JSON file and point to it:

```bash
export CELLSCOPE_METADATA_CONFIG=/path/to/metadata_config.json
```

Example config:

```json
{
  "file_fields": [
    {"key": "classification", "predicate": "schema:category"},
    {"key": "sensitivity", "predicate": "https://example.org/vocab#sensitivity"}
  ],
  "variable_fields": [
    {"key": "unit", "predicate": "https://qudt.org/schema/qudt/unit"}
  ]
}
```

How it works:
- `file_fields` are read from file entity properties and turned into triples.
- `variable_fields` are read from variable entities (`#var-...`).
- If you use a custom predicate URI, no extra code is required.

### 4.2 Provide `hints` directly (CLI or server)

Structure (YAML or JSON):

```yaml
roles:
  threshold: parameter
  df: dataset

# File metadata by basename
# Keys here are attached to file entities and used in the UI
# and SPARQL.
domains:
  climate_readings.csv:
    encodingFormat: text/csv
    keywords: [climate, sensor]
    accessURL: https://example.org/datasets/climate_readings.csv
    etag: "W/\"abc123\""
    retrievedAt: "2025-01-20T10:00:00Z"
    dateModified: "2025-01-15T12:00:00Z"
```

In CLI usage, pass this file as `--hints`. In the JupyterLab flow, the review
panel produces the same structure automatically.

### 4.3 Sidecars (optional extra entities)

If your domain needs extra objects (e.g., instruments, protocols, or external
registries), use sidecars. Each sidecar becomes a context entity linked via
`prov` and `oflow` relations.

Example sidecar:

```json
{
  "@id": "https://example.org/instrument/CTD-42",
  "@type": "https://example.org/vocab#Instrument",
  "name": "CTD-42",
  "manufacturer": "Acme Instruments"
}
```

Sidecars are passed through the export payload or CLI and stored in the crate
and SPARQL graph.

---

## 5) Code-level personalization (when you need new fields)

### 5.1 Add new UI inputs

File: `labextension/src/index.ts`
- Extend the review dialog inputs.
- Add fields to the `hints` object that is sent to `/cellscope/export`.
- Update filters if you want the field to be searchable/faceted.

### 5.2 Store new fields in RO-Crate

File: `cellscope/rocrate_io.py`
- Attach your new fields to **cell**, **variable**, or **file** entities.
- If you need RDF resolution, add the predicate in
  `CELLSCOPE_METADATA_CONFIG` or add a full URI.

### 5.3 Publish new fields to SPARQL

File: `cellscope/indexer.py`
- Update triple extraction to include your new fields.
- If you already used `CELLSCOPE_METADATA_CONFIG`, no code changes are needed.

### 5.4 Keep local vs SPARQL parity

Any new metadata you add must be surfaced in:
- RO-Crate JSON-LD (local mode)
- SPARQL summary reconstruction (SPARQL mode)
- Analyzer list filters (if you want to filter on it)

The goal is: analyze once, store once, show everywhere.

---

## 6) Personalize capture rules

### 6.1 Python capture

File: `cellscope/ast_capture.py`
- Add new file I/O functions or patterns to `_collect_file_io`.
- Extend `_collect_python_defs` to support additional definition patterns.
- Add or modify call detection if your domain has custom function calls.

### 6.2 R capture

File: `cellscope/containerizer_adapter.py`
- Extend the lists for `read_*` and `write_*` calls.
- Add new argument names for paths (e.g., `path`, `destfile`, `url`).

Both parsers are static and are designed to be extended incrementally.

---

## 7) Customize graph and list presentation

### 7.1 Graph style

File: `cellscope/visualize.py`
- Node styling, grouping, and popup panels are defined here.
- You can change shapes, colors, and which metadata appears in the tooltip.
- Both local and SPARQL graphs use the same renderer, so changes apply to both.

### 7.2 Analyzer list and filters

File: `labextension/src/index.ts`
- Add fields to the list renderer.
- Add new filter facets (e.g., classification, domain, dataset category).
- Keep filter state persisted in localStorage for per-notebook preferences.

---

## 8) Customize storage and outputs

- **Graph naming/versioning**: adjust in `cellscope/indexer.py` (graph URI
  format and version counter).
- **Output layout**: `cellscope/rocrate_io.py` controls where cells/files/env
  are copied.
- **SPARQL behavior**: update retry/backoff defaults or add new endpoints in
  `cellscope/indexer.py` and the settings dialog.

---

## 9) Personalization recipes

### Recipe A: Domain-specific dataset catalog

Goal: store dataset classification and license.

1) Add fields in the review dialog (classification, license).
2) Store values on file entities in `rocrate_io.py`.
3) Map them to RDF using `CELLSCOPE_METADATA_CONFIG`:

```json
{
  "file_fields": [
    {"key": "classification", "predicate": "schema:category"},
    {"key": "license", "predicate": "schema:license"}
  ]
}
```

### Recipe B: Regulated data workflows

Goal: track sensitivity and data handling rules.

- Add `sensitivity` and `handlingPolicy` fields in the UI.
- Store them on file entities and map to custom predicates.
- Add filters in the analyzer so users can quickly isolate restricted assets.

### Recipe C: Multi-team SPARQL catalog

Goal: centralize results across notebooks.

- Set `CELLSCOPE_SPARQL_ENDPOINT` in the environment or settings dialog.
- Use SPARQL data source in the panel.
- Ensure all added metadata fields are mapped in SPARQL so remote queries
  reflect the same detail as local mode.

---

## 10) Personalization checklist (before delivery)

- [ ] Do new metadata fields appear in the review dialog?
- [ ] Are the fields written into RO-Crate entities?
- [ ] Are the fields mapped into SPARQL triples?
- [ ] Do local and SPARQL modes show the same metadata?
- [ ] Are new fields searchable/filterable in the list if needed?
- [ ] Are config files (requirements, env) bundled if reproducibility matters?

---

## 11) Where to edit (quick map)

- UI: `labextension/src/index.ts`
- RO-Crate: `cellscope/rocrate_io.py`
- SPARQL mapping: `cellscope/indexer.py` + `cellscope/personalization.py`
- Python capture: `cellscope/ast_capture.py`
- R capture: `cellscope/containerizer_adapter.py`
- Graph rendering: `cellscope/visualize.py`

Keep changes additive and documented. If you introduce a new vocabulary or
metadata field, record it in this guide so other teams can extend it safely.
