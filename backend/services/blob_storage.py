"""Storage abstraction for contestant source and replay artifacts."""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]

class StorageUnavailable(RuntimeError):
    pass

class LocalObjectStorage:
    def __init__(self, root: Path | None = None):
        self.root = Path(root or os.getenv("LOCAL_STORAGE_ROOT", ROOT / "data" / "objects"))
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("Invalid object key.")
        return path

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        pending = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with pending.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if os.name != "nt": pending.chmod(0o600)
            os.replace(pending, path)
        finally:
            pending.unlink(missing_ok=True)
        return key

    def get_bytes(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file(): raise FileNotFoundError(key)
        return path.read_bytes()

    def exists(self, key: str) -> bool: return self._path(key).is_file()
    def delete_prefix(self,prefix: str):
        target=(self.root/prefix).resolve()
        if self.root.resolve() not in target.parents:raise ValueError("Invalid object prefix.")
        if target.is_dir():shutil.rmtree(target)
        elif target.is_file():target.unlink()
    def healthcheck(self) -> bool:
        self.root.mkdir(parents=True, exist_ok=True); return self.root.is_dir()

class S3ObjectStorage:
    def __init__(self):
        import boto3
        from botocore.config import Config
        endpoint=os.environ["OBJECT_STORAGE_ENDPOINT"]; self.bucket=os.environ["OBJECT_STORAGE_BUCKET"]
        self.client=boto3.client("s3",endpoint_url=endpoint,aws_access_key_id=os.environ["OBJECT_STORAGE_ACCESS_KEY"],aws_secret_access_key=os.environ["OBJECT_STORAGE_SECRET_KEY"],region_name=os.getenv("OBJECT_STORAGE_REGION","auto"),config=Config(s3={"addressing_style":"path"}))
    def put_bytes(self,key,data,content_type="application/octet-stream"):
        self.client.put_object(Bucket=self.bucket,Key=key,Body=data,ContentType=content_type);return key
    def get_bytes(self,key): return self.client.get_object(Bucket=self.bucket,Key=key)["Body"].read()
    def exists(self,key):
        try:self.client.head_object(Bucket=self.bucket,Key=key);return True
        except Exception:return False
    def delete_prefix(self,prefix):
        paginator=self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket,Prefix=prefix):
            objects=page.get("Contents",[])
            if objects:self.client.delete_objects(Bucket=self.bucket,Delete={"Objects":[{"Key":row["Key"]} for row in objects]})
    def healthcheck(self): self.client.head_bucket(Bucket=self.bucket);return True


class AzureBlobStorage:
    """Private Azure Blob container accessed with the API's managed identity."""
    def __init__(self):
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient
        account_url = os.environ["AZURE_STORAGE_ACCOUNT_URL"]
        self.container = os.environ["AZURE_STORAGE_CONTAINER"]
        if not account_url.startswith("https://"):
            raise StorageUnavailable("AZURE_STORAGE_ACCOUNT_URL must use HTTPS.")
        self.max_bytes = int(os.getenv("AZURE_MAX_OBJECT_BYTES", str(64 * 1024 * 1024)))
        self.client = BlobServiceClient(account_url=account_url, credential=DefaultAzureCredential(), retry_total=3)

    @staticmethod
    def _key(key: str) -> str:
        if (not isinstance(key, str) or not key or len(key) > 1024 or
            not re.fullmatch(r"[A-Za-z0-9_./-]+", key) or
            any(part in ("", ".", "..") for part in key.split("/"))):
            raise ValueError("Invalid object key.")
        return key

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        from azure.storage.blob import ContentSettings
        if len(data) > self.max_bytes:
            raise ValueError("Object exceeds the configured Azure Blob size limit.")
        self.client.get_blob_client(self.container, self._key(key)).upload_blob(
            data, overwrite=key.startswith("replays/"), content_settings=ContentSettings(content_type=content_type))
        return key

    def get_bytes(self, key: str) -> bytes:
        from azure.core.exceptions import ResourceNotFoundError
        try:
            data = bytearray()
            for chunk in self.client.get_blob_client(self.container, self._key(key)).download_blob().chunks():
                data.extend(chunk)
                if len(data) > self.max_bytes:
                    raise StorageUnavailable("Stored object exceeds the configured Azure Blob size limit.")
            return bytes(data)
        except ResourceNotFoundError as exc:
            raise FileNotFoundError(key) from exc

    def exists(self, key: str) -> bool:
        return self.client.get_blob_client(self.container, self._key(key)).exists()

    def delete_prefix(self, prefix: str) -> None:
        prefix = self._key(prefix)
        container = self.client.get_container_client(self.container)
        for item in container.list_blobs(name_starts_with=prefix):
            container.delete_blob(item.name)

    def healthcheck(self) -> bool:
        return bool(self.client.get_container_client(self.container).get_container_properties())

def build_storage():
    backend=os.getenv("STORAGE_BACKEND","local").lower()
    if backend=="local":return LocalObjectStorage()
    if backend=="s3":return S3ObjectStorage()
    if backend=="azure":return AzureBlobStorage()
    raise StorageUnavailable(f"Unsupported STORAGE_BACKEND: {backend}")

objects=build_storage()
