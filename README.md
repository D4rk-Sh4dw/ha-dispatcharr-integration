# Dispatcharr Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)

This is a custom integration for [Home Assistant](https://www.home-assistant.io/) that connects to your [Dispatcharr](https://github.com/Dispatcharr/Dispatcharr) instance. It provides real-time monitoring of active streams, creating dynamic media player entities for each stream, plus sensors for stream count, M3U account health, and system notifications.

This is a fork of [lyfesaver74/ha-dispatcharr](https://github.com/lyfesaver74/ha-dispatcharr), rebuilt on top of Dispatcharr's official API-key authentication, websocket realtime updates, and several new sensors — see the Features list below for what's changed.

## Features

* **Total Stream Count:** A dedicated sensor (`sensor.dispatcharr_total_active_streams`) that shows the total number of currently active streams.
* **Dynamic Media Player Entities:** Creates a new media player entity for each active stream automatically. These entities are removed when the stream stops, keeping your Home Assistant instance clean.
* **Rich Stream Data:** Each media player provides detailed attributes, including channel name, client count, video/audio codecs, and more.
* **Live Program Information (Optional):** Uses Dispatcharr's official `current-programs` API to show the currently airing program's title, description, and times as media player attributes. This feature can be disabled for performance.
* **Stop a Stream:** Media player entities support the `media_player.media_stop` service, which stops that channel's stream for all viewers via Dispatcharr's API.
* **M3U Account Sensors:** One sensor per configured M3U/Xtream account, showing status (`idle`/`fetching`/`error`/`success`/...), last message, and expiration dates — handy for catching a lapsed IPTV subscription before it surprises you. Refreshes every 5 minutes (fixed, not configurable) — see the note under [Realtime updates](#realtime-updates).
* **Unread Notifications Sensor:** Surfaces Dispatcharr's own system notifications (failed refreshes, update announcements, recommendations) as a count with the active notifications listed as attributes. Also refreshes every 5 minutes, plus immediately on a realtime notification event if enabled.
* **Realtime Websocket Updates (Optional):** Keeps a websocket connection to Dispatcharr open so relevant changes (recording started/ended, notifications, and — for admin accounts — live stream stats) push an update immediately instead of waiting for the next poll.
* **Client Visibility:** See who is watching what — per-stream client IP addresses and user agents, plus an `Active Clients` sensor summarising all viewers across every stream.
* **Configurable Update Interval:** Poll interval for active streams is adjustable from 2–300 seconds (default 10s).
* **Brand Icon:** Ships Dispatcharr's own logo (`custom_components/dispatcharr_sensor/brand/`) so the integration shows a real icon instead of the generic puzzle piece. Requires **Home Assistant 2026.3 or later** — older versions fall back to the generic icon (harmless, no error).

## Prerequisites

* An understanding and acceptance that AI helped me make this. If that is not your thang... don't use it.
* A running instance of [Dispatcharr](https://github.com/Dispatcharr/Dispatcharr), reachable at a URL (directly or behind a reverse proxy).
* [Home Assistant Community Store (HACS)](https://hacs.xyz/) installed on your Home Assistant instance.
* The username and password for your Dispatcharr user account. **For the realtime websocket stream-stats to work, this should be an admin account** — Dispatcharr only pushes live stream telemetry over the websocket to admin users (see Troubleshooting).

## Installation via HACS

This integration is not yet in the default HACS repository. You can add it as a custom repository.

1.  In Home Assistant, go to **HACS** > **Integrations**.
2.  Click the three dots in the top-right corner and select **"Custom repositories"**.
3.  In the "Repository" field, enter the URL to this GitHub repository: `https://github.com/D4rk-Sh4dw/ha-dispatcharr-integration`
4.  For the "Category" dropdown, select **"Integration"**.
5.  Click **"Add"**.
6.  You should now see the "Dispatcharr Integration" in your HACS integrations list. Click **"Install"** and proceed with the installation.
7.  Restart Home Assistant when prompted.

## Configuration

Once the integration is installed, you can add it to Home Assistant via the UI.

1.  Go to **Settings** > **Devices & Services**.
2.  Click the **"+ Add Integration"** button in the bottom right.
3.  Search for **"Dispatcharr"** and select it.
4.  A configuration dialog will appear. Enter the following information:
    * **URL:** The full base URL of your Dispatcharr server, including scheme, e.g. `http://192.168.0.121:9191` or `https://dispatcharr.example.com` if it's behind a reverse proxy.
    * **Username:** Your Dispatcharr username.
    * **Password:** Your Dispatcharr password.
5.  Click **"Submit"**.

Your username and password are used to call Dispatcharr's official `/api/accounts/api-keys/generate/` endpoint and obtain a permanent API key, which is used to authenticate normal REST requests (`X-API-Key` header). **Your username and password are also stored** (HA encrypts the config entry at rest) — Dispatcharr's websocket endpoint only accepts short-lived JWTs, not the API key, so the integration needs to be able to silently re-authenticate for the realtime feature (see below). This happens unconditionally during setup, before you ever reach the options screen — turning off "Enable realtime websocket updates" afterwards stops the stored password from being *used*, but does not remove it from the config entry. If you don't want your password stored at all, don't install this integration in its current form (or remove the entry after setup and use another Dispatcharr integration).

If the API key is ever revoked on the Dispatcharr side, Home Assistant will prompt you to reauthenticate.

## Optional Configuration (After Installation)

All of the below can be changed at any time without re-installing the integration.

1.  Go to **Settings** > **Devices & Services**.
2.  Find the Dispatcharr integration and click **"Configure"**.
3.  Adjust as needed:
    * **Enable EPG Data** — turn the now-playing program lookup on or off. Useful for performance tuning on slower servers. Channel names, numbers and logos are unaffected; only the recurring program lookups are skipped.
    * **Enable realtime websocket updates** — see the [Realtime updates](#realtime-updates) section below.
    * **Update interval (seconds)** — how often Home Assistant polls Dispatcharr for active streams. Defaults to `10` seconds. Can be set anywhere from `2` to `300` seconds. Realtime websocket events (if enabled) arrive immediately regardless of this setting.
4.  Click **"Submit"**. The integration will automatically reload with the new settings.

## Realtime updates

When enabled (default: on), the integration keeps a websocket connection open to Dispatcharr (`/ws/`) alongside its regular polling. When Dispatcharr pushes one of these events, the relevant sensors/media players refresh immediately instead of waiting for the next poll:

* A system notification is created or dismissed → the notifications sensor refreshes.
* Live per-channel stream stats change (client connects/disconnects, bitrate changes, etc.) → the stream sensors/media players refresh.
* Recording started / ended / rescheduled → currently just wakes up the same refresh as the notification events above (M3U account status + notifications). There's no DVR/recording sensor yet, so these events don't have anything recording-specific to update — that's a possible future addition.

**Admin-account caveat:** Dispatcharr restricts the live stream-stats websocket events to admin-level users — this is a Dispatcharr-side restriction, not something this integration controls. If the account you configured isn't an admin, the websocket still connects and notification/recording events still work, but stream state changes will only be picked up by the regular poll (still as low as every 2 seconds if you configure it that way).

Because Dispatcharr's websocket only accepts JWT access tokens (30-minute lifetime) via a `?token=` query parameter, and refresh tokens expire after 1 day, the integration stores your username/password to silently re-authenticate as needed. This is separate from, and in addition to, the permanent API key used for regular requests.

**M3U account and notification data don't have a fast path:** unlike stream data, they're polled on a fixed 5-minute interval that isn't exposed in the options. Notification/recording websocket events wake that poll up early, but there's no websocket event for "an M3U account's status changed" — so the M3U account sensors can lag up to 5 minutes behind reality even with realtime updates enabled.

## Provided Entities

* **`sensor.dispatcharr_total_active_streams`**: Total number of active streams.
* **`sensor.dispatcharr_active_clients`**: Total number of viewers across all active streams. Attributes: `clients` (each with `ip_address`, `user_agent`, `connected_at`, `output_format` and the `channel_name` they're watching), `clients_per_channel`, and `clients_listed`.
* **`sensor.dispatcharr_unread_notifications`**: Count of active (non-dismissed) Dispatcharr system notifications, with the notifications themselves (title, message, priority, type) as an attribute list.
* **`sensor.dispatcharr_<account_name>_status`** (Dynamic, one per M3U/Xtream account): State is the account's status (`idle`, `fetching`, `parsing`, `error`, `success`, `pending_setup`, `disabled`). Attributes include `last_message`, `max_streams`, `earliest_expiration`, `all_expirations`, and `exp_date`.
* **`media_player.dispatcharr_<channel_name>`** (Dynamic): A new media player entity for each active stream, removed again once the stream stops. Because these entities only exist while someone is watching, don't reference them directly in automations — use the `Active Clients` or `Total Active Streams` sensors, which are always present.
    * State is `playing` while active.
    * Supports the `media_player.media_stop` service to stop the channel's stream (for **all** viewers — this isn't a per-client action, see Troubleshooting).

### Media Player Attributes

| Attribute | Description | Example |
|---|---|---|
| `media_title` | The title of the currently airing program. | `Doctor Who` |
| `media_series_title` | The friendly name of the channel. | `US: BBC AMERICA HD` |
| `media_content_id` | The channel's EPG id (`tvg_id`). | `bbcamerica.us` |
| `app_name` | The source of the stream. | `Dispatcharr` |
| `entity_picture` | A direct URL to the channel's logo image. | `https://.../logos/262/cache/` |
| `channel_number` | The channel's number in Dispatcharr. | `98.2` |
| `channel_name` | The channel's name. | `US: BBC AMERICA HD` |
| `tvg_id` | The channel's EPG id. | `bbcamerica.us` |
| `clients` | Number of clients watching this stream. | `2` |
| `client_ips` | IP addresses of those clients. | `["192.168.0.50", "192.168.0.51"]` |
| `client_details` | Per-client `ip_address`, `user_agent`, `connected_at`, `output_format`, `client_id`. | see below |
| `resolution` | The current video resolution. | `1920x1080` |
| `fps` | Frames per second of the source. | `50.0` |
| `video_codec` | The video codec being used. | `h264` |
| `audio_codec` | The audio codec being used. | `ac3` |
| `audio_channels` | Number of audio channels. | `6` |
| `avg_bitrate` | The average bitrate of the stream. | `5.18 Mbps` |
| `uptime` | Seconds the stream has been running. | `132.5` |
| `stream_profile` | The stream profile in use. | `default` |
| `program_title` | Title of the current program. | `Doctor Who` |
| `program_description` | A description of the current program. | `The Doctor travels through time...` |
| `program_start` | The start time of the current program. | `2026-08-28T14:00:00+02:00` |
| `program_stop` | The end time of the current program. | `2026-08-28T15:00:00+02:00` |

**Client list caveat:** Dispatcharr's status API returns at most the first 10 clients per channel. `clients` (the count) stays accurate above that, but `client_ips` and `client_details` are capped at 10 entries.

Note: season/episode numbers are not exposed (`media_season`/`media_episode`), since Dispatcharr's official `current-programs` endpoint used for EPG matching doesn't provide that field — this is a deliberate trade-off for far more reliable channel-to-program matching than the upstream project's name-guessing approach.

## Troubleshooting

* **Program Data is `null`:** If the `media_title` and other program attributes are `null` (and the EPG option is enabled), it means Dispatcharr has no currently-airing program in its guide for that channel. Make sure the channel has EPG data assigned in the Dispatcharr UI and that your EPG source has been refreshed recently.
* **Authentication Errors:** If you receive errors during setup, double-check that your Dispatcharr URL, username and password are correct, and that the URL is reachable from your Home Assistant instance (check any reverse proxy/firewall in between). If the integration later reports it needs reauthentication, your stored API key has been revoked on the Dispatcharr side — go through the reauth prompt with your username/password to mint a new one.
* **Websocket keeps disconnecting / stream sensors don't update in realtime:** Check the Home Assistant log for `Dispatcharr websocket disconnected` warnings. If it's constantly retrying, verify your stored credentials are still valid. Remember that live stream-stats events are admin-only on the Dispatcharr side (see [Realtime updates](#realtime-updates)) — a non-admin account will connect fine but simply won't receive those specific events; this isn't a bug.
* **Stopping a stream stops it for everyone:** `media_player.media_stop` calls Dispatcharr's `/proxy/ts/stop/{channel_id}`, which tears down the whole channel stream, not just one viewer's session. Dispatcharr doesn't expose enough per-client identity through this integration's data to target a single viewer.
* **Migrating from the upstream integration:** [lyfesaver74/ha-dispatcharr](https://github.com/lyfesaver74/ha-dispatcharr) stored your host/port and password directly and re-logged-in on every restart. On first startup after switching to this fork, existing config entries are migrated automatically to the new URL + API key format using your stored credentials — no action needed, but Dispatcharr must be reachable at that moment for the migration to succeed.

## License

This project is licensed under the MIT License - see the `LICENSE` file for details.
