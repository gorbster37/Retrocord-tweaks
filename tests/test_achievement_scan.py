import unittest
from datetime import datetime, timezone

from services.achievement_scan import AchievementScanState


class Achievement:
    def __init__(self, date):
        self.date = date


class AchievementScanStateTests(unittest.TestCase):
    def test_delayed_scan_uses_a_wider_lookback_and_filters_old_results(self):
        state = AchievementScanState(interval_minutes=30)
        first_scan = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
        delayed_scan = datetime(2026, 9, 7, 12, 45, tzinfo=timezone.utc)

        self.assertEqual(state.lookback_minutes("player", first_scan), 30)
        state.mark_successful({"player": first_scan})

        self.assertEqual(state.lookback_minutes("player", delayed_scan), 46)
        achievements = [
            Achievement("2026-09-07 12:00:00"),
            Achievement("2026-09-07 12:10:00"),
        ]
        self.assertEqual(state.filter_new("player", achievements), achievements[1:])
