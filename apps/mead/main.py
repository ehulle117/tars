"""Mead log: FastAPI + stdlib sqlite3 + Jinja templates."""
import os
import sqlite3
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

import chem
import seed

DB = os.environ.get("MEAD_DB", "mead.db")
STATUSES = ["planned", "primary", "secondary", "aging", "bottled", "archived", "recipe"]
KINDS = ["honey", "fruit", "water", "nutrient", "acid", "tannin", "spice", "oak", "stabilizer", "other"]
EVENTS = ["pitch", "nutrient", "degas", "rack", "stabilize", "backsweeten", "bottle", "tasting", "note"]
INV_KINDS = ["honey", "fruit", "yeast", "nutrient", "acid", "tannin", "spice", "oak", "stabilizer",
             "packaging", "equipment", "cleaning", "other"]
UNITS = ["lb", "oz", "kg", "g", "gal", "l", "ml", "tsp", "tbsp", "each"]
BOTTLES_PER_GAL = 3785.41 / 750
PROTOCOLS = {"tosna": "TOSNA (Fermaid-O)", "recipe": "As recipe (no checklist)"}
WIKI = "https://wiki.meadtools.com/en/"

SCHEMA = """
CREATE TABLE IF NOT EXISTS batch (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'planned',
  style TEXT, volume_gal REAL, yeast TEXT, n_need TEXT DEFAULT 'medium',
  nutrient_protocol TEXT DEFAULT 'tosna', goferm INTEGER DEFAULT 1,
  start_date TEXT, bottle_date TEXT, target_og REAL, target_fg REAL, target_fg_max REAL,
  source_url TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS ingredient (
  id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL REFERENCES batch ON DELETE CASCADE,
  kind TEXT, name TEXT, amount REAL, unit TEXT, ppg REAL, added_on TEXT);
CREATE TABLE IF NOT EXISTS reading (
  id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL REFERENCES batch ON DELETE CASCADE,
  taken_on TEXT NOT NULL, sg REAL NOT NULL, temp_f REAL, ph REAL, note TEXT);
CREATE TABLE IF NOT EXISTS event (
  id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL REFERENCES batch ON DELETE CASCADE,
  on_date TEXT NOT NULL, kind TEXT, note TEXT, rating INTEGER);
CREATE TABLE IF NOT EXISTS inventory (
  id INTEGER PRIMARY KEY, kind TEXT, name TEXT NOT NULL, qty REAL NOT NULL DEFAULT 0, unit TEXT,
  unit_cost REAL, notes TEXT);
CREATE TABLE IF NOT EXISTS expense (
  id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL REFERENCES batch ON DELETE CASCADE,
  spent_on TEXT NOT NULL, item TEXT NOT NULL, amount REAL NOT NULL, note TEXT,
  inventory_id INTEGER REFERENCES inventory ON DELETE SET NULL, qty REAL);
CREATE TABLE IF NOT EXISTS payment (
  id INTEGER PRIMARY KEY, paid_on TEXT NOT NULL, paid_by TEXT NOT NULL, amount REAL NOT NULL, item TEXT NOT NULL,
  paid_to TEXT, note TEXT, batch_id INTEGER REFERENCES batch ON DELETE SET NULL);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, author TEXT, page TEXT, message TEXT NOT NULL,
  done INTEGER NOT NULL DEFAULT 0);
"""


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


with db() as _c:
    _c.executescript(SCHEMA)
    seed.run(_c)

app = FastAPI()
tpl = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


def payers() -> list:
    """Everyone who has paid or been paid back, for the "Paid by" suggestions."""
    with db() as con:
        return [r[0] for r in con.execute("SELECT paid_by FROM payment WHERE paid_by != '' UNION SELECT paid_to "
                                          "FROM payment WHERE paid_to IS NOT NULL ORDER BY 1")]


tpl.env.globals["payers"] = payers


def record_payment(con, f, amount, item, batch_id=None):
    """Book a purchase in the who-paid ledger when the form says who paid."""
    who = (f.get("paid_by") or "").strip()
    if who and amount:
        con.execute("INSERT INTO payment (paid_on, paid_by, amount, item, batch_id) VALUES (?,?,?,?,?)",
                    (f.get("spent_on") or date.today().isoformat(), who, amount, item, batch_id))


