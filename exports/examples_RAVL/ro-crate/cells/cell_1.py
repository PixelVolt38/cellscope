# DO NOT CONTAINERISE
# parametrization - v95
# Run specific - fill in text to preset, keep empty to prompt
import os


param_radar = "HRW"  # DHL | HRW | DBL
param_start_date = (
    "2019-12-31T23:00+00:00"  # %Y%m%dT%H:%M+TZ; 2019-12-31T23:00+00:00
)
param_end_date = (
    "2020-01-01T01:00+00:00"  # %Y%m%dT%H:%M+TZ; 2020-01-01T01:00+00:00
)
param_concurrency = 5
param_interval_in_minutes = 60
# This is to control uploads / cleaning
# Move results to S3?
param_upload_results = "True"
# Store and retrieve data from the public S3 / MinIO bucket
param_public_minio_data = 0
# Remove input after processing KNMI format to ODIM format
param_clean_knmi_input = "True"
# Should we remove the final Polar Volumes after producing a VP and or RBC
param_clean_pvol_output = "True"
#
param_clean_vp_output = "True"
# The maximum number of timepoints to download and create vertical profiles and polar volumes from
param_maximum_KNMI_files = 4

# Param
### User specific, not neccesarily run specific.
#### Update: Perhaps some of these userinfo should be hardcoded parameters. I mean
#### Not something we'd enter every single time but should be set at setup time.
param_user_number = "001"

#### Visualization parameters
param_dtype = "pvol"  # pvol | vp
param_country = "NL"  # only NL
param_year = "2023"  # as string, YYYY
param_month = "12"  # as string, mm
param_day = "31"  # as string, dd

# Perhaps param prefix works better
param_prefix = "NL/DHL/2023/12/31"

# parameters
param_elevation = 3  #
param_param = "VRADH"  # I know...VRADH, DBZH, TH, WRADH, RHOHV, DBZ...
param_imtype = "ppi"  # Likely only type so far. PVOL -> PPI, VP -> VPTS. Future there would be more.