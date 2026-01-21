# cell_6_initializer
import pathlib

# Make directories on shared (local) storage
for local_dir in [
    conf_local_root,
    conf_local_knmi,
    conf_local_odim,
    conf_local_vp,
    conf_local_conf,
]:
    local_dir = pathlib.Path(local_dir)
    if not local_dir.exists():
        local_dir.mkdir(parents=True, exist_ok=True)
# Reference files
if not pathlib.Path(conf_local_radar_db).exists():
    from minio import Minio, S3Error

    minioClient = Minio(
        endpoint=conf_minio_endpoint,
        access_key=secret_minio_access_key,
        secret_key=secret_minio_secret_key,
        secure=True,
    )
    print(f"{conf_local_radar_db} not found, downloading")
    minioClient.fget_object(
        bucket_name=conf_minio_public_bucket_name,
        object_name=conf_minio_public_conf_radar_db_object_name,
        file_path=conf_local_radar_db,
    )

# Now produce a variable which acts as a marker for the workflow manager
# We can then drag a line from the configuration / initializer
# and time the start of the rest of the workflow
# If you decide to make different sets of configurations, you can store them
# and decide per workflow which config to attach
init_complete = "Yes"  # Cant sent bool
print("Finished initialization")