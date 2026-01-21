# SPARQL Latency Results

Endpoint (query): `http://localhost:3030/cellscope/sparql`

## list_graphs

Timing: {'runs': 10, 'p50_ms': 11.176, 'p95_ms': 29.869, 'min_ms': 7.435, 'max_ms': 378.551}

## count_triples

Timing: {'runs': 10, 'p50_ms': 9.818, 'p95_ms': 13.037, 'min_ms': 8.151, 'max_ms': 38.974}

Sample bindings (first 3):
```json
[
  {
    "count": {
      "type": "literal",
      "datatype": "http://www.w3.org/2001/XMLSchema#integer",
      "value": "0"
    }
  }
]
```

## datasets_per_graph

Timing: {'runs': 10, 'p50_ms': 11.753, 'p95_ms': 13.718, 'min_ms': 9.91, 'max_ms': 16.244}

## producers

Timing: {'runs': 10, 'p50_ms': 13.845, 'p95_ms': 14.51, 'min_ms': 10.638, 'max_ms': 16.202}

## consumers

Timing: {'runs': 10, 'p50_ms': 11.758, 'p95_ms': 16.558, 'min_ms': 10.31, 'max_ms': 18.078}
