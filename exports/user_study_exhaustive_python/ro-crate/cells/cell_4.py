summary = compute_stats(df)
Path("examples/data_outputs/summary.json").write_text(json.dumps(summary))
