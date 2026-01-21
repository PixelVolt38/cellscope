# Reproduction Guide

This document describes how to reproduce the evaluation artifacts shipped with
this repository. All commands assume you are in the repo root.

## 0) Environment setup

```bash
python -m venv .venv_linux
./.venv_linux/bin/python -m pip install -U pip
./.venv_linux/bin/python -m pip install -e .
```

Optional (JupyterLab UI):

```bash
cd labextension
npm install
npm run stage
```

## O1 Coverage (gold labels vs. predictions)

Artifacts live under `evaluation/o1_coverage/` and are regenerated with:

```bash
./.venv_linux/bin/python evaluation/o1_coverage/run_coverage.py
```

This regenerates:

- `evaluation/o1_coverage/gold_predictions/predicted_*.json`
- `evaluation/o1_coverage/coverage_results.json`
- `evaluation/o1_coverage/coverage_results.md`
- `evaluation/o1_coverage/coverage_results_all.json`
- `evaluation/o1_coverage/coverage_results_all.md`

Gold templates used as the reference are stored in
`evaluation/o1_coverage/gold_templates/` and point to the notebooks listed in
`evaluation/README.md`.

## O2 User study (materials + results)

The study is manual and uses the protocol plus sanitized notebooks in:

- Protocol: `evaluation/o2_user_study/user_study_protocol.md`
- Notebooks: `evaluation/o2_user_study/user_study/*.ipynb`
- Results sheet (filled manually during the study):
  `evaluation/o2_user_study/user_study_results.xlsx`

Run the study following the protocol and append new rows in the spreadsheet.

## O3 Latency benchmarks (local)

Synthetic notebooks used for latency are in `evaluation/o3_benchmarks/notebooks/`.
Run the benchmarks with:

```bash
./.venv_linux/bin/python evaluation/o3_benchmarks/run_latency_benchmarks.py
```

Outputs:

- `evaluation/o3_benchmarks/benchmark_results.json`
- `evaluation/o3_benchmarks/benchmark_results.md`
- `evaluation/o3_benchmarks/benchmark_results_examples.json`
- `evaluation/o3_benchmarks/benchmark_results_examples.md`

## O3 Latency benchmarks (SPARQL)

Start a local Fuseki instance (example):

```bash
java -jar fuseki-server.jar --mem /cellscope
```

### Empty store latency

```bash
./.venv_linux/bin/python evaluation/o3_benchmarks/run_sparql_latency.py \
  --out-json evaluation/o3_benchmarks/sparql_latency.json \
  --out-md evaluation/o3_benchmarks/sparql_latency.md
```

### Loaded store latency

Load existing crates from `exports/` into Fuseki:

```bash
./.venv_linux/bin/python evaluation/o3_benchmarks/load_exports_to_sparql.py \
  --endpoint http://localhost:3030/cellscope/update \
  --out evaluation/o3_benchmarks/index_results.json
```

Then re-run latency collection:

```bash
./.venv_linux/bin/python evaluation/o3_benchmarks/run_sparql_latency.py \
  --out-json evaluation/o3_benchmarks/sparql_latency_loaded.json \
  --out-md evaluation/o3_benchmarks/sparql_latency_loaded.md
```

## Representative exports

Representative RO-Crates (with the offline HTML graph viewer) are stored under
`exports/*/ro-crate/`.

## Sanity check (optional)

A quick end-to-end smoke test is available:

```bash
./.venv_linux/bin/python scripts/run_full_test.py
```
