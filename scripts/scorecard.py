"""
scorecard.py — the honest model scorecard: skill vs the ranking, and vs the market.

Assembles two benchmarks per tour into one card + SVG:
  * vs RANKING  — held-out log-loss/accuracy; Elo should win (it does).
  * vs MARKET   — model vs de-vigged Pinnacle close; value ROI; CLV. The market is
                  expected to win on main tour — the point is to report it honestly.

Writes out/scorecard.html (+ scorecard.svg). Slow (~2 min): it runs four full passes.
"""
from __future__ import annotations

import json
import os

from scripts.benchmark_market import run as market_run
from scripts.validate import evaluate
from tennis import viz

OUT = os.path.join(os.path.dirname(__file__), "..", "out")


def build():
    cards, raw = [], {}
    for tour, label in (("atp", "ATP"), ("wta", "WTA")):
        val = evaluate(tour, 20250601, verbose=False)
        mkt = market_run(tour, 20190101, edge=0.05, verbose=False)
        raw[tour] = {"validation": val, "market": mkt}
        b = mkt["bets"]
        cards.append({
            "tour": label,
            "rows": [
                ("Log-loss vs ranking", val["elo"]["log_loss"], val["ranking_logistic"]["log_loss"], "low"),
                ("Accuracy vs ranking", val["elo"]["accuracy"], val["ranking_logistic"]["accuracy"], "high"),
                ("Log-loss vs market", mkt["model_logloss"], mkt["market_logloss"], "low"),
                ("Accuracy vs market", mkt["model_acc"], mkt["market_acc"], "high"),
                ("Value ROI (flat, edge 5%)", f"{b.get('roi',0)*100:.1f}%", "0.0%", "high"),
                ("Avg CLV vs close", f"{(b.get('avg_clv') or 0)*100:.1f}%", "0.0%", "high"),
            ],
        })
    return cards, raw


def main():
    os.makedirs(OUT, exist_ok=True)
    cards, raw = build()
    svg = viz.scorecard_svg(cards, title="Tennis model scorecard — skill vs ranking & market")
    html = ["<!doctype html><meta charset='utf-8'><title>Model scorecard</title>",
            "<style>body{background:#0d1117;color:#e6edf3;font-family:Inter,system-ui,sans-serif;"
            "max-width:840px;margin:0 auto;padding:24px}svg{width:100%;height:auto}"
            ".note{color:#8b949e;font-size:14px;line-height:1.5}</style>",
            "<h1>Tennis prediction — model scorecard</h1>", svg,
            "<p class='note'>Green = winner of each row. <b>vs ranking</b>: Elo beats the official "
            "ATP/WTA ranking on held-out matches. <b>vs market</b>: on main-tour events the de-vigged "
            "Pinnacle close is sharper than the model, and a naive value strategy returns negative ROI "
            "with negative CLV — i.e. no exploitable edge where the market is efficient. Per the brief, "
            "edge is expected in lower tiers (Challenger/ITF) and early rounds, which this odds source "
            "(main tour only) cannot test. CLV, not short-run W/L, is the honest measure.</p>"]
    open(os.path.join(OUT, "scorecard.svg"), "w").write('<?xml version="1.0"?>\n' + svg)
    open(os.path.join(OUT, "scorecard.html"), "w").write("\n".join(html))
    print(json.dumps(raw, indent=2, default=str))
    print(f"\nWrote {os.path.relpath(os.path.join(OUT,'scorecard.html'))}")


if __name__ == "__main__":
    main()
