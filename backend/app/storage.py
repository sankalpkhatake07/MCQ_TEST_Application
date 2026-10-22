"""Pluggable object storage for snapshots, images and generated files: local | s3 | azure | gcs."""
import os
from pathlib import Path

from . import config


class StorageError(Exception):
    pass


class LocalStorage:
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents:
            raise StorageError("invalid key")
        return p

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, p)

    def get(self, key: str) -> bytes:
        p = self._path(key)
        if not p.exists():
            raise FileNotFoundError(key)
        return p.read_bytes()

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink()
        except FileNotFoundError:
            pass


class S3Storage:
    def __init__(self):
        import boto3
        self.bucket = config.S3_BUCKET
        self.client = boto3.client("s3", region_name=config.S3_REGION, endpoint_url=config.S3_ENDPOINT)

    def put(self, key, data, content_type="application/octet-stream"):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def get(self, key):
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self.client.exceptions.NoSuchKey as e:
            raise FileNotFoundError(key) from e

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=key)


class AzureStorage:
    def __init__(self):
        from azure.storage.blob import BlobServiceClient
        svc = BlobServiceClient.from_connection_string(config.AZURE_CONNECTION_STRING)
        self.container = svc.get_container_client(config.AZURE_CONTAINER)
        try:
            self.container.create_container()
        except Exception:  # already exists
            pass

    def put(self, key, data, content_type="application/octet-stream"):
        from azure.storage.blob import ContentSettings
        self.container.upload_blob(key, data, overwrite=True, content_settings=ContentSettings(content_type=content_type))

    def get(self, key):
        try:
            return self.container.download_blob(key).readall()
        except Exception as e:
            raise FileNotFoundError(key) from e

    def delete(self, key):
        try:
            self.container.delete_blob(key)
        except Exception:
            pass


class GCSStorage:
    def __init__(self):
        from google.cloud import storage
        self.bucket = storage.Client().bucket(config.GCS_BUCKET)

    def put(self, key, data, content_type="application/octet-stream"):
        self.bucket.blob(key).upload_from_string(data, content_type=content_type)

    def get(self, key):
        blob = self.bucket.blob(key)
        if not blob.exists():
            raise FileNotFoundError(key)
        return blob.download_as_bytes()

    def delete(self, key):
        blob = self.bucket.blob(key)
        if blob.exists():
            blob.delete()


_instance = None


def get_storage():
    global _instance
    if _instance is None:
        b = config.STORAGE_BACKEND
        if b == "s3":
            _instance = S3Storage()
        elif b == "azure":
            _instance = AzureStorage()
        elif b == "gcs":
            _instance = GCSStorage()
        else:
            _instance = LocalStorage(config.STORAGE_DIR)
    return _instance
