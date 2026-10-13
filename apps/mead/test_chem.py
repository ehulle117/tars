from pytest import approx

import chem
import seed


def test_og_from_honey():
    # 3 lb honey in 1 gal ≈ 1.105
    assert chem.estimate_og([{"amount": 3, "unit": "lb", "ppg": 35}], 1) == approx(1.105)
    # metric: 1.36 kg ≈ 3 lb; items without ppg ignored
    og = chem.estimate_og([{"amount": 1.36, "unit": "kg", "ppg": 35},
                           {"amount": 2, "unit": "tsp", "ppg": None}], 1)
    assert og == approx(1.105, abs=0.001)
    # liquids: ppg = points per gallon of the liquid
    assert chem.estimate_og([{"amount": 1, "unit": "gal", "ppg": 50}], 1) == approx(1.050)


def test_abv():
    assert chem.abv(1.100, 1.000) == approx(13.125)
    assert chem.abv_high(1.100, 1.000) == approx(14.2, abs=0.05)
    assert chem.attenuation(1.100, 1.010) == approx(90)


def test_temp_correct():
    assert chem.temp_correct(1.050, 60) == approx(1.050)
    assert chem.temp_correct(1.050, 80) == approx(1.0526, abs=0.0003)


def test_brix_roundtrip():
    assert chem.sg_to_brix(1.100) == approx(23.8, abs=0.2)
    assert chem.brix_to_sg(chem.sg_to_brix(1.080)) == approx(1.080, abs=0.0005)


def test_sugar_break_and_tosna():
    assert chem.sugar_break(1.120) == approx(1.080)
    # MeadTools reference: 1.100, 1 gal, medium, GoFerm -> ~235 ppm, ~5.6 g Fermaid-O
    t = chem.tosna(1.100, 1, "medium")
    assert t["yan_ppm"] == approx(235, abs=3)
    assert t["total_g"] == approx(5.6, abs=0.15)
    assert len(t["doses"]) == 4 and not t["capped"]
    assert t["total_g"] == approx(sum(d["g"] for d in t["doses"]), abs=0.2)
    assert chem.tosna(1.100, 1, "medium", goferm=False)["total_g"] > t["total_g"]  # x3 credit, not x4
    big = chem.tosna(1.150, 1, "very high")
    assert big["capped"] and big["total_g"] == approx(2.5 * chem.L_PER_GAL, abs=0.1)


def test_stabilize():
    k = chem.kmeta_g(3.5, 5)
    assert k["free_so2_ppm"] == approx(40, abs=1)
    assert k["g"] == approx(1.3, abs=0.05)
    assert k["campden"] == approx(k["g"] / 0.44, abs=0.1)
    assert chem.sorbate_g(1) == approx(1.02, abs=0.02)


def test_backsweeten_and_stable():
    assert chem.backsweeten_lb(1.000, 1.010, 5) == approx(1.43, abs=0.01)
    assert chem.backsweeten_lb(1.020, 1.010, 5) == 0
    # wiki rule: matching readings at least a week apart
    assert chem.is_stable([("2026-10-01", 1.050), ("2026-10-05", 1.000), ("2026-10-12", 1.0005)])
    assert not chem.is_stable([("2026-10-05", 1.000), ("2026-10-08", 1.000)])  # too close together
    assert not chem.is_stable([("2026-10-01", 1.010), ("2026-10-09", 1.000)])  # still dropping
    assert not chem.is_stable([])


def test_style_class():
    assert chem.style_class(1.060, 1.000) == "hydromel · dry"
    assert chem.style_class(1.110, 1.015) == "standard · semi-sweet"
    assert chem.style_class(1.130, 1.030) == "sack · sweet"
    assert chem.style_class(None, None) == ""


def test_seed_recipes_match_wiki_targets():
    # catches typos in seed data; fruit melomels skipped — fruit sugar is too variable to estimate
    for r in seed.RECIPES:
        if r["style"] == "melomel":
            continue
        ings = [{"amount": a, "unit": u, "ppg": p} for _, _, a, u, p in r["ings"]]
        assert chem.estimate_og(ings, r["volume_gal"]) == approx(r["target_og"], abs=0.008), r["name"]
