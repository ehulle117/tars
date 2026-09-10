import json
import logging
import os
import subprocess

logger = logging.getLogger(__name__)


def post_to_channel(channel_id, content):
    """Posts a plain message to a Discord text channel via the Tars bot.

    Shells out to curl rather than using requests/urllib directly - Discord's
    edge blocks Python's default TLS/HTTP fingerprint with a 403 (same issue
    worked around with wget in apps/pod-health-check.yaml and
    apps/resource-pressure-check.yaml; this image is python:3.11-slim, which
    has curl - installed for the Trivy install script - but not wget).
    """
    bot_token = os.environ.get("DISCORD_BOT_TOKEN")
    if not bot_token or not channel_id:
        logger.warning("DISCORD_BOT_TOKEN or channel id missing. Cannot post to Discord.")
        return

    try:
        result = subprocess.run(
            [
                "curl", "-sS", "-f",
                "-H", "Authorization: Bot " + bot_token,
                "-H", "Content-Type: application/json",
                "-d", json.dumps({"content": content}),
                f"https://discord.com/api/v10/channels/{channel_id}/messages",
            ],
            check=True, timeout=15, capture_output=True, text=True,
        )
        logger.info("Successfully posted digest to Discord.")
        return result.stdout
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to post to Discord: {e.stderr}")
    except Exception as e:
        logger.error(f"Failed to post to Discord: {e}")


def format_weekly_digest(os_updates, container_updates):
    """Builds a plain-text weekly OS/container update summary for Discord,
    replacing the old weekly_digest.html email template."""
    lines = ["**📅 Tars Weekly Update Digest**", ""]

    lines.append("**System Packages**")
    if os_updates:
        for update in os_updates:
            lines.append(f"- {update['name']} ({update['version']})")
    else:
        lines.append("No baremetal OS packages require updating.")
    lines.append("")

    lines.append("**Container Images**")
    if container_updates:
        for update in container_updates:
            lines.append(f"- {update['name']} is outdated (current: {update['current']})")
    else:
        lines.append("All scanned containers appear to be up to date.")

    return "\n".join(lines)
