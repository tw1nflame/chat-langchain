import minio
from minio import Minio
from minio.error import S3Error
import os
from urllib.parse import urlparse

class MinioManager:
    def __init__(self, endpoint, access_key, secret_key, secure=True):
        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure
        )

    def ensure_bucket(self, bucket_name):
        if not self.client.bucket_exists(bucket_name):
            self.client.make_bucket(bucket_name)

    def upload_file(self, bucket_name, file_path, object_name, content_type=None):
        self.ensure_bucket(bucket_name)
        self.client.fput_object(
            bucket_name,
            object_name,
            file_path,
            content_type=content_type
        )
        return object_name

    def get_file_url(self, bucket_name, object_name, expires=3600):
        return self.client.presigned_get_object(bucket_name, object_name, expires=expires)

    def remove_file(self, bucket_name, object_name):
        self.client.remove_object(bucket_name, object_name)

# Фабрика для создания менеджера из переменных окружения
def get_minio_manager_from_env():
    endpoint = os.getenv('MINIO_ENDPOINT')
    access_key = os.getenv('MINIO_ACCESS_KEY')
    secret_key = os.getenv('MINIO_SECRET_KEY')
    # Allow MINIO_SECURE override; if not provided, infer from scheme when present
    minio_secure_env = os.getenv('MINIO_SECURE')

    # Normalize endpoint: allow values like '127.0.0.1:9000' or 'http://127.0.0.1:9000'
    if endpoint:
        parsed = urlparse(endpoint)
        if parsed.scheme in ('http', 'https'):
            # If path is present and not just '/', reject (Minio endpoint must not contain a path)
            if parsed.path and parsed.path != '/':
                raise RuntimeError(f"MINIO_ENDPOINT must not include a path: {endpoint}")
            endpoint = parsed.netloc
            inferred_secure = parsed.scheme == 'https'
        else:
            # No scheme, assume endpoint provided as host[:port]
            inferred_secure = None
    else:
        inferred_secure = None

    if minio_secure_env is not None:
        secure = minio_secure_env.lower() == 'true'
    else:
        # If scheme was present, use inferred, otherwise default to True
        secure = inferred_secure if inferred_secure is not None else True
    missing = []
    if not endpoint:
        missing.append('MINIO_ENDPOINT')
    if not access_key:
        missing.append('MINIO_ACCESS_KEY')
    if not secret_key:
        missing.append('MINIO_SECRET_KEY')
    if missing:
        raise RuntimeError(f"Missing required Minio environment variables: {', '.join(missing)}")

    # Endpoint must be host[:port] when passed to Minio
    return MinioManager(endpoint, access_key, secret_key, secure)
