# Validation Chapter Draft (examples/ corpus)

This document describes, in detail, the validation work carried out over the notebooks in `examples/`. It is written as a self-contained chapter draft and includes the full methodology, artifacts produced, and measured results. All results below are derived from actual runs in this repository and the files referenced are stored under `evaluation/`.

## 1) Scope and environment

Validation was run locally on the repository at `/path/to/repo` using the project’s Python environment at `./.venv_linux`. The validation steps are strictly static-analysis driven (no notebook execution). The core pipeline invoked is:

- `cellscope.ast_capture.parse_notebook` (per-cell defs/uses and file IO)
- `cellscope.cross_kernel.infer_cross_kernel_edges` (file hand-off edges)
- `cellscope.serialization.capture_to_json` (prediction payload)
- `cellscope.rocrate_io.build_rocrate` (RO-Crate export for indexing)
- `cellscope.indexer.index_crate` (SPARQL update payload generation and POST)

Any network or runtime behavior inside the notebooks was **not executed**. This is a static capture, which is appropriate for O1 coverage and O4 latency validation but not for runtime provenance.

### Reproducibility metadata

- **Repo commit:** `11dbcaa6f6161465cb36bc59fab1c0a6599a36c3`
- **OS:** `Linux 5.15.167.4-microsoft-standard-WSL2` (WSL2)
- **CPU:** AMD Ryzen 7 4800HS (8 cores / 16 threads)
- **Memory:** ~7.5 GiB available in WSL2 at time of runs
- **Python:** 3.12.3 (`./.venv_linux/bin/python`)
- **Timing notes:** runs are warm (same process, no cold-start measurements), no GPU acceleration, network excluded from O4 local timing.

### Notebook corpus

The notebooks were split into two classes to mirror validation intent:

**Synthetic test notebooks (controlled, ground-truth-friendly)**
- `examples/exhaustive_python.ipynb` — Python stress-test for defs/uses and file IO.
- `examples/exhaustive_r.ipynb` — R stress-test for defs/uses and file IO, includes URL download.
- `examples/multi_kernel_demo.ipynb` — cross-kernel hand-off via files (SoS magics removed; file hand-offs only).

**Real RAVL notebooks (virtual lab artifacts)**
- `examples/RAVL/RAVL.ipynb` — full virtual lab pipeline with API calls and MinIO integration.
- `examples/RAVL/RAVL_R_source.ipynb` — R-based visualization pipeline.
- `examples/RAVL/SecretsProvider_demo.ipynb` — secrets integration demo.
- `examples/RAVL/migrate_secrets.ipynb` — secrets migration helper.

The RAVL notebooks are real examples from a virtual lab and therefore contain richer code, complex IO, and external service usage. For coverage validation, they are included for realism and regression checking.

### Why mix synthetic and real notebooks?

The synthetic notebooks isolate specific constructs so recall/precision can be interpreted as unit-style quality signals. The RAVL notebooks provide ecological validity: they exercise real pipeline structure, IO, and third-party calls that expose practical limitations. Both are needed to avoid overstating performance on clean synthetic data.

### Key findings (headline)

- **Python coverage is strong** on the synthetic notebook (`exhaustive_python` is 1.00 F1 for defs/uses/edges).
- **R coverage lags**: missing `read.csv` and `$`-access patterns reduce recall in `exhaustive_r`.
- **Real notebook recall is moderate**: in `RAVL`, uses recall is ~0.53 and edges recall ~0.63, reflecting conservative static capture.
- **Kernel detection is a hard failure**: `RAVL_R_source` yields empty predictions because the kernel name is not recognized as R.
- **Variable-driven file IO and function args** remain systematic sources of false negatives.

## 2) O1 Coverage: methodology and artifacts

### 2.1 Prediction generation (model output)

For each notebook, predictions are generated using the static capture pipeline:

1. `parse_notebook(..., collect_materialized=True)`
2. `infer_cross_kernel_edges(capture)`
3. `capture_to_json(capture)`

This yields a per-cell structure containing:
- `var_defs`, `var_uses`
- `funcs`, `func_calls`
- `file_reads`, `file_writes`
- `edges` between defining and using cells

Predictions were written to:

- `evaluation/o1_coverage/gold_predictions/predicted_<notebook>.json`

### 2.2 Gold template construction

Gold templates were created for **every** notebook under `examples/`.

Two rule sets were used, both documented explicitly in the gold templates’ `notes` field:

1) **Python AST rule set** (for `RAVL`):
   - Definitions = assignment targets + imports + function/class names + **function parameters**.
   - Uses = `Name` loads not defined in the same cell.
   - File IO = literal/derivable paths from `open(...)`, `read_csv(...)`, `write_*` etc.

