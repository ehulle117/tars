"""Mead log: FastAPI + stdlib sqlite3 + Jinja templates."""
import csv
import io
import math
import os
import re
import sqlite3
import uuid
from datetime import date, datetime, timedelta
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

import chem
import seed

DB = os.environ.get("MEAD_DB", "mead.db")
UPLOADS = os.path.join(os.path.dirname(os.path.abspath(DB)), "uploads")  # beside the database: same volume, same backup
IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}
MAX_UPLOAD = 10 * 1024 * 1024
STATUSES = ["planned", "primary", "secondary", "aging", "bottled", "archived", "recipe"]
KINDS = ["honey", "fruit", "water", "nutrient", "acid", "tannin", "spice", "oak", "stabilizer", "other"]
EVENTS = ["pitch", "nutrient", "degas", "rack", "stabilize", "backsweeten", "bottle", "tasting", "note"]
INV_KINDS = ["honey", "fruit", "yeast", "nutrient", "acid", "tannin", "spice", "oak", "stabilizer",
             "packaging", "equipment", "cleaning", "other"]
UNITS = ["lb", "oz", "kg", "g", "gal", "l", "ml", "tsp", "tbsp", "each"]
# the unit Add item starts with for each kind; equipment is kept, not used up, so it's never charged to a batch
KIND_UNIT = {"honey": "lb", "fruit": "lb", "yeast": "each", "nutrient": "g", "acid": "g", "tannin": "g", "spice": "g",
             "oak": "oz", "stabilizer": "g", "packaging": "each", "equipment": "each", "cleaning": "oz", "other": "each"}
BOTTLES_PER_GAL = 3785.41 / 750
DEVICE_NOTE = "iSpindel"  # the note on readings the iSpindel logs
TRACKING = "iSpindel is tracking gravity"  # next step while it does; nothing for people to do
LOG_EVERY = timedelta(minutes=55)  # one logged reading an hour, however often it posts
STALE = timedelta(hours=12)
LOW_BATTERY = 3.5  # volts
BOTTLE_KINDS = ["drank", "gave away", "broke"]
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
CREATE TABLE IF NOT EXISTS shopping (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, qty REAL, unit TEXT, note TEXT, added_on TEXT NOT NULL, who TEXT,
  done INTEGER NOT NULL DEFAULT 0, inventory_id INTEGER REFERENCES inventory ON DELETE SET NULL,
  batch_id INTEGER REFERENCES batch ON DELETE SET NULL);
CREATE TABLE IF NOT EXISTS bottle_out (
  id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL REFERENCES batch ON DELETE CASCADE, on_date TEXT NOT NULL,
  qty INTEGER NOT NULL DEFAULT 1, kind TEXT, rating INTEGER, note TEXT, who TEXT);
