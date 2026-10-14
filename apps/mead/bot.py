"""Mead Log Discord bot: posts each due task at 6 AM ET; replies feed readings and steps back into the app.

Reply to a task message with:
  - a reading, e.g. "1.040" or "1.040 68F"  -> saved
  - "done"                                  -> logs the step (nutrient, stabilize, ...)
"""
import datetime as dt
import logging
import os
import re
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord.ext import tasks

MEAD_URL = os.environ.get("MEAD_URL", "http://mead-svc:8770")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://homebrew.case.local")
REPOST_DAYS = 3  # an open task is posted again after this many days
SG_RE = re.compile(r"\b([01]\.\d{3,4})\b")
TEMP_RE = re.compile(r"\b(\d{2,3}(?:\.\d)?)\s*°?\s*f\b", re.I)
BATCH_RE = re.compile(r"\(#(\d+)\)")
# task wording (main.next_action) -> event logged on "done"; first match wins
DONE_EVENTS = [("nutrient", "nutrient"), ("backsweeten", "backsweeten"), ("stabilize", "stabilize"),
               ("bottle", "bottle"), ("rack", "rack")]


def parse_reading(text: str) -> Optional[Tuple[float, Optional[float]]]:
    """'1.040 68F' -> (1.040, 68.0); no gravity -> None."""
    m = SG_RE.search(text)
    if not m:
        return None
    t = TEMP_RE.search(text)
    return float(m.group(1)), float(t.group(1)) if t else None


def batch_of(message_text: str) -> Optional[int]:
    m = BATCH_RE.search(message_text)
    return int(m.group(1)) if m else None


def done_event(task_text: str) -> str:
    low = task_text.lower()
    return next((ev for word, ev in DONE_EVENTS if word in low), "note")


def task_message(t: dict) -> str:
    last = f"Last reading {t['last_sg']:.3f} on {t['last_date']}." if t["last_sg"] else "No readings yet."
    link = f" Guide: <{t['link']}>" if t["link"] else ""
    return (f"🍯 **{t['name']}** (#{t['batch_id']}): {t['task']}\n{last}{link}\n"
            f"Reply with a reading (`1.040 68F`) or `done`. "
            f"<{PUBLIC_URL}/batch/{t['batch_id']}>")


def main():
    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger("mead-bot")
    token = os.environ["DISCORD_BOT_TOKEN"]
    channel_id = int(os.environ["CHANNEL_ID"])
    allowed = {int(u) for u in os.environ["ALLOWED_USER_IDS"].split(",") if u.strip()}
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    http: Optional[aiohttp.ClientSession] = None

    async def save_reading(bid: int, sg: float, temp: Optional[float], note: str) -> str:
        data = {"sg": f"{sg:.3f}", "temp_f": "" if temp is None else str(temp), "note": note,
                "taken_on": dt.datetime.now(ZoneInfo("America/New_York")).date().isoformat()}
        async with http.post(f"{MEAD_URL}/batch/{bid}/reading", data=data, allow_redirects=False) as r:
            if r.status != 303:
                return f"⚠️ Not saved: {(await r.text())[:200]}"
        async with http.get(f"{MEAD_URL}/api/batch/{bid}") as r:
            b = await r.json()
        abv = f", ABV {b['abv']}%" if b["abv"] is not None else ""
        nxt = f"\nNext: {b['task']}" if b["task"] else ""
        return f"✅ Saved {sg:.3f}{f' at {temp:g}°F' if temp else ''} for **{b['name']}**{abv}.{nxt}"

    @tasks.loop(time=dt.time(6, 0, tzinfo=ZoneInfo("America/New_York")))
    async def post_tasks():
        channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=REPOST_DAYS)
        recent = [m.content async for m in channel.history(after=since, limit=200) if m.author == client.user]
        async with http.get(f"{MEAD_URL}/api/tasks") as r:
            todo = [t for t in await r.json() if t["due"]]
        for t in todo:
            if any(f"(#{t['batch_id']})" in c and t["task"] in c for c in recent):
                continue
            await channel.send(task_message(t))
        log.info("posted tasks: %d due", len(todo))

    @client.event
    async def on_ready():
        nonlocal http
        http = http or aiohttp.ClientSession()
        log.info("logged in as %s", client.user)
        if not post_tasks.is_running():
            post_tasks.start()
            await post_tasks()  # catch up after a restart; the repost window keeps this from spamming

    @client.event
    async def on_message(msg: discord.Message):
        if msg.author.id not in allowed or msg.channel.id != channel_id or not msg.reference:
            return
        ref = msg.reference.resolved or await msg.channel.fetch_message(msg.reference.message_id)
        if ref.author != client.user or not (bid := batch_of(ref.content)):
            return
        reading = parse_reading(msg.content)
        if reading:
            await msg.reply(await save_reading(bid, *reading, note="via Discord"))
        elif msg.content.strip().lower() in ("done", "did it", "✅"):
            task = ref.content.split(": ", 1)[-1].split("\n")[0]
            kind = done_event(task)
            async with http.post(f"{MEAD_URL}/batch/{bid}/event", allow_redirects=False,
                                 data={"kind": kind, "note": f"Done via Discord: {task}"}) as r:
                ok = r.status == 303
            await msg.reply(f"✅ Logged **{kind}**." if ok else "⚠️ Couldn't log that.")
        else:
            await msg.reply("Reply with a reading like `1.040` (optionally `68F`), or `done`.")

    client.run(token, log_handler=None)


if __name__ == "__main__":
    main()
