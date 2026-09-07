import discord
import json
from datetime import datetime

from services.achievement_scan import AchievementScanState
from services.api import (
    get_achievement_distribution,
    get_game_info_and_user_progress,
    get_user_completion_progress,
    get_user_profile,
    get_user_recent_achievements,
)
from services.api_cache import ApiCache
from services.ra_client import RetroAchievementsClient
from utils.image import get_discord_color
from utils.datetime import ordinal
from config.config import DISCORD_IMAGE, ACHIEVEMENT_EMBED_STYLE

from utils.custom_logger import logger

async def process_achievements(
    users,
    client: RetroAchievementsClient,
    achievements_channel,
    mastery_channel,
    scan_state: AchievementScanState,
    api_cache: ApiCache,
):
    achievement_embeds = []
    mastery_embeds = []
    successful_markers = {}
    for user in users:
        started_at = scan_state.now()
        try:
            lookback_minutes = scan_state.lookback_minutes(user, started_at)
            recent_achievements = await get_user_recent_achievements(
                client,
                user,
                lookback_minutes,
                request_type="achievement",
            )
            achievements = scan_state.filter_new(user, recent_achievements)
            if achievements:
                profile = await get_user_profile(
                    client, user, request_type="achievement"
                )
                game_details, game_achievements = await get_achievements(
                    user, achievements, client
                )
                completed_games = []
                for game_id, achievements in game_achievements.items():
                    game = game_details[game_id]
                    process_game_achievements(
                        game, user, achievements, profile, achievement_embeds
                    )
                    if game.is_completed():
                        completed_games.append(game)

                if completed_games:
                    progress = await get_user_completion_progress(
                        client, user, request_type="achievement"
                    )
                    for mastery_count, game in enumerate(completed_games):
                        await process_game_mastery(
                            game,
                            user,
                            profile,
                            mastery_embeds,
                            mastery_count,
                            progress,
                            client,
                            api_cache,
                        )
            else:
                logger.info(f'No achievements found for user {user}')
            successful_markers[user] = started_at
        except Exception as e:
            logger.error(f'Error processing user {user}: {e}')

        logger.info(f'Finished fetching achievements for user {user}')

    try:
        await send_achievement_embeds(achievement_embeds, achievements_channel)
        await send_mastery_embeds(mastery_embeds, mastery_channel)
    except Exception as error:
        logger.error(f'Error sending achievement messages: {error}')
    else:
        scan_state.mark_successful(successful_markers)


async def get_achievements(user, achievements, client):
    game_ids = set()
    game_details = {}
    game_achievements = {}

    for achievement in achievements:
        game_ids.add(achievement.game_id)
        logger.info(
            f"{user} has earned an achievement: {achievement.title} "
            f"({achievement.points}) ({achievement.retropoints}) for {achievement.game_title}"
        )
        game_achievements.setdefault(achievement.game_id, []).append(achievement)

    logger.debug(f'Found {len(game_ids)} unique game IDs in achievements')
    for game_id in game_ids:
        logger.info(f'Getting game progress details for game {game_id}')
        game_details[game_id] = await get_game_info_and_user_progress(
            client, game_id, user, request_type="achievement"
        )
        logger.info(f'Got game progress details for game {game_id}')

    return game_details, game_achievements


def process_game_achievements(game, user, achievements, profile, achievement_embeds):
    achievements.sort(key=lambda x: datetime.strptime(x.date, "%Y-%m-%d %H:%M:%S"))
    for i, achievement in enumerate(achievements):
        embed = create_achievement_embed(game, user, achievement, profile, i+1, len(achievements))
        achievement_embeds.append((datetime.strptime(achievement.date, "%Y-%m-%d %H:%M:%S"), embed))