def balances(rows) -> dict:
    """Shared costs split evenly between everyone in the ledger; paying someone back moves money between two
    people. Positive = is owed, negative = owes. Unassigned purchases (no payer yet) wait until someone's named."""
    rows = [r for r in rows if r["paid_by"]]
    people = {r["paid_by"] for r in rows} | {r["paid_to"] for r in rows if r["paid_to"]}
    if not people:
        return {}
    shared = sum(r["amount"] for r in rows if not r["paid_to"])
    bal = {p: -shared / len(people) for p in people}
    for r in rows:
        bal[r["paid_by"]] += r["amount"]
        if r["paid_to"]:
            bal[r["paid_to"]] -= r["amount"]
    return {p: round(v, 2) for p, v in sorted(bal.items())}


def num(v) -> Optional[float]:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except ValueError:
        raise HTTPException(400, f"not a number: {v!r}")


def day(d: date) -> str:
    """'Sat Oct 12', with the year only when it isn't this year."""
    return d.strftime("%a %b ") + str(d.day) + (d.strftime(", %Y") if d.year != date.today().year else "")


def back(path: str):
    return RedirectResponse(path, status_code=303)


def stats(con, b) -> dict:
    """Everything derived for one batch."""
    ings = [dict(r) for r in con.execute("SELECT * FROM ingredient WHERE batch_id=? ORDER BY added_on, id", (b["id"],))]
    reads = [dict(r) for r in con.execute("SELECT * FROM reading WHERE batch_id=? ORDER BY taken_on, id", (b["id"],))]
    for r in reads:
        r["sg_c"] = chem.temp_correct(r["sg"], r["temp_f"]) if r["temp_f"] else r["sg"]
    evs = con.execute("SELECT kind, on_date FROM event WHERE batch_id=? ORDER BY on_date, id", (b["id"],)).fetchall()
    kinds = [e[0] for e in evs]
    stabilized = [e[1] for e in evs if e[0] == "stabilize"]
    est_og = chem.estimate_og(ings, b["volume_gal"] or 0)
    og = reads[0]["sg_c"] if reads else (est_og or b["target_og"])
    cur = reads[-1]["sg_c"] if len(reads) > 1 else None
    stable = chem.is_stable([(r["taken_on"], r["sg_c"]) for r in reads])
    exps = [dict(r) for r in con.execute("SELECT * FROM expense WHERE batch_id=? ORDER BY spent_on, id", (b["id"],))]
    cost = sum(e["amount"] for e in exps)
    s = {"ings": ings, "reads": reads, "expenses": exps, "cost": cost, "est_og": est_og, "og": og, "cur": cur, "stable": stable,
         "nutrient_done": kinds.count("nutrient"), "state": None, "next": None, "next_link": None,
         # sweetness from the real FG only once fermentation is done; until then, the target
         "style_class": chem.style_class(og, cur if cur and (stable or b["status"] in ("aging", "bottled", "archived"))
                                         else b["target_fg"])}
    if og and cur:
        s["abv"] = chem.abv_high(og, cur) if og > 1.100 else chem.abv(og, cur)
        s["att"] = chem.attenuation(og, cur)
    if og and b["volume_gal"]:
        s["break"] = chem.sugar_break(og)
        if b["nutrient_protocol"] == "tosna":
            s["tosna"] = chem.tosna(og, b["volume_gal"], b["n_need"] or "medium", bool(b["goferm"]))
            pitch = date.fromisoformat(b["start_date"]) if b["start_date"] else None
            for n, d in enumerate(s["tosna"]["doses"]):  # dates from the pitch date, when there is one
                if not pitch:
                    d["when"] = "at " + d["when"]
                elif n < 3:
                    d["when"] = "on " + day(pitch + timedelta(days=n + 1))
                else:
                    d["when"] = f"at the 1/3 break (SG {s['break']:.3f}) or by {day(pitch + timedelta(days=7))}"
    if cost and b["volume_gal"]:
        s["cost_gal"] = cost / b["volume_gal"]
        s["cost_bottle"] = s["cost_gal"] / BOTTLES_PER_GAL
    if b["start_date"]:
        s["days"] = (date.today() - date.fromisoformat(b["start_date"])).days
    s["state"], s["next"], s["next_link"] = next_action(b, s, kinds, stabilized[-1] if stabilized else None)
    return s


