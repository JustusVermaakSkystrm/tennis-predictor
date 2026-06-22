"""
project_draw.py — Wimbledon-2026-style grass draw projection.

Fits Elo over all history, selects the current grass field for each tour, simulates a
seeded single-elim draw (ATP best-of-5, WTA best-of-3), and writes an HTML page with
title-odds bars + a seeded bracket per tour into out/.

When the real Wimbledon 2026 draw is published, pass an explicit slot list to
simulate(slots=...) instead of seeding by rating.

Usage: python -m scripts.project_draw [draw_size]   (default 32; 64/128 supported)
"""
from __future__ import annotations

import os
import sys

from tennis import viz
from tennis.engine import current_table, fit
from tennis.simulator import seeded_slot_order, simulate

OUT = os.path.join(os.path.dirname(__file__), "..", "out")
TOURS = [("atp", 5, "ATP — Gentlemen's Singles"), ("wta", 3, "WTA — Ladies' Singles")]


def project(tour: str, best_of: int, draw_size: int):
    elo, df = fit(tour)
    asof = int(df["tourney_date"].max())
    active = (asof // 10000 - 1) * 10000 + (asof % 10000)   # active in last ~12 months
    # min_n=25 trims the worst small-sample rating spikes from the seeded field.
    field = [r.key for r in current_table(elo, "Grass", tour=tour,
                                          active_since=active, min_n=25, top=draw_size)]
    slots = seeded_slot_order(field, elo, "Grass")
    res = simulate(field, elo, "Grass", best_of=best_of, n_sims=40000,
                   slots=slots, bo5_sharpen=0.15)
    return elo, res, slots, asof


def main():
    draw_size = int(sys.argv[1]) if len(sys.argv) > 1 else 32
    os.makedirs(OUT, exist_ok=True)
    sections = []
    for tour, bo, label in TOURS:
        elo, res, slots, asof = project(tour, bo, draw_size)
        champ = res.champion_table(3)
        fav = ", ".join(f"{n} {w*100:.0f}%" for n, w, _, _ in champ)
        print(f"\n{label}  (as of {asof}, Bo{bo}, {res.draw_size}-draw)")
        print(f"{'player':<22}{'Win%':>7}{'Final%':>8}{'SF%':>7}")
        for n, w, f, sf in res.champion_table(10):
            print(f"{n:<22}{w*100:>6.1f}{f*100:>7.1f}{sf*100:>6.1f}")
        odds = viz.odds_svg(res, top=12, title=f"{label} — title odds",
                            subtitle=f"Grass · Bo{bo} · {res.draw_size}-draw · {res.n_sims:,} sims · favourites: {fav}")
        path = viz.path_svg(res, top=8, title=f"{label} — path to the final")
        bracket = viz.bracket_svg(res, slots, title=f"{label} — seeded bracket")
        sections.append((label, odds, path, bracket))

    html = ["<!doctype html><meta charset='utf-8'><title>Wimbledon 2026 projection</title>",
            "<style>body{background:#0d1117;color:#e6edf3;font-family:Inter,system-ui,sans-serif;"
            "max-width:1100px;margin:0 auto;padding:24px}h1{font-weight:800}.sub{color:#8b949e}"
            "section{margin:28px 0}svg{width:100%;height:auto;margin:10px 0}</style>",
            "<h1>Wimbledon 2026 — model projection</h1>",
            "<p class='sub'>Surface-weighted Elo · seeded-by-rating field (illustrative until the official draw). "
            "Path-to-the-final probabilities from Monte Carlo bracket simulation.</p>"]
    for label, odds, path, bracket in sections:
        html.append(f"<section><h2>{label}</h2>{odds}{path}"
                    f"<details><summary class='sub'>seeded bracket</summary>{bracket}</details></section>")
    out_path = os.path.join(OUT, "wimbledon2026.html")
    with open(out_path, "w") as f:
        f.write("\n".join(html))
    print(f"\nWrote {os.path.relpath(out_path)}")


if __name__ == "__main__":
    main()
