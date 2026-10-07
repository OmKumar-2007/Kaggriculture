"""Storage abstraction for contestant source and replay artifacts."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

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
        path = self._path(key); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data); return key

    def get_bytes(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file(): raise FileNotFoundError(key)
        return path.read_bytes()

    def exists(self, key: str) -> bool: return self._path(key).is_file()
    def delete_prefix(self,prefix: str):
        target=(self.root/prefix).resolve()
        if self.root.resolve() not in target.parents:raise ValueError("Invalid object prefix.")
        if target.exists():shutil.rmtree(target)
    def healthcheck(self) -> bool:
        self.root.mkdir(parents=True, exist_ok=True); return self.root.is_dir()

class S3ObjectStorage:
    def __init__(self):
        import boto3
        endpoint=os.environ["OBJECT_STORAGE_ENDPOINT"]; self.bucket=os.environ["OBJECT_STORAGE_BUCKET"]
        self.client=boto3.client("s3",endpoint_url=endpoint,aws_access_key_id=os.environ["OBJECT_STORAGE_ACCESS_KEY"],aws_secret_access_key=os.environ["OBJECT_STORAGE_SECRET_KEY"],region_name=os.getenv("OBJECT_STORAGE_REGION","auto"))
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

def build_storage():
    backend=os.getenv("STORAGE_BACKEND","local").lower()
    if backend=="local":return LocalObjectStorage()
    if backend=="s3":return S3ObjectStorage()
    raise StorageUnavailable(f"Unsupported STORAGE_BACKEND: {backend}")

objects=build_storage()
