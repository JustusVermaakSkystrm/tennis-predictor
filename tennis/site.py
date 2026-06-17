"""
site.py — static site generator for the tennis prediction engine.

Assembles the pieces already built — model scorecard, Wimbledon draw projections
(title odds + brackets), current-form tables — into a single self-contained dark-theme
page written to docs/index.html (GitHub Pages serves from /docs). Re-running rebuilds
it against the latest data, so the hourly workflow just calls build().
"""
from __future__ import annotations

import os

from . import engine, viz
from .simulator import seeded_slot_order, simulate

DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")

CSS = """
:root{
  --bg:#0d1117; --card:#161b22; --txt:#e6edf3; --mut:#8b949e; --line:#30363d;
  --accent:#2f81f7; --accent2:#3fb950; --barbg:#21262d; --font:'Inter',system-ui,-apple-system,sans-serif;
}
*{box-sizing:border-box} html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--txt);font-family:var(--font);line-height:1.5}
.wrap{max-width:1080px;margin:0 auto;padding:0 20px}
header{padding:64px 0 40px;border-bottom:1px solid var(--line)}
.eyebrow{color:var(--accent);font-weight:600;letter-spacing:.04em;text-transform:uppercase;font-size:13px}
h1{font-size:clamp(30px,5vw,46px);font-weight:800;margin:10px 0 8px;letter-spacing:-.02em}
.lede{color:var(--mut);font-size:18px;max-width:620px;margin:0}
.meta{color:var(--mut);font-size:13px;margin-top:18px;display:flex;gap:18px;flex-wrap:wrap}
.meta b{color:var(--txt);font-weight:600}
section{padding:48px 0;border-bottom:1px solid var(--line)}
h2{font-size:26px;font-weight:700;margin:0 0 6px;letter-spacing:-.01em}
.sub{color:var(--mut);margin:0 0 22px;max-width:640px}
svg{width:100%;height:auto;display:block;border-radius:12px}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:22px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px}
.card h3{margin:0 0 12px;font-size:16px;font-weight:700}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line)}
th{color:var(--mut);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.03em}
td.num{text-align:right;font-variant-numeric:tabular-nums;color:var(--mut)}
td.lead{font-weight:600;color:var(--txt)}
.rank{color:var(--mut);width:26px}
details{margin-top:12px} summary{color:var(--mut);cursor:pointer;font-size:14px;padding:6px 0}
.note{color:var(--mut);font-size:15px;line-height:1.65} .note b{color:var(--txt)}
.pill{display:inline-block;background:var(--barbg);border:1px solid var(--line);border-radius:999px;
  padding:3px 11px;font-size:12px;color:var(--mut);margin:2px 4px 2px 0}
.win{color:var(--accent2);font-weight:700}
footer{padding:36px 0 64px;color:var(--mut);font-size:13px}
a{color:var(--accent);text-decoration:none} a:hover{text-decoration:underline}
"""


def _fmt_date(d: int) -> str:
    s = str(d)
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"


