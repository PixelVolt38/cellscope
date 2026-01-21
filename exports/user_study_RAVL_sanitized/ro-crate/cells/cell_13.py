# cell_13_s3_vp_downloader
# ---
# NaaVRE:
#  cell:
#   outputs:
#    - vp_paths: List
# ...

# Code analyzer fix block. Assign empty strings to variables that should not be picked up by the analyzer.
minioClient = ""

# libraries
from minio import Minio
import pandas as pd
import pathlib

# functions

# main
psd = pd.to_datetime(param_start_date)
ped = pd.to_datetime(param_end_date)
minioClient = Minio(
    endpoint=conf_minio_endpoint,
    access_key=secret_minio_access_key,
    secret_key=secret_minio_secret_key,
    secure=True,
)

download_objs = []

# grab psd and ped, rework them to include a start_after prefix
psd_prefix = f"user@example.com/vp/NL/{param_radar}/{psd.year}/{psd.month:02}/{psd.day:02}"
psd_start_after_prefix = f"{psd_prefix}/NL{param_radar}_vp_{psd.year}{psd.month:02}{psd.day:02}T{psd.hour:02}{psd.minute:02}"
psd_prefix_objs = minioClient.list_objects(
    bucket_name=conf_minio_user_bucket_name,
    prefix=psd_prefix,
    start_after=psd_start_after_prefix,
    recursive=True,
)
download_objs += list(psd_prefix_objs)

# For PED we need a 'until'.
# So, we need to determine which part of the list of the final prefix we require.
# in essence, we need a ped_until_prefix.
ped_prefix = f"user@example.com/vp/NL/{param_radar}/{ped.year}/{ped.month:02}/{ped.day:02}"
ped_until_prefix = f"{ped_prefix}/NL{param_radar}_vp_{ped.year}{ped.month:02}{ped.day:02}T{ped.hour:02}{ped.minute:02}"
ped_until_datetimestr = (
    f"{ped.year}{ped.month:02}{ped.day:02}T{ped.hour:02}{ped.minute:02}"
)
ped_until_timestamp = pd.to_datetime(ped_until_datetimestr)
ped_prefix_objs = minioClient.list_objects(
    bucket_name=conf_minio_user_bucket_name, prefix=ped_prefix, recursive=True
)
ped_prefix_objs = list(ped_prefix_objs)
for obj in ped_prefix_objs:
    fpath = pathlib.Path(obj._object_name)
    fname = fpath.name
    corad, dtype, datetimestr, radcode, v2b_version_suffix = fname.split("_")
    timestamp = pd.to_datetime(datetimestr)
    if timestamp <= ped_until_timestamp:
        download_objs.append(obj)

vp_paths = []
for obj in download_objs:
    obj_path = pathlib.Path(obj._object_name)
    uname, dtype, country, radar, year, month, day, filename = obj_path.parts
    local_vp_path = (
        f"{conf_local_vp}/{country}/{radar}/{year}/{month}/{day}/{filename}"
    )
    print(local_vp_path)
    minioClient.fget_object(
        bucket_name=obj._bucket_name,
        object_name=obj._object_name,
        file_path=local_vp_path,
    )
    vp_paths.append(local_vp_path)