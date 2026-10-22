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
    assert "Re-check gravity on" in c.get("/").text and "Primary · fermenting</span>" in c.get("/").text
    c.post(f"/batch/{bid}/reading", data={"taken_on": "2026-10-12", "sg": "1.040"})
    c.post(f"/batch/{bid}/reading", data={"taken_on": "2026-10-19", "sg": "1.040"})
    assert "· possibly stuck</span>" in c.get("/").text and "check for a stuck fermentation" in c.get("/").text
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
    c.post("/inventory/save", data={"name-%d" % iid: "x", "qty-%d" % iid: "1", "remove-%d" % iid: "on"})
    assert not main.db().execute("SELECT 1 FROM inventory WHERE id=?", (iid,)).fetchone()
    c.post(f"/batch/{bid}/delete")  # cascades its expenses
    assert q("SELECT COUNT(*) FROM expense WHERE batch_id=?", bid) == 0


def test_inventory_edit():
    c.post("/inventory", data={"kind": "honey", "name": "clover", "qty": "5", "unit": "lb", "paid": "20"})
    c.post("/inventory", data={"kind": "oak", "name": "cubes", "qty": "2", "unit": "oz"})
    a, b = [r[0] for r in main.db().execute("SELECT id FROM inventory WHERE name IN ('clover', 'cubes') ORDER BY id")]
    assert 'name="name-%d"' % a not in c.get("/inventory").text  # read-only until Edit
    assert 'name="name-%d"' % a in c.get("/inventory?edit=1").text and "Save &amp; done" in c.get("/inventory?edit=1").text
    row = lambda i: tuple(main.db().execute("SELECT kind, name, qty, unit, unit_cost, notes FROM inventory WHERE id=?", (i,)).fetchone())  # noqa: E731
    bad = {f"name-{a}": "cherries", f"qty-{a}": "2.5", f"name-{b}": "", f"qty-{b}": "1"}
    assert c.post("/inventory/save", data=bad).status_code == 400 and row(a)[1] == "clover"  # all or nothing
    c.post("/inventory/save", data={f"kind-{a}": "fruit", f"name-{a}": "cherries", f"qty-{a}": "2.5", f"unit-{a}": "kg",
                                    f"unit_cost-{a}": "6", f"notes-{a}": "freezer",
                                    f"name-{b}": "cubes", f"qty-{b}": "2", f"remove-{b}": "on"})
    assert row(a) == ("fruit", "cherries", 2.5, "kg", 6.0, "freezer")
    assert not main.db().execute("SELECT 1 FROM inventory WHERE id=?", (b,)).fetchone()

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
    assert "$100.00" in page and page.count(">even<") == 2 and "paid back Ethan" in page
    assert '<option>Gabe</option>' in c.get("/inventory").text  # suggestions on other pages


def test_who_paid_unassigned_and_edit():
    con = main.db()
    con.execute("DELETE FROM payment")
    con.execute("INSERT INTO payment (paid_on, paid_by, amount, item) VALUES ('2026-01-01', '', 40, 'corker')")
    con.execute("INSERT INTO payment (paid_on, paid_by, amount, item) VALUES ('2026-01-02', 'Ethan', 20, 'yeast')")
    con.execute("INSERT INTO payment (paid_on, paid_by, amount, item) VALUES ('2026-01-03', 'Ethan', 5, 'oops')")
    con.commit()
    p, y, x = [r[0] for r in con.execute("SELECT id FROM payment ORDER BY id")]
    page = c.get("/money").text
    assert "Unassigned (not split yet)" in page and "$40.00" in page and ">even<" in page  # Ethan alone: even
    assert f'name="item-{p}"' not in page and f'name="item-{p}"' in c.get("/money?edit=1").text
    row = lambda i, by="Ethan", amt="20": {f"paid_on-{i}": "2026-01-01", f"paid_by-{i}": by, f"item-{i}": "x", f"amount-{i}": amt}  # noqa: E731
    bad = {**row(p, "Gabe", "40"), **row(y, amt="0")}
    assert c.post("/money/save", data=bad).status_code == 400  # all or nothing
    assert con.execute("SELECT paid_by FROM payment WHERE id=?", (p,)).fetchone()[0] == ""
    c.post("/money/save", data={**row(p, "Gabe", "40"), **row(y), **row(x, amt="5"), f"remove-{x}": "on"})
    page = c.get("/money").text  # $60 shared, $30 each: Gabe paid 40, Ethan 20
    assert "Unassigned" not in page and "is owed $10.00" in page and "owes $10.00" in page and "oops" not in page


