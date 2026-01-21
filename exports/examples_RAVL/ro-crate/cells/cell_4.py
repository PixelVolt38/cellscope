# DO NOT CONTAINERISE
# configuration - v95
import os
import pathlib

conf_minio_user_bucket_name = "example-user-bucket"  # the user bucket name
conf_minio_tutorial_prefix = "example-tutorial"
conf_minio_public_bucket_name = "example-public-bucket"  # the public bucket name
conf_minio_public_root_prefix = "example-public-root"
conf_minio_public_conf_prefix = "example-public-root/conf"
conf_minio_public_conf_radar_db_object_name = (
    "example-public-root/conf/OPERA_RADARS_DB.json"
)
conf_minio_endpoint = "minio.example.org:9000"

### Directories
conf_local_root = "/tmp/data"
conf_local_knmi = "/tmp/data/knmi"
conf_local_odim = "/tmp/data/odim"
conf_local_vp = "/tmp/data/vp"
conf_local_ppi = "/tmp/data/ppi"
conf_local_vpts = "/tmp/data/vpts"
conf_local_conf = "/tmp/data/conf"
conf_local_radar_db = "/tmp/data/conf/OPERA_RADARS_DB.json"
conf_local_visualization_input = "/tmp/data/visualizations/input"
conf_local_visualization_output = "/tmp/data/visualizatons/output"

conf_pvol_output_prefix = "pvol"
conf_vp_output_prefix = "vp"
conf_ppi_output_prefix = "ppi"
conf_vpts_output_prefix = "vpts"
conf_user_directory = "user"

# radar configuration for the KNMI api
# Rewritten in a long format without page breaks. This is to prevent
# the code analyzer to yield an error.
# datasetName, datasetVersion, api_url, radar code (odim)
conf_herwijnen = [
    "radar_volume_full_herwijnen",
    1.0,
    "https://api.dataplatform.knmi.nl/open-data/v1/datasets/radar_volume_full_herwijnen/versions/1.0/files",
    "NL/HRW",
]
conf_denhelder = [
    "radar_volume_full_denhelder",
    2.0,
    "https://api.dataplatform.knmi.nl/open-data/v1/datasets/radar_volume_denhelder/versions/2.0/files",
    "NL/DHL",
]
conf_radars = {
    "hrw": conf_herwijnen,
    "herwijnen": conf_herwijnen,
    "dhl": conf_denhelder,
    "den helder": conf_denhelder,
}