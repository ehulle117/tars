#!/usr/bin/env python3
"""Post a message (optionally with an image) to Discord via the bot API.

Reads the bot token from ~/.config/adsb-tools/discord_bot_token (same Tars
bot as noaa-apt-decoder; never hardcoded, never logged).
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

TOKEN_FILE = Path.home() / ".config" / "adsb-tools" / "discord_bot_token"

# Surfaced in state.json so the map can warn when alerts are failing.
STATUS: dict = {"last_ok": None, "last_error": None, "last_error_at": None}


def post(channel_id: str, content: str, image_path: str | None = None) -> None:
    token = TOKEN_FILE.read_text().strip()
    args = [
        "curl", "-sS", "-f",
        "-H", f"Authorization: Bot {token}",
    ]
    if image_path:
        args += [
            "-F", f"payload_json={json.dumps({'content': content})}",
            "-F", f"file=@{image_path}",
        ]
    else:
        args += ["-H", "Content-Type: application/json", "-d", json.dumps({"content": content})]
    args.append(f"https://discord.com/api/v10/channels/{channel_id}/messages")
    try:
        subprocess.run(args, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        # Raise a fresh error: str(e) would include the full command line, token and all.
        lines = (e.stderr or "").strip().splitlines()
        msg = lines[-1] if lines else f"curl exit {e.returncode}"
        STATUS["last_error"], STATUS["last_error_at"] = msg, time.time()
        raise RuntimeError(f"discord post failed: {msg}") from None
    STATUS["last_ok"] = time.time()


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        print(f"Usage: {sys.argv[0]} <channel_id> <content> [image_path]")
        sys.exit(1)
    channel_id, content = sys.argv[1], sys.argv[2]
    image_path = sys.argv[3] if len(sys.argv) > 3 else None
    post(channel_id, content, image_path)
