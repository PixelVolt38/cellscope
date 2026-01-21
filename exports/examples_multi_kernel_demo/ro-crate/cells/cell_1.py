# materialize outputs for hand-off
data_dir = 'data_outputs'
import os
os.makedirs(data_dir, exist_ok=True)

csv_path = os.path.join(data_dir, 'climate_readings.csv')
json_path = os.path.join(data_dir, 'climate_summary.json')

climate.to_csv(csv_path, index=False)
climate_summary_df = pd.DataFrame([climate_summary])
climate_summary_df.to_json(json_path, orient='records', indent=2)
print(f"wrote {csv_path} and {json_path}")

# share the climate summary via SoS for other kernels