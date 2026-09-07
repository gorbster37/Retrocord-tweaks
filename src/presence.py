import discord
import json
import random
from datetime import datetime, timedelta

from services.api import get_user_recently_played_games
from services.ra_client import RetroAchievementsClient
from utils.achievement import CONSOLE_NAME_MAP
from utils.custom_logger import logger

try:
    from config.config import PRESENCE_ACTIVE_WINDOW_DAYS
except ImportError:
    PRESENCE_ACTIVE_WINDOW_DAYS = 3

try:
    from config.config import PRESENCE_RECENT_GAMES_COUNT
except ImportError:
    PRESENCE_RECENT_GAMES_COUNT = 2

LAST_PLAYED_FORMAT = "%Y-%m-%d %H:%M:%S"


def load_presence_cache():
    try:
        with open('games.json', 'r') as f:
            cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning("games.json not found or corrupted, starting fresh.")
        return {"users": {}}

    if "users" in cache:
        users_cache = {}
        for cached_user, user_games in cache.get("users", {}).items():
            if isinstance(user_games, list):
                users_cache[cached_user] = user_games
            elif isinstance(user_games, dict):
                users_cache[cached_user] = [{
                    "game_id": user_games.get("game_id"),
                    "title": user_games.get("title"),
                    "platform": user_games.get("platform"),
                    "last_played": user_games.get("last_played")
                }]
        return {"users": users_cache}

    users_cache = {}
    for game_id, game_data in cache.items():
        cached_user = game_data.get("user")
        if cached_user:
            users_cache.setdefault(cached_user, []).append({
                "game_id": str(game_id),
                "title": game_data.get("title"),
                "platform": game_data.get("platform"),
                "last_played": None
            })

    return {"users": users_cache}


def save_presence_cache(cache):
    with open('games.json', 'w') as f:
        json.dump(cache, f, indent=4)


def parse_last_played(last_played, user=None):
    if not last_played:
        return None
    try:
        return datetime.strptime(last_played, LAST_PLAYED_FORMAT)
    except ValueError:
        user_text = f" for user {user}" if user else ""
        logger.warning(f"Invalid LastPlayed value{user_text}: {last_played}")
        return None


def is_recent(last_played, cutoff):
    played_at = parse_last_played(last_played)
    return played_at is not None and played_at >= cutoff


def format_game(game):
    console_name = game.get("ConsoleName", "N/A")
    return {
        "game_id": str(game.get("GameID", "N/A")),
        "title": game.get("Title", "N/A"),
        "platform": CONSOLE_NAME_MAP.get(console_name, console_name),
        "last_played": game.get("LastPlayed")
    }


def update_user_games(cache, user, recent_games, cutoff):
    games_for_user = [
        format_game(game)
        for game in recent_games
        if is_recent(game.get("LastPlayed"), cutoff)
    ]

    users_cache = cache.setdefault("users", {})
    if games_for_user:
        users_cache[user] = games_for_user
        logger.info(f"Found {len(games_for_user)} recently played games for user {user}")
    else:
        users_cache.pop(user, None)
        logger.info(f"No games played within {PRESENCE_ACTIVE_WINDOW_DAYS} days for user {user}")
    return cache


async def refresh_presence_cache_for_user(user, client: RetroAchievementsClient, cache=None, request_type="presence"):
    cutoff = datetime.utcnow() - timedelta(days=PRESENCE_ACTIVE_WINDOW_DAYS)
    user_recent_games = await get_user_recently_played_games(
        client,
        user,
        PRESENCE_RECENT_GAMES_COUNT,
        request_type=request_type,
    )
    return update_user_games(cache or load_presence_cache(), user, user_recent_games, cutoff)


def get_recent_presence_games(cache):
    cutoff = datetime.utcnow() - timedelta(days=PRESENCE_ACTIVE_WINDOW_DAYS)
    active_games = [
        (cached_user, game_data)
        for cached_user, user_games in cache.get("users", {}).items()
        for game_data in user_games
        if is_recent(game_data.get("last_played"), cutoff)
    ]
    active_games.sort(
        key=lambda item: parse_last_played(item[1].get("last_played")) or datetime.min,
        reverse=True
    )
    return active_games[:5]


async def process_presence(bot, user, client: RetroAchievementsClient):
    """Process the presence of a user in Discord from recently played games.

    Args:
        bot: The Discord bot instance.
        user: The user for whom the presence is being processed.
        client: The shared RetroAchievements client.

    Returns:
        None

    Raises:
        Exception: If an error occurs during the processing.

    Examples:
        await process_presence(bot_instance, user_instance, api_client)
    """
    try:
        games = await refresh_presence_cache_for_user(user, client)
        recent_games = get_recent_presence_games(games)

        # Safety fallback (if games.json is empty)
        if not recent_games:
            save_presence_cache(games)
            return

        # Remove same user as last presence (no back-to-back users)
        last_presence_user = getattr(process_presence, "last_presence_user", None)
        if last_presence_user is not None:
            filtered_games = [
                g for g in recent_games
                if g[0] != last_presence_user
            ]

            # If filtering removes everything, fall back to original list
            if filtered_games:
                recent_games = filtered_games

        # Vary the displayed game while keeping the most recently active games eligible.
        game_user, game_data = random.choice(recent_games)

        # Extract selected game info
        game_title = game_data.get("title")
        game_platform = game_data.get("platform")

        # Store last user to prevent repeats
        process_presence.last_presence_user = game_user

        # Save updated games.json
        save_presence_cache(games)

        # Set rich presence to the selected recently played game
        await bot.change_presence(activity=discord.Game(name=f"{game_title} ({game_platform}) | User: {game_user}"))
        logger.info(
            f"Setting rich presence to {game_title} ({game_platform}) for user {game_user}; "
            f"refreshed user {user}"
        )

    except Exception as e:
        logger.error(f'Error processing user {user}: {e}')