async def process_game_mastery(
    game,
    user,
    profile,
    mastery_embeds,
    mastery_count,
    progress,
    client,
    api_cache,
):
    unlock_distribution = await get_achievement_distribution(
        client, api_cache, game.id, request_type="achievement"
    )
    highest_unlock = unlock_distribution.get_highest_unlock()
    mastered_count = ordinal(int(progress.count_mastered()) - mastery_count)
    mastery_time = game.days_since_last_achievement()
    mastery_percentage = (
        round((highest_unlock / game.total_players_hardcore) * 100, 2)
        if highest_unlock is not None and game.total_players_hardcore
        else 0
    )
    if game_progress := next(
        (result for result in progress.results if result.game_id == game.id),
        None,
    ):
        logger.info(f"{user} has mastered {game.title}! {game.total_achievements} achievements have been earned in {mastery_time}! {highest_unlock} out of {game.total_players_hardcore} players have mastered the game! ({mastery_percentage}%)")
        mastery_embed = create_mastery_embed(game, user, profile, game_progress, mastered_count, mastery_time, highest_unlock, mastery_percentage)
        mastery_embeds.append((datetime.strptime(game_progress.highest_award_date, "%Y-%m-%dT%H:%M:%S%z"), mastery_embed))
        
# Embed creation wrapper function
def create_achievement_embed(game, user, achievement, profile, current, total):
    if ACHIEVEMENT_EMBED_STYLE == 1:
        return create_achievement_embed_v1(game, user, achievement, profile, current, total)
    elif ACHIEVEMENT_EMBED_STYLE == 2:
        return create_achievement_embed_v2(game, user, achievement, profile, current, total)
    else:
        raise ValueError("Invalid ACHIEVEMENT_EMBED configuration value")

# First style of achievement embed
def create_achievement_embed_v1(game, user, achievement, profile, current, total):
    if achievement.mode == "Hardcore":
        completion = game.total_achievements_earned_hardcore - total + current
    else:  # Assuming 'softcore' as the default else case
        completion = game.total_achievements_earned_softcore - total + current

    percentage = (completion / game.total_achievements) * 100
    unlock_percentage = (game.achievements[achievement.title]['NumAwardedHardcore'] / game.total_players_hardcore) * 100 if game.total_players_hardcore else 0
    most_common_color = get_discord_color(achievement.game_icon)

    # Load emoji mappings
    with open('emoji.json') as f:
        emoji_mappings = json.load(f)
    # Get the emoji ID based on console name, with a general emoji if no specific match is found
    console_name = game.remap_console_name()
    emoji_id = emoji_mappings.get(console_name.lower())
    emoji = f"<:{console_name}:{emoji_id}>" if emoji_id else ":video_game:"

    embed = discord.Embed(
        description=(
            f"**[{achievement.game_title}]({achievement.game_url})** "
            f"{emoji}\n\n"
            f"{achievement.description}\n\n"
            f"Unlocked by **{game.achievements[achievement.title]['NumAwardedHardcore']}** out of "
            f"**{game.total_players_hardcore}** players (**{unlock_percentage:.2f}%**)"
        ),
        color=most_common_color
    )

    # Check if achievement type is 'Missable'
    achievement_title = (
        f"[{achievement.title}]({achievement.url}) (m)"
        if achievement.type == "missable"
        else f"[{achievement.title}]({achievement.url})"
    )

    embed.add_field(name="Achievement", value=achievement_title, inline=True)
    embed.add_field(name="Points", value=f"**{achievement.points}** ({achievement.retropoints_format})", inline=True)
    embed.add_field(name="Completion", value=f"{completion}/{game.total_achievements} (**{percentage:.2f}%**)", inline=True)
    embed.set_image(url=DISCORD_IMAGE)
    embed.set_thumbnail(url=achievement.badge_url)
    embed.set_footer(text=f"{user} • {achievement.date_amsterdam}", icon_url=profile.profile.user_pic_unique)
    embed.set_author(name=f"{achievement.mode} Achievement Unlocked", icon_url=achievement.game_icon)
    return embed

