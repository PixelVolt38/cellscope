# cell_11_retrieve_pvol_deprecated
from minio import Minio
import sys
import pathlib

if PVOL_VP_converter_complete:
    print("PVOL-VP-converter successfull")
else:
    print("PVOL-VP-converter was not complete, exitting")
    import sys

    sys.exit(1)

#
minioClient = Minio(
    endpoint=conf_minio_endpoint,
    access_key=secret_minio_access_key,
    secret_key=secret_minio_secret_key,
    secure=True,
)

# dtype = "pvol"
# country = "NL"
# radar = "DHL"
# year = "2023"
# month = "12"
# day = "31"
recursive = True

if param_dtype.lower() in ["pvol", "polar volume", "polarvolume"]:
    search_prefix = f"{conf_minio_tutorial_prefix}/{conf_user_directory+param_user_number}/{conf_pvol_output_prefix}/{param_country}/{param_radar}/{param_year}/{param_month}/{param_day}"
elif param_dtype.lower() in ["vp", "vertical profile", "verticalprofile"]:
    search_prefix = f"{conf_minio_tutorial_prefix}/{conf_user_directory+param_user_number}/{conf_vp_output_prefix}/{param_country}/{param_radar}/{param_year}/{param_month}/{param_day}"
else:
    print(f"{param_dtype} not understood")
    sys.exit(1)
print(f"{search_prefix=}")
# To be implemented:
# The below works, but we can use this for the filtering from parameters at some point.
# This shoud be done after the demo version.
# start_after_prefix=f'{conf_minio_tutorial_prefix}/{conf_pvol_output_prefix}/{country}/{radar}/{year}/{month}/{day}/{country}{radar}_{dtype}_{year}{month}{day}T2200_6234.h5'
# print(f"{start_after_prefix=}")
# objects = minioClient.list_objects(bucket_name=conf_minio_user_bucket_name,
#                                   prefix=search_prefix,
#                                   recursive=recursive,
#                                   start_after=start_after_prefix
#                                  )
objects = minioClient.list_objects(
    bucket_name=(
        conf_minio_public_bucket_name
        if param_public_minio_data
        else conf_minio_user_bucket_name
    ),
    prefix=search_prefix,
    recursive=recursive,
)
local_file_paths = []
for obj in objects:
    obj_path = pathlib.Path(obj._object_name)
    local_file_path = f"{conf_local_visualization_input}/{obj_path.name}"
    local_file_paths.append(local_file_path)
    print(f"Downloading {obj._object_name} to {local_file_path}")
    minioClient.fget_object(
        bucket_name=obj._bucket_name,
        object_name=obj._object_name,
        file_path=local_file_path,
    )
    local_file_paths.append(local_file_path)
print("Finished")