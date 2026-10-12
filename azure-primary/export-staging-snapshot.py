"""Export an internally consistent, private Azure staging DB snapshot.

Run inside the staging API container. This intentionally never prints DB secrets,
row values, or a connection URL. The archive is a trusted Python pickle and must
only be loaded from the verified private Blob object created by this script.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import pickle
from datetime import datetime, timezone

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings
from sqlalchemy import MetaData, create_engine, select


def main() -> None:
    assert os.environ["STORAGE_BACKEND"] == "azure"
    assert os.environ["AZURE_STORAGE_CONTAINER"] == "private-artifacts"
    assert "farmcraftstgpg20261012omk.postgres.database.azure.com/farmcraft" in os.environ["DATABASE_URL"]

    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    metadata = MetaData()
    metadata.reflect(bind=engine)
    tables = {}
    with engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        for table in metadata.sorted_tables:
            tables[table.name] = [dict(row._mapping) for row in connection.execute(select(table))]
        connection.rollback()

    created_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = {"format": "farmcraft-staging-sqlalchemy-rows-v1", "createdAt": created_at,
               "tables": tables, "tableOrder": [table.name for table in metadata.sorted_tables]}
    payload = gzip.compress(pickle.dumps(archive, protocol=5), compresslevel=6)
    digest = hashlib.sha256(payload).hexdigest()
    purpose = os.environ.get("FARMCRAFT_SNAPSHOT_PURPOSE", "pre-load30")
    assert purpose in {"pre-load30", "post-load30"}
    key = f"backups/{purpose}/{created_at}-{digest[:12]}.pkl.gz"
    client = BlobServiceClient(account_url=os.environ["AZURE_STORAGE_ACCOUNT_URL"],
                               credential=DefaultAzureCredential())
    blob = client.get_blob_client(os.environ["AZURE_STORAGE_CONTAINER"], key)
    blob.upload_blob(payload, overwrite=False,
                     content_settings=ContentSettings(content_type="application/gzip"))
    verified = blob.download_blob().readall()
    assert hashlib.sha256(verified).hexdigest() == digest
    loaded = pickle.loads(gzip.decompress(verified))
    assert loaded["format"] == archive["format"]
    assert {name: len(rows) for name, rows in loaded["tables"].items()} == {
        name: len(rows) for name, rows in tables.items()}
    print(json.dumps({"backupKey": key, "sha256": digest, "bytes": len(payload),
                      "tableCounts": {name: len(rows) for name, rows in tables.items()}}, sort_keys=True))


if __name__ == "__main__":
    main()
