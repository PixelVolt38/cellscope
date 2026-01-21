# cell_12_s3_pvol_downloader
# ---
# NaaVRE:
#  cell:
#   outputs:
#    - local_pvol_paths: List
# ...

# Code analyzer fix block. Assign empty strings to variables that should not be picked up by the analyzer.
minioClient = ""

# libraries
from minio import Minio
import pandas as pd
import pathlib


# functions
def get_pvol_storage_path(relative_path: str = "") -> str:
    if param_public_minio_data:
        return (
            pathlib.Path(conf_minio_public_root_prefix)
            .joinpath(conf_minio_tutorial_prefix)
            .joinpath(conf_pvol_output_prefix)
            .joinpath(relative_path)
        )
    else:
        return (
            pathlib.Path(conf_minio_tutorial_prefix)
            .joinpath(conf_user_directory + param_user_number)
            .joinpath(conf_pvol_output_prefix)
            .joinpath(relative_path)
        )


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
psd_prefix = f"{get_pvol_storage_path()}/NL/{param_radar}/{psd.year}/{psd.month:02}/{psd.day:02}"
print(f"Parsing first prefix: {psd_prefix}")
psd_start_after_prefix = f"{psd_prefix}/NL{param_radar}_pvol_{psd.year}{psd.month:02}{psd.day:02}T{psd.hour:02}{psd.minute:02}"
print(f"Building an start after prefix: {psd_start_after_prefix}")
psd_prefix_objs = minioClient.list_objects(
    bucket_name=(
        conf_minio_public_bucket_name
        if param_public_minio_data
        else conf_minio_user_bucket_name
    ),
    prefix=psd_prefix,
    start_after=psd_start_after_prefix,
    recursive=True,
)
psd_prefix_objs = list(psd_prefix_objs)
print(f"{psd_prefix_objs=}")
download_objs += psd_prefix_objs

# Now we need a middle prefix download. The prefixes that are between psd and ped.
print(f"Determining middle prefixes...")
drange = pd.date_range(start=psd, end=ped, freq="5 min")
date_prefix_list = [
    f"{dstamp.year}/{dstamp.month:02}/{dstamp.day:02}" for dstamp in drange
]
unique_date_prefix_list = list(set(date_prefix_list))
# sort the dates
unique_date_prefix_list.sort()
# remove first prefix, we evaluate that differently
middle_prefixes = unique_date_prefix_list[1:-1]
# Now add the correct country, radar to the date prefixes
middle_prefixes = [
    f"{get_pvol_storage_path()}/NL/{param_radar}/{middle_prefix}"
    for middle_prefix in middle_prefixes
]
print(f"Parsing {len(middle_prefixes)} middle prefixes.")
for middle_prefix in middle_prefixes:
    print(f"Downloading {middle_prefix}")
    middle_prefix_objs = minioClient.list_objects(
        bucket_name=(
            conf_minio_public_bucket_name
            if param_public_minio_data
            else conf_minio_user_bucket_name
        ),
        prefix=middle_prefix,
        recursive=True,
    )
    download_objs += list(middle_prefix_objs)


# For PED we need a 'until'.
# So, we need to determine which part of the list of the final prefix we require.
# in essence, we need a ped_until_prefix.
ped_prefix = f"{get_pvol_storage_path()}/NL/{param_radar}/{ped.year}/{ped.month:02}/{ped.day:02}"

ped_until_prefix = f"{ped_prefix}/NL{param_radar}_pvol_{ped.year}{ped.month:02}{ped.day:02}T{ped.hour:02}{ped.minute:02}"
print(f"Parsing last prefix:{ped_prefix}")
ped_until_datetimestr = (
    f"{ped.year}{ped.month:02}{ped.day:02}T{ped.hour:02}{ped.minute:02}"
)
ped_until_timestamp = pd.to_datetime(ped_until_datetimestr)
print(f"Building an end timestamp for object filtering: {ped_until_timestamp}")
ped_prefix_objs = minioClient.list_objects(
    bucket_name=(
        conf_minio_public_bucket_name
        if param_public_minio_data
        else conf_minio_user_bucket_name
    ),
    prefix=ped_prefix,
    recursive=True,
)
print(f"Filtering last prefix objects on timestamps")
ped_prefix_objs = list(ped_prefix_objs)
print(f"{ped_prefix_objs=}")
_ped_prefix_objs = []
for obj in ped_prefix_objs:
    fpath = pathlib.Path(obj._object_name)
    fname = fpath.name
    corad, dtype, datetimestr, radcode_suffix = fname.split("_")
    timestamp = pd.to_datetime(datetimestr)
    if timestamp <= ped_until_timestamp:
        _ped_prefix_objs.append(obj)
        download_objs.append(obj)

ped_prefix_objs = _ped_prefix_objs

# Ensure that download objects are not duplicated in case of single prefix searches
if psd_prefix == ped_prefix:
    # same prefix
    print("Single prefix filtering")
    psd_object_names = [
        psd_prefix_obj._object_name for psd_prefix_obj in psd_prefix_objs
    ]
    print(f"{psd_object_names=}")
    ped_object_names = [
        ped_prefix_obj._object_name for ped_prefix_obj in ped_prefix_objs
    ]
    print(f"{ped_object_names=}")
    intersect_object_names = [
        obj_name
        for obj_name in psd_object_names
        if obj_name in ped_object_names
    ]
    print(f"{intersect_object_names=}")
    # Reset download_objs list
    download_objs = []
    for psd_prefix_obj in psd_prefix_objs:
        if psd_prefix_obj._object_name in intersect_object_names:
            download_objs.append(psd_prefix_obj)


local_pvol_paths = []
for obj in download_objs:
    obj_path = pathlib.Path(obj._object_name)
    if param_public_minio_data:
        lab, workshop, dtype, country, radar, year, month, day, filename = (
            obj_path.parts
        )
    else:
        workshop, uname, dtype, country, radar, year, month, day, filename = (
            obj_path.parts
        )
    local_pvol_path = (
        f"{conf_local_odim}/{country}/{radar}/{year}/{month}/{day}/{filename}"
    )
    print(local_pvol_path)
    minioClient.fget_object(
        bucket_name=obj._bucket_name,
        object_name=obj._object_name,
        file_path=local_pvol_path,
    )
    local_pvol_paths.append(local_pvol_path)