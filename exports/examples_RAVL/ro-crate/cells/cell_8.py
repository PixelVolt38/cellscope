# Download-KNMI
##libraries
import requests
from pathlib import Path
import os

# Changes per 16-11-2023
# Test if we are working with a one element nested list
dataset_files
n_files = len(dataset_files)
print(f"Starting download of {n_files} files.")
_, _, api_url, radar_code = conf_radars.get(param_radar.lower())
knmi_pvol_paths = []
idx = 1
for dataset_file in dataset_files:
    filename = dataset_file[0]
    fname_parts = filename.split("_")
    fname_date_part = fname_parts[-1].split(".")[0]
    year = fname_date_part[0:4]
    month = fname_date_part[4:6]
    day = fname_date_part[6:8]
    p = Path(f"{conf_local_knmi}/{radar_code}/{year}/{month}/{day}/{filename}")
    knmi_pvol_paths.append("{}".format(str(p)))

    if not p.exists():
        print(f"Downloading file {idx}/{n_files}")
        endpoint = f"{api_url}/{filename}/url"
        get_file_response = requests.get(
            endpoint, headers={"Authorization": secret_key_knmi_api}
        )
        download_url = get_file_response.json().get("temporaryDownloadUrl")
        dataset_file_response = requests.get(download_url)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(dataset_file_response.content)
    else:
        print(f"{p} already exists, skipping")
    idx += 1
print(knmi_pvol_paths)
print("Finished downloading files")