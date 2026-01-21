with open("examples/data_outputs/summary.json", "r") as handle:
    raw = handle.read()
parsed = json.loads(raw)
