# cell_2_do_not_containerise
# Get secrets, if they dont exist, set them
from SecretsProvider import SecretsProvider
from getpass import getpass


secrets_provider = SecretsProvider(input_func=getpass)
secret_key_knmi_api = secrets_provider.get_secret("secret_knmi_api_key")
secret_minio_access_key = secrets_provider.get_secret(
    "secret_minio_access_key"
)
secret_minio_secret_key = secrets_provider.get_secret(
    "secret_minio_secret_key"
)