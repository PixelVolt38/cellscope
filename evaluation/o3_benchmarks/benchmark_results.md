# Local Benchmark Results

This uses synthetic notebooks created in evaluation/o3_benchmarks/notebooks.
Analyze = parse_notebook + infer_cross_kernel_edges + capture_to_json.
Export+index = parse_notebook + build_rocrate + index_crate (no endpoint).

## synth_10.ipynb (10 code cells)

Analyze: {'runs': 10, 'p50_s': 0.0006, 'p95_s': 0.0007, 'min_s': 0.0004, 'max_s': 0.0016}
Export+index: {'runs': 5, 'p50_s': 0.019, 'p95_s': 0.0198, 'min_s': 0.0177, 'max_s': 0.0329}

## synth_50.ipynb (50 code cells)

Analyze: {'runs': 10, 'p50_s': 0.0019, 'p95_s': 0.002, 'min_s': 0.0017, 'max_s': 0.002}
Export+index: {'runs': 5, 'p50_s': 0.0314, 'p95_s': 0.0332, 'min_s': 0.031, 'max_s': 0.0916}

## synth_100.ipynb (100 code cells)

Analyze: {'runs': 10, 'p50_s': 0.0037, 'p95_s': 0.0039, 'min_s': 0.0036, 'max_s': 0.0043}
Export+index: {'runs': 5, 'p50_s': 0.0496, 'p95_s': 0.0497, 'min_s': 0.049, 'max_s': 0.0504}
