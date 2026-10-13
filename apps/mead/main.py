"""Mead log: FastAPI + stdlib sqlite3 + Jinja templates."""
import os
import sqlite3
from datetime import date
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


def num(v) -> Optional[float]:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except ValueError:
        raise HTTPException(400, f"not a number: {v!r}")


def back(path: str):
    return RedirectResponse(path, status_code=303)


def stats(con, b) -> dict:
    """Everything derived for one batch."""
    ings = [dict(r) for r in con.execute("SELECT * FROM ingredient WHERE batch_id=? ORDER BY added_on, id", (b["id"],))]
    reads = [dict(r) for r in con.execute("SELECT * FROM reading WHERE batch_id=? ORDER BY taken_on, id", (b["id"],))]
    for r in reads:
        r["sg_c"] = chem.temp_correct(r["sg"], r["temp_f"]) if r["temp_f"] else r["sg"]
    kinds = [e[0] for e in con.execute("SELECT kind FROM event WHERE batch_id=? ORDER BY on_date, id", (b["id"],))]
    est_og = chem.estimate_og(ings, b["volume_gal"] or 0)
    og = reads[0]["sg_c"] if reads else (est_og or b["target_og"])
    cur = reads[-1]["sg_c"] if len(reads) > 1 else None
    stable = chem.is_stable([(r["taken_on"], r["sg_c"]) for r in reads])
    s = {"ings": ings, "reads": reads, "est_og": est_og, "og": og, "cur": cur, "stable": stable,
         "nutrient_done": kinds.count("nutrient"), "next": None, "next_link": None,
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
    if b["start_date"]:
        s["days"] = (date.today() - date.fromisoformat(b["start_date"])).days
    s["next"], s["next_link"] = next_action(b, s, kinds)
    return s


def next_action(b, s, kinds):
    """One prompt for the dashboard, following the wiki's process."""
    if b["status"] not in ("primary", "secondary", "aging"):
        return None, None
    if s.get("tosna") and s["nutrient_done"] < 4 and b["status"] == "primary":
        d = s["tosna"]["doses"][s["nutrient_done"]]
        return f"Nutrient dose {s['nutrient_done'] + 1}: {d['g']} g Fermaid-O ({d['when']})", None
    if len(s["reads"]) < 2:
        return "Take a gravity reading", None
    if not s["stable"]:
        return "Fermenting — re-check gravity in a week", None
    top = b["target_fg_max"] or b["target_fg"]
    if top and s["cur"] > top + 0.002:
        return "Stable above target FG — possibly stuck", WIKI + "protocol/stuck_fermentation"
    if "stabilize" not in kinds:
        return "Stable — stabilize (K-meta + sorbate)", WIKI + "process/stabilization"
    if "backsweeten" not in kinds and "bottle" not in kinds:
        return "Stabilized — wait 24 h, then backsweeten if wanted", WIKI + "process/back_sweeten"
    return "Clear? Bottle or keep aging", WIKI + "process/packaging"


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
        "b": b, "s": s, "events": events, "statuses": STATUSES, "kinds": KINDS, "event_kinds": EVENTS,
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


@app.post("/batch/{bid}/{table}/{rid}/delete")
def delete_row(bid: int, table: str, rid: int):
    if table not in ("ingredient", "reading", "event"):  # whitelist: table name is interpolated
        raise HTTPException(404)
    with db() as con:
        con.execute(f"DELETE FROM {table} WHERE id=? AND batch_id=?", (rid, bid))
    return back(f"/batch/{bid}")


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