def next_action(b, s, kinds, stabilized_on=None):
    """(where the batch is, what to do next, guide link), following the wiki's process."""
    if b["status"] not in ("primary", "secondary", "aging"):
        return None, None, None
    if s.get("tosna") and s["nutrient_done"] < 4 and b["status"] == "primary":
        d = s["tosna"]["doses"][s["nutrient_done"]]
        return "Fermenting", f"Nutrient dose {s['nutrient_done'] + 1}: {d['g']} g Fermaid-O {d['when']}", None
    if len(s["reads"]) < 2:
        return "Just pitched", "Take a gravity reading", None
    if not s["stable"]:
        recheck = date.fromisoformat(s["reads"][-1]["taken_on"]) + timedelta(days=7)
        return "Fermenting", f"Re-check gravity on {day(recheck)}", None
    top = b["target_fg_max"] or b["target_fg"]
    if top and s["cur"] > top + 0.002:
        return "Possibly stuck", "Stable above target FG: check for a stuck fermentation", WIKI + "protocol/stuck_fermentation"
    if "stabilize" not in kinds:
        return "Stable", "Stabilize (K-meta + sorbate)", WIKI + "process/stabilization"
    if "backsweeten" not in kinds and "bottle" not in kinds:
        after = f"on or after {day(date.fromisoformat(stabilized_on) + timedelta(days=1))}" if stabilized_on else "after 24 h"
        return "Stabilized", f"Backsweeten {after} if wanted", WIKI + "process/back_sweeten"
    return "Aging", "Bottle when clear, or keep aging", WIKI + "process/packaging"


@app.get("/")
def index(request: Request):
    with db() as con:
        rows = con.execute("SELECT * FROM batch WHERE status != 'recipe' ORDER BY start_date DESC, id DESC").fetchall()
        groups = {st: [] for st in STATUSES[:-1]}
        for b in rows:
            groups[b["status"]].append((b, stats(con, b)))
    return tpl.TemplateResponse(request, "index.html", {"groups": groups})


@app.get("/recipes")
def recipes(request: Request):
    with db() as con:
        rows = [(b, stats(con, b)) for b in con.execute("SELECT * FROM batch WHERE status='recipe' ORDER BY volume_gal, name")]
    return tpl.TemplateResponse(request, "recipes.html", {"rows": rows})


@app.post("/batch")
async def batch_create(request: Request):
    f = await request.form()
    if not f.get("name"):
        raise HTTPException(400, "name required")
    with db() as con:
        cur = con.execute("INSERT INTO batch (name, status) VALUES (?, 'planned')", (f["name"],))
    return back(f"/batch/{cur.lastrowid}")


def get_batch(con, bid: int):
    b = con.execute("SELECT * FROM batch WHERE id=?", (bid,)).fetchone()
    if not b:
        raise HTTPException(404)
    return b


@app.get("/batch/{bid}")
def batch_view(request: Request, bid: int):
    with db() as con:
        b = get_batch(con, bid)
        s = stats(con, b)
        events = con.execute("SELECT * FROM event WHERE batch_id=? ORDER BY on_date, id", (bid,)).fetchall()
    return tpl.TemplateResponse(request, "batch.html", {
        "b": b, "s": s, "events": events, "statuses": STATUSES, "kinds": KINDS, "event_kinds": EVENTS, "units": UNITS,
        "stock": con.execute("SELECT * FROM inventory WHERE qty > 0 ORDER BY kind, name").fetchall(),
        "n_needs": list(chem.N_FACTOR), "protocols": PROTOCOLS, "today": date.today().isoformat()})


