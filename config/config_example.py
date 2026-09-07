"""	
This is an example configuration file. You should rename this file to config.py and fill in the values.

api_key: Your RetroAchievements API key
api_username: Your RetroAchievements username that belongs to the API key
token: Your Discord bot token
users: A list of RetroAchievements usernames to track, for example ["User1", "User2", "User3"]

DISCORD_IMAGE: The image URL to use for Discord embeds, this uses a transparent image by default to set a max width, recommended not to change
RETRO_DAILY_IMAGE: The image URL to use for the daily RetroAchievements embed, this is a placeholder by default

ACHIEVEMENTS_CHANNEL_ID: The Discord channel ID to send achievement updates to
DAILY_OVERVIEW_CHANNEL_ID: The Discord channel ID to send the daily RetroAchievements embed to
MASTERY_CHANNEL_ID: The Discord channel ID to send the mastery updates to
RETROACHIEVEMENTS_INTERVAL: The number of minutes to wait between Achievement scans, default is 30 minutes
PRESENCE_INTERVAL: The number of minutes to wait between Presence requests, default is 120 minutes, minimum is 1 minute
PRESENCE_ACTIVE_WINDOW_DAYS: The number of days a user's recently played games remain eligible for presence, default is 3 days
PRESENCE_RECENT_GAMES_COUNT: The number of recently played games to fetch per presence check, default is 2
secondary_api_username / secondary_api_key: Optional fallback credential, used only after a primary 429 response
RA_*: RetroAchievements request pacing, timeout, retry, cooldown, and fallback settings
DAILY_OVERVIEW_TIMEZONE / DAILY_OVERVIEW_TIME: The local timezone and daily run time, for example America/New_York and 00:00
DAILY_OVERVIEW_EXCLUSIVE_WINDOW_MINUTES: The period after the scheduled daily run where only Daily Overview API calls start
EMBED_IMAGE_TIMEOUT_SECONDS: Timeout for non-RetroAchievements image downloads used to calculate embed colors
TASK_START_DELAY: A dictionary to specify whether achievement and presence tasks start immediately or wait for their next interval
"""

api_key = ""
api_username = ""
# Optional fallback credential. It is used only after a primary 429 response.
secondary_api_key = ""
secondary_api_username = ""
token = ''
users = []

BASE_URL = "https://retroachievements.org"

DISCORD_IMAGE = "https://i.postimg.cc/KvSTwcQ0/undefined-Imgur.png"
RETRO_DAILY_IMAGE = "https://i.imgur.com/P0nEGGs.png"

ACHIEVEMENTS_CHANNEL_ID = ""
DAILY_OVERVIEW_CHANNEL_ID = ""
MASTERY_CHANNEL_ID = ""
RETROACHIEVEMENTS_INTERVAL = 30
PRESENCE_INTERVAL = 120
ACHIEVEMENT_EMBED_STYLE = 2
PRESENCE_ACTIVE_WINDOW_DAYS = 3
PRESENCE_RECENT_GAMES_COUNT = 2

# RetroAchievements request safety.
RA_REQUEST_GAP_SECONDS = 1.0
RA_CONNECT_TIMEOUT_SECONDS = 5
RA_REQUEST_TIMEOUT_SECONDS = 20
RA_TRANSIENT_RETRY_DELAY_SECONDS = 3
RA_MAX_TRANSIENT_RETRIES = 1
RA_RATE_LIMIT_COOLDOWN_SECONDS = 60
RA_SECONDARY_MODE = "fallback"

# Daily Overview runs at this local time and receives an exclusive request window.
DAILY_OVERVIEW_TIMEZONE = "America/New_York"
DAILY_OVERVIEW_TIME = "00:00"
DAILY_OVERVIEW_EXCLUSIVE_WINDOW_MINUTES = 30

# Image-color downloads use this timeout and fall back to a default color on error.
EMBED_IMAGE_TIMEOUT_SECONDS = 5

# The delay before starting the tasks, useful for debugging, otherwise it will start within the first 15th minute
TASK_START_DELAY = {
    'process_achievements': True,
    'process_daily_overview': True,
    'process_presence': True
}
