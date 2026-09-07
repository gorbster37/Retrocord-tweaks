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
API_INTERVAL: The number of minutes to wait between Achievement requests, default is 15 minutes, minimum is 1 minute
PRESENCE_INTERVAL: The number of minutes to wait between Presence requests, default is 120 minutes, minimum is 1 minute
PRESENCE_ACTIVE_WINDOW_DAYS: The number of days a user's recently played games remain eligible for presence, default is 3 days
PRESENCE_RECENT_GAMES_COUNT: The number of recently played games to fetch per presence check, default is 2
PRESENCE_STARTUP_USER_DELAY_SECONDS: The number of seconds to wait between users while preloading the presence cache at startup, default is 1 second
DAILY_OVERVIEW_USER_DELAY_SECONDS: The number of seconds to wait between users during the daily overview task, default is 1 second
TASK_START_DELAY: A dictionary to specify if the tasks should start immediately or wait until the next 15th minute, useful for debugging if set to False
"""

api_key = ""
api_username = ""
token = ''
users = []

BASE_URL = "https://retroachievements.org"

DISCORD_IMAGE = "https://i.postimg.cc/KvSTwcQ0/undefined-Imgur.png"
RETRO_DAILY_IMAGE = "https://i.imgur.com/P0nEGGs.png"

ACHIEVEMENTS_CHANNEL_ID = ""
DAILY_OVERVIEW_CHANNEL_ID = ""
MASTERY_CHANNEL_ID = ""
RETROACHIEVEMENTS_INTERVAL = 5
PRESENCE_INTERVAL = 120
ACHIEVEMENT_EMBED_STYLE = 2
PRESENCE_ACTIVE_WINDOW_DAYS = 3
PRESENCE_RECENT_GAMES_COUNT = 2
PRESENCE_STARTUP_USER_DELAY_SECONDS = 1
DAILY_OVERVIEW_USER_DELAY_SECONDS = 1

# The delay before starting the tasks, useful for debugging, otherwise it will start within the first 15th minute
TASK_START_DELAY = {
    'process_achievements': True,
    'process_daily_overview': True,
    'process_presence': True
}