@app.post("/batch/{bid}")
async def batch_update(bid: int, request: Request):
    f = await request.form()
    if (f.get("status") not in STATUSES or f.get("n_need") not in chem.N_FACTOR
            or f.get("nutrient_protocol") not in PROTOCOLS or not f.get("name")):
        raise HTTPException(400, "bad name/status/nitrogen need/protocol")
    with db() as con:
        get_batch(con, bid)
        con.execute("""UPDATE batch SET name=?, status=?, style=?, volume_gal=?, yeast=?, n_need=?,
                       nutrient_protocol=?, goferm=?, start_date=?, bottle_date=?, target_og=?, target_fg=?,
                       target_fg_max=?, source_url=?, notes=? WHERE id=?""",
                    (f["name"], f["status"], f.get("style"), num(f.get("volume_gal")), f.get("yeast"), f["n_need"],
                     f["nutrient_protocol"], 1 if f.get("goferm") else 0, f.get("start_date") or None,
                     f.get("bottle_date") or None, num(f.get("target_og")), num(f.get("target_fg")),
                     num(f.get("target_fg_max")), f.get("source_url") or None, f.get("notes"), bid))
    return back(f"/batch/{bid}")


def copy_batch(con, bid: int, name: str, status: str) -> int:
    """Copy a batch's plan (not its readings/log) — used for recipe→batch and batch→recipe."""
    get_batch(con, bid)
    new = con.execute("""INSERT INTO batch (name, status, style, volume_gal, yeast, n_need, nutrient_protocol, goferm,
                                            target_og, target_fg, target_fg_max, source_url, notes)
                         SELECT ?, ?, style, volume_gal, yeast, n_need, nutrient_protocol, goferm,
                                target_og, target_fg, target_fg_max, source_url, notes FROM batch WHERE id=?""",
                      (name, status, bid)).lastrowid
    con.execute("""INSERT INTO ingredient (batch_id, kind, name, amount, unit, ppg)
                   SELECT ?, kind, name, amount, unit, ppg FROM ingredient WHERE batch_id=?""", (new, bid))
    return new


@app.post("/batch/{bid}/clone")
def batch_clone(bid: int):
    with db() as con:
        b = get_batch(con, bid)
        name = b["name"] if b["status"] == "recipe" else b["name"] + " (copy)"
        new = copy_batch(con, bid, name, "planned")
    return back(f"/batch/{new}")


@app.post("/batch/{bid}/save-recipe")
def batch_save_recipe(bid: int):
    with db() as con:
        new = copy_batch(con, bid, get_batch(con, bid)["name"], "recipe")
    return back(f"/batch/{new}")


@app.post("/batch/{bid}/delete")
def batch_delete(bid: int):
    with db() as con:
        b = get_batch(con, bid)
        con.execute("DELETE FROM batch WHERE id=?", (bid,))
    return back("/recipes" if b["status"] == "recipe" else "/")


@app.post("/batch/{bid}/ingredient")
async def add_ingredient(bid: int, request: Request):
    f = await request.form()
    amount = num(f.get("amount"))
    if amount is None:
        raise HTTPException(400, "amount required")
    ppg = num(f.get("ppg"))
    if ppg is None and f.get("kind") == "honey":
        ppg = chem.HONEY_PPG
    with db() as con:
        get_batch(con, bid)
        con.execute("INSERT INTO ingredient (batch_id, kind, name, amount, unit, ppg, added_on) VALUES (?,?,?,?,?,?,?)",
                    (bid, f.get("kind"), f.get("name"), amount, f.get("unit"), ppg, f.get("added_on") or None))
    return back(f"/batch/{bid}")


@app.post("/batch/{bid}/reading")
async def add_reading(bid: int, request: Request):
    f = await request.form()
    sg = num(f.get("sg"))
    if sg is None or not 0.980 <= sg <= 1.200:
        raise HTTPException(400, "SG must be between 0.980 and 1.200")
    with db() as con:
        get_batch(con, bid)
        con.execute("INSERT INTO reading (batch_id, taken_on, sg, temp_f, ph, note) VALUES (?,?,?,?,?,?)",
                    (bid, f.get("taken_on") or date.today().isoformat(), sg, num(f.get("temp_f")),
                     num(f.get("ph")), f.get("note")))
    return back(f"/batch/{bid}")


@app.post("/batch/{bid}/event")
async def add_event(bid: int, request: Request):
    f = await request.form()
    rating = num(f.get("rating"))
    with db() as con:
        get_batch(con, bid)
        con.execute("INSERT INTO event (batch_id, on_date, kind, note, rating) VALUES (?,?,?,?,?)",
                    (bid, f.get("on_date") or date.today().isoformat(), f.get("kind"), f.get("note"),
                     None if rating is None else int(rating)))
    return back(f"/batch/{bid}")


