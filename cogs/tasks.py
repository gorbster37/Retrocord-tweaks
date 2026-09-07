import asyncio
from datetime import time
from zoneinfo import ZoneInfo

from discord.ext import commands, tasks

from config.config import (
    ACHIEVEMENTS_CHANNEL_ID,
    DAILY_OVERVIEW_CHANNEL_ID,
    MASTERY_CHANNEL_ID,
    PRESENCE_INTERVAL,
    RETROACHIEVEMENTS_INTERVAL,
    TASK_START_DELAY,
    api_key,
    api_username,
    users,
)
from services.achievement_scan import AchievementScanState
from services.api_cache import ApiCache
from services.ra_client import RetroAchievementsClient
from src.achievements import process_achievements
from src.daily_overview import process_daily_overview
from src.presence import (
    load_presence_cache,
    process_presence,
    refresh_presence_cache_for_user,
    save_presence_cache,
)
from utils.custom_logger import logger
from utils.datetime import delay_until_next_interval

try:
    from config.config import (
        DAILY_OVERVIEW_EXCLUSIVE_WINDOW_MINUTES,
        DAILY_OVERVIEW_TIME,
        DAILY_OVERVIEW_TIMEZONE,
        RA_CONNECT_TIMEOUT_SECONDS,
        RA_MAX_TRANSIENT_RETRIES,
        RA_RATE_LIMIT_COOLDOWN_SECONDS,
        RA_REQUEST_GAP_SECONDS,
        RA_REQUEST_TIMEOUT_SECONDS,
        RA_SECONDARY_MODE,
        RA_TRANSIENT_RETRY_DELAY_SECONDS,
        secondary_api_key,
        secondary_api_username,
    )
except ImportError:
    DAILY_OVERVIEW_EXCLUSIVE_WINDOW_MINUTES = 30
    DAILY_OVERVIEW_TIME = "00:00"
    DAILY_OVERVIEW_TIMEZONE = "America/New_York"
    RA_CONNECT_TIMEOUT_SECONDS = 5
    RA_MAX_TRANSIENT_RETRIES = 1
    RA_RATE_LIMIT_COOLDOWN_SECONDS = 60
    RA_REQUEST_GAP_SECONDS = 1.0
    RA_REQUEST_TIMEOUT_SECONDS = 20
    RA_SECONDARY_MODE = "fallback"
    RA_TRANSIENT_RETRY_DELAY_SECONDS = 3
    secondary_api_key = ""
    secondary_api_username = ""


def daily_schedule_time(value: str, timezone_name: str) -> time:
    try:
        hour, minute = (int(part) for part in value.split(":", 1))
        return time(hour=hour, minute=minute, tzinfo=ZoneInfo(timezone_name))
    except (TypeError, ValueError) as error:
        raise ValueError("DAILY_OVERVIEW_TIME must use HH:MM 24-hour format.") from error


DAILY_SCHEDULE_TIME = daily_schedule_time(DAILY_OVERVIEW_TIME, DAILY_OVERVIEW_TIMEZONE)


class TasksCog(commands.Cog):
    def __init__(self, bot: commands.Bot, start_delay: dict = None) -> None:
        self.bot = bot
        self.start_delay = start_delay or {}
        self.api_client = RetroAchievementsClient(
            api_username,
            api_key,
            secondary_username=secondary_api_username if RA_SECONDARY_MODE == "fallback" else "",
            secondary_api_key=secondary_api_key if RA_SECONDARY_MODE == "fallback" else "",
            request_gap_seconds=RA_REQUEST_GAP_SECONDS,
            connect_timeout_seconds=RA_CONNECT_TIMEOUT_SECONDS,
            request_timeout_seconds=RA_REQUEST_TIMEOUT_SECONDS,
            transient_retry_delay_seconds=RA_TRANSIENT_RETRY_DELAY_SECONDS,
            max_transient_retries=RA_MAX_TRANSIENT_RETRIES,
            rate_limit_cooldown_seconds=RA_RATE_LIMIT_COOLDOWN_SECONDS,
            daily_window_start=DAILY_OVERVIEW_TIME,
            daily_window_timezone=DAILY_OVERVIEW_TIMEZONE,
            daily_window_minutes=DAILY_OVERVIEW_EXCLUSIVE_WINDOW_MINUTES,
        )
        self.api_cache = ApiCache()
        self.achievement_scan_state = AchievementScanState(RETROACHIEVEMENTS_INTERVAL)
        self.users = users
        self.current_user_index = 0

        self.process_achievements.start()
        self.process_daily_overview.start()
        if not self.start_delay.get("process_daily_overview", False):
            self.bot.loop.create_task(self.run_daily_overview())

        self.presence_preload_task = self.bot.loop.create_task(self.preload_presence_cache())
        self.process_presence.start()

    async def preload_presence_cache(self):
        await self.bot.wait_until_ready()
        cache = load_presence_cache()
        for user in self.users:
            try:
                cache = await refresh_presence_cache_for_user(
                    user,
                    self.api_client,
                    cache,
                    request_type="startup",
                )
                save_presence_cache(cache)
            except Exception as error:
                logger.error(f"Error preloading presence cache for user {user}: {error}")
        logger.info("Finished preloading presence cache.")

    @tasks.loop(minutes=RETROACHIEVEMENTS_INTERVAL)
    async def process_achievements(self):
        achievements_channel = self.bot.get_channel(ACHIEVEMENTS_CHANNEL_ID)
        mastery_channel = self.bot.get_channel(MASTERY_CHANNEL_ID)
        try:
            await process_achievements(
                self.users,
                self.api_client,
                achievements_channel,
                mastery_channel,
                self.achievement_scan_state,
                self.api_cache,
            )
        except Exception as error:
            logger.error(f"Error processing achievements: {error}")

    @process_achievements.before_loop
    async def before_process_achievements(self):
        await self.bot.wait_until_ready()
        if self.start_delay.get("process_achievements", False):
            delay = delay_until_next_interval("retro")
            logger.info(f"Waiting {delay} seconds for Achievements task to start")
            await asyncio.sleep(delay)

    @tasks.loop(time=DAILY_SCHEDULE_TIME)
    async def process_daily_overview(self):
        await self.run_daily_overview()

    async def run_daily_overview(self):
        await self.bot.wait_until_ready()
        channel = self.bot.get_channel(DAILY_OVERVIEW_CHANNEL_ID)
        try:
            await process_daily_overview(self.users, self.api_client, channel)
        except Exception as error:
            logger.error(f"Error processing daily overview: {error}")

    @process_daily_overview.before_loop
    async def before_process_daily_overview(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=PRESENCE_INTERVAL)
    async def process_presence(self):
        try:
            user = self.users[self.current_user_index]
            await process_presence(self.bot, user, self.api_client)
            self.current_user_index = (self.current_user_index + 1) % len(self.users)
        except Exception as error:
            logger.error(f"Error processing presence: {error}")

    @process_presence.before_loop
    async def before_process_presence(self):
        await self.bot.wait_until_ready()
        if self.presence_preload_task:
            await self.presence_preload_task
        if self.start_delay.get("process_presence", False):
            delay = delay_until_next_interval("presence")
            logger.info(f"Waiting {delay} seconds for Presence task to start")
            await asyncio.sleep(delay)

    def cog_unload(self):
        self.process_achievements.cancel()
        self.process_daily_overview.cancel()
        self.process_presence.cancel()
        self.api_client.close()


async def setup(bot):
    await bot.add_cog(TasksCog(bot, start_delay=TASK_START_DELAY))
