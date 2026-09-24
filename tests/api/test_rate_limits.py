"""Rate limits per client IP: 120 requests a minute overall, 30 of them writes."""

import httpx

from tests.api.envelope import expect


def _assert_rate_limited(response: httpx.Response) -> None:
    error = expect(response, 429)
    assert error["code"] == "RATE_LIMITED"
    assert 1 <= int(response.headers["retry-after"]) <= 60


async def test_writes_are_limited_to_30_a_minute(client: httpx.AsyncClient):
    for _ in range(30):
        expect(await client.post("/patients", json={}), 422)

    _assert_rate_limited(await client.post("/patients", json={}))
    expect(await client.get("/patients"), 200)  # reads still have room


async def test_all_requests_share_120_a_minute(client: httpx.AsyncClient):
    for _ in range(120):
        expect(await client.get("/dashboard/config"), 200)

    _assert_rate_limited(await client.get("/patients"))
    _assert_rate_limited(await client.post("/patients", json={}))
    expect(await client.get("/health"), 200)  # never limited, for the uptime pinger
