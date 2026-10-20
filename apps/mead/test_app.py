from pytest import approx
import os
import tempfile

os.environ["MEAD_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

c = TestClient(main.app)


def test_recipe_to_batch_flow():
    page = c.get("/recipes").text
    assert "Basic Traditional" in page and "Standard Cyser (5 gal)" in page
    rid = main.db().execute("SELECT id FROM batch WHERE name='Basic Traditional'").fetchone()[0]
    r = c.post(f"/batch/{rid}/clone")
    bid = int(r.url.path.split("/")[-1])
    assert "Basic Traditional" in r.text and "Brew this" not in r.text
    c.post(f"/batch/{bid}", data={"name": "Basic Traditional", "status": "primary", "volume_gal": "1",
                                  "n_need": "medium", "nutrient_protocol": "tosna", "goferm": "on",
                                  "start_date": "2026-10-01", "target_fg": "1.012", "target_fg_max": "1.022"})
    c.post(f"/batch/{bid}/reading", data={"taken_on": "2026-10-01", "sg": "1.110", "temp_f": "60"})
    assert "Nutrient dose 1" in c.get("/").text
    for _ in range(4):
        c.post(f"/batch/{bid}/event", data={"kind": "nutrient"})
    c.post(f"/batch/{bid}/reading", data={"taken_on": "2026-10-05", "sg": "1.050"})
    assert "Re-check gravity on" in c.get("/").text and "<td>Fermenting</td>" in c.get("/").text
    c.post(f"/batch/{bid}/reading", data={"taken_on": "2026-10-12", "sg": "1.040"})
    c.post(f"/batch/{bid}/reading", data={"taken_on": "2026-10-19", "sg": "1.040"})
    assert "<td>Possibly stuck</td>" in c.get("/").text and "check for a stuck fermentation" in c.get("/").text
    c.post(f"/batch/{bid}/save-recipe")
    assert c.get("/recipes").text.count("Basic Traditional") == 2


def test_bad_input_rejected():
    rid = main.db().execute("SELECT id FROM batch LIMIT 1").fetchone()[0]
    assert c.post(f"/batch/{rid}/reading", data={"sg": "2"}).status_code == 400
    assert c.post(f"/batch/{rid}/bogus/1/delete").status_code == 404
    assert c.post(f"/batch/{rid}", data={"name": "x", "status": "nope"}).status_code == 400
    assert "Check your inputs" in c.get("/calc?og=abc&fg=1").text


def test_calc_page():
    t = c.get("/calc?og=1.1&fg=1.0&t_og=1.1&t_vol=1&t_goferm=on&ph=3.5&s_vol=5&abv=15&b_cur=1.0&b_tgt=1.01&b_vol=5").text
    assert "14.20%" in t and "standard · dry" in t and "Campden" in t
    assert "sorbate may not be effective" in t and "1.43 lb" in t


def test_seed_upgrade_no_duplicates_and_deletes_stick():
    import sqlite3

    import seed
    con = sqlite3.connect(":memory:")
    con.executescript(main.SCHEMA)
    old = seed.RECIPES
    seed.RECIPES = old[:8]  # a database seeded before recipes 9-14 and the `seeded` table existed
    seed.run(con)
    con.execute("DROP TABLE seeded")
    seed.RECIPES = old
    count = "SELECT COUNT(*) FROM batch WHERE status='recipe'"
    seed.run(con)
    assert con.execute(count).fetchone()[0] == len(old) == 14
    con.execute("DELETE FROM batch WHERE name='Bochet (5 gal)'")
    seed.run(con)
    assert con.execute(count).fetchone()[0] == 13


def test_api_tasks_due():
    from datetime import date, timedelta
    bid = int(c.post("/batch", data={"name": "api-check"}).url.path.split("/")[-1])
    c.post(f"/batch/{bid}", data={"name": "api-check", "status": "secondary", "volume_gal": "1", "n_need": "low",
                                  "nutrient_protocol": "recipe", "start_date": "2026-09-11"})
    c.post(f"/batch/{bid}/reading", data={"taken_on": "2026-09-11", "sg": "1.120"})
    t = next(t for t in c.get("/api/tasks").json() if t["batch_id"] == bid)
    assert t["task"] == "Just pitched — Take a gravity reading" and t["due"]
    c.post(f"/batch/{bid}/reading", data={"taken_on": date.today().isoformat(), "sg": "1.040"})
    t = next(t for t in c.get("/api/tasks").json() if t["batch_id"] == bid)
    assert t["task"].startswith("Fermenting") and not t["due"]  # read today: nothing to do for a week
    c.post(f"/batch/{bid}/reading", data={"taken_on": (date.today() - timedelta(days=8)).isoformat(), "sg": "1.060"})
    assert c.get(f"/api/batch/{bid}").json()["last_sg"] == approx(1.040)  # latest by date, not insert order


def test_costs_and_inventory():
    q = lambda sql, *a: main.db().execute(sql, a).fetchone()[0]  # noqa: E731
    bid = int(c.post("/batch", data={"name": "cost-check"}).url.path.split("/")[-1])
    c.post(f"/batch/{bid}", data={"name": "cost-check", "status": "planned", "volume_gal": "1", "n_need": "low",
                                  "nutrient_protocol": "recipe"})
    c.post("/inventory", data={"kind": "honey", "name": "wildflower", "qty": "12", "unit": "lb", "paid": "48"})
    iid = q("SELECT id FROM inventory WHERE name='wildflower'")
    c.post(f"/inventory/{iid}", data={"delta": "12", "paid": "72"})  # restock: (48 + 72) / 24 lb
    assert q("SELECT unit_cost FROM inventory WHERE id=?", iid) == approx(5.0)
    assert c.post(f"/batch/{bid}/use", data={"inventory_id": iid, "qty": "25"}).status_code == 400  # only 24 on hand
    c.post(f"/batch/{bid}/use", data={"inventory_id": iid, "qty": "3"})
    c.post(f"/batch/{bid}/expense", data={"item": "71B yeast", "amount": "5.04"})
    assert q("SELECT qty FROM inventory WHERE id=?", iid) == approx(21)
    page = c.get(f"/batch/{bid}").text
    assert "$20.04" in page and "$3.97" in page  # total, and per 750 mL bottle (5.05 per gal)
    assert "$20.04" in c.get("/").text
    used = q("SELECT id FROM expense WHERE batch_id=? AND inventory_id IS NOT NULL", bid)
    c.post(f"/batch/{bid}/expense/{used}/delete")  # undo puts the honey back
    assert q("SELECT qty FROM inventory WHERE id=?", iid) == approx(24)
    assert "$120.00" in c.get("/inventory").text
    assert c.post(f"/inventory/{iid}", data={"delta": "-30"}).status_code == 400
    c.post(f"/inventory/{iid}/delete")
    c.post(f"/batch/{bid}/delete")  # cascades its expenses
    assert q("SELECT COUNT(*) FROM expense WHERE batch_id=?", bid) == 0


def test_inventory_edit():
    c.post("/inventory", data={"kind": "honey", "name": "clover", "qty": "5", "unit": "lb", "paid": "20"})
    iid = main.db().execute("SELECT id FROM inventory WHERE name='clover'").fetchone()[0]
    c.post(f"/inventory/{iid}/edit", data={"kind": "fruit", "name": "cherries", "qty": "2.5", "unit": "kg",
                                           "unit_cost": "6", "notes": "freezer"})
    row = main.db().execute("SELECT kind, name, qty, unit, unit_cost, notes FROM inventory WHERE id=?", (iid,)).fetchone()
    assert tuple(row) == ("fruit", "cherries", 2.5, "kg", 6.0, "freezer")
    assert 'action="/inventory/%d/edit"' % iid not in c.get("/inventory").text  # read-only until Edit
    assert 'action="/inventory/%d/edit"' % iid in c.get("/inventory?edit=1").text
    assert c.post(f"/inventory/{iid}/edit", data={"name": "", "qty": "1"}).status_code == 400
    assert c.post(f"/inventory/{iid}/edit", data={"name": "x", "qty": "-1"}).status_code == 400
    assert c.post("/inventory/99999/edit", data={"name": "x", "qty": "1"}).status_code == 404


def test_next_steps_have_dates():
    from datetime import date, timedelta
    task = lambda bid: c.get(f"/api/batch/{bid}").json()["task"]  # noqa: E731
    today = date.today()
    pitch = today - timedelta(days=2)
    bid = int(c.post("/batch", data={"name": "date-check"}).url.path.split("/")[-1])
    c.post(f"/batch/{bid}", data={"name": "date-check", "status": "primary", "volume_gal": "1", "n_need": "medium",
                                  "nutrient_protocol": "tosna", "goferm": "on", "start_date": pitch.isoformat()})
    c.post(f"/batch/{bid}/reading", data={"taken_on": pitch.isoformat(), "sg": "1.100"})
    assert task(bid) == "Fermenting — Nutrient dose 1: 1.4 g Fermaid-O on " + main.day(pitch + timedelta(days=1))
    t = next(t for t in c.get("/api/tasks").json() if t["batch_id"] == bid)
    assert t["due"]  # a nutrient dose is due even with a fresh reading
    for _ in range(3):
        c.post(f"/batch/{bid}/event", data={"kind": "nutrient"})
    assert task(bid).endswith("or by " + main.day(pitch + timedelta(days=7)))  # dose 4: break or day 7
    assert " g on " + main.day(pitch + timedelta(days=3)) + "</li>" in c.get(f"/batch/{bid}").text  # dose 3 on the page
    c.post(f"/batch/{bid}/event", data={"kind": "nutrient"})
    c.post(f"/batch/{bid}/reading", data={"taken_on": today.isoformat(), "sg": "1.050"})
    assert task(bid) == "Fermenting — Re-check gravity on " + main.day(today + timedelta(days=7))
    c.post(f"/batch/{bid}/reading", data={"taken_on": (today + timedelta(days=7)).isoformat(), "sg": "1.010"})
    c.post(f"/batch/{bid}/reading", data={"taken_on": (today + timedelta(days=14)).isoformat(), "sg": "1.010"})
    c.post(f"/batch/{bid}/event", data={"kind": "stabilize", "on_date": "2026-01-05"})
    assert task(bid) == "Stabilized — Backsweeten on or after Tue Jan 6" + ("" if today.year == 2026 else ", 2026") + " if wanted"
    assert main.day(date(today.year, 3, 7)).count(",") == 0 and main.day(date(2020, 3, 7)) == "Sat Mar 7, 2020"


def test_feedback():
    assert 'href="/feedback?from=/inventory"' in c.get("/inventory").text  # link on every page, carries the page
    assert 'value="/inventory"' in c.get("/feedback?from=/inventory").text
    assert c.post("/feedback", data={"message": "  "}).status_code == 400
    c.post("/feedback", data={"author": "Gabe", "page": "/inventory", "message": "Sort by kind please"})
    c.post("/feedback", data={"page": "https://evil.example", "message": "anon <b>hi</b>"})
    rows = main.db().execute("SELECT id, author, page, done FROM feedback ORDER BY id").fetchall()
    assert [tuple(r)[1:] for r in rows] == [("Gabe", "/inventory", 0), (None, None, 0)]  # off-site page dropped
    page = c.get("/feedback").text
    assert "Sort by kind please" in page and "&lt;b&gt;hi&lt;/b&gt;" in page  # escaped
    c.post(f"/feedback/{rows[0][0]}/toggle")
    assert main.db().execute("SELECT done FROM feedback WHERE id=?", (rows[0][0],)).fetchone()[0] == 1


def test_who_paid():
    q = lambda sql, *a: main.db().execute(sql, a).fetchall()  # noqa: E731
    main.db().execute("DELETE FROM payment").connection.commit()
    bid = int(c.post("/batch", data={"name": "money-check"}).url.path.split("/")[-1])
    c.post("/inventory", data={"kind": "honey", "name": "buckwheat", "qty": "10", "unit": "lb", "paid": "60",
                               "paid_by": "Ethan"})
    iid = q("SELECT id FROM inventory WHERE name='buckwheat'")[0][0]
    c.post(f"/inventory/{iid}", data={"delta": "5", "paid": "30", "paid_by": "Gabe"})  # restock
    c.post(f"/inventory/{iid}", data={"delta": "-1", "paid_by": "Gabe"})  # a correction isn't a payment
    c.post(f"/batch/{bid}/expense", data={"item": "spices", "amount": "10", "paid_by": "Gabe"})
    c.post(f"/batch/{bid}/expense", data={"item": "no payer", "amount": "5"})  # paid_by is optional
    c.post(f"/batch/{bid}/use", data={"inventory_id": iid, "qty": "2"})  # using stock isn't a payment
    rows = q("SELECT paid_by, amount, item, batch_id FROM payment ORDER BY id")
    assert [tuple(r) for r in rows] == [("Ethan", 60, "10 lb buckwheat", None), ("Gabe", 30, "5 lb buckwheat (restock)", None),
                                        ("Gabe", 10, "spices", bid)]
    page = c.get("/money").text  # $100 shared: $50 each; Ethan paid 60, Gabe 40
    assert "$100.00" in page and "is owed $10.00" in page and "owes $10.00" in page
    assert c.post("/money", data={"paid_by": "Gabe", "paid_to": "Gabe", "amount": "10"}).status_code == 400
    c.post("/money", data={"paid_by": "Gabe", "paid_to": "Ethan", "amount": "10"})  # settle up
    page = c.get("/money").text
    assert "$100.00" in page and page.count(">even<") == 2 and "Paid back Ethan" in page
    assert '<option>Gabe</option>' in c.get("/inventory").text  # suggestions on other pages
