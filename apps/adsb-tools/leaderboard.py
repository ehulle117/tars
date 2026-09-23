#!/usr/bin/env python3
"""Print the closest-approach leaderboard. Usage: python3 leaderboard.py [top_n]"""
import sys

from closest_approach import leaderboard

if __name__ == "__main__":
    top_n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    rows = leaderboard(top_n=top_n)
    if not rows:
        print("No aircraft tracked yet.")
    for i, (hex_, flight, range_km, alt) in enumerate(rows, 1):
        label = (flight or hex_).strip()
        print(f"{i:2d}. {label:10s} {range_km:6.2f} km  alt {alt or '?'} ft")