def test_units_and_equipment():
    db = lambda sql, *a: main.db().execute(sql, a).fetchone()  # noqa: E731
    bid = int(c.post("/batch", data={"name": "units-check"}).url.path.split("/")[-1])
    c.post("/inventory", data={"kind": "nutrient", "name": "Fermaid K", "qty": "100", "unit": "g", "paid": "10"})
    c.post("/inventory", data={"kind": "equipment", "name": "Kitchen scale", "qty": "1", "unit": "each", "paid": "18",
                               "paid_by": "Ethan"})
    fk, scale = db("SELECT id FROM inventory WHERE name='Fermaid K'")[0], db("SELECT id FROM inventory WHERE name='Kitchen scale'")[0]
    assert db("SELECT item FROM payment WHERE amount=18")[0] == "Kitchen scale"  # not "1 each Kitchen scale"
    inv = c.get("/inventory").text
    assert '<h2 id="equipment">Equipment' in inv and "equipment <b class=\"num\" style=\"color:var(--fg)\">$18.00</b>" in inv
    assert '"equipment": "each"' in inv  # kind -> default unit map for Add item
    page = c.get(f"/batch/{bid}").text
    assert f'<option value="{fk}">' in page and f'<option value="{scale}">' not in page  # equipment isn't "used"
    c.post(f"/batch/{bid}/use", data={"inventory_id": fk, "qty": "0.5", "unit": "oz"})  # 14.17 g
    assert db("SELECT qty FROM inventory WHERE id=?", fk)[0] == approx(100 - 14.1748, abs=1e-3)
    assert db("SELECT item FROM expense WHERE batch_id=?", bid)[0] == "0.5 oz Fermaid K (= 14.17 g)"
    assert c.post(f"/batch/{bid}/use", data={"inventory_id": fk, "qty": "1", "unit": "tsp"}).status_code == 400
    assert c.post(f"/batch/{bid}/use", data={"inventory_id": fk, "qty": "1", "unit": "kg"}).status_code == 400  # > on hand
    eid = db("SELECT id FROM expense WHERE batch_id=?", bid)[0]
    c.post(f"/batch/{bid}/expense/{eid}/delete")  # undo returns the converted grams
    assert db("SELECT qty FROM inventory WHERE id=?", fk)[0] == approx(100)


def test_up_next_batch_panel_and_settle_up():
    from datetime import date, timedelta
    today = date.today()
    bid = int(c.post("/batch", data={"name": "next-check"}).url.path.split("/")[-1])
    c.post(f"/batch/{bid}", data={"name": "next-check", "status": "secondary", "volume_gal": "1", "n_need": "low",
                                  "nutrient_protocol": "recipe", "start_date": (today - timedelta(days=20)).isoformat()})
    c.post(f"/batch/{bid}/reading", data={"taken_on": (today - timedelta(days=20)).isoformat(), "sg": "1.100"})
    c.post(f"/batch/{bid}/reading", data={"taken_on": (today - timedelta(days=9)).isoformat(), "sg": "1.010"})
    home = c.get("/").text  # re-check was due 2 days ago
    assert "Up next" in home and "Overdue since " + main.day(today - timedelta(days=2)) in home
    page = c.get(f"/batch/{bid}").text
    assert 'id="log-reading"' in page and "Gravity today" in page
    c.post(f"/batch/{bid}/reading", data={"taken_on": today.isoformat(), "sg": "1.010"})  # stable now
    assert "Due today" in c.get("/").text and "Stabilize" in c.get("/").text
    r = c.post(f"/batch/{bid}/event", data={"kind": "stabilize", "back": "/"}, follow_redirects=False)
    assert r.headers["location"] == "/"  # Mark done on the dashboard returns there
    r = c.post(f"/batch/{bid}/event", data={"kind": "note", "back": "//evil.example"}, follow_redirects=False)
    assert r.headers["location"] == f"/batch/{bid}"  # no off-site redirects
    assert "Backsweeten on or after " + main.day(today + timedelta(days=1)) in c.get("/").text

    con = main.db()
    con.execute("DELETE FROM payment")
    con.execute("INSERT INTO payment (paid_on, paid_by, amount, item) VALUES ('2026-01-01', 'Ethan', 100, 'honey')")
    con.execute("INSERT INTO payment (paid_on, paid_by, amount, item) VALUES ('2026-01-01', 'Gabe', 40, 'yeast')")
    con.commit()
    assert "Gabe owes Ethan $30.00" in c.get("/money").text
    c.post("/money", data={"paid_by": "Gabe", "paid_to": "Ethan", "amount": "30.00", "item": "Settle up"})
    page = c.get("/money").text
    assert "owes Ethan" not in page and "All square." in page