@app.post("/batch/{bid}/expense")
async def add_expense(bid: int, request: Request):
    f = await request.form()
    amount = num(f.get("amount"))
    if amount is None or amount < 0 or not f.get("item"):
        raise HTTPException(400, "item and a non-negative amount required")
    with db() as con:
        get_batch(con, bid)
        con.execute("INSERT INTO expense (batch_id, spent_on, item, amount, note) VALUES (?,?,?,?,?)",
                    (bid, f.get("spent_on") or date.today().isoformat(), f["item"], amount, f.get("note")))
        record_payment(con, f, amount, f["item"], bid)
    return back(f"/batch/{bid}")


@app.post("/batch/{bid}/use")
async def use_stock(bid: int, request: Request):
    """Take stock off the shelf for a batch: lowers inventory and books its cost as a batch expense."""
    f = await request.form()
    qty = num(f.get("qty"))
    with db() as con:
        get_batch(con, bid)
        inv = con.execute("SELECT * FROM inventory WHERE id=?", (num(f.get("inventory_id")),)).fetchone()
        if not inv or qty is None or not 0 < qty <= inv["qty"]:
            raise HTTPException(400, "pick an item and a quantity no more than what's on hand")
        con.execute("UPDATE inventory SET qty = qty - ? WHERE id=?", (qty, inv["id"]))
        con.execute("INSERT INTO expense (batch_id, spent_on, item, amount, inventory_id, qty) VALUES (?,?,?,?,?,?)",
                    (bid, f.get("spent_on") or date.today().isoformat(), f"{qty:g} {inv['unit'] or ''} {inv['name']}",
                     round(qty * (inv["unit_cost"] or 0), 2), inv["id"], qty))
    return back(f"/batch/{bid}")


@app.post("/batch/{bid}/{table}/{rid}/delete")
def delete_row(bid: int, table: str, rid: int):
    if table not in ("ingredient", "reading", "event", "expense"):  # whitelist: table name is interpolated
        raise HTTPException(404)
    with db() as con:
        if table == "expense":  # undoing a "use from inventory" puts the stock back
            con.execute("""UPDATE inventory SET qty = qty + (SELECT qty FROM expense WHERE id=? AND batch_id=?)
                           WHERE id = (SELECT inventory_id FROM expense WHERE id=? AND batch_id=?)""", (rid, bid, rid, bid))
        con.execute(f"DELETE FROM {table} WHERE id=? AND batch_id=?", (rid, bid))
    return back(f"/batch/{bid}")


@app.get("/inventory")
def inventory(request: Request):
    with db() as con:
        items = con.execute("SELECT * FROM inventory ORDER BY kind, name").fetchall()
    value = sum(i["qty"] * (i["unit_cost"] or 0) for i in items)
    return tpl.TemplateResponse(request, "inventory.html", {"items": items, "value": value, "kinds": INV_KINDS,
                                                            "units": UNITS, "editing": "edit" in request.query_params})


@app.post("/inventory")
async def inventory_add(request: Request):
    f = await request.form()
    qty, paid = num(f.get("qty")) or 0, num(f.get("paid"))
    if not f.get("name") or qty < 0:
        raise HTTPException(400, "name and a non-negative quantity required")
    with db() as con:
        con.execute("INSERT INTO inventory (kind, name, qty, unit, unit_cost, notes) VALUES (?,?,?,?,?,?)",
                    (f.get("kind"), f["name"], qty, f.get("unit"), paid / qty if paid is not None and qty else None,
                     f.get("notes")))
        record_payment(con, f, paid, f"{qty:g} {f.get('unit') or ''} {f['name']}")
    return back("/inventory")


@app.post("/inventory/{iid:int}")  # :int, so /inventory/save isn't taken for an id
async def inventory_adjust(iid: int, request: Request):
    """Restock (+qty with what you paid: unit cost becomes the weighted average) or correct the count (-qty)."""
    f = await request.form()
    delta, paid = num(f.get("delta")), num(f.get("paid"))
    with db() as con:
        inv = con.execute("SELECT * FROM inventory WHERE id=?", (iid,)).fetchone()
        if not inv or delta is None or inv["qty"] + delta < 0:
            raise HTTPException(400, "can't take out more than what's on hand")
        cost = inv["unit_cost"]
        if paid is not None and delta > 0:
            cost = (inv["qty"] * (cost or paid / delta) + paid) / (inv["qty"] + delta)
        con.execute("UPDATE inventory SET qty=?, unit_cost=? WHERE id=?", (inv["qty"] + delta, cost, iid))
        if delta > 0:
            record_payment(con, f, paid, f"{delta:g} {inv['unit'] or ''} {inv['name']} (restock)")
    return back("/inventory")


