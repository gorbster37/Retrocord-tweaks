"""Typed RetroAchievements endpoint helpers backed by the shared client."""

from typing import TYPE_CHECKING, List

from services.api_cache import ApiCache
from services.ra_client import RetroAchievementsClient
from services.progress import Progress
from utils.custom_logger import logger

if TYPE_CHECKING:
    from services.achievement import Achievement
    from services.game import Game, UnlockDistribution
    from services.profile import Profile


async def get_game_details(
    client: RetroAchievementsClient, game_id: int, *, request_type: str
) -> "Game":
    from services.game import Game

    data = await client.get(
        "API_GetGameExtended.php", {"i": game_id}, request_type=request_type
    )
    return Game(data)


async def get_user_recent_achievements(
    client: RetroAchievementsClient,
    username: str,
    minutes: int,
    *,
    request_type: str,
) -> List["Achievement"]:
    from services.achievement import Achievement

    data = await client.get(
        "API_GetUserRecentAchievements.php",
        {"u": username, "m": minutes},
        request_type=request_type,
    )
    return [Achievement(item) for item in data]


async def get_achievements_earned_between(
    client: RetroAchievementsClient,
    username: str,
    start_epoch: int,
    end_epoch: int,
    *,
    request_type: str,
) -> List["Achievement"]:
    from services.achievement import Achievement

    data = await client.get(
        "API_GetAchievementsEarnedBetween.php",
        {"u": username, "f": start_epoch, "t": end_epoch},
        request_type=request_type,
    )
    return [Achievement(item) for item in data]


async def get_user_completion_progress(
    client: RetroAchievementsClient, username: str, *, request_type: str
) -> Progress:
    offset = 0
    results = []
    total = None
    while total is None or offset < total:
        data = await client.get(
            "API_GetUserCompletionProgress.php",
            {"u": username, "c": 500, "o": offset},
            request_type=request_type,
        )
        page = data.get("Results", [])
        results.extend(page)
        total = data.get("Total", len(results))
        count = data.get("Count", len(page))
        if not page or not count:
            break
        offset += count
    return Progress({"Count": len(results), "Total": total or len(results), "Results": results})


async def get_game_info_and_user_progress(
    client: RetroAchievementsClient,
    game_id: int,
    username: str,
    *,
    request_type: str,
) -> "Game":
    from services.game import Game

    data = await client.get(
        "API_GetGameInfoAndUserProgress.php",
        {"u": username, "g": game_id},
        request_type=request_type,
    )
    return Game(data)


async def get_user_profile(
    client: RetroAchievementsClient, username: str, *, request_type: str
) -> "Profile":
    from services.profile import Profile

    data = await client.get(
        "API_GetUserProfile.php", {"u": username}, request_type=request_type
    )
    return Profile(data)


async def get_user_recently_played_games(
    client: RetroAchievementsClient,
    username: str,
    count: int,
    *,
    request_type: str,
) -> list:
    return await client.get(
        "API_GetUserRecentlyPlayedGames.php",
        {"u": username, "c": count},
        request_type=request_type,
    )


async def get_achievement_distribution(
    client: RetroAchievementsClient,
    cache: ApiCache,
    game_id: int,
    *,
    request_type: str,
) -> "UnlockDistribution":
    from services.game import UnlockDistribution

    cached = cache.get_distribution(game_id)
    if cached is not None:
        logger.debug("Using cached achievement distribution for game %s", game_id)
        return UnlockDistribution(cached)
    data = await client.get(
        "API_GetAchievementDistribution.php",
        {"i": game_id, "h": "1", "f": "3"},
        request_type=request_type,
    )
    cache.set_distribution(game_id, data)
    return UnlockDistribution(data)
