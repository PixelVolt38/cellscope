# cell_9_knmi_to_odim_converter
"""
notes:
Need to add this such that it can upload the PVOL From this stage
Need to add option such that this can remove the PVOL files from this stage.
Warning, with the removal of PVOL on this stage auto-bricks the VP / RBC gen
We can introduce a flag check where RBC and VP check if PVOL 'needed' to be removed
If that flag is met - abort, there 'shouldnt' be any INPUT files then.
"""
import subprocess
import pathlib
import h5py
import json
import sys
import shutil


# from typing import List, Object
import math


def str2bool(v):
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "t", "y", "1"):
        return True
    elif v.lower() in ("no", "false", "f", "n", "0"):
        return False
    else:
        raise Exception


class FileTranslatorFileTypeError(LookupError):
    """raise this when there's a filetype mismatch derived from h5 file"""


def load_radar_db(radar_db_path):
    """Load and return the radar database

    Output dict sample (wmo code is used as key):
    {
        11038: {'number': '1209', 'country': 'Austria', 'countryid': 'LOWM41', 'oldcountryid': 'OS41', 'wmocode': '11038', 'odimcode': 'atrau', 'location': 'Wien/Schwechat', 'status': '1', 'latitude': '48.074', 'longitude': '16.536', 'heightofstation': ' ', 'band': 'C', 'doppler': 'Y', 'polarization': 'D', 'maxrange': '224', 'startyear': '1978', 'heightantenna': '224', 'diametrantenna': ' ', 'beam': ' ', 'gain': ' ', 'frequency': '5.625', 'single_rrr': 'Y', 'composite_rrr': 'Y', 'wrwp': 'Y'},
        11052: {'number': '1210', 'country': 'Austria', 'countryid': 'LOWM43', 'oldcountryid': 'OS43', 'wmocode': '11052', 'odimcode': 'atfel', 'location': 'Salzburg/Feldkirchen', 'status': '1', 'latitude': '48.065', 'longitude': '13.062', 'heightofstation': ' ', 'band': 'C', 'doppler': 'Y', 'polarization': 'D', 'maxrange': '224', 'startyear': '1992', 'heightantenna': '581', 'diametrantenna': ' ', 'beam': ' ', 'gain': ' ', 'frequency': '5.6', 'single_rrr': 'Y', 'composite_rrr': ' ', 'wrwp': ' '},
        ...
    }
    """
    with open(radar_db_path, mode="r") as f:
        radar_db_json = json.load(f)
    radar_db = {}
    # Reorder list to a usable dict with sub dicts which we can search with wmo codes
    for radar_dict in radar_db_json:
        try:
            wmo_code = int(radar_dict.get("wmocode"))
            radar_db.update({wmo_code: radar_dict})
        except Exception:  # Happens when there is for ex. no wmo code.
            pass
    return radar_db


def translate_wmo_odim(radar_db, wmo_code):
    """ """
    if not isinstance(wmo_code, int):
        raise ValueError("Expecting a wmo_code [int]")
    else:
        pass
    odim_code = (
        radar_db.get(wmo_code).get("odimcode").upper().strip()
    )  # Apparently, people sometimes forget to remove whitespace..
    return odim_code


def extract_wmo_code(in_path):
    with h5py.File(in_path, mode="r") as f:
        # DWD Specific
        # Main attributes
        what = f["what"].attrs
        # Source block
        source = what.get("source")
        source = source.decode("utf-8")
        # Determine if we are dealing with a WMO code or with an ODIM code set
        # Example from Germany where source block is set as WMO
        # what/source: "WMO:10103"
        # Example from The Netherlands where source block is set as a combination of ODIM and various codes
        # what/source: RAD:NL52,NOD:nlhrw,PLC:Herwijnen
        source_list = source.split(sep=",")
    wmo_code = [string for string in source_list if "WMO" in string]
    # Determine if we had exactly one WMO hit
    if len(wmo_code) == 1:
        wmo_code = wmo_code[0]
        wmo_code = wmo_code.replace("WMO:", "")
    # No wmo code found, most likeley dealing with a dutch radar
    elif len(wmo_code) == 0:
        rad_str = [string for string in source_list if "RAD" in string]

        if len(rad_str) == 1:
            rad_str = rad_str[0]
        else:
            print(
                "Something went wrong with determining the rad_str and it wasnt WMO either, exitting"
            )
            sys.exit(1)
        # Split the rad_str
        rad_str_split = rad_str.split(":")
        # [0] = RAD, [1] = rad code
        rad_code = rad_str_split[1]

        rad_codes = {"NL52": "6356", "NL51": "6234", "NL50": "6260"}

        wmo_code = rad_codes.get(rad_code)
    return int(wmo_code)


