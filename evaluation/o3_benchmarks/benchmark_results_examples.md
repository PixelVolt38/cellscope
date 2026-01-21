# Local Benchmark Results (examples)

Analyze = parse_notebook + infer_cross_kernel_edges + capture_to_json.
Export+index = parse_notebook + build_rocrate + index_crate (no endpoint).

## RAVL
Notebook: `examples/RAVL/RAVL.ipynb`
Analyze: {'runs': 5, 'p50_s': 0.033608, 'p95_s': 0.09244, 'min_s': 0.03163, 'max_s': 0.09244}
Export+index: {'runs': 3, 'p50_s': 0.082414, 'p95_s': 0.100295, 'min_s': 0.081698, 'max_s': 0.100295}

## RAVL_R_source
Notebook: `examples/RAVL/RAVL_R_source.ipynb`
Analyze: {'runs': 5, 'p50_s': 0.001659, 'p95_s': 0.002094, 'min_s': 0.00155, 'max_s': 0.002094}
Export+index: {'runs': 3, 'p50_s': 0.021333, 'p95_s': 0.022438, 'min_s': 0.021118, 'max_s': 0.022438}

## SecretsProvider_demo
Notebook: `examples/RAVL/SecretsProvider_demo.ipynb`
Analyze: {'runs': 5, 'p50_s': 0.000549, 'p95_s': 0.00073, 'min_s': 0.000518, 'max_s': 0.00073}
Export+index: {'runs': 3, 'p50_s': 0.019248, 'p95_s': 0.01943, 'min_s': 0.018331, 'max_s': 0.01943}

## migrate_secrets
Notebook: `examples/RAVL/migrate_secrets.ipynb`
Analyze: {'runs': 5, 'p50_s': 0.001324, 'p95_s': 0.001381, 'min_s': 0.001161, 'max_s': 0.001381}
Export+index: {'runs': 3, 'p50_s': 0.019838, 'p95_s': 0.021138, 'min_s': 0.018998, 'max_s': 0.021138}

## exhaustive_python
Notebook: `examples/exhaustive_python.ipynb`
Analyze: {'runs': 5, 'p50_s': 0.00159, 'p95_s': 0.002193, 'min_s': 0.001415, 'max_s': 0.002193}
Export+index: {'runs': 3, 'p50_s': 0.025645, 'p95_s': 0.026098, 'min_s': 0.025282, 'max_s': 0.026098}

## exhaustive_r
Notebook: `examples/exhaustive_r.ipynb`
Analyze: {'runs': 5, 'p50_s': 0.000771, 'p95_s': 0.001352, 'min_s': 0.000651, 'max_s': 0.001352}
Export+index: {'runs': 3, 'p50_s': 0.022099, 'p95_s': 0.022132, 'min_s': 0.02112, 'max_s': 0.022132}

## multi_kernel_demo
Notebook: `examples/multi_kernel_demo.ipynb`
Analyze: {'runs': 5, 'p50_s': 0.00259, 'p95_s': 0.003282, 'min_s': 0.002379, 'max_s': 0.003282}
Export+index: {'runs': 3, 'p50_s': 0.028566, 'p95_s': 0.029496, 'min_s': 0.027547, 'max_s': 0.029496}
