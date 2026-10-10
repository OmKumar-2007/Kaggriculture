"""Concurrent first reads must not race to insert singleton configuration rows."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from backend.services.storage import CompetitionState, EventConfig, PlatformStore


def test_first_competition_and_event_config_reads_are_concurrent_safe(tmp_path):
    store = PlatformStore(tmp_path / "singletons.db")
    gate = Barrier(12)

    def read(index):
        gate.wait()
        return store.competition() if index % 2 else store.event_config()

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(read, range(12)))

    assert len(results) == 12
    with store.session() as db:
        assert db.query(CompetitionState).count() == 1
        assert db.query(EventConfig).count() == 1
