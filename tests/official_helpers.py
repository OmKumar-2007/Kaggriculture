"""Arrange an open Round 1 for storage-level tests."""
from datetime import timedelta

from backend.services.storage import CompetitionState, utc_now


def open_round_one(store):
    with store.session() as db:
        state = db.get(CompetitionState, 1)
        if state is None:
            state = CompetitionState(id=1)
            db.add(state)
        state.phase = "QUALIFICATION_OPEN"
        state.started_at = utc_now() - timedelta(seconds=1)


def official_payload():
    return {"submissionSha256": "a" * 64}