CREATE TABLE IF NOT EXISTS photo (
  id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL REFERENCES batch ON DELETE CASCADE, file TEXT NOT NULL,
  caption TEXT, added_on TEXT NOT NULL, who TEXT, on_label INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS device (
  name TEXT PRIMARY KEY, last_seen TEXT, last_logged TEXT, gravity REAL, temp_f REAL, battery REAL, angle REAL,
  rssi INTEGER, interval INTEGER, offset REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, author TEXT, page TEXT, message TEXT NOT NULL,
  done INTEGER NOT NULL DEFAULT 0);
"""


ADDED_COLUMNS = [("batch", "bottles", "INTEGER"), ("reading", "who", "TEXT"), ("event", "who", "TEXT"),
                 ("expense", "who", "TEXT"), ("inventory", "reorder_at", "REAL"),
                 ("batch", "ready_on", "TEXT"), ("batch", "ispindel", "TEXT")]


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


with db() as _c:
    _c.executescript(SCHEMA)
    for table, col, kind in ADDED_COLUMNS:  # columns added after launch; CREATE IF NOT EXISTS won't add them
        if col not in [r[1] for r in _c.execute(f"PRAGMA table_info({table})")]:
            _c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {kind}")
    seed.run(_c)
os.makedirs(UPLOADS, exist_ok=True)

app = FastAPI()
tpl = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


def payers() -> list:
    """Everyone who has paid or been paid back, for the "Paid by" suggestions."""
    with db() as con:
        return [r[0] for r in con.execute("SELECT paid_by FROM payment WHERE paid_by != '' UNION SELECT paid_to "
                                          "FROM payment WHERE paid_to IS NOT NULL ORDER BY 1")]


tpl.env.globals["payers"] = payers


def who(request: Request):
    """Whoever this device says it is (the picker in the header), or None."""
    return (request.cookies.get("who") or "").strip()[:40] or None
tpl.env.filters["money"] = lambda v: f"${v:,.2f}"  # $1,205.85


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
    cents = lambda v: round(v * 100)  # noqa: E731 -- whole cents: the same answer whatever order rows come in
    shared = sum(cents(r["amount"]) for r in rows if not r["paid_to"])
    bal = {p: 0 for p in people}
    for r in rows:
        bal[r["paid_by"]] += cents(r["amount"])
        if r["paid_to"]:
            bal[r["paid_to"]] -= cents(r["amount"])
    return {p: round((v - shared / len(people)) / 100, 2) for p, v in sorted(bal.items())}


def settle_up(rows):
    """(balances, who pays whom to even out or None). Two people only; rounded so both sides match."""
    bal = balances(rows)
    settle = None
    if len(bal) == 2:
        (debtor, owes), (creditor, _) = sorted(bal.items(), key=lambda kv: kv[1])
        if owes < -0.005:
            settle = {"from": debtor, "to": creditor, "amount": round(-owes, 2)}
            bal[creditor] = settle["amount"]  # rounded separately they can differ by a cent
    return bal, settle


def spark(points, w=160, h=40) -> str:
    """SVG polyline points for a gravity sparkline: [(iso date, sg), ...] scaled into w x h."""
    if len(points) < 2:
        return ""
    t0 = date.fromisoformat(points[0][0])
    xs = [(date.fromisoformat(d) - t0).days for d, _ in points]
    lo, hi = min(sg for _, sg in points), max(sg for _, sg in points)
    span_x, span_y = (xs[-1] or 1), (hi - lo or 0.001)
    return " ".join(f"{4 + x / span_x * (w - 8):.1f},{4 + (hi - sg) / span_y * (h - 8):.1f}"
                    for x, (_, sg) in zip(xs, points))


STAGES = ["planned", "primary", "secondary", "stabilized", "aging", "bottled"]
STAGE_POS = {"planned": 0, "primary": 1, "secondary": 2, "aging": 4, "bottled": 5, "archived": 5, "recipe": -1}
COST_GROUPS = ["honey", "fruit", "yeast", "nutrient", "packaging", "other"]


def cost_group(e) -> str:
    """Bucket a batch cost line for the breakdown bar: the inventory kind when it came from stock, else a guess."""
    k = e.get("inv_kind") or ("honey" if "honey" in e["item"].lower() else "other")
    return k if k in COST_GROUPS else "other"


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


def stock_label(qty: float, unit: str, name: str) -> str:
    """'3 lb honey', but 'Kitchen scale' / 'Carboy ×2' for things counted each."""
    if unit in ("each", None, ""):
        return name if qty == 1 else f"{name} ×{qty:g}"
    return f"{qty:g} {unit} {name}"


def back(path: str):
    return RedirectResponse(path, status_code=303)


def stats(con, b) -> dict:
    """Everything derived for one batch."""
    ings = [dict(r) for r in con.execute("SELECT * FROM ingredient WHERE batch_id=? ORDER BY added_on, id", (b["id"],))]
    reads = [dict(r) for r in con.execute("SELECT * FROM reading WHERE batch_id=? ORDER BY taken_on, id", (b["id"],))]
    for r in reads:
        r["sg_c"] = chem.temp_correct(r["sg"], r["temp_f"]) if r["temp_f"] else r["sg"]
    evs = con.execute("SELECT kind, on_date, note, who, rating FROM event WHERE batch_id=? ORDER BY on_date, id",
                      (b["id"],)).fetchall()
    kinds = [e[0] for e in evs]
    stabilized = [e[1] for e in evs if e[0] == "stabilize"]
    est_og = chem.estimate_og(ings, b["volume_gal"] or 0)
    og = reads[0]["sg_c"] if reads else (est_og or b["target_og"])
    cur = reads[-1]["sg_c"] if len(reads) > 1 else None
    stable = chem.is_stable([(r["taken_on"], r["sg_c"]) for r in reads])
    recent = [r["sg_c"] for r in reads if r["note"] == DEVICE_NOTE
              and (date.today() - date.fromisoformat(r["taken_on"])).days <= 3]
    if not stable and len(recent) >= 24 and max(recent) - min(recent) <= 0.001:
        stable = True  # three days of hourly iSpindel points that agree beat waiting a week for two by hand
    exps = [dict(r) for r in con.execute("SELECT e.*, i.kind AS inv_kind FROM expense e LEFT JOIN inventory i "
                                          "ON i.id = e.inventory_id WHERE batch_id=? ORDER BY spent_on, e.id", (b["id"],))]
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
    if cost and b["bottles"]:
        s["per_bottle"] = cost / b["bottles"]  # actual bottles filled beats the 750 mL estimate
    s["spark"] = spark([(r["taken_on"], r["sg_c"]) for r in reads])
    outs = [dict(r) for r in con.execute("SELECT * FROM bottle_out WHERE batch_id=? ORDER BY on_date DESC, id DESC",
                                         (b["id"],))]
    s["outs"] = outs
    if b["bottles"]:
        s["left"] = max(b["bottles"] - sum(o["qty"] for o in outs), 0)
    rated = [o["rating"] for o in outs if o["rating"]] + [r for k, _, _, _, r in evs if k == "tasting" and r]
    if rated:
        s["rating"] = sum(rated) / len(rated)
    if b["ready_on"]:
        ready = date.fromisoformat(b["ready_on"])
        s["ready"] = "Ready now" if ready <= date.today() else f"Ready {day(ready)}"
    groups = {}
    for e in exps:
        groups[cost_group(e)] = groups.get(cost_group(e), 0) + e["amount"]
    s["cost_parts"] = [(g, groups[g]) for g in COST_GROUPS if groups.get(g)]
    # the brewing stages, ticked off from status and the log
    first = {}
    for k, d, _, _, _ in evs:
        first.setdefault(k, d)
    pos = STAGE_POS.get(b["status"], 0)
    dates = {"primary": b["start_date"], "secondary": first.get("rack"), "stabilized": first.get("stabilize"),
             "bottled": b["bottle_date"] or first.get("bottle")}
    s["stages"] = [{"name": st, "date": dates.get(st), "now": i == pos,
                    "done": i < pos or (st == "stabilized" and "stabilize" in kinds)} for i, st in enumerate(STAGES)]
    # newest first: readings and log entries together
    device = [r for r in reads if r["note"] == DEVICE_NOTE]
    s["device_reads"] = len(device)
    tl = [{"on": r["taken_on"], "what": f"Reading {r['sg']:.3f}" + (f" at {r['temp_f']:g}°F" if r["temp_f"] else ""),
           "note": r["note"], "who": r["who"]} for r in reads if r["note"] != DEVICE_NOTE or r is device[-1]]
    tl += [{"on": d, "what": k.capitalize() + (" " + "★" * r if r else ""), "note": n, "who": w} for k, d, n, w, r in evs]
    tl += [{"on": o["on_date"], "what": f"{o['kind'].capitalize()} {o['qty']} bottle{'s' if o['qty'] != 1 else ''}"
            + (" " + "★" * o["rating"] if o["rating"] else ""), "note": o["note"], "who": o["who"]} for o in outs]
    s["timeline"] = sorted(tl, key=lambda t: t["on"], reverse=True)
    if b["start_date"]:
        s["days"] = (date.today() - date.fromisoformat(b["start_date"])).days
    s["state"], s["next"], s["next_link"], s["due"], s["done_kind"] = next_action(
        b, s, kinds, stabilized[-1] if stabilized else None)
    s["due_label"] = due_label(s["due"]) if s["next"] else None
    s["auto"] = s["next"] == TRACKING
    if s["auto"]:
        s["due_label"] = "Automatic"
    return s


def next_action(b, s, kinds, stabilized_on=None):
    """(where the batch is, what to do next, guide link, due date or None, event that marks it done or None),
    following the wiki's process."""
    if b["status"] not in ("primary", "secondary", "aging"):
        return None, None, None, None, None
    today = date.today()
    if s.get("tosna") and s["nutrient_done"] < 4 and b["status"] == "primary":
        n = s["nutrient_done"]
        d = s["tosna"]["doses"][n]
        due = date.fromisoformat(b["start_date"]) + timedelta(days=(1, 2, 3, 7)[n]) if b["start_date"] else today
        return "Fermenting", f"Nutrient dose {n + 1}: {d['g']} g Fermaid-O {d['when']}", None, due, "nutrient"
    if len(s["reads"]) < 2:
        return "Just pitched", "Take a gravity reading", None, today, None
    if not s["stable"] and b["ispindel"] and s["reads"][-1]["note"] == DEVICE_NOTE:
        return "Fermenting", TRACKING, None, None, None
    if not s["stable"]:
        recheck = date.fromisoformat(s["reads"][-1]["taken_on"]) + timedelta(days=7)
        return "Fermenting", f"Re-check gravity on {day(recheck)}", None, recheck, None
    top = b["target_fg_max"] or b["target_fg"]
    if top and s["cur"] > top + 0.002:
        return ("Possibly stuck", "Stable above target FG: check for a stuck fermentation",
                WIKI + "protocol/stuck_fermentation", today, None)
    if "stabilize" not in kinds:
        return "Stable", "Stabilize (K-meta + sorbate)", WIKI + "process/stabilization", today, "stabilize"
    if "backsweeten" not in kinds and "bottle" not in kinds:
        ok = date.fromisoformat(stabilized_on) + timedelta(days=1) if stabilized_on else today
        after = f"on or after {day(ok)}" if stabilized_on else "after 24 h"
        return "Stabilized", f"Backsweeten {after} if wanted", WIKI + "process/back_sweeten", ok, "backsweeten"
    return "Aging", "Bottle when clear, or keep aging", WIKI + "process/packaging", None, "bottle"


def due_label(due) -> str:
    """'Due today', 'Overdue since Mon Oct 19', 'Wed Oct 28 · in 7 days', or no date at all."""
    if due is None:
        return "Whenever it's clear"
    days = (due - date.today()).days
    if days < 0:
        return f"Overdue since {day(due)}"
    if days == 0:
        return "Due today"
    return f"{day(due)} · in {days} day{'s' if days != 1 else ''}"


@app.get("/")
def index(request: Request):
    with db() as con:
        rows = con.execute("SELECT * FROM batch WHERE status != 'recipe' ORDER BY start_date DESC, id DESC").fetchall()
        groups = {st: [] for st in STATUSES[:-1]}
        for b in rows:
            groups[b["status"]].append((b, stats(con, b)))
        payments = con.execute("SELECT * FROM payment").fetchall()
        out = [(i["name"], "Out" if i["qty"] <= 0.005 else f"{i['qty']:g} {i['unit'] or ''} left") for i in low_stock(con)]
        shopping_open = con.execute("SELECT COUNT(*) FROM shopping WHERE done=0").fetchone()[0]
        device_alerts = [(b, p) for b, _ in [bs for st in ("primary", "secondary", "aging") for bs in groups[st]]
                         for p in device_problems(con, b)]
        tracked = [b for st in ("primary", "secondary", "aging") for b, _ in groups[st] if b["ispindel"]]
        unpriced = con.execute("SELECT COUNT(*) FROM inventory WHERE kind IS NOT 'equipment' AND qty > 0.005 "
                               "AND (unit_cost IS NULL OR unit_cost = 0)").fetchone()[0]
        bottles = con.execute("SELECT COALESCE(SUM(qty), 0) FROM inventory WHERE kind='packaging' "
                              "AND lower(name) LIKE '%bottle%'").fetchone()[0]
        made = con.execute("SELECT SUM(bottles), SUM(volume_gal) FROM batch WHERE bottles > 0 "
                           "AND volume_gal > 0").fetchone()
    upnext = sorted(((b, s) for g in groups.values() for b, s in g if s["next"] and not s["auto"]),
                    key=lambda bs: bs[1]["due"] or date.max)
    active = [bs for st in ("primary", "secondary", "aging") for bs in groups[st]]
    per_gal = made[0] / made[1] if made[0] else BOTTLES_PER_GAL  # your own past yield, once there is one
    shelf = {"out": out, "unpriced": unpriced, "bottles": bottles, "shopping": shopping_open,
             "need": round(sum(b["volume_gal"] or 0 for b, _ in active) * per_gal)}
    bal, settle = settle_up(payments)
    return tpl.TemplateResponse(request, "index.html", {
        "groups": groups, "upnext": upnext, "active": active, "today": date.today(), "shelf": shelf,
        "settle": settle, "spent": sum(p["amount"] for p in payments if not p["paid_to"]),
        "cellar": groups["bottled"] + groups["archived"], "planned": groups["planned"],
        "device_alerts": device_alerts, "tracked": tracked})


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
        plan = plan_rows(con, b, s["ings"]) if b["status"] in ("planned", "primary") else []
        photos = con.execute("SELECT * FROM photo WHERE batch_id=? ORDER BY id DESC", (bid,)).fetchall()
        device_names = [r[0] for r in con.execute("SELECT name FROM device ORDER BY name")]
        stock_all = con.execute("SELECT * FROM inventory WHERE kind IS NOT 'equipment' ORDER BY kind, name").fetchall()
    return tpl.TemplateResponse(request, "batch.html", {"plan": plan, "stock_all": stock_all, "photos": photos,
        "device_names": device_names,
        "b": b, "s": s, "events": events, "statuses": STATUSES, "kinds": KINDS, "event_kinds": EVENTS, "units": UNITS,
        "stock": con.execute("SELECT * FROM inventory WHERE qty > 0.005 AND kind IS NOT 'equipment' "
                             "ORDER BY kind, name").fetchall(),
        "n_needs": list(chem.N_FACTOR), "protocols": PROTOCOLS, "today": date.today().isoformat(),
        "bottle_kinds": BOTTLE_KINDS})


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
                       target_fg_max=?, source_url=?, notes=?, bottles=?, ready_on=?, ispindel=? WHERE id=?""",
                    (f["name"], f["status"], f.get("style"), num(f.get("volume_gal")), f.get("yeast"), f["n_need"],
                     f["nutrient_protocol"], 1 if f.get("goferm") else 0, f.get("start_date") or None,
                     f.get("bottle_date") or None, num(f.get("target_og")), num(f.get("target_fg")),
                     num(f.get("target_fg_max")), f.get("source_url") or None, f.get("notes"),
                     int(num(f.get("bottles"))) if num(f.get("bottles")) else None, f.get("ready_on") or None,
                     (f.get("ispindel") or "").strip() or None, bid))
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
        con.execute("INSERT INTO reading (batch_id, taken_on, sg, temp_f, ph, note, who) VALUES (?,?,?,?,?,?,?)",
                    (bid, f.get("taken_on") or date.today().isoformat(), sg, num(f.get("temp_f")),
                     num(f.get("ph")), f.get("note"), who(request)))
    return back(f"/batch/{bid}")


@app.get("/log")
def quick_log(request: Request):
    """Phone-sized: pick an active batch, type the gravity, save."""
    with db() as con:
        rows = [(b, stats(con, b)) for b in con.execute(
            "SELECT * FROM batch WHERE status IN ('primary', 'secondary', 'aging') ORDER BY start_date DESC, id DESC")]
    pick = request.query_params.get("batch")
    return tpl.TemplateResponse(request, "log.html", {
        "rows": rows, "pick": int(pick) if (pick or "").isdigit() else (rows[0][0]["id"] if rows else None),
        "saved": request.query_params.get("saved"), "today": date.today().isoformat()})


@app.post("/log")
async def quick_log_save(request: Request):
    f = await request.form()
    bid = num(f.get("batch_id"))
    if bid is None:
        raise HTTPException(400, "pick a batch")
    await add_reading(int(bid), request)  # same checks and insert as the batch page
    with db() as con:
        name = get_batch(con, int(bid))["name"]
    return back(f"/log?batch={int(bid)}&saved={quote(name)}")


@app.post("/batch/{bid}/event")
async def add_event(bid: int, request: Request):
    f = await request.form()
    rating = num(f.get("rating"))
    with db() as con:
        get_batch(con, bid)
        con.execute("INSERT INTO event (batch_id, on_date, kind, note, rating, who) VALUES (?,?,?,?,?,?)",
                    (bid, f.get("on_date") or date.today().isoformat(), f.get("kind"), f.get("note"),
                     None if rating is None else int(rating), who(request)))
    dest = f.get("back") or ""  # Mark done on the dashboard returns there; only same-site paths
    return back(dest if dest.startswith("/") and not dest.startswith("//") else f"/batch/{bid}")


@app.post("/batch/{bid}/expense")
async def add_expense(bid: int, request: Request):
    f = await request.form()
    amount = num(f.get("amount"))
    if amount is None or amount < 0 or not f.get("item"):
        raise HTTPException(400, "item and a non-negative amount required")
    with db() as con:
        get_batch(con, bid)
        con.execute("INSERT INTO expense (batch_id, spent_on, item, amount, note, who) VALUES (?,?,?,?,?,?)",
                    (bid, f.get("spent_on") or date.today().isoformat(), f["item"], amount, f.get("note"), who(request)))
        record_payment(con, f, amount, f["item"], bid)
    return back(f"/batch/{bid}")


def take_stock(con, bid, inv_id, entered, unit, on, by):
    """Take stock off the shelf for a batch: lowers inventory and books its cost as a batch expense."""
    inv = con.execute("SELECT * FROM inventory WHERE id=?", (inv_id,)).fetchone()
    if not inv or entered is None or entered <= 0:
        raise HTTPException(400, "pick an item and a quantity")
    unit = unit or inv["unit"]
    qty = chem.convert(entered, unit, inv["unit"])  # in the stock's own unit, so undo puts back the same
    if qty is None:
        raise HTTPException(400, f"can't turn {unit} into {inv['unit']} for {inv['name']}: weigh it, or use "
                                 f"{inv['unit']}")
    if qty > inv["qty"] + 1e-9:
        raise HTTPException(400, f"only {inv['qty']:g} {inv['unit']} of {inv['name']} on hand")
    qty = min(qty, inv["qty"])
    label = stock_label(entered, unit, inv["name"]) + ("" if unit == inv["unit"] else f" (= {qty:.4g} {inv['unit']})")
    con.execute("UPDATE inventory SET qty = qty - ? WHERE id=?", (qty, inv["id"]))
    con.execute("INSERT INTO expense (batch_id, spent_on, item, amount, inventory_id, qty, who) VALUES (?,?,?,?,?,?,?)",
                (bid, on or date.today().isoformat(), label, round(qty * (inv["unit_cost"] or 0), 2), inv["id"], qty, by))


@app.post("/batch/{bid}/use")
async def use_stock(bid: int, request: Request):
    f = await request.form()
    with db() as con:
        get_batch(con, bid)
        take_stock(con, bid, num(f.get("inventory_id")), num(f.get("qty")), f.get("unit") or None,
                   f.get("spent_on"), who(request))
    return back(f"/batch/{bid}")


def tokens(text: str) -> set:
    """Words and numbers, plurals folded: 'Campden tablets' -> {'campden', 'tablet'}."""
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in re.findall(r"[a-z0-9]+", (text or "").lower())}


def match_stock(name: str, kind: str, stock):
    """The shelf item a recipe line means, or None. Honey: any honey (the most of it). Else every word of the
    stock item's name must be in the recipe's wording ('Lalvin 71B' fits 'Lalvin 71B-1122 (5 g)', 'Fermaid O'
    doesn't fit 'Fermaid K'), or one squashed name holds the other ('Go-Ferm' / 'GoFerm PE')."""
    squash = lambda t: re.sub(r"[^a-z0-9]", "", (t or "").lower())  # noqa: E731
    if kind == "honey":
        honey = [i for i in stock if i["kind"] == "honey"]
        return max(honey, key=lambda i: i["qty"]) if honey else None
    want, best = tokens(name), None
    for i in stock:
        if i["kind"] == "equipment" or (kind not in ("other", None) and i["kind"] not in (kind, "other")):
            continue
        a, b = squash(i["name"]), squash(name)
        if (tokens(i["name"]) and tokens(i["name"]) <= want) or (len(a) >= 3 and (a in b or (len(b) >= 3 and b in a))):
            best = best if best and best["qty"] >= i["qty"] else i
    return best


def plan_rows(con, b, ings):
    """What brewing this batch takes from the shelf: one row per ingredient (plus the yeast), matched to stock,
    converted to the stock's unit where it can be, with what's on hand and what's already been used."""
    stock = con.execute("SELECT * FROM inventory WHERE kind IS NOT 'equipment' ORDER BY kind, name").fetchall()
    used = dict(con.execute("SELECT inventory_id, SUM(qty) FROM expense WHERE batch_id=? AND inventory_id IS NOT NULL "
                            "GROUP BY inventory_id", (b["id"],)).fetchall())
    lines = [(i["name"] or i["kind"], i["kind"], i["amount"], i["unit"]) for i in ings if i["kind"] != "water"]
    if b["yeast"]:
        grams = re.search(r"(\d+(?:\.\d+)?)\s*g\b", b["yeast"])
        packets = math.ceil(float(grams.group(1)) / 5) if grams and "lalvin" in b["yeast"].lower() else 1
        lines.append((b["yeast"], "yeast", packets, "each"))
    rows = []
    for name, kind, amount, unit in lines:
        inv = match_stock(name, kind, stock)
        need = chem.convert(amount, unit, inv["unit"]) if inv and amount else None
        rows.append({"name": name, "kind": kind, "amount": amount, "unit": unit, "inv": inv, "need": need,
                     "have": inv["qty"] if inv else None, "used": used.get(inv["id"]) if inv else None,
                     "enough": inv is not None and need is not None and need <= inv["qty"] + 1e-9,
                     "later": bool(re.search(r"secondary|post", name.lower()))})
    return rows


@app.post("/batch/{bid}/use-many")
async def use_many(bid: int, request: Request):
    """The plan panel's 'Use selected from inventory': every ticked row, all or nothing."""
    f = await request.form()
    with db() as con:
        get_batch(con, bid)
        for n in sorted({k.split("-", 1)[1] for k in f.keys() if k.startswith("use-")}):
            if f.get(f"inv-{n}") and f.get(f"qty-{n}"):
                take_stock(con, bid, num(f.get(f"inv-{n}")), num(f.get(f"qty-{n}")), f.get(f"unit-{n}") or None,
                           None, who(request))
    return back(f"/batch/{bid}#plan")


@app.post("/batch/{bid}/shortfalls")
def add_shortfalls(bid: int, request: Request):
    """Put whatever brewing this batch is short of on the shopping list (skipping what's already there)."""
    with db() as con:
        b = get_batch(con, bid)
        ings = con.execute("SELECT * FROM ingredient WHERE batch_id=?", (bid,)).fetchall()
        listed = {r[0].lower() for r in con.execute("SELECT name FROM shopping WHERE done=0")}
        for r in plan_rows(con, b, ings):
            if r["enough"] or (r["used"] and r["inv"]):
                continue
            inv = r["inv"]
            name = inv["name"] if inv else r["name"]
            if name.lower() in listed:
                continue
            short = r["need"] - inv["qty"] if inv and r["need"] is not None else None
            con.execute("INSERT INTO shopping (name, qty, unit, note, added_on, who, inventory_id, batch_id) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (name, round(short, 2) if short else (r["amount"] if not inv else None),
                         inv["unit"] if short else (r["unit"] if not inv else None), f"for {b['name']}",
                         date.today().isoformat(), who(request), inv["id"] if inv else None, bid))
            listed.add(name.lower())
    return back("/shopping")


def low_stock(con):
    """Supplies that are out, or at/below the reorder level set for them."""
    return con.execute("SELECT * FROM inventory WHERE kind IS NOT 'equipment' AND (qty <= 0.005 OR "
                       "(reorder_at IS NOT NULL AND qty <= reorder_at)) ORDER BY name").fetchall()


@app.get("/shopping")
def shopping(request: Request):
    with db() as con:
        items = con.execute("SELECT s.*, b.name AS batch_name FROM shopping s LEFT JOIN batch b ON b.id = s.batch_id "
                            "ORDER BY s.done, s.id DESC").fetchall()
        listed = {r["inventory_id"] for r in items if not r["done"] and r["inventory_id"]}
        suggest = [i for i in low_stock(con) if i["id"] not in listed]
    return tpl.TemplateResponse(request, "shopping.html", {
        "open": [i for i in items if not i["done"]], "got": [i for i in items if i["done"]][:15], "suggest": suggest,
        "units": UNITS})


@app.post("/shopping")
async def shopping_add(request: Request):
    f = await request.form()
    if not (f.get("name") or "").strip():
        raise HTTPException(400, "what do you need?")
    with db() as con:
        con.execute("INSERT INTO shopping (name, qty, unit, note, added_on, who, inventory_id) VALUES (?,?,?,?,?,?,?)",
                    (f["name"].strip(), num(f.get("qty")), f.get("unit") or None, f.get("note") or None,
                     date.today().isoformat(), who(request), num(f.get("inventory_id"))))
    return back("/shopping")


@app.post("/shopping/{sid}/{action}")
def shopping_change(sid: int, action: str):
    with db() as con:
        if action == "toggle":
            con.execute("UPDATE shopping SET done = 1 - done WHERE id=?", (sid,))
        elif action == "delete":
            con.execute("DELETE FROM shopping WHERE id=?", (sid,))
        else:
            raise HTTPException(404)
    return back("/shopping")


@app.post("/batch/{bid}/bottle")
async def open_bottle(bid: int, request: Request):
    """Bottles leaving the cellar (drunk, given away, broken), with an optional rating and tasting note."""
    f = await request.form()
    qty, rating = num(f.get("qty")) or 1, num(f.get("rating"))
    if f.get("kind") not in BOTTLE_KINDS or qty < 1 or qty != int(qty) or (rating is not None and not 1 <= rating <= 5):
        raise HTTPException(400, "a whole number of bottles, drank / gave away / broke, rating 1-5")
    with db() as con:
        b = get_batch(con, bid)
        if b["bottles"]:
            gone = con.execute("SELECT COALESCE(SUM(qty), 0) FROM bottle_out WHERE batch_id=?", (bid,)).fetchone()[0]
            if gone + qty > b["bottles"]:
                raise HTTPException(400, f"only {b['bottles'] - gone} bottle(s) left")
        con.execute("INSERT INTO bottle_out (batch_id, on_date, qty, kind, rating, note, who) VALUES (?,?,?,?,?,?,?)",
                    (bid, f.get("on_date") or date.today().isoformat(), int(qty), f["kind"],
                     None if rating is None else int(rating), f.get("note") or None, who(request)))
    return back(f"/batch/{bid}#cellar")


def looks_like_image(data: bytes) -> bool:
    """Trust the bytes, not the browser's say-so."""
    return (data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff" or data[:6] in (b"GIF87a", b"GIF89a")
            or (data[:4] == b"RIFF" and data[8:12] == b"WEBP"))


@app.post("/batch/{bid}/photo")
async def add_photo(bid: int, request: Request):
    f = await request.form()
    up = f.get("photo")
    if not hasattr(up, "read") or up.content_type not in IMAGE_TYPES:
        raise HTTPException(400, "pick a JPEG, PNG, WebP or GIF image")
    data = await up.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD or not looks_like_image(data):
        raise HTTPException(400, "images must be real JPEG/PNG/WebP/GIF files under 10 MB")
    name = f"{uuid.uuid4().hex}.{IMAGE_TYPES[up.content_type]}"
    with db() as con:
        get_batch(con, bid)
        with open(os.path.join(UPLOADS, name), "wb") as out:
            out.write(data)
        label = 1 if f.get("on_label") else 0
        if label:
            con.execute("UPDATE photo SET on_label=0 WHERE batch_id=?", (bid,))
        con.execute("INSERT INTO photo (batch_id, file, caption, added_on, who, on_label) VALUES (?,?,?,?,?,?)",
                    (bid, name, (f.get("caption") or "").strip() or None, date.today().isoformat(), who(request), label))
    return back(f"/batch/{bid}#photos")


@app.post("/batch/{bid}/photo/{pid}/label")
def photo_label(bid: int, pid: int):
    """Use this photo on the batch's labels (only one at a time); again to stop using it."""
    with db() as con:
        cur = con.execute("SELECT on_label FROM photo WHERE id=? AND batch_id=?", (pid, bid)).fetchone()
        if not cur:
            raise HTTPException(404)
        con.execute("UPDATE photo SET on_label=0 WHERE batch_id=?", (bid,))
        if not cur[0]:
            con.execute("UPDATE photo SET on_label=1 WHERE id=?", (pid,))
    return back(f"/batch/{bid}#photos")


@app.get("/uploads/{name}")
def upload_file(name: str):
    if not re.fullmatch(r"[0-9a-f]{32}\.(jpg|png|webp|gif)", name) or not os.path.exists(os.path.join(UPLOADS, name)):
        raise HTTPException(404)
    return FileResponse(os.path.join(UPLOADS, name), headers={"Cache-Control": "public, max-age=31536000, immutable"})


LABEL_SIZES = {"small": ("3in", "2in", "Small · 3 × 2 in"), "wine": ("3.5in", "4in", "Wine · 3.5 × 4 in")}


@app.get("/batch/{bid}/label")
def label_sheet(request: Request, bid: int):
    """A printable sheet of bottle labels, cut along the dashed lines."""
    q = request.query_params
    with db() as con:
        b = get_batch(con, bid)
        s = stats(con, b)
        photo = con.execute("SELECT * FROM photo WHERE batch_id=? ORDER BY on_label DESC, id DESC LIMIT 1",
                            (bid,)).fetchone()
        labeled = con.execute("SELECT COUNT(*) FROM photo WHERE batch_id=? AND on_label=1", (bid,)).fetchone()[0]
    size = q.get("size") if q.get("size") in LABEL_SIZES else "small"
    count = int(num(q.get("count")) or s.get("left") or b["bottles"] or 8)
    names = [p for p in payers()]
    return tpl.TemplateResponse(request, "label.html", {
        "b": b, "s": s, "photo": photo if labeled or q.get("image") == "any" else None, "has_photo": bool(photo),
        "size": size, "sizes": LABEL_SIZES, "count": max(1, min(count, 60)), "line": q.get("line", ""),
        "by": q.get("by", ("Brewed by " + " & ".join(names)) if names else "")})


@app.post("/batch/{bid}/{table}/{rid}/delete")
def delete_row(bid: int, table: str, rid: int):
    if table not in ("ingredient", "reading", "event", "expense", "bottle_out", "photo"):  # whitelisted: interpolated
        raise HTTPException(404)
    with db() as con:
        if table == "photo":  # the file goes too
            row = con.execute("SELECT file FROM photo WHERE id=? AND batch_id=?", (rid, bid)).fetchone()
            if row and os.path.exists(os.path.join(UPLOADS, row[0])):
                os.remove(os.path.join(UPLOADS, row[0]))
        if table == "expense":  # undoing a "use from inventory" puts the stock back
            con.execute("""UPDATE inventory SET qty = qty + (SELECT qty FROM expense WHERE id=? AND batch_id=?)
                           WHERE id = (SELECT inventory_id FROM expense WHERE id=? AND batch_id=?)""", (rid, bid, rid, bid))
        con.execute(f"DELETE FROM {table} WHERE id=? AND batch_id=?", (rid, bid))
    return back(f"/batch/{bid}")


@app.get("/inventory")
def inventory(request: Request):
    with db() as con:
        items = con.execute("SELECT * FROM inventory ORDER BY kind, name").fetchall()
    supplies = [i for i in items if i["kind"] != "equipment"]
    equipment = [i for i in items if i["kind"] == "equipment"]
    return tpl.TemplateResponse(request, "inventory.html", {
        "items": items, "supplies": supplies, "equipment": equipment,
        "value": sum(i["qty"] * (i["unit_cost"] or 0) for i in supplies),
        "equipment_value": sum(i["qty"] * (i["unit_cost"] or 0) for i in equipment),
        "kinds": INV_KINDS, "units": UNITS, "kind_unit": KIND_UNIT, "editing": "edit" in request.query_params})


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
        record_payment(con, f, paid, stock_label(qty, f.get("unit"), f["name"]))
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
            record_payment(con, f, paid, stock_label(delta, inv["unit"], inv["name"]) + " (restock)")
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
        for iid, r in edited_rows(f, ["name", "kind", "qty", "unit", "unit_cost", "notes", "reorder_at"]).items():
            if r["remove"]:
                con.execute("DELETE FROM inventory WHERE id=?", (iid,))
                continue
            qty, cost, reorder = num(r["qty"]), num(r["unit_cost"]), num(r["reorder_at"])
            if not (r["name"] or "").strip() or qty is None or qty < 0 or (cost is not None and cost < 0):
                raise HTTPException(400, f"{r['name'] or 'a row'}: needs a name and a non-negative quantity; "
                                         "unit cost can't be negative. Nothing was saved.")
            con.execute("UPDATE inventory SET kind=?, name=?, qty=?, unit=?, unit_cost=?, notes=?, reorder_at=? WHERE id=?",
                        (r["kind"], r["name"].strip(), qty, r["unit"], cost, r["notes"] or None, reorder, iid))
    return back("/inventory")


@app.get("/money")
def money(request: Request):
    with db() as con:
        rows = con.execute("SELECT p.*, b.name AS batch_name FROM payment p LEFT JOIN batch b ON b.id = p.batch_id "
                           "ORDER BY p.paid_on DESC, p.id DESC").fetchall()
    spent = sum(r["amount"] for r in rows if not r["paid_to"])
    unassigned = sum(r["amount"] for r in rows if not r["paid_by"])
    bal, settle = settle_up(rows)
    people = {}
    for r in rows:  # what each person put toward shared costs, for the person cards
        if r["paid_by"] and not r["paid_to"]:
            people[r["paid_by"]] = people.get(r["paid_by"], 0) + r["amount"]
    months = []
    for r in rows:  # already newest first
        key = r["paid_on"][:7]
        if not months or months[-1]["key"] != key:
            months.append({"key": key, "label": date.fromisoformat(key + "-01").strftime("%B %Y"), "rows": [], "total": 0})
        months[-1]["rows"].append(r)
        months[-1]["total"] += r["amount"] if not r["paid_to"] else 0
    return tpl.TemplateResponse(request, "money.html", {
        "rows": rows, "bal": bal, "settle": settle, "spent": spent, "unassigned": unassigned,
        "people": dict(sorted(people.items())), "share": spent / len(bal) if bal else 0, "months": months,
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


@app.post("/who")
async def set_who(request: Request):
    """The header's "you are" picker: remembered on this device for a year."""
    f = await request.form()
    dest = f.get("back") or "/"
    r = back(dest if dest.startswith("/") and not dest.startswith("//") else "/")
    name = (f.get("who") or "").strip()[:40]
    if name:
        r.set_cookie("who", name, max_age=365 * 86400, samesite="lax", httponly=True)
    else:
        r.delete_cookie("who")
    return r


def honey_per_gal(ings, vol):
    lb = sum(chem.to_lb(i["amount"], i["unit"]) or 0 for i in ings if i["kind"] == "honey")
    return lb / vol if lb and vol else None


@app.get("/compare")
def compare(request: Request):
    """Every batch side by side, to see what works."""
    with db() as con:
        rows = []
        for b in con.execute("SELECT * FROM batch WHERE status != 'recipe' ORDER BY start_date DESC, id DESC"):
            s = stats(con, b)
            rows.append({"b": b, "s": s, "honey": honey_per_gal(s["ings"], b["volume_gal"]),
                         "per_bottle": s.get("per_bottle", s.get("cost_bottle"))})
    return tpl.TemplateResponse(request, "compare.html", {"rows": rows,
                                                          "styles": sorted({r["b"]["style"] for r in rows if r["b"]["style"]})})


EXPORTS = {  # name: (columns, query); batches is built from stats() instead
    "readings": ("batch,date,sg,temp_f,ph,note,by", "SELECT b.name, r.taken_on, r.sg, r.temp_f, r.ph, r.note, r.who FROM reading r "
                 "JOIN batch b ON b.id = r.batch_id ORDER BY b.name, r.taken_on"),
    "costs": ("batch,date,item,amount,from_inventory,note,by", "SELECT b.name, e.spent_on, e.item, e.amount, e.inventory_id IS NOT NULL, "
              "e.note, e.who FROM expense e JOIN batch b ON b.id = e.batch_id ORDER BY b.name, e.spent_on"),
    "payments": ("date,paid_by,for,amount,paid_back_to,note,batch", "SELECT p.paid_on, p.paid_by, p.item, p.amount, p.paid_to, p.note, "
                 "b.name FROM payment p LEFT JOIN batch b ON b.id = p.batch_id ORDER BY p.paid_on"),
    "inventory": ("kind,item,on_hand,unit,unit_cost,value,reorder_at,notes", "SELECT kind, name, qty, unit, unit_cost, "
                  "ROUND(qty * COALESCE(unit_cost, 0), 2), reorder_at, notes FROM inventory ORDER BY kind, name"),
    "bottles": ("batch,date,bottles,what,rating,note,by", "SELECT b.name, o.on_date, o.qty, o.kind, o.rating, o.note, o.who "
                "FROM bottle_out o JOIN batch b ON b.id = o.batch_id ORDER BY b.name, o.on_date"),
}


@app.get("/export/{what}.csv")
def export(what: str):
    """Spreadsheet-ready copies of the data."""
    out = io.StringIO()
    w = csv.writer(out)
    with db() as con:
        if what == "batches":
            w.writerow("name,status,style,volume_gal,yeast,start,bottled,og,current,abv,cost,bottles,per_bottle,"
                       "bottles_left,rating,ready_on".split(","))
            for b in con.execute("SELECT * FROM batch WHERE status != 'recipe' ORDER BY start_date"):
                s = stats(con, b)
                r2 = lambda v, n=3: round(v, n) if v is not None else None  # noqa: E731
                w.writerow([b["name"], b["status"], b["style"], b["volume_gal"], b["yeast"], b["start_date"],
                            b["bottle_date"], r2(s["og"]), r2(s["cur"]), r2(s.get("abv"), 1), round(s["cost"], 2),
                            b["bottles"], r2(s.get("per_bottle"), 2), s.get("left"), r2(s.get("rating"), 1), b["ready_on"]])
        elif what in EXPORTS:
            cols, sql = EXPORTS[what]
            w.writerow(cols.split(","))
            w.writerows(con.execute(sql).fetchall())
        else:
            raise HTTPException(404)
    return Response(out.getvalue(), media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="mead-{what}-{date.today().isoformat()}.csv"'})


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


def plato_to_sg(p: float) -> float:
    return 1 + p / (258.6 - (p / 258.2) * 227.1)


def device_problems(con, b) -> list:
    """What's wrong with the iSpindel assigned to an active batch, as task text (empty when it's fine)."""
    if not b["ispindel"] or b["status"] not in ("primary", "secondary", "aging"):
        return []
    d = con.execute("SELECT * FROM device WHERE name=?", (b["ispindel"],)).fetchone()
    if not d or not d["last_seen"]:
        return [f"iSpindel {b['ispindel']} hasn't reported yet: check its WiFi and push settings"]
    out = []
    seen = datetime.fromisoformat(d["last_seen"])
    if datetime.now() - seen > STALE:
        out.append(f"iSpindel {b['ispindel']} hasn't reported since {day(seen.date())} {seen:%H:%M}: battery or WiFi?")
    if d["battery"] is not None and d["battery"] < LOW_BATTERY:
        out.append(f"Charge iSpindel {b['ispindel']} ({d['battery']:.2f} V)")
    return out


@app.post("/api/ispindel")
async def ispindel(request: Request):
    """Where an iSpindel / GravityMon posts (HTTP, iSpindel JSON format). Logs a reading for the active batch it's
    assigned to, at most hourly, with the device's calibration offset applied."""
    try:
        body = await request.json()
        name = str(body.get("name") or body.get("ID") or "").strip()[:40]
        raw = float(body["gravity"])
        temp = float(body["temperature"]) if body.get("temperature") is not None else None
    except (ValueError, KeyError, TypeError, AttributeError):
        raise HTTPException(400, "expected iSpindel JSON with name and gravity")
    if not name:
        raise HTTPException(400, "expected iSpindel JSON with name and gravity")
    unit = str(body.get("gravity-unit") or body.get("gravity_unit") or "G").upper()
    sg = plato_to_sg(raw) if unit.startswith("P") or raw > 1.5 else raw
    tu = str(body.get("temp_units") or body.get("temp-units") or "C").upper()
    temp_f = None if temp is None else temp if tu.startswith("F") else (temp - 273.15 if tu.startswith("K") else temp) * 9 / 5 + 32
    num_or = lambda k: float(body[k]) if isinstance(body.get(k), (int, float)) else None  # noqa: E731
    now = datetime.now()
    with db() as con:
        con.execute("INSERT INTO device (name) VALUES (?) ON CONFLICT(name) DO NOTHING", (name,))
        d = con.execute("SELECT * FROM device WHERE name=?", (name,)).fetchone()
        sg = round(sg + (d["offset"] or 0), 4)
        con.execute("UPDATE device SET last_seen=?, gravity=?, temp_f=?, battery=?, angle=?, rssi=?, interval=? WHERE name=?",
                    (now.isoformat(timespec="seconds"), sg, temp_f, num_or("battery"), num_or("angle"),
                     num_or("RSSI"), num_or("interval"), name))
        b = con.execute("SELECT * FROM batch WHERE ispindel=? AND status IN ('primary', 'secondary', 'aging') "
                        "ORDER BY start_date DESC, id DESC", (name,)).fetchone()
        due = not d["last_logged"] or now - datetime.fromisoformat(d["last_logged"]) >= LOG_EVERY
        logged = bool(b) and due and 0.980 <= sg <= 1.200
        if logged:
            con.execute("INSERT INTO reading (batch_id, taken_on, sg, temp_f, note, who) VALUES (?,?,?,?,?,?)",
                        (b["id"], now.date().isoformat(), sg, None if temp_f is None else round(temp_f, 1),
                         DEVICE_NOTE, DEVICE_NOTE))
            con.execute("UPDATE device SET last_logged=? WHERE name=?", (now.isoformat(timespec="seconds"), name))
    return {"ok": True, "batch": b["name"] if b else None, "logged": logged, "sg": sg}


@app.get("/devices")
def devices(request: Request):
    with db() as con:
        rows = con.execute("SELECT d.*, b.id AS batch_id, b.name AS batch_name FROM device d LEFT JOIN batch b "
                           "ON b.ispindel = d.name AND b.status IN ('primary', 'secondary', 'aging') ORDER BY d.name").fetchall()
    return tpl.TemplateResponse(request, "devices.html", {"rows": rows, "now": datetime.now(), "stale": STALE,
                                                          "low": LOW_BATTERY, "fromiso": datetime.fromisoformat})


@app.post("/devices/{name}")
async def device_update(name: str, request: Request):
    f = await request.form()
    with db() as con:
        if f.get("remove"):
            con.execute("DELETE FROM device WHERE name=?", (name,))
        else:
            con.execute("UPDATE device SET offset=? WHERE name=?", (num(f.get("offset")) or 0, name))
    return back("/devices")


@app.get("/api/tasks")
def api_tasks():
    """Next action per active batch, for the Discord bot. `due` is false for a gravity re-check
    whose last reading is under a week old — nothing to do yet."""
    out = []
    with db() as con:
        for b in con.execute("SELECT * FROM batch WHERE status IN ('primary', 'secondary', 'aging') ORDER BY id"):
            s = stats(con, b)
            for problem in device_problems(con, b):
                out.append({**summary(b, s), "task": problem, "link": None, "due": True})
            if not s["next"] or s["auto"]:
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
