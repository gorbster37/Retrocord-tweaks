# Retrocord Lightweight Reliability Plan

## Goal

Make the existing friends bot calmer and more reliable as it grows from about 10 tracked users toward 50.

Keep the current behavior:

- scan achievements every 30 minutes;
- post achievement, mastery, daily-overview, and Discord-presence updates;
- run locally on the Raspberry Pi; and
- keep the project easy to understand and maintain.

## Boundaries

- Keep the current Python stack and `requests` dependency.
- Use JSON files only. Do not add SQLite, Redis, a queue service, NoSQL, or hosted integrations.
- Do not add persistent duplicate-post tracking. An occasional duplicate after a crash/restart is acceptable.
- Keep delayed-scan markers only in memory. They reset on restart and are not saved to JSON.
- Do not redesign embeds or add a web UI.
- Do not rely on a second API key instead of reducing unnecessary calls. The optimized request design comes first; the second key is used only for `429` rate-limit fallback.
- Keep the tracked-user list as usernames. Do not add stored ULID mappings; log a clear error if a username no longer resolves.

## What Needs Improvement

The normal quiet scan is modest: 50 users means 50 recent-achievement calls every 30 minutes. The problem is an active scan.

For a user with new achievements in `G` games, including `M` new masteries, the current code makes:

```text
1 x recent achievements
1 x profile
G x game information + user progress
M x full completion progress
M x achievement distribution
```

Calls use synchronous `requests.get()` without a timeout. Achievement scans, daily overview, presence, and startup preload can all currently make requests independently. This makes bursts and temporary rate limits more likely.

## Small Design

### One Shared API Client

Create one small `RetroAchievementsClient` and route every RetroAchievements call through it. It will manage a primary credential and an optional secondary credential.

The client will:

1. Keep one reusable `requests.Session` and pacing lane per configured credential.
2. Run blocking HTTP work with `asyncio.to_thread()` so a slow request does not freeze Discord's event loop.
3. Use one shared dispatcher so all feature types enter the same request path.
4. Serialize calls per credential with a separate `asyncio.Lock` and wait at least one configurable second between calls on that credential.
5. Use a connection timeout and total request timeout.
6. Retry a timeout, connection error, or `5xx` once on the same credential after a short configurable delay.
7. Respect `Retry-After` when RetroAchievements sends it. Otherwise use a conservative configured cooldown and mark that credential unavailable until the cooldown expires.
8. Log endpoint, status, duration, and retry count without logging API keys or full query URLs.

This is intentionally a small dispatcher, not a job queue service. Achievement scans, daily overview, presence, and startup preload may all run, but their calls are serialized per credential. Normal traffic uses the primary lane. A primary `429` sends the affected request, and work queued while the primary is cooling down, to the secondary lane. The secondary token is not used for timeouts, connection failures, `5xx` responses, or proactive load balancing.

With a one-second request gap, one credential handles an unusual 250-call burst in a little over four minutes. The secondary token is a rate-limit escape valve, not routine capacity.

### Minimal Configuration

Add these non-secret settings to `config_example.py`:

```python
RA_REQUEST_GAP_SECONDS = 1.0
RA_CONNECT_TIMEOUT_SECONDS = 5
RA_REQUEST_TIMEOUT_SECONDS = 20
RA_TRANSIENT_RETRY_DELAY_SECONDS = 3
RA_MAX_TRANSIENT_RETRIES = 1
RA_RATE_LIMIT_COOLDOWN_SECONDS = 60

# IANA timezone matching the Raspberry Pi's local timezone.
DAILY_OVERVIEW_TIMEZONE = "America/New_York"

# Local time in DAILY_OVERVIEW_TIMEZONE at which the Daily Overview begins.
DAILY_OVERVIEW_TIME = "00:00"

# Reserve this many minutes from the Daily Overview start time. During the
# window, only Daily Overview requests may start.
DAILY_OVERVIEW_EXCLUSIVE_WINDOW_MINUTES = 30

# Non-RetroAchievements image download safety.
EMBED_IMAGE_TIMEOUT_SECONDS = 5

# Optional second credential. Configure only an account you are authorized to use.
secondary_api_username = ""
secondary_api_key = ""

# The secondary key is used only when primary work receives a 429 or the
# primary lane is in its resulting cooldown. Do not enable balancing.
RA_SECONDARY_MODE = "fallback"
```

The primary `api_username` and `api_key` remain the normal credential. Set `DAILY_OVERVIEW_TIMEZONE` to the actual IANA timezone configured on the Raspberry Pi. `DAILY_OVERVIEW_TIME` replaces the current fixed-midnight scheduling behavior; its exclusive window begins at that same local time. Keep `RA_SECONDARY_MODE` on `fallback`; there is no balanced mode in scope.

### Daily Overview Exclusive Window

