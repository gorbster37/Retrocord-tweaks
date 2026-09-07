"""Small JSON cache for broadly static RetroAchievements responses."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Optional


class ApiCache:
    def __init__(self, path: str = "data/api_cache.json", distribution_ttl_hours: int = 24) -> None:
        self.path = Path(path)
        self.distribution_ttl = timedelta(hours=distribution_ttl_hours)
        self._data: Optional[dict] = None

    def get_distribution(self, game_id: int) -> Optional[dict]:
        data = self._load()
        entry = data["achievement_distribution"].get(str(game_id))
        if not entry:
            return None
        try:
            fetched_at = datetime.fromisoformat(entry["fetched_at"])
        except (KeyError, TypeError, ValueError):
            return None
        if datetime.now(timezone.utc) - fetched_at > self.distribution_ttl:
            return None
        return entry.get("data")

    def set_distribution(self, game_id: int, distribution: dict) -> None:
        data = self._load()
        data["achievement_distribution"][str(game_id)] = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "data": distribution,
        }
        self._prune_distributions(data)
        self._save(data)

    def _load(self) -> dict:
        if self._data is not None:
            return self._data
        try:
            with self.path.open("r", encoding="utf-8") as cache_file:
                data = json.load(cache_file)
            if data.get("version") != 1 or not isinstance(
                data.get("achievement_distribution"), dict
            ):
                raise ValueError("Unsupported cache shape")
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            data = {"version": 1, "achievement_distribution": {}}
        self._data = data
        return data

    def _prune_distributions(self, data: dict) -> None:
        now = datetime.now(timezone.utc)
        entries = data["achievement_distribution"]
        expired_keys = []
        for game_id, entry in entries.items():
            try:
                fetched_at = datetime.fromisoformat(entry["fetched_at"])
            except (KeyError, TypeError, ValueError):
                expired_keys.append(game_id)
                continue
            if now - fetched_at > self.distribution_ttl:
                expired_keys.append(game_id)
        for game_id in expired_keys:
            entries.pop(game_id, None)

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        with temp_path.open("w", encoding="utf-8") as cache_file:
            json.dump(data, cache_file, separators=(",", ":"))
        temp_path.replace(self.path)
