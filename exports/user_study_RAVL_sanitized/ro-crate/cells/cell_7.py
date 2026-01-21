# cell_7_list_knmi_files
"""
consume dummy var from config to signal workflow start
There is something dodgy going on with how
strings are being passed around.
The string "Yes" is being sent as '"Yes"'
So, to prevent extra quotes being introduced
we eval init_complete first before
we test if it contains "Yes"
"""
# Libraries
import requests


def validate_api_errors():
    if api_response.status_code >= 400:
        raise ValueError(
            f"API {api_response.url} returned an error status code: {api_response.status_code}. {api_response.json()=}"
        )


def validate_number_of_KNMI_files():
    if len(dataset_files) > param_maximum_KNMI_files:
        raise ValueError(
            f"{len(dataset_files)} KNMI files were found to download, but {param_maximum_KNMI_files=}."
            f"\n The data was retrieved with the following parameters:"
            f"\n {param_start_date=} \n {param_end_date=} \n {param_interval_in_minutes=}"
            f"\n Increase {param_maximum_KNMI_files=}, decrease the time range, or increase the interval."
        )


# Strip any extra quotes
init_complete = init_complete.replace("'", "")
init_complete = init_complete.replace('"', "")
if init_complete == "Yes":
    print("Workflow configuration succesfull")
else:
    print("Workflow configuration was not complete, exitting")
    import sys

    sys.exit(1)

# Notes:
# Timestamps in iso8601
# 2020-01-01T00:00+00:00

# configure
start_ts = param_start_date
end_ts = param_end_date
datasetName, datasetVersion, api_url, _ = conf_radars.get(param_radar.lower())
params = {
    "datasetName": datasetName,
    "datasetVersion": datasetVersion,
    "maxKeys": 10,
    "sorting": "asc",
    "orderBy": "created",
    "begin": start_ts,
    "end": end_ts,
}
# Request a response from the KNMI severs
# Try the next page tokens
dataset_files = []
while True:
    api_response = requests.get(
        url=api_url,
        headers={"Authorization": secret_key_knmi_api},
        params=params,
    )
    validate_api_errors()

    api_reponse_json = api_response.json()
    dset_files = api_reponse_json.get("files")

    dset_files = [list(dset_file.values()) for dset_file in dset_files]
    dataset_files += dset_files
    nextPageToken = api_reponse_json.get("nextPageToken")
    if not nextPageToken:
        break
    else:
        params.update({"nextPageToken": nextPageToken})

# KNMI outputs per 5 minutes, per 15 is less of a heavy hit on downloads and processing
# Quick and dirty way to only keep the 15 minute measurements.
# Check API if we can filter for this on their end. If not fine
filtered_list = []
interval_list = list(range(0, 60, param_interval_in_minutes))
for dataset_file in dataset_files:
    minute = int(dataset_file[0].split("_")[-1].split(".")[0][-2:])
    if minute in interval_list:
        filtered_list.append(dataset_file)

dataset_files = filtered_list

validate_number_of_KNMI_files()

print(f"Found {len(dataset_files)} files")
print(dataset_files)