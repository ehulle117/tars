from pytest import approx

import bot


def test_parse_reading():
    assert bot.parse_reading("1.040") == (approx(1.040), None)
    assert bot.parse_reading("it's at 1.0405 68F") == (approx(1.0405), approx(68))
    assert bot.parse_reading("0.998 at 70.5 °F") == (approx(0.998), approx(70.5))
    assert bot.parse_reading("done") is None
    assert bot.parse_reading("about 1.04") is None  # needs 3+ decimals, so a stray number isn't saved


def test_batch_and_done_mapping():
    msg = bot.task_message({"batch_id": 20, "name": "Green Zinger", "task": "Nutrient dose 2: 1.4 g Fermaid-O on Tue Oct 13",
                            "link": None, "last_sg": 1.046, "last_date": "2026-10-13"})
    assert bot.batch_of(msg) == 20 and "1.046 on 2026-10-13" in msg
    assert bot.batch_of("no id here") is None
    assert bot.done_event("Nutrient dose 2: 1.4 g Fermaid-O on Tue Oct 13") == "nutrient"
    assert bot.done_event("Stabilized — Backsweeten on or after Wed Oct 22 if wanted") == "backsweeten"
    assert bot.done_event("Stable — Stabilize (K-meta + sorbate)") == "stabilize"
    assert bot.done_event("Aging — Bottle when clear, or keep aging") == "bottle"
    assert bot.done_event("Possibly stuck — Stable above target FG: check for a stuck fermentation") == "note"
    assert bot.done_event("Fermenting — Re-check gravity on Tue Oct 20") == "note"


def test_reminder_message():
    t = {"batch_id": 21, "name": "Black Tea", "task": "Reminder — Taste; pull the clove (Sun Nov 8)", "link": None,
         "last_sg": 1.028, "last_date": "2026-11-06", "reminder": 3, "every_days": 1}
    msg = bot.task_message(t)
    assert bot.reminder_of(msg) == 3 and bot.batch_of(msg) == 21 and "reminded tomorrow" not in msg
    assert "in 1 day." in msg and "`not yet`" in msg
    assert "reminded tomorrow" in bot.task_message({**t, "every_days": None})
    assert bot.reminder_of(bot.task_message({**t, "reminder": None})) is None
