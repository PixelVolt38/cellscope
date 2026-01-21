def compute_stats(df):
    mean_temp = df["temperature"].mean()
    above = (df["temperature"] > threshold).sum()
    return {"mean_temp": mean_temp, "above_threshold": int(above)}
