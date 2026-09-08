"""Paced RetroAchievements HTTP client shared by every bot feature."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import time
from typing import Callable, Dict, Optional
from zoneinfo import ZoneInfo

import requests

from utils.custom_logger import logger


class RetroAchievementsError(Exception):
    """Base error raised for RetroAchievements requests."""


class RetroAchievementsRateLimited(RetroAchievementsError):
    """Raised when no eligible credential can complete a rate-limited request."""


class RetroAchievementsCredentialError(RetroAchievementsError):
    """Raised when a credential is rejected by RetroAchievements."""


@dataclass
class CredentialLane:
    name: str
    username: str
    api_key: str
    session: requests.Session
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    next_request_at: float = 0.0
    cooldown_until: float = 0.0
    disabled: bool = False


class RetroAchievementsClient:
    """Serialize, pace, and safely retry RetroAchievements API requests."""

    def __init__(
        self,
        api_username: str,
        api_key: str,
        *,
        base_url: str = "https://retroachievements.org",
        secondary_username: str = "",
        secondary_api_key: str = "",
        request_gap_seconds: float = 1.0,
        connect_timeout_seconds: float = 5.0,
        request_timeout_seconds: float = 20.0,
        transient_retry_delay_seconds: float = 3.0,
        max_transient_retries: int = 1,
        rate_limit_cooldown_seconds: float = 60.0,
        daily_window_start: str = "00:00",
        daily_window_timezone: str = "America/New_York",
        daily_window_minutes: int = 30,
        session_factory: Callable[[], requests.Session] = requests.Session,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], object] = asyncio.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.request_gap_seconds = request_gap_seconds
        self.timeout = (connect_timeout_seconds, request_timeout_seconds)
        self.transient_retry_delay_seconds = transient_retry_delay_seconds
        self.max_transient_retries = max_transient_retries
        self.rate_limit_cooldown_seconds = rate_limit_cooldown_seconds
        self.daily_window_minutes = daily_window_minutes
        self.daily_timezone = ZoneInfo(daily_window_timezone)
        self.daily_window_time = self._parse_time(daily_window_start)
        self._monotonic = monotonic
        self._sleep = sleep

        self.primary = CredentialLane("primary", api_username, api_key, session_factory())
        self.secondary: Optional[CredentialLane] = None
        if secondary_username and secondary_api_key:
            self.secondary = CredentialLane(
                "secondary", secondary_username, secondary_api_key, session_factory()
            )

    async def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, object]] = None,
        *,
        request_type: str,
    ) -> dict:
        """Get JSON data, applying pacing and the approved fallback policy."""
        while True:
            await self._wait_for_daily_window(request_type)
            lane = self._select_lane()
            if lane is None:
                raise RetroAchievementsRateLimited(
                    "No RetroAchievements credential is currently available."
                )

            try:
                return await self._get_from_lane(lane, endpoint, params, request_type)
            except _CredentialCoolingDown:
                continue
            except RetroAchievementsRateLimited:
                if lane is self.primary and self.secondary and self._is_available(self.secondary):
                    return await self._get_from_lane(
                        self.secondary, endpoint, params, request_type
                    )
                raise

    async def wait_for_request_window(self, request_type: str) -> None:
        """Wait until this request type is allowed to start."""
        await self._wait_for_daily_window(request_type)

    async def _get_from_lane(
        self,
        lane: CredentialLane,
        endpoint: str,
        params: Optional[Dict[str, object]],
        request_type: str,
    ) -> dict:
        retries = 0
        while True:
            try:
                response = await self._send(lane, endpoint, params, request_type)
            except (requests.ConnectionError, requests.Timeout) as error:
                if retries >= self.max_transient_retries:
                    logger.warning(
                        f"RetroAchievements {endpoint} failed after {retries} retries: {error}"
                    )
                    raise RetroAchievementsError(str(error)) from error
                retries += 1
                logger.warning(
                    f"RetroAchievements {endpoint} connection failure; retrying in "
                    f"{self.transient_retry_delay_seconds}s ({retries}/{self.max_transient_retries})"
                )
                await self._sleep(self.transient_retry_delay_seconds)
                continue

            if response.status_code == 429:
                self._set_rate_limit_cooldown(lane, response.headers.get("Retry-After"))
                logger.warning(
                    f"RetroAchievements {endpoint} rate-limited the {lane.name} credential"
                )
                raise RetroAchievementsRateLimited(
                    f"RetroAchievements rate-limited the {lane.name} credential."
                )

            if response.status_code in (401, 403):
                lane.disabled = True
                logger.error(
                    f"RetroAchievements rejected the {lane.name} credential with status "
                    f"{response.status_code}"
                )
                raise RetroAchievementsCredentialError(
                    f"RetroAchievements rejected the {lane.name} credential."
                )

            if response.status_code in (500, 502, 503, 504):
                if retries >= self.max_transient_retries:
                    response.raise_for_status()
                retries += 1
                logger.warning(
                    f"RetroAchievements {endpoint} returned {response.status_code}; retrying in "
                    f"{self.transient_retry_delay_seconds}s ({retries}/{self.max_transient_retries})"
                )
                await self._sleep(self.transient_retry_delay_seconds)
                continue

            response.raise_for_status()
            try:
                return response.json()
            except ValueError as error:
                raise RetroAchievementsError(
                    f"RetroAchievements {endpoint} returned invalid JSON."
                ) from error

    async def _send(
        self,
        lane: CredentialLane,
        endpoint: str,
        params: Optional[Dict[str, object]],
        request_type: str,
    ) -> requests.Response:
        # Keep the lock while the worker thread runs so a Session is never shared concurrently.
        async with lane.lock:
            if not self._is_available(lane):
                raise _CredentialCoolingDown()

            await self._wait_for_lane_gap(lane)
            if self._is_in_daily_window() and request_type != "daily":
                raise _CredentialCoolingDown()
            if not self._is_available(lane):
                raise _CredentialCoolingDown()

            request_params = {"z": lane.username, "y": lane.api_key}
            if params:
                request_params.update(params)

            lane.next_request_at = self._monotonic() + self.request_gap_seconds
            started_at = self._monotonic()
            response = await asyncio.to_thread(
                lane.session.get,
                f"{self.base_url}/API/{endpoint}",
                params=request_params,
                timeout=self.timeout,
            )
            duration = self._monotonic() - started_at
            logger.debug(
                f"RetroAchievements {endpoint} via {lane.name} returned "
                f"{response.status_code} in {duration:.2f}s"
            )
            return response

    async def _wait_for_lane_gap(self, lane: CredentialLane) -> None:
        delay = lane.next_request_at - self._monotonic()
        if delay > 0:
            await self._sleep(delay)

    async def _wait_for_daily_window(self, request_type: str) -> None:
        if request_type == "daily":
            return
        delay = self.seconds_until_daily_window_end()
        if delay > 0:
            logger.info(
                f"Waiting {delay:.1f}s for the Daily Overview exclusive window to end"
            )
            await self._sleep(delay)

    def _select_lane(self) -> Optional[CredentialLane]:
        if self._is_available(self.primary):
            return self.primary
        if self.primary.disabled:
            return None
        if self.secondary and self._is_available(self.secondary):
            return self.secondary
        return None

    def _is_available(self, lane: CredentialLane) -> bool:
        return not lane.disabled and self._monotonic() >= lane.cooldown_until

    def _set_rate_limit_cooldown(self, lane: CredentialLane, retry_after: Optional[str]) -> None:
        cooldown = self.rate_limit_cooldown_seconds
        if retry_after:
            try:
                cooldown = max(cooldown, float(retry_after))
            except ValueError:
                pass
        lane.cooldown_until = self._monotonic() + cooldown

    def _is_in_daily_window(self, now: Optional[datetime] = None) -> bool:
        if self.daily_window_minutes <= 0:
            return False
        current = now.astimezone(self.daily_timezone) if now else datetime.now(self.daily_timezone)
        start = current.replace(
            hour=self.daily_window_time.hour,
            minute=self.daily_window_time.minute,
            second=0,
            microsecond=0,
        )
        if current < start:
            start -= timedelta(days=1)
        return start <= current < start + timedelta(minutes=self.daily_window_minutes)

    def seconds_until_daily_window_end(self, now: Optional[datetime] = None) -> float:
        if not self._is_in_daily_window(now):
            return 0.0
        current = now.astimezone(self.daily_timezone) if now else datetime.now(self.daily_timezone)
        start = current.replace(
            hour=self.daily_window_time.hour,
            minute=self.daily_window_time.minute,
            second=0,
            microsecond=0,
        )
        if current < start:
            start -= timedelta(days=1)
        return max(0.0, (start + timedelta(minutes=self.daily_window_minutes) - current).total_seconds())

    def close(self) -> None:
        self.primary.session.close()
        if self.secondary:
            self.secondary.session.close()

    @staticmethod
    def _parse_time(value: str):
        try:
            hour, minute = (int(part) for part in value.split(":", 1))
            if not 0 <= hour <= 23 or not 0 <= minute <= 59:
                raise ValueError
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError("DAILY_OVERVIEW_TIME must use HH:MM 24-hour format.") from error
        return datetime(2000, 1, 1, hour, minute).time()


class _CredentialCoolingDown(Exception):
    """Internal signal used when queue state changes while a request is waiting."""
