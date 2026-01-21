df = pd.read_csv("examples/data_outputs/climate_readings.csv")
df["temp_f"] = df["temperature"] * 9 / 5 + 32
