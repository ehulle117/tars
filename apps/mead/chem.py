"""Mead chemistry. Pure functions; US units (gal, lb, °F) unless noted."""
from datetime import date
from typing import Dict, List, Optional, Tuple

L_PER_GAL = 3.78541
LB_PER = {"lb": 1.0, "oz": 1 / 16, "kg": 2.20462, "g": 0.00220462}
GAL_PER = {"gal": 1.0, "l": 1 / L_PER_GAL, "ml": 0.001 / L_PER_GAL}
HONEY_PPG = 35.0  # gravity points per lb per gallon


def to_lb(amount: float, unit: str) -> Optional[float]:
    f = LB_PER.get(unit.lower())
    return None if f is None else amount * f


def to_gal(amount: float, unit: str) -> Optional[float]:
    f = GAL_PER.get(unit.lower())
    return None if f is None else amount * f


def estimate_og(ingredients: List[Dict], volume_gal: float) -> Optional[float]:
    """ingredients: dicts with amount, unit, ppg. ppg is points per lb for weighed items,
    points per gallon for liquids (apple juice ~50). Items without ppg are ignored."""
    if not volume_gal:
        return None
    points = 0.0
    for i in ingredients:
        qty = to_lb(i["amount"], i["unit"]) or to_gal(i["amount"], i["unit"])
        if qty and i.get("ppg"):
            points += qty * i["ppg"]
    return round(1 + points / volume_gal / 1000, 4) if points else None


def abv(og: float, fg: float) -> float:
    """Standard formula; drifts low above ~1.100 OG — see abv_high."""
    return (og - fg) * 131.25


def abv_high(og: float, fg: float) -> float:
    """Hall formula, better for high-gravity meads."""
    return (76.08 * (og - fg) / (1.775 - og)) * (fg / 0.794)


def attenuation(og: float, fg: float) -> float:
    return (og - fg) / (og - 1) * 100 if og > 1 else 0.0


def temp_correct(sg: float, temp_f: float, calib_f: float = 60.0) -> float:
    def d(t):
        return 1.00130346 - 0.000134722124 * t + 0.00000204052596 * t**2 - 0.00000000232820948 * t**3
    return sg * d(temp_f) / d(calib_f)


def sg_to_brix(sg: float) -> float:
    return ((182.4601 * sg - 775.6821) * sg + 1262.7794) * sg - 669.5622


def brix_to_sg(brix: float) -> float:
    return 1 + brix / (258.6 - (brix / 258.2) * 227.1)


def sugar_break(og: float, fg: float = 1.0) -> float:
    """Gravity at the 1/3 sugar break (last staggered nutrient dose)."""
    return og - (og - fg) / 3


N_FACTOR = {"low": 0.75, "medium": 0.9, "high": 1.25, "very high": 1.8}


def tosna(og: float, volume_gal: float, n_need: str = "medium", goferm: bool = True) -> Dict:
    """TOSNA Fermaid-O schedule, same math as MeadTools (packages/core/src/nutrients.ts):
    target YAN = Brix * SG * 10 * factor; Fermaid-O = 40 ppm per g/L, x4 organic credit
    with GoFerm rehydration (x3 without); capped at 2.5 g/L."""
    yan = sg_to_brix(og) * og * 10 * N_FACTOR[n_need]
    g_per_l = min(yan / (40 * (4 if goferm else 3)), 2.5)
    total_g = g_per_l * volume_gal * L_PER_GAL
    dose = total_g / 4
    return {
        "yan_ppm": round(yan),
        "capped": g_per_l == 2.5,
        "total_g": round(total_g, 1),
        "doses": [
            {"when": "24h", "g": round(dose, 1)},
            {"when": "48h", "g": round(dose, 1)},
            {"when": "72h", "g": round(dose, 1)},
            {"when": f"1/3 break (SG {sugar_break(og):.3f}) or day 7", "g": round(dose, 1)},
        ],
    }


def kmeta_g(ph: float, volume_gal: float, molecular: float = 0.8) -> Dict:
    """Potassium metabisulfite for a target molecular SO2 (0.8 ppm typical)."""
    free_so2 = molecular * (1 + 10 ** (ph - 1.81))
    grams = free_so2 * volume_gal * L_PER_GAL / 1000 / 0.576
    return {"free_so2_ppm": round(free_so2), "g": round(grams, 2), "campden": round(grams / 0.44, 1)}


def sorbate_g(volume_gal: float, sorbic_ppm: float = 200) -> float:
    """Potassium sorbate (74% sorbic acid)."""
    return round(sorbic_ppm * volume_gal * L_PER_GAL / 1000 / 0.74, 2)


def backsweeten_lb(current_sg: float, target_sg: float, volume_gal: float,
                   ppg: float = HONEY_PPG) -> float:
    return round(max(0.0, (target_sg - current_sg) * 1000 * volume_gal / ppg), 2)


def is_stable(readings: List[Tuple[str, float]], days: int = 7, tol: float = 0.001) -> bool:
    """readings: (iso date, sg) sorted by date. Stable (finished or stuck) when the latest
    reading matches the most recent one taken at least `days` earlier — per the wiki."""
    if not readings:
        return False
    last_d, last_sg = date.fromisoformat(readings[-1][0]), readings[-1][1]
    for d, sg in reversed(readings[:-1]):
        if (last_d - date.fromisoformat(d)).days >= days:
            return abs(sg - last_sg) <= tol
    return False


def style_class(og: Optional[float], fg: Optional[float]) -> str:
    """BJCP strength by OG and sweetness by FG, as listed on the wiki."""
    parts = []
    if og:
        parts.append("hydromel" if og < 1.080 else "standard" if og < 1.120 else "sack")
    if fg:
        parts.append("dry" if fg < 1.010 else "semi-sweet" if fg < 1.025 else "sweet")
    return " · ".join(parts)
