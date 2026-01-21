# Evaluation artifacts

This folder holds the artifacts used to validate CellScope. It mirrors the thesis
objectives (O1 coverage, O2 user study, O3 latency benchmarks). The reproduction
steps are summarized in `REPRODUCE.md` at the repo root.

## O1 Coverage (gold labels)
- Templates: `evaluation/o1_coverage/gold_templates/*.json`
- Predictions: `evaluation/o1_coverage/gold_predictions/*.json`
- Report: `evaluation/o1_coverage/validation_report.md`

Gold label notebooks (sources):
- `examples/exhaustive_python.ipynb`
- `examples/multi_kernel_demo.ipynb`
- `examples/exhaustive_r.ipynb`
- `examples/RAVL/RAVL.ipynb`
- `examples/RAVL/RAVL_R_source.ipynb`
- `examples/RAVL/SecretsProvider_demo.ipynb`
- `examples/RAVL/migrate_secrets.ipynb`

Notes:
- Gold templates are manually filled and serve as the reference labels.
- Predictions are produced by the current code for comparison.
- Regenerate O1 results with `evaluation/o1_coverage/run_coverage.py`.

## O2 User study materials
- Protocol: `evaluation/o2_user_study/user_study_protocol.md`
- Notebooks: `evaluation/o2_user_study/user_study/*.ipynb`
- Results: `evaluation/o2_user_study/user_study_results.xlsx`

Results sheet structure (worksheet `Hoja1`):
- Round 1 (prototype): 10 participants with condition order, experience, Task A/B times, feedback, and dev notes.
- Round 2 (final prototype): 10 participants with CellScope-only timings for Task A or Task B.

Sanitized and study-ready copies are also available in:
- `examples/evaluation/`

## O3 Benchmarks and latency
- Synthetic notebooks: `evaluation/o3_benchmarks/notebooks/synth_*.ipynb`
- Results: `evaluation/o3_benchmarks/*.md` and `evaluation/o3_benchmarks/*.json`
- Benchmark scripts:
  - `evaluation/o3_benchmarks/run_latency_benchmarks.py`
  - `evaluation/o3_benchmarks/run_sparql_latency.py`
  - `evaluation/o3_benchmarks/load_exports_to_sparql.py`

## Representative exports
- RO-Crates (one per evaluation notebook): `exports/*/ro-crate/`
