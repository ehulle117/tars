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
    assert "re-check gravity" in c.get("/").text
    c.post(f"/batch/{bid}/reading", data={"taken_on": "2026-10-12", "sg": "1.040"})
    c.post(f"/batch/{bid}/reading", data={"taken_on": "2026-10-19", "sg": "1.040"})
    assert "possibly stuck" in c.get("/").text
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
