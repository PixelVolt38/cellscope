# cell_15_s3_vpts_uploader
# Libraries
from minio import Minio

minioClient = Minio(
    endpoint=conf_minio_endpoint,
    access_key=secret_minio_access_key,
    secret_key=secret_minio_secret_key,
    secure=True,
)

for path in local_vpts_paths:
    # strip the leading "/tmp/data"
    print(path)
    obj_key = pathlib.Path(*pathlib.Path(path).parts[3:])
    obj_name = f"{conf_minio_tutorial_prefix}/{obj_key}"
    print(obj_name)
    minioClient.fput_object(
        bucket_name=conf_minio_user_bucket_name,
        object_name=obj_name,
        file_path=path,
    )