# CellScope Customization Guide

CellScope is designed as a skeleton that adopters can extend without forking the core. This guide lists the hook points to add or change metadata, vocabularies, and provenance fields.

## Metadata flow (UI → crate → indexer)
1) **Collect**: Add fields to the review dialog (labextension) so users can enter custom metadata. Pass them through the export payload as additional keys under `hints`.
2) **Attach**: In `cellscope/rocrate_io.py`, attach those keys to the relevant entities (cells, variables, files) and, if you want resolvable RDF, add context terms or use existing vocab prefixes.
3) **Publish**: In `cellscope/indexer.py`, map your crate keys to RDF predicates so they appear in SPARQL triples.
4) **Consume**: Downstream tools can read the JSON-LD or the SPARQL graph; keep additions additive so existing consumers keep working.

## Examples of customizable fields
- Variable roles: `hints.roles[var] = "algorithm"` → stored on activities as `roles` and emitted as `schema:roles`.
- File metadata: `encodingFormat`, `keywords`, `accessURL`, `etag`, `retrievedAt`, `dateModified` (remote fetch optional), all attached to file entities.
- Sidecars/domain objects: add via the export payload; they become context entities linked with `oflow:hasInput/Output` and `prov:used/wasGeneratedBy`.

## Adding a new metadata field
1) **Front-end**: Add an input in the review form and include it in the `domains` map with your chosen key (e.g., `myOrg:classification` or `classification`). For quick wins, reuse existing text inputs (tags, source URL, etag, retrievedAt) or add new ones.
2) **Crate builder**: In `build_rocrate`, copy the key onto the target entity; if using a custom prefix, extend the crate context so it resolves (or use full URIs).
3) **Indexer**: Map the key to an RDF predicate so it survives SPARQL export. You can now do this without code edits via `CELLSCOPE_METADATA_CONFIG` (see below).

## Remote datasets
- HTTP(S) paths are captured as file artifacts with `accessURL`; optional auto-metadata (ETag/Last-Modified, retrieved time) is added when `CELLSCOPE_FETCH_REMOTE_METADATA` is set and `requests` is available.
- Users can override/add `accessURL`, `etag`/version, `retrievedAt`, and `encodingFormat` in the review UI.

## Config-driven mapping (no code changes)
You can provide a JSON config to map crate fields to RDF predicates without touching code. Set:
```
export CELLSCOPE_METADATA_CONFIG=/path/to/metadata_config.json
```
Structure:
```json
{
  "file_fields": [
    {"key": "classification", "predicate": "schema:category"},
    {"key": "myOrg:foo", "predicate": "https://example.org/vocab#foo"}
  ],
  "variable_fields": []
}
```
Defaults cover `encodingFormat`, `keywords`, `accessURL`, `etag`, `retrievedAt`, `dateModified`; any additional `file_fields` will be emitted as triples using the provided predicates.

## JupyterLab settings panel
The CellScope panel includes a Settings dialog where you can set:
- SPARQL endpoint + auth (token or basic), retries/backoff, and an optional index output path.
- Data source preference (local capture vs SPARQL) and a test button to list remote graphs.
Preferences are stored per-user in `localStorage` and are sent with export requests when filled.

## Runtimes and extensibility
- Python capture: extend AST heuristics in `ast_capture.py` to recognize new file I/O patterns or magics.
- R capture: extend call lists in `containerizer_adapter.py` for additional read/write functions; remote URLs are preserved.
- Workflows: workflow support is gated; keep defaults off for portability, but you can re-enable or replace with your own orchestration.

Keep changes additive: prefer adding keys/context terms over modifying existing ones, so downstream consumers continue to work. Document your custom fields and vocabularies for your team.***
