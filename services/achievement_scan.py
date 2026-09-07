"""In-memory state that makes delayed achievement scans safe."""

from datetime import datetime, timezone
from math import ceil
from typing import Dict, Iterable, List


class AchievementScanState:
    def __init__(self, interval_minutes: int, safety_buffer_minutes: int = 1) -> None:
        self.interval_minutes = interval_minutes
        self.safety_buffer_minutes = safety_buffer_minutes
        self._last_successful_scan_at: Dict[str, datetime] = {}

    def lookback_minutes(self, user: str, started_at: datetime) -> int:
        marker = self._last_successful_scan_at.get(user)
        if marker is None:
            return self.interval_minutes
        elapsed_minutes = (started_at - marker).total_seconds() / 60
        return max(
            self.interval_minutes,
            ceil(elapsed_minutes) + self.safety_buffer_minutes,
        )

    def filter_new(self, user: str, achievements: Iterable[object]) -> List[object]:
        marker = self._last_successful_scan_at.get(user)
        if marker is None:
            return list(achievements)
        return [
            achievement
            for achievement in achievements
            if self._achievement_time(achievement) > marker
        ]

    def mark_successful(self, markers: Dict[str, datetime]) -> None:
        self._last_successful_scan_at.update(markers)

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _achievement_time(achievement: object) -> datetime:
        value = getattr(achievement, "date")
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
