import discord
import json
import random
import time

from services.api import UserProfile, GameDetails
from utils.custom_logger import logger


async def process_presence(bot, user, api_username, api_key):
    """Process the presence of a user in Discord by randomly setting their rich presence from games.json or adding new games.

    Args:
        bot: The Discord bot instance.
        user: The user for whom the presence is being processed.
        api_username: The API username for fetching user data.
        api_key: The API key for authentication.

    Returns:
        None

    Raises:
        Exception: If an error occurs during the processing.

    Examples:
        await process_presence(bot_instance, user_instance, 'api_username', 'api_key')
    """
    try:
        # Fetch user profile and last game played
        user_profile = UserProfile(user, api_username, api_key)
        profile = user_profile.get_profile()
        last_game_id = profile.last_game_id

        def get_or_fetch_game(game_id):
            try:
                with open('games.json', 'r') as f:
                    games = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                logger.warning("games.json not found or corrupted, starting fresh.")
                games = {}

            # If the game is not in games.json, fetch and add it
            if str(game_id) not in games:
                logger.info(f"Fetching game ID {game_id} from API.")
                game_details = GameDetails(game_id, api_username, api_key)
                game = game_details.get_game()
                games[str(game_id)] = {
                    "user": user,
                    "title": game.title,
                    "platform": game.remap_console_name(),
                    "last_seen": time.time()
                }

                # Save the new game to games.json
                with open('games.json', 'w') as f:
                    json.dump(games, f, indent=4)
            else:
                logger.info(f"Game ID {game_id} found in JSON.")
            return games

        # Fetch or add the last played game to games.json
        games = get_or_fetch_game(last_game_id)

        # Pick a random game from the updated games.json
        # Sort games by most recent activity
        sorted_games = sorted(
            games.items(),
            key=lambda item: item[1].get("last_seen", 0),
            reverse=True
        )

        # Take only the last 5 most recent games
        recent_games = sorted_games[:5]

        # Safety fallback (if games.json is empty)
        if not recent_games:
            return

        # Remove same user as last presence (no back-to-back users)
        if process_presence.last_presence_user is not None:
            filtered_games = [
                g for g in recent_games
                if g[1].get("user") != process_presence.last_presence_user
            ]

            # If filtering removes everything, fall back to original list
            if filtered_games:
                recent_games = filtered_games

        # Pick randomly from recent pool
        random_game_id, game_data = random.choice(recent_games)

        # Extract selected game info
        game_title = game_data.get("title")
        game_platform = game_data.get("platform")
        game_user = game_data.get("user")

        # Store last user to prevent repeats
        process_presence.last_presence_user = game_user

        # Update last_seen for selected game
        games[random_game_id]["last_seen"] = time.time()

        # Save updated games.json
        with open('games.json', 'w') as f:
            json.dump(games, f, indent=4)

        # Set rich presence to a randomly selected game
        await bot.change_presence(activity=discord.Game(name=f"{game_title} ({game_platform}) | User: {game_user}"))
        logger.info(f"Setting rich presence for {user} to {game_title} ({game_platform})")

    except Exception as e:
        logger.error(f'Error processing user {user}: {e}')