def test_redesign_pages():
    from datetime import date, timedelta
    today = date.today()
    bid = int(c.post("/batch", data={"name": "cellar-check"}).url.path.split("/")[-1])
    c.post(f"/batch/{bid}", data={"name": "cellar-check", "status": "secondary", "volume_gal": "1", "n_need": "low",
                                  "nutrient_protocol": "recipe", "start_date": (today - timedelta(days=30)).isoformat()})
    c.post(f"/batch/{bid}/reading", data={"taken_on": (today - timedelta(days=30)).isoformat(), "sg": "1.100"})
    c.post(f"/batch/{bid}/event", data={"kind": "rack", "on_date": (today - timedelta(days=10)).isoformat(), "note": "to glass"})
    c.post(f"/batch/{bid}/expense", data={"item": "3 lb clover honey", "amount": "12"})
    c.post(f"/batch/{bid}/expense", data={"item": "airlock", "amount": "3"})
    s = main.stats(main.db(), main.get_batch(main.db(), bid))
    assert s["cost_parts"] == [("honey", 12), ("other", 3)]
    assert [st["name"] for st in s["stages"] if st["done"]] == ["planned", "primary"] and s["stages"][2]["now"]
    assert s["timeline"][0]["what"] == "Rack" and s["timeline"][0]["note"] == "to glass"

    # quick log: pick a batch, save, land back with a confirmation
    page = c.get("/log").text
    assert f'value="{bid}"' in page and "Save reading" in page
    r = c.post("/log", data={"batch_id": bid, "sg": "1.020", "taken_on": today.isoformat()})
    assert "Saved for cellar-check" in r.text
    assert c.post("/log", data={"batch_id": bid, "sg": "3"}).status_code == 400
    assert main.stats(main.db(), main.get_batch(main.db(), bid))["spark"]  # two readings: a sparkline

    # bottles filled -> real per-bottle cost in the cellar
    c.post(f"/batch/{bid}", data={"name": "cellar-check", "status": "bottled", "volume_gal": "1", "n_need": "low",
                                  "nutrient_protocol": "recipe", "bottles": "5", "bottle_date": today.isoformat()})
    assert main.get_batch(main.db(), bid)["bottles"] == 5
    home = c.get("/").text
    assert "In the cellar" in home and "$3.00" in home  # $15 over 5 bottles
    assert 'class="on">Batches' in home and 'href="/log"' in home


def test_balances_ignore_row_order():
    rows = [{"paid_by": "Ethan", "paid_to": None, "amount": a} for a in (0.1, 0.2, 830.55)] + \
           [{"paid_by": "Gabe", "paid_to": None, "amount": 375.0}]
    assert main.settle_up(rows) == main.settle_up(rows[::-1])  # half-cent splits round the same way


