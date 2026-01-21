# DO NOT CONTAINERISE - v60
# Set initial resource in minio, the conf in common
debug = False
from minio import Minio, S3Error
import os
import pathlib

minioClient = Minio(
    endpoint=conf_minio_endpoint,
    access_key=secret_minio_access_key,
    secret_key=secret_minio_secret_key,
    secure=True,
)
# Stat object to see if it is there. We could also just try a try except on fget
# However, canonically this seems better to stat
# Cast to str as stat object doesnt like posix
try:
    radar_db_stat = minioClient.stat_object(
        bucket_name=pathlib.Path(conf_minio_public_bucket_name).as_posix(),
        object_name=pathlib.Path(
            conf_minio_public_conf_radar_db_object_name
        ).as_posix(),
    )
    print(
        f"Reference file found [{pathlib.Path(conf_minio_public_bucket_name).as_posix()}]/{pathlib.Path(conf_minio_public_conf_radar_db_object_name).as_posix()}"
    )
    print(radar_db_stat)

except S3Error as e:
    print(
        f"Failed to find reference file [{pathlib.Path(conf_minio_public_bucket_name).as_posix()}]/{pathlib.Path(conf_minio_public_conf_radar_db_object_name).as_posix()}"
    )
    if debug:
        print(f"{e=}")

    file_stat = os.stat("/path/to/jovyan/data/conf/OPERA_RADARS_DB.json")
    with open(
        "/path/to/jovyan/data/conf/OPERA_RADARS_DB.json", mode="rb"
    ) as file_data:
        put_result = minioClient.put_object(
            bucket_name=pathlib.Path(conf_minio_public_bucket_name).as_posix(),
            object_name=pathlib.Path(
                conf_minio_public_conf_radar_db_object_name
            ).as_posix(),
            data=file_data,
            length=file_stat.st_size,
        )
    print(f"{put_result=}")
    # check put result if we indeed uploaded succesfully
    # if we dont try except we will lazily evaluate the result, as fail likely yields hard crash
    print("Succesfully uploaded reference file")