def edited_rows(f, fields) -> dict:
    """Edit-mode forms name each input `field-<row id>`; regroup them as {row id: {field: value}}."""
    ids = {k.split("-", 1)[1] for k in f.keys() if k.startswith(fields[0] + "-")}
    return {int(i): {fld: f.get(f"{fld}-{i}") for fld in fields + ["remove"]} for i in ids if i.isdigit()}


@app.post("/inventory/save")
async def inventory_save(request: Request):
    """Edit mode's Save & done: every row at once, all or nothing."""
    f = await request.form()
    with db() as con:  # an HTTPException inside rolls the whole save back
        for iid, r in edited_rows(f, ["name", "kind", "qty", "unit", "unit_cost", "notes"]).items():
            if r["remove"]:
                con.execute("DELETE FROM inventory WHERE id=?", (iid,))
                continue
            qty, cost = num(r["qty"]), num(r["unit_cost"])
            if not (r["name"] or "").strip() or qty is None or qty < 0 or (cost is not None and cost < 0):
                raise HTTPException(400, f"{r['name'] or 'a row'}: needs a name and a non-negative quantity; "
                                         "unit cost can't be negative. Nothing was saved.")
            con.execute("UPDATE inventory SET kind=?, name=?, qty=?, unit=?, unit_cost=?, notes=? WHERE id=?",
                        (r["kind"], r["name"].strip(), qty, r["unit"], cost, r["notes"] or None, iid))
    return back("/inventory")


@app.get("/money")
def money(request: Request):
    with db() as con:
        rows = con.execute("SELECT p.*, b.name AS batch_name FROM payment p LEFT JOIN batch b ON b.id = p.batch_id "
                           "ORDER BY p.paid_on DESC, p.id DESC").fetchall()
    spent = sum(r["amount"] for r in rows if not r["paid_to"])
    unassigned = sum(r["amount"] for r in rows if not r["paid_by"])
    return tpl.TemplateResponse(request, "money.html", {
        "rows": rows, "bal": balances(rows), "spent": spent, "unassigned": unassigned,
        "editing": "edit" in request.query_params, "today": date.today().isoformat()})


@app.post("/money")
async def money_add(request: Request):
    f = await request.form()
    amount = num(f.get("amount"))
    who, to = (f.get("paid_by") or "").strip(), (f.get("paid_to") or "").strip() or None
    if not who or amount is None or amount <= 0 or not (f.get("item") or to) or who == to:
        raise HTTPException(400, "who paid, what for and a positive amount are required")
    with db() as con:
        con.execute("INSERT INTO payment (paid_on, paid_by, amount, item, paid_to, note) VALUES (?,?,?,?,?,?)",
                    (f.get("paid_on") or date.today().isoformat(), who, amount,
                     (f.get("item") or "").strip() or "Paid back", to, f.get("note") or None))
    return back("/money")


@app.post("/money/save")
async def money_save(request: Request):
    """Edit mode's Save & done: every row at once, all or nothing."""
    f = await request.form()
    with db() as con:  # an HTTPException inside rolls the whole save back
        for pid, r in edited_rows(f, ["item", "paid_on", "paid_by", "amount", "paid_to", "note"]).items():
            if r["remove"]:
                con.execute("DELETE FROM payment WHERE id=?", (pid,))
                continue
            amount = num(r["amount"])
            who, to = (r["paid_by"] or "").strip(), (r["paid_to"] or "").strip() or None
            if amount is None or amount <= 0 or not (r["item"] or "").strip() or not r["paid_on"] or (to and to == who):
                raise HTTPException(400, f"{r['item'] or 'a row'}: needs a date, what it was for and a positive "
                                         "amount, and can't pay back the payer. Nothing was saved.")
            con.execute("UPDATE payment SET paid_on=?, paid_by=?, item=?, amount=?, paid_to=?, note=? WHERE id=?",
                        (r["paid_on"], who, r["item"].strip(), amount, to, r["note"] or None, pid))
    return back("/money")