def _ratings_table(elo, tour, surface, asof, n=10) -> str:
    active = (asof // 10000 - 1) * 10000 + (asof % 10000)
    rows = engine.current_table(elo, surface, tour=tour, active_since=active, min_n=20, top=n)
    trs = []
    for i, r in enumerate(rows, 1):
        trs.append(f"<tr><td class='rank'>{i}</td><td class='lead'>{r.name}</td>"
                   f"<td class='num'>{r.blended:.0f}</td><td class='num'>{r.surface:.0f}</td></tr>")
    return (f"<div class='card'><h3>{tour.upper()} — current grass form</h3>"
            f"<table><thead><tr><th></th><th>Player</th><th class='num'>Blended</th>"
            f"<th class='num'>Grass</th></tr></thead><tbody>{''.join(trs)}</tbody></table></div>")


def build(draw_size: int = 32) -> str:
    """Build the full page HTML and write docs/index.html. Returns the HTML."""
    from scripts.scorecard import build as scorecard_build
    cards, raw = scorecard_build()
    scorecard = viz.scorecard_svg(cards, title="Skill vs the ranking & the market")

    proj_sections, rating_cards, asof = [], [], 0
    for tour, bo, label in (("atp", 5, "ATP — Gentlemen's Singles"), ("wta", 3, "WTA — Ladies' Singles")):
        elo, df = engine.fit(tour)
        asof = int(df["tourney_date"].max())
        active = (asof // 10000 - 1) * 10000 + (asof % 10000)
        field = [r.key for r in engine.current_table(elo, "Grass", tour=tour,
                                                      active_since=active, min_n=25, top=draw_size)]
        slots = seeded_slot_order(field, elo, "Grass")
        res = simulate(field, elo, "Grass", best_of=bo, n_sims=40000, slots=slots, bo5_sharpen=0.15)
        fav = ", ".join(f"{n} {w*100:.0f}%" for n, w, _, _ in res.champion_table(2))
        odds = viz.odds_svg(res, top=10, title=label,
                            subtitle=f"Grass · Bo{bo} · {res.draw_size}-draw · {res.n_sims:,} sims")
        bracket = viz.bracket_svg(res, slots, title=f"{label} — seeded bracket")
        proj_sections.append(
            f"<div><div>{odds}</div><details><summary>seeded bracket (top {draw_size})</summary>{bracket}</details>"
            f"<p class='note' style='margin-top:8px'>Favourites: <b>{fav}</b></p></div>")
        rating_cards.append(_ratings_table(elo, tour, "Grass", asof))

    n_total = sum(raw[t]["validation"]["n_eval"] for t in raw)
    atp_v, wta_v = raw["atp"]["validation"], raw["wta"]["validation"]

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tennis Model — ATP & WTA prediction engine</title>
<meta name="description" content="Surface-weighted Elo predictions for ATP & WTA tennis, with a path-to-the-final draw projection and an honest market/CLV benchmark.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>{CSS}</style></head>
<body><div class="wrap">

<header>
  <div class="eyebrow">ATP · WTA · surface-weighted Elo</div>
  <h1>Tennis prediction model</h1>
  <p class="lede">Ratings that beat the official rankings, path-to-the-final draw projections,
  and an honest benchmark against the betting market.</p>
  <div class="meta">
    <span>Data through <b>{_fmt_date(asof)}</b></span>
    <span><b>360k+</b> matches, 1968–2026</span>
    <span>Both tours</span>
  </div>
</header>

<section id="scorecard">
  <h2>How good is it?</h2>
  <p class="sub">Two benchmarks, held out from training. Green marks the winner of each row.</p>
  {scorecard}
  <p class="note" style="margin-top:16px">
  <b>Versus the ranking</b> — surface-weighted Elo beats the official ATP/WTA ranking on held-out
  matches (ATP {atp_v['elo']['log_loss']} vs {atp_v['ranking_logistic']['log_loss']} log-loss;
  WTA {wta_v['elo']['log_loss']} vs {wta_v['ranking_logistic']['log_loss']}).
  <b>Versus the market</b> — on main-tour events the de-vigged Pinnacle close is sharper, and a naive
  value strategy returns negative ROI and negative CLV. That's the honest result: a pure-ratings model
  with no serve, injury or matchup signal should not beat the closing line where the market is efficient.
  Edge is expected in lower tiers (Challenger/ITF) and early rounds — not tested by this main-tour odds source.</p>
</section>

<section id="wimbledon">
  <h2>Wimbledon 2026 — projection</h2>
  <p class="sub">Monte Carlo bracket simulation on grass (ATP best-of-5, WTA best-of-3). Field seeded
  by current rating — illustrative until the official draw is published.</p>
  <div class="grid2">{''.join(proj_sections)}</div>
</section>

<section id="form">
  <h2>Current grass form</h2>
  <p class="sub">Top of each tour by blended (overall + grass) Elo, active in the last 12 months.</p>
  <div class="grid2">{''.join(rating_cards)}</div>
</section>

<section id="how">
  <h2>How it works</h2>
  <p class="note">
  Every match in tour history is replayed in order, updating each player's <b>overall</b> and
  <b>per-surface</b> Elo. A dynamic K-factor lets newcomers move fast and veterans stay stable;
  an inactivity decay keeps ratings current through injuries and off-seasons. A match probability
  is the logistic of the blended rating gap. Draw projections Monte-Carlo the bracket; the market
  benchmark joins bookmaker closing odds and measures closing-line value (CLV) — the honest measure,
  since single matches are high variance.</p>
  <div style="margin-top:14px">
    <span class="pill">surface-weighted Elo</span><span class="pill">inactivity decay</span>
    <span class="pill">Monte Carlo brackets</span><span class="pill">de-vigged market odds</span>
    <span class="pill">closing-line value</span><span class="pill">both tours, 1968–2026</span>
  </div>
</section>

<footer>
  <p>Built with surface-weighted Elo. Match data: <a href="https://github.com/LuckyLoser91/TennisCourtLog">TennisCourtLog</a>
  (a live mirror of Jeff Sackmann's format). Odds: <a href="http://www.tennis-data.co.uk">tennis-data.co.uk</a>.
  Not affiliated with the ATP, WTA, or Wimbledon. For research, not betting advice.</p>
</footer>

</div></body></html>"""

    os.makedirs(DOCS, exist_ok=True)
    with open(os.path.join(DOCS, "index.html"), "w") as f:
        f.write(html)
    with open(os.path.join(DOCS, ".nojekyll"), "w") as f:
        f.write("")
    return html


if __name__ == "__main__":
    build()
    print(f"Wrote {os.path.join('docs', 'index.html')}")
