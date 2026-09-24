"""Rate limits per client IP: 120 requests a minute overall, 30 of them writes."""

import httpx

from tests.api.envelope import expect

ID = "00000000-0000-4000-8000-000000000001"
EVERY_ROUTE = [
    ("GET", "/patients"),
    ("POST", "/patients"),
    ("GET", f"/patients/{ID}"),
    ("PUT", f"/patients/{ID}"),
    ("DELETE", f"/patients/{ID}"),
    ("GET", f"/patients/{ID}/calls"),
    ("GET", f"/patients/{ID}/appointments"),
    ("GET", "/calls"),
    ("GET", f"/calls/{ID}"),
    ("GET", "/doctors"),
    ("GET", "/dashboard/config"),
]


def _assert_rate_limited(response: httpx.Response) -> None:
    error = expect(response, 429)
    assert error["code"] == "RATE_LIMITED"
    assert 1 <= int(response.headers["retry-after"]) <= 60


async def test_writes_are_limited_to_30_a_minute(client: httpx.AsyncClient):
    for _ in range(30):
        expect(await client.post("/patients", json={}), 422)

    _assert_rate_limited(await client.post("/patients", json={}))
    expect(await client.get("/patients"), 200)  # reads still have room


async def test_every_route_shares_120_requests_a_minute(client: httpx.AsyncClient):
    for _ in range(120):
        expect(await client.get("/dashboard/config"), 200)

    for method, path in EVERY_ROUTE:
        body = {} if method in {"POST", "PUT"} else None
        _assert_rate_limited(await client.request(method, path, json=body))
    expect(await client.get("/health"), 200)  # never limited, for the uptime pinger