@app.get("/feedback")
def feedback(request: Request):
    with db() as con:
        rows = con.execute("SELECT * FROM feedback ORDER BY done, id DESC").fetchall()
    page = request.query_params.get("from", "")
    return tpl.TemplateResponse(request, "feedback.html", {"rows": rows, "page": page if page.startswith("/") else ""})


@app.post("/feedback")
async def feedback_add(request: Request):
    f = await request.form()
    if not (f.get("message") or "").strip():
        raise HTTPException(400, "write a remark first")
    page = f.get("page") or ""
    with db() as con:
        con.execute("INSERT INTO feedback (created_at, author, page, message) VALUES (?,?,?,?)",
                    (datetime.now().strftime("%Y-%m-%d %H:%M"), (f.get("author") or "").strip() or None,
                     page if page.startswith("/") else None, f["message"].strip()))
    return back("/feedback")


@app.post("/feedback/{fid}/toggle")
def feedback_toggle(fid: int):
    with db() as con:
        con.execute("UPDATE feedback SET done = 1 - done WHERE id=?", (fid,))
    return back("/feedback")


def summary(b, s) -> dict:
    last = s["reads"][-1] if s["reads"] else None
    return {"batch_id": b["id"], "name": b["name"], "task": s["next"] and f"{s['state']} — {s['next']}", "link": s["next_link"],
            "og": round(s["og"], 3) if s["og"] else None, "abv": round(s["abv"], 1) if "abv" in s else None,
            "last_sg": round(last["sg_c"], 3) if last else None, "last_date": last["taken_on"] if last else None}


@app.get("/api/tasks")
def api_tasks():
    """Next action per active batch, for the Discord bot. `due` is false for a gravity re-check
    whose last reading is under a week old — nothing to do yet."""
    out = []
    with db() as con:
        for b in con.execute("SELECT * FROM batch WHERE status IN ('primary', 'secondary', 'aging') ORDER BY id"):
            s = stats(con, b)
            if not s["next"]:
                continue
            t = summary(b, s)
            t["due"] = not (s["next"].startswith("Re-check gravity") and t["last_date"]
                            and (date.today() - date.fromisoformat(t["last_date"])).days < 7)
            out.append(t)
    return out


@app.get("/api/batch/{bid}")
def api_batch(bid: int):
    with db() as con:
        b = get_batch(con, bid)
        return summary(b, stats(con, b))


@app.get("/calc")
def calc(request: Request):
    q = {k: v for k, v in request.query_params.items() if v != ""}
    out = {}
    try:
        if "og" in q and "fg" in q:
            og, fg = float(q["og"]), float(q["fg"])
            out["abv"] = (chem.abv(og, fg), chem.abv_high(og, fg), chem.attenuation(og, fg), chem.style_class(og, fg))
        if "sg" in q and "temp_f" in q:
            out["temp"] = chem.temp_correct(float(q["sg"]), float(q["temp_f"]))
        if "honey_lb" in q and "vol" in q:
            out["og_est"] = chem.estimate_og([{"amount": float(q["honey_lb"]), "unit": "lb", "ppg": chem.HONEY_PPG}], float(q["vol"]))
        if "t_og" in q and "t_vol" in q:
            out["tosna"] = chem.tosna(float(q["t_og"]), float(q["t_vol"]), q.get("t_n", "medium"), "t_goferm" in q)
        if "ph" in q and "s_vol" in q:
            out["kmeta"] = chem.kmeta_g(float(q["ph"]), float(q["s_vol"]))
            out["sorbate"] = chem.sorbate_g(float(q["s_vol"]))
        if "b_cur" in q and "b_tgt" in q and "b_vol" in q:
            out["sweet"] = chem.backsweeten_lb(float(q["b_cur"]), float(q["b_tgt"]), float(q["b_vol"]))
    except (ValueError, KeyError):
        out["error"] = "Check your inputs — numbers only."
    return tpl.TemplateResponse(request, "calc.html", {"q": q, "out": out, "n_needs": list(chem.N_FACTOR),
                                                       "abv": num(q.get("abv"))})