def translate_knmi_filename(in_path_h5):
    wmo_code = extract_wmo_code(in_path_h5)
    odim_code = translate_wmo_odim(radar_db, wmo_code)
    with h5py.File(in_path_h5, mode="r") as f:
        what = f["what"].attrs
        # Date block
        date = what.get("date")
        date = date.decode("utf-8")
        # Time block
        time = what.get("time")
        # time = f['dataset1/what'].attrs['endtime']
        time = time.decode("utf-8")
        hh = time[:2]
        mm = time[2:4]
        ss = time[4:]
        time = time[:-2]  # Do not include seconds
        # File type
        filetype = what.get("object")
        filetype = filetype.decode("utf-8")
        if filetype != "PVOL":
            raise FileTranslatorFileTypeError("File type was NOT pvol")
    name = [
        odim_code,
        filetype.lower(),
        date + "T" + time,
        str(wmo_code) + ".h5",
    ]
    ibed_fname = "_".join(name)
    return ibed_fname


def knmi_to_odim(in_fpath, out_fpath):
    """
    Converter usage:
    Usage: KNMI_vol_h5_to_ODIM_h5 ODIM_file.h5 KNMI_input_file.h5

    Returns out_fpath and returncode
    """
    converter = "/opt/radar/vol2bird/bin/./KNMI_vol_h5_to_ODIM_h5"
    command = [converter, out_fpath, in_fpath]
    proc = subprocess.run(command, stderr=subprocess.PIPE)
    output = proc.stderr.decode("utf-8")
    returncode = int(proc.returncode)
    return (out_fpath, returncode, output)


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


print(f"{knmi_pvol_paths=}")
odim_pvol_paths = []
radar_db = load_radar_db(conf_local_radar_db)
for knmi_path in knmi_pvol_paths:
    out_path_pvol_odim = pathlib.Path(knmi_path.replace("knmi", "odim"))
    print(f"{knmi_path=}")
    print(f"{out_path_pvol_odim=}")
    if not out_path_pvol_odim.parent.exists():
        out_path_pvol_odim.parent.mkdir(parents=True, exist_ok=False)
    converter_results = knmi_to_odim(
        in_fpath=str(knmi_path), out_fpath=str(out_path_pvol_odim)
    )
    print(f"{converter_results=}")
    if param_clean_knmi_input:
        pathlib.Path(knmi_path).unlink()
        if not any(pathlib.Path(knmi_path).parent.iterdir()):
            pathlib.Path(knmi_path).parent.rmdir()
    # Determine name for our convention
    ibed_pvol_name = translate_knmi_filename(in_path_h5=out_path_pvol_odim)
    out_path_pvol_odim_tce = pathlib.Path(out_path_pvol_odim).parent.joinpath(
        ibed_pvol_name
    )
    shutil.move(src=out_path_pvol_odim, dst=out_path_pvol_odim_tce)
    odim_pvol_paths.append(out_path_pvol_odim_tce)

print(f"{odim_pvol_paths=}")
if str2bool(param_upload_results):
    # Minio version
    from minio import Minio

    minioClient = Minio(
        endpoint=conf_minio_endpoint,
        access_key=secret_minio_access_key,
        secret_key=secret_minio_secret_key,
        secure=True,
    )
    print(f"Uploading results to {get_pvol_storage_path()}")
    for odim_pvol_path in odim_pvol_paths:
        odim_pvol_path = pathlib.Path(odim_pvol_path)
        local_pvol_storage = pathlib.Path(conf_local_odim)
        relative_path = odim_pvol_path.relative_to(local_pvol_storage)
        remote_odim_pvol_path = get_pvol_storage_path(relative_path)
        # check if this exists
        exists = False
        try:
            _ = minioClient.stat_object(
                bucket=(
                    conf_minio_public_bucket_name
                    if param_public_minio_data
                    else conf_minio_user_bucket_name
                ),
                prefix=remote_odim_pvol_path.as_posix(),
            )
            exists = True
        except:
            pass
        if not exists:
            print(f"Uploading {odim_pvol_path} to {remote_odim_pvol_path}")
            with open(odim_pvol_path, mode="rb") as file_data:
                file_stat = os.stat(odim_pvol_path)
                minioClient.put_object(
                    bucket_name=(
                        conf_minio_public_bucket_name
                        if param_public_minio_data
                        else conf_minio_user_bucket_name
                    ),
                    object_name=remote_odim_pvol_path.as_posix(),
                    data=file_data,
                    length=file_stat.st_size,
                )
        else:
            print(f"{remote_odim_pvol_path} exists, skipping ")
    print("Finished uploading results")
# cast to string to not break json serializer
odim_pvol_paths = [path.as_posix() for path in odim_pvol_paths]