import asyncio

from starlette.requests import Request
import backend.main as main


def test_completed_job_streams_event(monkeypatch):
    job = {
        "id": "test-job-123",
        "team": None,
        "type": "sandbox",
        "status": "completed",
        "result": {"status": "success"},
    }

    monkeypatch.setattr(main.store, "get_job", lambda job_id: job)
    monkeypatch.setattr(main, "queue_position", lambda job: None)

    async def read_events():
        request = Request({
            "type": "http",
            "method": "GET",
            "headers": [],
        })

        response = await main.job_events("test-job-123", request)

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        return "".join(chunks)

    output = asyncio.run(read_events())

    assert "event: job" in output
    assert '"status": "completed"' in output
