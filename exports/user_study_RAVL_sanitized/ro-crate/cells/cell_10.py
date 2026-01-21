# cell_10_pvol_vp_converter
import pandas as pd
import re
import pathlib


def str2bool(v):
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "t", "y", "1"):
        return True
    elif v.lower() in ("no", "false", "f", "n", "0"):
        return False
    else:
        raise Exception


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
    """"""
    # class FileTranslatorFileTypeError(LookupError):
    #    '''raise this when there's a filetype mismatch derived from h5 file'''
    if not isinstance(wmo_code, int):
        raise ValueError("Expecting a wmo_code [int]")
    else:
        pass
    odim_code = (
        radar_db.get(wmo_code).get("odimcode").upper().strip()
    )  # Apparently, people sometimes forget to remove whitespace..
    return odim_code


def extract_wmo_code(in_path):
    with h5py.File(in_path, "r") as f:
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
                "Something went wrong with determining the rad_str and it wasnt WMO either, exiting"
            )
            sys.exit(1)
        # Split the rad_str
        rad_str_split = rad_str.split(":")
        # [0] = RAD, [1] = rad code
        rad_code = rad_str_split[1]
        rad_codes = {"NL52": "6356", "NL51": "6234", "NL50": "6260"}
        wmo_code = rad_codes.get(rad_code)
    return int(wmo_code)


def vol2bird(
    in_file,
    out_dir,
    radar_db,
    add_version=True,
    add_sector=False,
    overwrite=False,
):
    # Construct output file
    date_regex = "([0-9]{8})"
    if add_version == True:
        version = "v0-3-20"
        suffix = pathlib.Path(in_file).suffix
        in_file_name = pathlib.Path(in_file).name
        in_file_stem = pathlib.Path(in_file_name).stem
        #
        out_file_name = in_file_stem.replace("pvol", "vp")
        out_file_name = "_".join([out_file_name, version]) + suffix
        # odim = odim_code(out_file_name)
        wmo = extract_wmo_code(in_file)
        odim = translate_wmo_odim(radar_db, wmo)
        datetime = pd.to_datetime(re.search(date_regex, out_file_name)[0])
        ibed_path = "/".join(
            [
                odim[:2],
                odim[2:],
                str(datetime.year),
                str(datetime.month).zfill(2),
                str(datetime.day).zfill(2),
            ]
        )
        # check if we need to make this dir
        out_file = "/".join([out_dir, ibed_path, out_file_name])
        out_file_dir = pathlib.Path(out_file).parent
        if not out_file_dir.exists():
            out_file_dir.mkdir(parents=True)

    process = False
    if not overwrite:
        if not pathlib.Path(out_file).exists():
            process = True
            print(f"Not processing, overwrite is set to {overwrite}")
    else:
        process = True

    if process:
        command = ["vol2bird", in_file, out_file]
        result = subprocess.run(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT
        )
    return [in_file, out_file]


def get_vp_storage_path(relative_path: str = "") -> str:
    if param_public_minio_data:
        return (
            pathlib.Path(conf_minio_public_root_prefix)
            .joinpath(conf_minio_tutorial_prefix)
            .joinpath(conf_vp_output_prefix)
            .joinpath(relative_path)
        )
    else:
        return (
            pathlib.Path(conf_minio_tutorial_prefix)
            .joinpath(conf_user_directory + param_user_number)
            .joinpath(conf_vp_output_prefix)
            .joinpath(relative_path)
        )


vertical_profile_paths = []
radar_db = load_radar_db(conf_local_radar_db)
# cast back to pathlib after deserializing
odim_pvol_paths = [pathlib.Path(path) for path in odim_pvol_paths]
for odim_pvol_path in odim_pvol_paths:
    pvol_path, vp_path = vol2bird(
        odim_pvol_path, conf_local_vp, radar_db, overwrite=False
    )
    vertical_profile_paths.append(vp_path)
print(vertical_profile_paths)

if str2bool(param_clean_pvol_output):
    print("Removing PVOL output from local storage")
    for pvol_path in odim_pvol_paths:
        pathlib.Path(pvol_path).unlink()
        if not any(pathlib.Path(pvol_path).parent.iterdir()):
            pathlib.Path(pvol_path).parent.rmdir()

if str2bool(param_upload_results):
    # Minio version
    from minio import Minio

    minioClient = Minio(
        endpoint=conf_minio_endpoint,
        access_key=secret_minio_access_key,
        secret_key=secret_minio_secret_key,
        secure=True,
    )
    print(f"Uploading results to {get_vp_storage_path()}")
    for vp_path in vertical_profile_paths:
        vp_path = pathlib.Path(vp_path)
        local_vp_storage = pathlib.Path(conf_local_vp)
        relative_path = vp_path.relative_to(local_vp_storage)
        remote_vp_path = get_vp_storage_path(relative_path)
        # check if this exists
        exists = False
        try:
            _ = minioClient.stat_object(
                bucket=(
                    conf_minio_public_bucket_name
                    if param_public_minio_data
                    else conf_minio_user_bucket_name
                ),
                prefix=remote_vp_path.as_posix(),
            )
            exists = True
        except:
            pass
        if not exists:
            print(f"Uploading {vp_path} to {remote_vp_path}")
            with open(vp_path, mode="rb") as file_data:
                file_stat = os.stat(vp_path)
                minioClient.put_object(
                    bucket_name=(
                        conf_minio_public_bucket_name
                        if param_public_minio_data
                        else conf_minio_user_bucket_name
                    ),
                    object_name=remote_vp_path.as_posix(),
                    data=file_data,
                    length=file_stat.st_size,
                )
        else:
            print(f"{remote_vp_path} exists, skipping ")
    print("Finished uploading results")
if str2bool(param_clean_vp_output):
    print("Removing VP output from local storage")
    for vp_path in vertical_profile_paths:
        pathlib.Path(vp_path).unlink()
        if not any(pathlib.Path(vp_path).parent.iterdir()):
            pathlib.Path(vp_path).parent.rmdir()

PVOL_VP_converter_complete = 1