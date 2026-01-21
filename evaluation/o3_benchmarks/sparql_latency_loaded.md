# SPARQL Latency Results (loaded)

Endpoint (query): `http://localhost:3030/cellscope/sparql`

## list_graphs

Timing: {'runs': 10, 'p50_ms': 12.134, 'p95_ms': 25.166, 'min_ms': 8.841, 'max_ms': 25.166}

Sample bindings (first 3):
```json
[
  {
    "g": {
      "type": "uri",
      "value": "https://cellscope.local/graph/multi-kernel-demo?v=8"
    }
  },
  {
    "g": {
      "type": "uri",
      "value": "https://cellscope.local/graph/exhaustive-python?v=3"
    }
  },
  {
    "g": {
      "type": "uri",
      "value": "https://cellscope.local/graph/exhaustive-r?v=1"
    }
  }
]
```

## count_triples

Timing: {'runs': 10, 'p50_ms': 11.458, 'p95_ms': 17.729, 'min_ms': 9.529, 'max_ms': 17.729}

Sample bindings (first 3):
```json
[
  {
    "count": {
      "type": "literal",
      "datatype": "http://www.w3.org/2001/XMLSchema#integer",
      "value": "898"
    }
  }
]
```

## datasets_per_graph

Timing: {'runs': 10, 'p50_ms': 11.455, 'p95_ms': 20.311, 'min_ms': 9.501, 'max_ms': 20.311}

Sample bindings (first 3):
```json
[
  {
    "g": {
      "type": "uri",
      "value": "https://cellscope.local/graph/exhaustive-python?v=3"
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
      "value": "https://cellscope.local/graph/multi-kernel-demo?v=8"
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
      "value": "https://cellscope.local/graph/exhaustive-python?v=5"
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

Timing: {'runs': 10, 'p50_ms': 10.381, 'p95_ms': 13.913, 'min_ms': 8.941, 'max_ms': 13.913}

## consumers

Timing: {'runs': 10, 'p50_ms': 9.51, 'p95_ms': 14.542, 'min_ms': 8.567, 'max_ms': 14.542}
