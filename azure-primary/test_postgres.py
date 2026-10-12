"""Approved isolated PostgreSQL smoke test; never connects to Render or Neon."""
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg
from sqlalchemy import inspect, text
from sqlalchemy.engine import URL

from backend.services.storage import PlatformStore


HOST = "farmcraftpgtest20261011omk.postgres.database.azure.com"
DATABASE = "farmcraft_test"
USER = "farmcrafttestadmin"


def main() -> None:
    password = os.environ.pop("FARMCRAFT_PG_TEST_PASSWORD")
    connection_args = dict(host=HOST, dbname=DATABASE, user=USER,
                           password=password, connect_timeout=15)
    with psycopg.connect(**connection_args, sslmode="require") as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
            assert cursor.fetchone()[0] is True
            cursor.execute("SELECT current_database()")
            assert cursor.fetchone()[0] == DATABASE
    print("TLS connection: passed")

    try:
        with psycopg.connect(**connection_args, sslmode="disable"):
            raise AssertionError("Unencrypted connection was unexpectedly accepted")
    except psycopg.OperationalError:
        print("Unencrypted connection rejection: passed")

    url = URL.create("postgresql+psycopg", username=USER, password=password,
                     host=HOST, database=DATABASE, query={"sslmode": "require"})
    store = PlatformStore(url.render_as_string(hide_password=False))
    tables = set(inspect(store.engine).get_table_names())
    assert {"teams", "simulation_jobs", "event_config"}.issubset(tables)
    assert store.ping()
    print(f"SQLAlchemy schema initialization: passed ({len(tables)} tables)")

    probe_id = str(uuid.uuid4())
    with store.engine.begin() as connection:
        connection.execute(text("CREATE TABLE IF NOT EXISTS phase3_probe (id text PRIMARY KEY, value text NOT NULL)"))
        connection.execute(text("INSERT INTO phase3_probe (id, value) VALUES (:id, :value)"),
                           {"id": probe_id, "value": "persisted"})
    with store.engine.connect() as first, store.engine.connect() as second:
        assert first.execute(text("SELECT 1")).scalar_one() == 1
        assert second.execute(text("SELECT 1")).scalar_one() == 1
        assert store.engine.pool.checkedout() >= 2
    store.engine.dispose()
    with store.engine.connect() as connection:
        assert connection.execute(text("SELECT value FROM phase3_probe WHERE id = :id"),
                                  {"id": probe_id}).scalar_one() == "persisted"
    print("Write/read persistence, two pooled connections, and reconnect: passed")


if __name__ == "__main__":
    main()
