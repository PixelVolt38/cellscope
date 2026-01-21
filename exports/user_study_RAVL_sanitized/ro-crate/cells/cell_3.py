# cell_3_do_not_containerize
# Use to re-set existing keys
from SecretsProvider import SecretsProvider
from getpass import getpass


secrets_provider = SecretsProvider(input_func=getpass)
secrets_provider.set_secret("secret_knmi_api_key")
secrets_provider.set_secret("secret_minio_access_key")
secrets_provider.set_secret("secret_minio_secret_key")