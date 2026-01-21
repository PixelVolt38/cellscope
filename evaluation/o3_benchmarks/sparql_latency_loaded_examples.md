# SPARQL Latency Results (loaded examples)

Endpoint (query): `http://localhost:3030/cellscope/sparql`

## list_graphs

Timing: {'runs': 10, 'p50_ms': 40.754, 'p95_ms': 205.341, 'min_ms': 35.52, 'max_ms': 205.341}

Sample bindings (first 3):
```json
[
  {
    "g": {
      "type": "uri",
      "value": "file:///path/to/repo/examples/RAVL/RAVL.ipynb"
    }
  },
  {
    "g": {
      "type": "uri",
      "value": "file:///path/to/repo/examples/exhaustive_python.ipynb"
    }
  },
  {
    "g": {
      "type": "uri",
      "value": "file:///path/to/repo/examples/RAVL/RAVL_R_source.ipynb"
    }
  }
]
```

## count_triples

Timing: {'runs': 10, 'p50_ms': 32.83, 'p95_ms': 89.443, 'min_ms': 28.442, 'max_ms': 89.443}

Sample bindings (first 3):
```json
[
  {
    "count": {
      "type": "literal",
      "datatype": "http://www.w3.org/2001/XMLSchema#integer",
      "value": "2166"
    }
  }
]
```

## datasets_per_graph

Timing: {'runs': 10, 'p50_ms': 24.912, 'p95_ms': 35.807, 'min_ms': 21.39, 'max_ms': 35.807}

Sample bindings (first 3):
```json
[
  {
    "g": {
      "type": "uri",
      "value": "file:///path/to/repo/examples/exhaustive_python.ipynb"
    },
    "count": {
      "type": "literal",
      "datatype": "http://www.w3.org/2001/XMLSchema#integer",
      "value": "1"
    }
  },
  {
    "g": {
      "type": "uri",
      "value": "file:///path/to/repo/examples/exhaustive_r.ipynb"
    },
    "count": {
      "type": "literal",
      "datatype": "http://www.w3.org/2001/XMLSchema#integer",
      "value": "1"
    }
  },
  {
    "g": {
      "type": "uri",
      "value": "file:///path/to/repo/examples/multi_kernel_demo.ipynb"
    },
    "count": {
      "type": "literal",
      "datatype": "http://www.w3.org/2001/XMLSchema#integer",
      "value": "1"
    }
  }
]
```

## producers

Timing: {'runs': 10, 'p50_ms': 20.521, 'p95_ms': 30.741, 'min_ms': 13.711, 'max_ms': 30.741}

## consumers

Timing: {'runs': 10, 'p50_ms': 14.472, 'p95_ms': 16.293, 'min_ms': 11.792, 'max_ms': 16.293}
