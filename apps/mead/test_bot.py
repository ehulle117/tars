from pytest import approx

import bot


def test_parse_reading():
    assert bot.parse_reading("1.040") == (approx(1.040), None)
    assert bot.parse_reading("it's at 1.0405 68F") == (approx(1.0405), approx(68))
    assert bot.parse_reading("0.998 at 70.5 °F") == (approx(0.998), approx(70.5))
    assert bot.parse_reading("done") is None
    assert bot.parse_reading("about 1.04") is None  # needs 3+ decimals, so a stray number isn't saved


def test_batch_and_done_mapping():
    msg = bot.task_message({"batch_id": 20, "name": "Green Zinger", "task": "Nutrient dose 2: 1.4 g Fermaid-O (48h)",
                            "link": None, "last_sg": 1.046, "last_date": "2026-10-13"})
    assert bot.batch_of(msg) == 20 and "1.046 on 2026-10-13" in msg
    assert bot.batch_of("no id here") is None
    assert bot.done_event("Nutrient dose 2: 1.4 g Fermaid-O (48h)") == "nutrient"
    assert bot.done_event("Stabilized — wait 24 h, then backsweeten if wanted") == "backsweeten"
    assert bot.done_event("Stable — stabilize (K-meta + sorbate)") == "stabilize"
    assert bot.done_event("Clear? Bottle or keep aging") == "bottle"
    assert bot.done_event("Stable above target FG — possibly stuck") == "note"
