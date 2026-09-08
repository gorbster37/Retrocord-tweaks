import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from services.ra_client import RetroAchievementsClient, RetroAchievementsRateLimited


class FakeResponse:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        pass


class MutableClock:
    def __init__(self):
        self.value = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.value

    async def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds


class RetroAchievementsClientTests(unittest.IsolatedAsyncioTestCase):
    def build_client(self, sessions, **kwargs):
        queue = list(sessions)

        def session_factory():
            return queue.pop(0)

        kwargs.setdefault("daily_window_minutes", 0)
        return RetroAchievementsClient(
            "primary-user",
            "primary-key",
            session_factory=session_factory,
            **kwargs,
        )

    async def test_paces_requests_on_one_credential(self):
        clock = MutableClock()
        session = FakeSession([FakeResponse(200), FakeResponse(200)])
        client = self.build_client(
            [session],
            request_gap_seconds=1,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

        await client.get("first.php", request_type="achievement")
        await client.get("second.php", request_type="achievement")

        self.assertEqual(clock.sleeps, [1])
        self.assertEqual(session.calls[1]["params"]["y"], "primary-key")

    async def test_primary_429_falls_back_to_secondary(self):
        primary = FakeSession([FakeResponse(429)])
        secondary = FakeSession([FakeResponse(200, {"ok": True})])
        client = self.build_client(
            [primary, secondary],
            secondary_username="secondary-user",
            secondary_api_key="secondary-key",
        )

        data = await client.get("endpoint.php", {"u": "tracked-user"}, request_type="achievement")

        self.assertEqual(data, {"ok": True})
        self.assertEqual(secondary.calls[0]["params"]["y"], "secondary-key")
        self.assertEqual(secondary.calls[0]["params"]["u"], "tracked-user")

    async def test_secondary_429_stops_the_request(self):
        primary = FakeSession([FakeResponse(429)])
        secondary = FakeSession([FakeResponse(429)])
        client = self.build_client(
            [primary, secondary],
            secondary_username="secondary-user",
            secondary_api_key="secondary-key",
        )

        with self.assertRaises(RetroAchievementsRateLimited):
            await client.get("endpoint.php", request_type="achievement")

    async def test_retries_a_server_error_after_a_delay(self):
        clock = MutableClock()
        session = FakeSession([FakeResponse(503), FakeResponse(200, {"ok": True})])
        client = self.build_client(
            [session],
            transient_retry_delay_seconds=3,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

        self.assertEqual(
            await client.get("endpoint.php", request_type="achievement"),
            {"ok": True},
        )
        self.assertIn(3, clock.sleeps)

    async def test_non_daily_requests_wait_inside_the_daily_window(self):
        clock = MutableClock()
        client = self.build_client(
            [FakeSession([])],
            daily_window_start="12:00",
            daily_window_timezone="UTC",
            daily_window_minutes=30,
            sleep=clock.sleep,
        )
        now = datetime(2026, 9, 7, 12, 10, tzinfo=ZoneInfo("UTC"))

        self.assertTrue(client._is_in_daily_window(now))
        self.assertEqual(client.seconds_until_daily_window_end(now), 20 * 60)
        client.seconds_until_daily_window_end = lambda: 20 * 60

        await client.wait_for_request_window("achievement")
        await client.wait_for_request_window("daily")

        self.assertEqual(clock.sleeps, [20 * 60])