# Second style of achievement embed
def create_achievement_embed_v2(game, user, achievement, profile, current, total):
    if achievement.mode == "Hardcore":
        completion = game.total_achievements_earned_hardcore - total + current
    else:  # Assuming 'softcore' as the default else case
        completion = game.total_achievements_earned_softcore - total + current

    percentage = (completion / game.total_achievements) * 100
    unlock_percentage = (game.achievements[achievement.title]['NumAwardedHardcore'] / game.total_players_hardcore) * 100 if game.total_players_hardcore else 0
    most_common_color = get_discord_color(achievement.game_icon)

    # Load emoji mappings
    with open('emoji.json') as f:
        emoji_mappings = json.load(f)
    # Get the emoji ID based on console name, with a general emoji if no specific match is found
    console_name = game.remap_console_name()
    emoji_id = emoji_mappings.get(console_name.lower())
    emoji = f"<:{console_name}:{emoji_id}>" if emoji_id else ":video_game:"
    
    # Check if achievement type is 'Missable'
    achievement_title = (
        f"{achievement.title} (m)"
        if achievement.type == "missable"
        else f"{achievement.title}"
    )

    embed = discord.Embed(
        title=achievement_title,
        description=(
            f"{achievement.description}\n\n"
            f"{achievement.mode}\n"
            f"**[{achievement.game_title}]({achievement.game_url})** "
            f"{emoji}\n\n"
        ),
        color=most_common_color
    )

    embed.add_field(name="Unlock Ratio", value=f"{int(unlock_percentage * 10) / 10:.1f}%", inline=True)
    embed.add_field(name="Points", value=f"{achievement.points} ({achievement.retropoints_format})", inline=True)
    embed.add_field(name="Progress", value=f"{completion}/{game.total_achievements} ({percentage:.2f}%)", inline=True)
    embed.set_image(url=DISCORD_IMAGE)
    embed.set_thumbnail(url=achievement.badge_url)
    embed.set_footer(text=f"{user} • {achievement.date_amsterdam}", icon_url=profile.profile.user_pic_unique)
    embed.set_author(name="Achievement unlocked", icon_url=achievement.game_icon)
    return embed

def create_mastery_embed(game, user, profile, game_progress, mastered_count, mastery_time, highest_unlock, mastery_percentage):
    most_common_color = get_discord_color(game.image_icon)
    
    # Load emoji mappings
    with open('emoji.json') as f:
        emoji_mappings = json.load(f)
    # Get the emoji ID based on console name, with a general emoji if no specific match is found
    console_name = game.remap_console_name()
    emoji_id = emoji_mappings.get(console_name.lower())
    emoji = f"<:{console_name}:{emoji_id}>" if emoji_id else ":video_game:"

    embed = discord.Embed(
        description=(
            f"**[{game.title}]({game.url})** "
            f"{emoji}\n\n"
            f"This is [{user}]({profile.profile.user_url})'s **{mastered_count}** mastery!\n\n"
            f"Mastered in {mastery_time}\n\n"
            f"Mastered by {highest_unlock} out of {game.total_players_hardcore} players "
            f"({mastery_percentage}%)"
        ),
        color=most_common_color
    )

    embed.set_footer(
        text=f"{user} • Mastery achieved on {game_progress.highest_award_date_format}",
        icon_url=profile.profile.user_pic_unique
    )
    embed.add_field(name="Achievements", value=f"{game.total_achievements}", inline=True)
    embed.add_field(name="Points", value=f"{game.total_points} ({game.calculate_total_true_ratio()})", inline=True)
    embed.set_author(name="Game Mastered", icon_url=game.image_icon)
    embed.set_image(url=DISCORD_IMAGE)
    embed.set_thumbnail(url=game.image_icon)

    return embed
    

async def send_achievement_embeds(achievement_embeds, achievements_channel):
    achievement_embeds.sort(key=lambda x: x[0])
    if achievement_embeds:
        logger.info(f"Sending {len(achievement_embeds)} embeds to {achievements_channel}")
        for embed in achievement_embeds:
            await achievements_channel.send(embed=embed[1])  # Send each embed individually

async def send_mastery_embeds(mastery_embeds, mastery_channel):
    mastery_embeds.sort(key=lambda x: x[0])
    if mastery_embeds:
        logger.info(f"Sending {len(mastery_embeds)} mastery embeds to {mastery_channel}")
        for embed in mastery_embeds:
            await mastery_channel.send(embed=embed[1])  # Send each embed individually