def test_who_is_using_this():
    bid = int(c.post("/batch", data={"name": "who-check"}).url.path.split("/")[-1])
    r = c.post("/who", data={"who": "Gabe", "back": f"/batch/{bid}"}, follow_redirects=False)
    assert r.headers["location"] == f"/batch/{bid}" and "who=Gabe" in r.headers["set-cookie"]
    c.cookies.set("who", "Gabe")
    c.post(f"/batch/{bid}/reading", data={"sg": "1.100"})
    c.post(f"/batch/{bid}/event", data={"kind": "pitch", "note": "71B"})
    assert main.db().execute("SELECT who FROM reading WHERE batch_id=?", (bid,)).fetchone()[0] == "Gabe"
    page = c.get(f"/batch/{bid}").text
    assert 'value="Gabe"' in page and "· Gabe" in page  # picker and timeline
    assert c.post("/who", data={"who": "x", "back": "//evil.example"}, follow_redirects=False).headers["location"] == "/"
    c.cookies.clear()


def test_plan_from_shelf_shopping_and_reorder():
    con = main.db()
    q = lambda sql, *a: con.execute(sql, a).fetchall()  # noqa: E731
    for k, n, qty, u, paid in [("honey", "Plan honey", 10, "lb", 40), ("nutrient", "DAP", 50, "g", 5),
                               ("yeast", "Lalvin 71B", 5, "each", 8), ("nutrient", "Fermaid O", 1, "g", 2)]:
        c.post("/inventory", data={"kind": k, "name": n, "qty": qty, "unit": u, "paid": paid})
    rid = q("SELECT id FROM batch WHERE name='Basic Melomel' AND status='recipe'")[0][0]
    bid = int(c.post(f"/batch/{rid}/clone").url.path.split("/")[-1])  # Brew this -> planned batch
    plan = {r["name"]: r for r in main.plan_rows(con, main.get_batch(con, bid), q("SELECT * FROM ingredient WHERE batch_id=?", bid))}
    assert plan["wildflower or orange blossom"]["inv"]["kind"] == "honey" and plan["wildflower or orange blossom"]["enough"]
    assert plan["Lalvin 71B-1122 (5 g)"]["inv"]["name"] == "Lalvin 71B" and plan["Lalvin 71B-1122 (5 g)"]["need"] == 1
    assert plan["blueberries (secondary)"]["inv"] is None and plan["Fermaid O"]["enough"] is False  # 1.7 g, have 1
    assert plan["raspberries (secondary)"]["later"]
    page = c.get(f"/batch/{bid}").text
    assert 'id="plan"' in page and "not stocked" in page and "short · 1 of 1.7 g" in page
    honey_id = q("SELECT id FROM inventory WHERE name='Plan honey'")[0][0]
    yeast_id = q("SELECT id FROM inventory WHERE name='Lalvin 71B'")[0][0]
    c.post(f"/batch/{bid}/use-many", data={"use-1": "on", "inv-1": honey_id, "qty-1": "3",
                                           "use-2": "on", "inv-2": yeast_id, "qty-2": "1", "inv-3": honey_id, "qty-3": "9"})
    assert q("SELECT qty FROM inventory WHERE id=?", honey_id)[0][0] == 7  # unticked row 3 ignored
    assert len(q("SELECT id FROM expense WHERE batch_id=?", bid)) == 2
    bad = {"use-1": "on", "inv-1": honey_id, "qty-1": "1", "use-2": "on", "inv-2": yeast_id, "qty-2": "99"}
    assert c.post(f"/batch/{bid}/use-many", data=bad).status_code == 400  # all or nothing
    assert q("SELECT qty FROM inventory WHERE id=?", honey_id)[0][0] == 7
    assert "used 1 each" in c.get(f"/batch/{bid}").text  # yeast already charged
    c.post(f"/batch/{bid}/shortfalls")
    names = {r[0]: r for r in q("SELECT name, qty, unit FROM shopping WHERE batch_id=?", bid)}
    assert "blueberries (secondary)" in names and names["Fermaid O"][1:] == (0.7, "g") and "Lalvin 71B" not in names
    c.post(f"/batch/{bid}/shortfalls")  # no duplicates
    assert len(q("SELECT id FROM shopping WHERE batch_id=?", bid)) == len(names)

    dap = q("SELECT id FROM inventory WHERE name='DAP'")[0][0]
    c.post("/inventory/save", data={f"name-{dap}": "DAP", f"kind-{dap}": "nutrient", f"qty-{dap}": "50",
                                    f"unit-{dap}": "g", f"reorder_at-{dap}": "60"})
    assert "running low" in c.get("/inventory").text and ">Low<" in c.get("/inventory").text
    assert "DAP" in c.get("/shopping").text and "Running out" in c.get("/shopping").text
    sid = q("SELECT id FROM shopping WHERE name='blueberries (secondary)'")[0][0]
    c.post(f"/shopping/{sid}/toggle")
    assert q("SELECT done FROM shopping WHERE id=?", sid)[0][0] == 1
    assert c.post(f"/shopping/{sid}/bogus").status_code == 404


