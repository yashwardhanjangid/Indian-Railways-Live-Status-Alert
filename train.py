"""
Indian Railways Live Status Alert
----------------------------------
Fetches live status for a train from RailRadar and sends a Telegram
message only when something meaningful has changed since the last run.

Field names below match RailRadar's documented response for
GET /v1/trains/{number}/live (https://railradar.in/docs/live-train-status).
"""

import os
import sys
import json
import logging
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger("train-alert")

RAILRADAR_API_KEY = os.getenv("RAILRADAR_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Kept as a hardcoded default (same as your original script) but can be
# overridden without touching code, e.g. via a repo variable/secret later.
TRAIN_NUMBER = os.getenv("TRAIN_NUMBER", "12956")

RAILRADAR_URL = f"https://api.railradar.in/v1/trains/{TRAIN_NUMBER}/live"
TELEGRAM_API_URL_TEMPLATE = "https://api.telegram.org/bot{token}/sendMessage"

STATUS_FILE = "previous_status.json"
REQUEST_TIMEOUT = 15  # seconds

# Fields used to decide whether anything "changed". lastUpdatedAt / raw
# timestamps are deliberately excluded here -- RailRadar refreshes those
# on almost every poll even when nothing about the journey has actually
# changed, which would otherwise spam a Telegram message every 15 minutes.
COMPARISON_KEYS = [
    "status",
    "delay_minutes",
    "current_station_code",
    "current_station_name",
    "current_station_action",
    "previous_station_name",
    "next_station_name",
    "platform",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fail(message: str) -> None:
    """Log an error and exit non-zero so the GitHub Actions step is marked failed."""
    logger.error(message)
    sys.exit(1)


def validate_environment() -> None:
    missing = [
        name
        for name, value in (
            ("RAILRADAR_API_KEY", RAILRADAR_API_KEY),
            ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
            ("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID),
        )
        if not value
    ]
    if missing:
        fail(f"Missing required environment variable(s): {', '.join(missing)}")


def escape_markdown(value) -> str:
    """Escape characters that break Telegram's classic Markdown parse mode."""
    if value is None:
        return value
    text = str(value)
    for ch in ("_", "*", "`", "["):
        text = text.replace(ch, f"\\{ch}")
    return text


# ---------------------------------------------------------------------------
# RailRadar
# ---------------------------------------------------------------------------

def fetch_live_status() -> dict:
    headers = {"Authorization": f"Bearer {RAILRADAR_API_KEY}"}
    logger.info("Requesting live status for train %s ...", TRAIN_NUMBER)

    try:
        response = requests.get(RAILRADAR_URL, headers=headers, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as exc:
        fail(f"Network error while calling RailRadar: {exc}")
        return {}  # unreachable, keeps linters happy

    logger.info("RailRadar responded with HTTP %s", response.status_code)

    try:
        payload = response.json()
    except ValueError:
        fail(
            f"RailRadar returned a non-JSON response "
            f"(HTTP {response.status_code}): {response.text[:300]}"
        )
        return {}

    if response.status_code != 200 or not payload.get("success"):
        error = payload.get("error", {}) or {}
        code = error.get("code", "UNKNOWN")
        message = error.get("message", "No error message provided")
        if response.status_code == 429:
            fail(
                f"RailRadar rate limit exceeded [{code}]: {message}. "
                f"Free tier is 50 requests/day -- consider a less frequent cron schedule."
            )
        fail(f"RailRadar API error [{code}]: {message}")
        return {}

    data = payload.get("data")
    if not data:
        fail("RailRadar response did not contain a 'data' object.")
        return {}

    return data


def find_route_stop(route: list, station_code: str) -> dict:
    """Look up a stop in the route array by station code."""
    if not station_code:
        return {}
    for stop in route or []:
        if stop.get("stationCode") == station_code:
            return stop
    return {}


def extract_snapshot(data: dict) -> dict:
    """
    Flatten the fields we care about out of RailRadar's nested response.
    Every lookup uses .get() with a safe default so a missing or
    renamed field never crashes the run -- it just shows as "Not available".
    """
    route = data.get("route") or []
    current_location = data.get("currentLocation") or {}
    previous_halt = data.get("previousHalt") or {}
    next_halt = data.get("nextHalt") or {}

    current_station_code = current_location.get("stationCode")
    current_route_stop = find_route_stop(route, current_station_code)

    return {
        "train_number": data.get("trainNumber", TRAIN_NUMBER),
        "train_name": data.get("trainName", ""),
        "status": data.get("status", "unknown"),
        "delay_minutes": data.get("delayMinutes"),
        "last_updated_at": data.get("lastUpdatedAt"),
        "is_live": data.get("isLive"),
        "current_station_code": current_station_code,
        # currentLocation itself has no station name -- pull it from
        # the matching route entry, which also carries the platform.
        "current_station_name": current_route_stop.get("stationName"),
        "current_station_action": current_location.get("status"),  # e.g. "departed" / "arrived"
        "segment_progress": current_location.get("segmentProgress"),
        "previous_station_code": previous_halt.get("stationCode"),
        "previous_station_name": previous_halt.get("stationName"),
        "next_station_code": next_halt.get("stationCode"),
        "next_station_name": next_halt.get("stationName"),
        "platform": current_route_stop.get("platform"),
    }


# ---------------------------------------------------------------------------
# State (previous_status.json)
# ---------------------------------------------------------------------------

def load_previous_status() -> dict:
    if not os.path.exists(STATUS_FILE):
        logger.info("No previous status file found -- treating as first run.")
        return {}

    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
    except OSError as exc:
        logger.warning("Could not read %s (%s) -- treating as first run.", STATUS_FILE, exc)
        return {}

    if not content:
        return {}

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.warning("%s contains invalid JSON -- treating as first run.", STATUS_FILE)
        return {}


def save_status(snapshot: dict) -> None:
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)
        f.write("\n")
    logger.info("Saved updated snapshot to %s", STATUS_FILE)


def has_changed(previous: dict, current: dict) -> bool:
    if not previous:
        logger.info("No previous snapshot on record -- treating as a change.")
        return True

    changed = False
    for key in COMPARISON_KEYS:
        if previous.get(key) != current.get(key):
            logger.info("Change detected in '%s': %r -> %r", key, previous.get(key), current.get(key))
            changed = True
    return changed


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def format_telegram_message(snapshot: dict) -> str:
    status_emojis = {
        "running": "🟢",
        "not-started": "⚪",
        "completed": "🏁",
        "cancelled": "🔴",
    }
    status = snapshot.get("status", "unknown")
    emoji = status_emojis.get(status, "ℹ️")

    delay = snapshot.get("delay_minutes")
    if delay is None:
        delay_line = "Not available"
    elif delay <= 0:
        delay_line = "On time"
    else:
        delay_line = f"{delay} min late"

    current_name = escape_markdown(
        snapshot.get("current_station_name") or snapshot.get("current_station_code") or "Unknown"
    )
    action = escape_markdown(snapshot.get("current_station_action") or "at")
    prev_name = escape_markdown(snapshot.get("previous_station_name") or "—")
    next_name = escape_markdown(snapshot.get("next_station_name") or "—")
    platform = escape_markdown(snapshot.get("platform") or "Not available")
    updated = escape_markdown(snapshot.get("last_updated_at") or "Not available")
    train_name = escape_markdown(snapshot.get("train_name") or "Train")
    train_number = escape_markdown(snapshot.get("train_number") or TRAIN_NUMBER)

    lines = [
        f"{emoji} *{train_name} ({train_number})*",
        "",
        f"*Status:* {status.replace('-', ' ').title()}",
        f"*Delay:* {delay_line}",
        f"*Current station:* {current_name} ({action})",
        f"*Previous stop:* {prev_name}",
        f"*Next stop:* {next_name}",
        f"*Platform:* {platform}",
        f"*Last updated:* {updated}",
    ]
    return "\n".join(lines)


def send_telegram_message(text: str) -> None:
    url = TELEGRAM_API_URL_TEMPLATE.format(token=TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(url, data=payload, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as exc:
        fail(f"Network error while calling Telegram: {exc}")
        return

    if response.status_code != 200:
        fail(f"Telegram API error (HTTP {response.status_code}): {response.text[:300]}")
        return

    logger.info("Telegram message sent successfully.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    validate_environment()

    data = fetch_live_status()
    snapshot = extract_snapshot(data)
    previous = load_previous_status()

    if has_changed(previous, snapshot):
        logger.info("Status changed -- sending Telegram alert.")
        message = format_telegram_message(snapshot)
        send_telegram_message(message)
        save_status(snapshot)
    else:
        logger.info("No meaningful change since last run -- skipping Telegram message.")
        # previous_status.json is intentionally left untouched here so the
        # workflow's git-commit step has nothing to commit on a no-change run.

    logger.info("Run complete.")


if __name__ == "__main__":
    main()