Reserve a configurable 30-minute period beginning at the configured Daily Overview start time, in `DAILY_OVERVIEW_TIMEZONE`. This is an exclusive *start* window: while it is active, the dispatcher starts only Daily Overview requests. Achievement scans, presence refreshes, and startup preload requests stay queued without being dropped.

Rules:

- The daily task captures one shared rolling 24-hour epoch range when the window opens. Every user receives that exact same range, regardless of queueing.
- A request already in progress when the window opens is allowed to finish; no new non-daily request starts after that.
- When the window ends, normal request scheduling resumes. If an unusual delay leaves Daily Overview unfinished, its remaining calls continue through the normal paced dispatcher rather than being cancelled or deferred a full day.
- A request that begins just before the window ends may finish shortly afterward; the boundary controls when calls begin, not forcibly terminating safe in-flight HTTP work.
- The shared client still applies the per-credential gap, rate-limit cooldowns, and fallback-only credential rules inside the window.

At the expected 50-user scale, a normal Daily Overview should fit comfortably inside the initial 30-minute reservation. The bot should log the configured start, window end, actual finish, number of calls, and any work that carries past the window, making it easy to revisit the duration later if needed. The scheduler must preserve the configured local wall-clock time across daylight-saving changes; a fixed `hours=24` loop alone is not sufficient.

## Second API Token

Use the second token only as a controlled `429` fallback.

In `fallback` mode, a primary `429` puts only the primary lane into cooldown. The dispatcher retries the affected request on the secondary lane and routes work that arrives during that cooldown to the secondary lane. The primary becomes the normal lane again when its cooldown ends.

If the secondary credential also receives a `429`, do not wait, rotate, or keep retrying. Log the failure and let the next scheduled scan catch up. The achievement scan marker will ensure that this produces a delayed notification instead of a missed one.

### Retry and Failover Rules

| Result | Action |
| --- | --- |
| Primary `429 Too Many Requests` | Put the primary lane into cooldown and retry once with the secondary credential, if configured. |
| Secondary `429 Too Many Requests`, or `429` without a secondary credential | Put that credential into cooldown, log the failure, and stop this request. Do not wait or retry again. |
| `401 Unauthorized` or `403 Forbidden` | Mark that credential unavailable for the rest of the bot process and log a clear operator warning. Do not use the secondary credential, because fallback is reserved for `429` responses only. |
| Timeout, connection error, `500`, `502`, `503`, or `504` | Retry once after `RA_TRANSIENT_RETRY_DELAY_SECONDS` using the same credential. A second credential will not fix an upstream or network failure. |
| Other `4xx` response | Do not retry or fail over. Log the safe endpoint name and status for diagnosis. |

## JSON State

Keep the existing `games.json` presence cache.

Add only one small file: `data/api_cache.json`.

Initially cache only Achievement Distribution responses:

```json
{
  "version": 1,
  "achievement_distribution": {
    "game-id:hardcore": {
      "fetched_at": "2026-09-07T12:00:00Z",
      "data": {}
    }
  }
}
```

Rules:

- Keep each distribution result for 24 hours.
- Write atomically: write `api_cache.json.tmp`, then replace `api_cache.json`.
- If the file is missing or invalid, start with an empty cache.
- Prune old entries when saving.
- Do not cache API keys, request URLs, recent achievements, or per-user progress.

This cache is small, easy to inspect, and avoids repeatedly requesting broadly static mastery-rarity data.

The displayed global mastery count may be up to 24 hours old. The mastery event itself is still based on the current user-progress request.

## Delayed Achievement Scans

The Daily Overview window, rate-limit cooldowns, and transient failures can delay an achievement scan beyond its normal 30-minute interval. `API_GetUserRecentAchievements.php` only returns the requested lookback period, so a fixed 30-minute request after a delay could miss achievements.

Keep `last_successful_achievement_scan_at` in memory for each tracked user:

- When there is no marker, such as after a restart, request the normal 30-minute lookback. A restart can therefore produce an occasional duplicate, which is acceptable.
- For later scans, request enough minutes to cover the time since that user's last successful scan plus a small safety buffer.
- Filter the response to achievements strictly newer than that user's marker before creating embeds.
- Advance the marker only after the user's relevant Discord messages have been sent successfully.

This eliminates normal duplicate posts and prevents delayed scans from missing achievements without adding a database or persistent duplicate history.

## Implementation Steps

### 1. Add the Shared Request Gate