2) **R regex rule set** (for `RAVL_R_source`):
   - Definitions = left/right assignment targets and function definitions.
   - Uses = identifiers in expressions that are not defined in the same cell.
   - File IO = common read/write calls when literal or resolvable paths are present.

Manual labels were still applied for the synthetic notebooks and the smaller RAVL demos (`SecretsProvider_demo`, `migrate_secrets`) to reflect the intended gold standard.

**Gold label governance:** gold templates were authored by the project author using documented rules and then manually spot-checked against the notebook source. No second annotator or formal adjudication was used. This is a known limitation and is addressed in the Threats to Validity section.

Gold templates are stored in:

- `evaluation/o1_coverage/gold_templates/gold_template_<notebook>.json`

### 2.3 Coverage scoring

Coverage is computed by comparing gold vs. prediction sets:

- **Defs**: set of `(cell_idx, symbol)` pairs from `defs` vs. `var_defs`.
- **Uses**: set of `(cell_idx, symbol)` pairs from `uses` vs. `var_uses`.
- **Edges**: set of `(source_idx, target_idx, symbol)` pairs from `edges`.

Metrics: precision, recall, and F1 are computed for each of the three sets.

Results are stored in:

- `evaluation/o1_coverage/coverage_results_all.md`
- `evaluation/o1_coverage/coverage_results_all.json`

## 3) O1 Coverage: results (per notebook)

Below is the consolidated coverage output with key observations.

### 3.1 `exhaustive_python`

- defs: precision 1.0000, recall 1.0000, F1 1.0000
- uses: precision 1.0000, recall 1.0000, F1 1.0000
- edges: precision 1.0000, recall 1.0000, F1 1.0000

This is a controlled Python notebook and the static AST capture matches gold labels exactly.

### 3.2 `multi_kernel_demo`

- defs: precision 1.0000, recall 1.0000, F1 1.0000
- uses: precision 1.0000, recall 0.9412, F1 0.9697
- edges: precision 1.0000, recall 1.0000, F1 1.0000

Mismatch: one missing use in the R cell (`read.csv`). File hand-offs and cross-kernel edges were correctly captured.

### 3.3 `exhaustive_r`

- defs: precision 0.5000, recall 0.5000, F1 0.5000
- uses: precision 1.0000, recall 0.4545, F1 0.6250
- edges: precision 1.0000, recall 0.3333, F1 0.5000

Observed gaps come from the R parser:
- Missed `read.csv` and `write.csv` in uses.
- Missed symbol uses in expressions like `df$temperature`.
- Missed downstream dataflow edges where `df` is used in later cells.

### 3.4 `SecretsProvider_demo`

- defs: precision 1.0000, recall 1.0000, F1 1.0000
- uses: precision 0.6000, recall 0.6000, F1 0.6000
- edges: precision 1.0000, recall 1.0000, F1 1.0000

Mismatches:
- False positives for `str` (caused by annotated types being read as a use).
- Missed `SecretsProvider` and `param_KMNI_key_name` as uses in one cell.

### 3.5 `migrate_secrets`

- defs: precision 1.0000, recall 0.8462, F1 0.9167
- uses: precision 0.6667, recall 0.8000, F1 0.7273
- edges: precision 0.0000, recall 0.0000, F1 0.0000

Mismatches:
- Function arguments (`source_path`, `destination_path`) are not treated as defs by the AST capture and are instead treated as uses.
- File IO is not captured because the file paths are stored in variables and passed to `open` rather than literal strings.

### 3.6 `RAVL`

- defs: precision 0.9442, recall 0.7488, F1 0.8358
- uses: precision 0.9802, recall 0.5302, F1 0.6881
- edges: precision 1.0000, recall 0.6341, F1 0.7762

This notebook introduces many nested functions, parameterized calls, and external service interactions. The primary loss in recall is from:

- function parameters treated as defs in the gold rule set but not by the current parser;
- variable-driven file IO (paths constructed from variables rather than string literals).

### 3.7 `RAVL_R_source`

- defs: precision 0.0000, recall 0.0000, F1 0.0000
- uses: precision 0.0000, recall 0.0000, F1 0.0000
- edges: precision 0.0000, recall 0.0000, F1 0.0000

The model outputs are empty for this notebook because the kernel name is `conda-env-ravl-r`, which is not currently detected as R by the capture layer. The gold labels expose this as a kernel detection gap rather than a parser error.

## 4) O4 Latency: local analysis and export

### 4.1 Methodology

For each notebook under `examples/`, the following timing loops were executed:

