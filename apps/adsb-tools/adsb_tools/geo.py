#!/usr/bin/env python3
"""Great-circle distance between two lat/lon points."""
import math

EARTH_RADIUS_KM = 6371.0


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in km between two (lat, lon) points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _self_check() -> None:
    # Ithaca, NY -> NYC: ~283 km
    d = haversine(42.4430, -76.5019, 40.7128, -74.0060)
    assert 260 < d < 310, f"unexpected distance: {d}"
    # same point -> 0
    assert haversine(1.0, 1.0, 1.0, 1.0) == 0.0
    print(f"self-check OK: Ithaca->NYC = {d:.1f} km")


if __name__ == "__main__":
    _self_check()