- Add `services/ra_client.py`.
- Move the existing `requests.get()` behavior from `BaseAPI.fetch_data()` behind the client.
- Give every request an explicit timeout.
- Add per-credential one-second gaps, cooldown tracking, fallback-only `429` handling, one delayed same-credential transient retry, and safe logging.
- Pass the shared client through every feature. Remove direct credential imports from feature modules so no request can bypass fallback behavior.
- Schedule Daily Overview from `DAILY_OVERVIEW_TIME` and `DAILY_OVERVIEW_TIMEZONE` rather than the current fixed-midnight helper. Derive its exclusive window from that start time plus `DAILY_OVERVIEW_EXCLUSIVE_WINDOW_MINUTES`, preserving local wall-clock time through daylight-saving changes.
- Convert API service methods to async calls; keep response-to-model classes (`Game`, `Profile`, `Achievement`, `Progress`) simple and synchronous.
- Route startup preload, achievement scans, daily overview, and presence through this client.

**Success:** no direct RetroAchievements request remains outside `ra_client.py`; each feature uses the central dispatcher, and a primary `429` falls back once to the secondary credential when configured.

### 2. Reduce Mastery Calls

- Keep the existing per-game `API_GetGameInfoAndUserProgress.php` calls. They are already grouped by unique game ID and preserve current embed data without a large model rewrite.
- Identify all mastery candidates for the user first.
- If there are no mastery candidates, do not request Completion Progress or Achievement Distribution.
- If there is one or more mastery candidate, request Completion Progress **once** for that user and reuse it for every mastery embed in the scan.
- Request Achievement Distribution through the 24-hour JSON cache for each confirmed mastery.
- Request Completion Progress with up to 500 results per page. Only request additional pages if the returned total requires them, so the mastery ordinal stays correct for larger libraries.

**Success:** multiple masteries in one scan create one Completion Progress sequence, not one per mastery.

### 3. Keep Presence and Daily Overview Active

- Remove feature-specific request sleeps once the shared client is pacing every call.
- Keep the presence cache and round-robin behavior exactly as it is.
- Let presence wait for the next available credential slot if an achievement scan is active; it must still complete its refresh rather than skipping the tick. During the Daily Overview exclusive window, it waits until the window ends.
- Let daily overview use the same client and dispatcher, with exclusive request starts for the configured duration from its configured local start time.
- Use one shared rolling 24-hour range for all users in a Daily Overview run.
- During startup, preload presence users through the same dispatcher, preventing an uncontrolled 50-user startup burst.

**Success:** all features remain active, Daily Overview has its exclusive 30-minute request window, and RetroAchievements sees paced request streams that do not overlap on the same credential.

### 4. Keep Delayed Achievement Scans Correct

- Add the in-memory per-user achievement scan marker and wider delayed-scan lookup described above.
- Do not write these markers to JSON.
- If an API request or Discord send fails, do not advance that user's marker.

**Success:** a Daily Overview window, rate-limit cooldown, or transient error can delay an achievement notification but cannot create a normal polling blind spot.

### 5. Make Image Color Fetches Safe

- Keep image-color downloads outside `ra_client.py`; they are not RetroAchievements API traffic.
- Add `EMBED_IMAGE_TIMEOUT_SECONDS` to the existing image request.
- On image download, decode, or color-extraction failure, use a stable default Discord color and continue posting the embed.

**Success:** a slow or broken image host cannot block the bot indefinitely or prevent an achievement message.

### 6. Verify Locally and on the Raspberry Pi

Before adding users:

1. Add a standalone standard-library `unittest` suite. It must mock HTTP and cover pacing, Daily Overview exclusivity, delayed achievement catch-up, completion-progress pagination, primary `429` fallback, secondary `429` stop behavior, and transient retry delay.
2. Back up `config.py`, `games.json`, `image_cache.json`, and the current log directory.
3. Run the tests locally without network access or extra packages.
4. Run the bot with the current 10 users for at least one full day.
5. Confirm achievement, mastery, daily, and presence messages still look the same.
6. Check that logs show a clear gap between requests and no API key values.
7. Confirm a simulated timeout, primary `429`, and secondary `429` behave as specified without stopping the bot.
8. Add users gradually and watch for rate-limit warnings and scan duration.

## Done Means

The work is complete when:

- all RetroAchievements calls use the shared, paced client;
- RetroAchievements requests have explicit timeouts, and image-color downloads fail safely;
- no API-call types collide;
- the Daily Overview window prevents new achievement, presence, and startup API calls from starting for its configured duration;
- every Daily Overview user shares one rolling 24-hour range in the Raspberry Pi's configured timezone;
- presence does not get skipped during achievement or daily work;
- delayed achievement scans catch up without normal duplicate posts or persistent duplicate state;
- a multi-mastery scan reuses one Completion Progress fetch;
- Achievement Distribution uses the small JSON cache;
- the second token is used only for primary-`429` fallback, never for normal balancing or non-rate-limit errors;
- standalone tests run without network access or new dependencies; and
- the existing 10-user bot runs normally before adding more friends.

## Reference

- [RetroAchievements Web API documentation](https://api-docs.retroachievements.org/)