- **Analyze**: `parse_notebook` + `infer_cross_kernel_edges` + `capture_to_json` (5 runs)
- **Export+index**: `parse_notebook` + `build_rocrate` + `index_crate` with no endpoint (3 runs)

This isolates local compute time without network overhead. Timing output is recorded as p50/p95/min/max in seconds.

### 4.2 Results

Results are stored in:

- `evaluation/o3_benchmarks/benchmark_results_examples.md`
- `evaluation/o3_benchmarks/benchmark_results_examples.json`

Highlights (P95 values):

- `RAVL`: analyze ~0.092s; export+index ~0.100s
- `multi_kernel_demo`: analyze ~0.0033s; export+index ~0.0295s
- `exhaustive_python`: analyze ~0.0022s; export+index ~0.0261s
- `exhaustive_r`: analyze ~0.0014s; export+index ~0.0221s

All runs are well below the draft O4 thresholds (P95 < 0.4s for 50 cells, < 2s for 100 cells).

## 5) O4 SPARQL latency (loaded store)

### 5.1 Indexing methodology

The Fuseki store was fresh (empty) at the start. For each notebook, a crate was exported to:

- `evaluation/crates/<notebook>/ro-crate`

Indexing used `index_crate` with `graph_uri` set to the notebook file URI (`file:///.../examples/<notebook>.ipynb`) so each notebook’s graph is stable and identifiable. Index results are stored in:

- `evaluation/o3_benchmarks/index_results_examples.json`

### 5.2 Query latency

Five query templates were executed 10 times each, and p50/p95/min/max were recorded:

- `list_graphs`
- `count_triples`
- `datasets_per_graph`
- `producers`
- `consumers`

Results are stored in:

- `evaluation/o3_benchmarks/sparql_latency_loaded_examples.md`
- `evaluation/o3_benchmarks/sparql_latency_loaded_examples.json`

Key outcomes:

- Total triples loaded: **2166**
- Median query latency (P50) ranges from **14 ms** to **41 ms**
- P95 stays below **210 ms** even for `list_graphs`

These values meet the O4 latency targets in the draft validation plan.

## 6) Artifacts produced

Coverage and prediction artifacts:

- `evaluation/o1_coverage/gold_templates/gold_template_*.json`
- `evaluation/o1_coverage/gold_predictions/predicted_*.json`
- `evaluation/o1_coverage/coverage_results_all.md`
- `evaluation/o1_coverage/coverage_results_all.json`

Latency artifacts:

- `evaluation/o3_benchmarks/benchmark_results_examples.md`
- `evaluation/o3_benchmarks/benchmark_results_examples.json`
- `evaluation/o3_benchmarks/sparql_latency_loaded_examples.md`
- `evaluation/o3_benchmarks/sparql_latency_loaded_examples.json`

Crates and index results:

- `evaluation/crates/<notebook>/ro-crate`
- `evaluation/o3_benchmarks/index_results_examples.json`

## 7) Observed limitations and notes

1) **R parser parity**
   - The R parser currently misses call tokens like `read.csv` and symbol uses inside `$` expressions.
   - This is visible in the `exhaustive_r` coverage scores and should be prioritized.

2) **Kernel detection for R**
   - `conda-env-ravl-r` is not detected as an R kernel, so `RAVL_R_source` produced empty predictions.
   - This is a clear integration gap for non-standard kernels.

3) **Function argument defs**
   - The Python AST heuristic does not treat function parameters as defs, causing mismatches in the RAVL notebook and in `migrate_secrets`.

4) **Variable-driven file IO**
   - File IO is only captured when paths are literal strings or trivially resolvable. If a file path is built from variables and passed to `open`, the capture is currently incomplete.

5) **Notebook ID warnings**
   - Several notebooks trigger `nbformat` warnings because `id` fields are missing. This should be normalized to avoid future errors when nbformat enforces IDs strictly.

## 8) Threats to validity

- **Construct validity:** defs/uses/edges are derived from static heuristics; dynamic name creation, metaprogramming, and runtime IO are under-approximated.
- **Internal validity:** single-annotator gold labels may reflect author bias. No inter-annotator agreement was computed.
- **External validity:** results are based on a limited corpus; RAVL provides realism but is domain-specific.
- **Reliability:** performance was measured on a single machine under WSL2; cold-start and cross-platform variance are not captured.

## 9) Mapping to objectives and research questions

- **O1 (Coverage) / RQ1:** sections 2–3 (coverage methodology and per-notebook results).
- **O4 (Real-time & scale) / RQ2-RQ3:** sections 4–5 (local latency and SPARQL latency).
- **O2 (Comprehension) / RQ3:** not executed yet; see remaining steps.
- **O3 (Portability/FAIRness) / RQ2:** not executed yet; see remaining steps.