def test_bottles_tastings_ready():
    from datetime import date, timedelta
    bid = int(c.post("/batch", data={"name": "cellar-life"}).url.path.split("/")[-1])
    soon = (date.today() + timedelta(days=60)).isoformat()
    c.post(f"/batch/{bid}", data={"name": "cellar-life", "status": "bottled", "volume_gal": "1", "n_need": "low",
                                  "nutrient_protocol": "recipe", "bottles": "5", "ready_on": soon})
    c.post(f"/batch/{bid}/bottle", data={"qty": "1", "kind": "drank", "rating": "4", "note": "a bit hot"})
    c.post(f"/batch/{bid}/bottle", data={"qty": "2", "kind": "gave away"})
    c.post(f"/batch/{bid}/event", data={"kind": "tasting", "rating": "2"})
    s = main.stats(main.db(), main.get_batch(main.db(), bid))
    assert s["left"] == 2 and s["rating"] == 3 and s["ready"].startswith("Ready ") and s["ready"] != "Ready now"
    assert c.post(f"/batch/{bid}/bottle", data={"qty": "3", "kind": "drank"}).status_code == 400  # only 2 left
    assert c.post(f"/batch/{bid}/bottle", data={"qty": "1", "kind": "spilled"}).status_code == 400
    page = c.get(f"/batch/{bid}").text
    assert "2</b> of 5 bottles left" in page and "Drank 1 bottle ★★★★" in page
    home = c.get("/").text
    assert "2<span class=\"muted\">/5</span>" in home
    oid = main.db().execute("SELECT id FROM bottle_out WHERE batch_id=? AND kind='gave away'", (bid,)).fetchone()[0]
    c.post(f"/batch/{bid}/bottle_out/{oid}/delete")
    assert main.stats(main.db(), main.get_batch(main.db(), bid))["left"] == 4


def test_photos_and_labels():
    import io
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    bid = int(c.post("/batch", data={"name": "photo-check"}).url.path.split("/")[-1])
    r = c.post(f"/batch/{bid}/photo", data={"caption": "racked", "on_label": "on"},
               files={"photo": ("p.png", io.BytesIO(png), "image/png")})
    assert r.status_code == 200
    row = main.db().execute("SELECT id, file, on_label FROM photo WHERE batch_id=?", (bid,)).fetchone()
    assert row[2] == 1 and os.path.exists(os.path.join(main.UPLOADS, row[1]))
    assert c.get(f"/uploads/{row[1]}").content == png
    assert c.get("/uploads/../mead.db").status_code == 404 and c.get("/uploads/nope.png").status_code == 404
    fake = c.post(f"/batch/{bid}/photo", files={"photo": ("x.png", io.BytesIO(b"<script>"), "image/png")})
    assert fake.status_code == 400  # bytes aren't an image
    assert c.post(f"/batch/{bid}/photo", files={"photo": ("x.svg", io.BytesIO(b"<svg/>"), "image/svg+xml")}).status_code == 400
    label = c.get(f"/batch/{bid}/label?size=wine&count=3&line=Patience").text
    assert label.count('class="label"') == 3 and f"/uploads/{row[1]}" in label and "Patience" in label
    c.post(f"/batch/{bid}/photo/{row[0]}/label")  # toggle off -> text-only labels
    assert f"/uploads/{row[1]}" not in c.get(f"/batch/{bid}/label").text
    c.post(f"/batch/{bid}/photo/{row[0]}/delete")
    assert not os.path.exists(os.path.join(main.UPLOADS, row[1]))
