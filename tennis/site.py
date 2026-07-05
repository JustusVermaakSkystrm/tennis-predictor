"""
site.py — static site generator for the tennis prediction engine.

Assembles the pieces already built — model scorecard, Wimbledon draw projections
(title odds + brackets), current-form tables — into a single self-contained dark-theme
page written to docs/index.html (GitHub Pages serves from /docs). Re-running rebuilds
it against the latest data, so the hourly workflow just calls build().
"""
from __future__ import annotations

import os

from . import calendar, engine, market, schedule, viz
from .simulator import seeded_slot_order, simulate

DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")

CSS = """
:root{
  --bg:#0e1320; --card:#161e31; --text:#e8ecf5; --muted:#93a0b8;
  --accent:#4cc38a; --accent2:#f5c542; --line:#26314f; --head:#1f2a44;
  /* aliases consumed by the embedded SVGs (viz.py uses --txt/--mut/--barbg/--bar2) */
  --txt:#e8ecf5; --mut:#93a0b8; --barbg:#1f2a44; --bar:#4cc38a; --bar2:#f5c542;
  --font:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
}
*{box-sizing:border-box} html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.55 var(--font)}
header.hero{background:linear-gradient(135deg,#14532d 0%,#1d4ed8 100%);padding:2.6rem 1rem 2.1rem;text-align:center}
header.hero h1{margin:0 0 .4rem;font-size:1.95rem;font-weight:800}
header.hero p{margin:.2rem auto;color:#dbeafe;font-size:.97rem;max-width:560px}
header.hero .meta{color:#cdd7ea;font-size:.85rem;margin-top:.7rem;display:flex;gap:1.1rem;justify-content:center;flex-wrap:wrap}
header.hero .meta b{color:#fff;font-weight:600}
main{max-width:960px;margin:0 auto;padding:1rem}
section{padding:.4rem 0}
h2{margin-top:2.4rem;padding-bottom:.35rem;font-size:1.3rem;border-bottom:2px solid var(--line);color:var(--accent2)}
h3{margin:1.4rem 0 .4rem;font-size:1.05rem;color:var(--accent)}
p.sub{color:var(--muted);font-size:.95rem;margin:.3rem 0 1rem;max-width:700px}
svg{width:100%;height:auto;display:block;margin:.6rem 0;border-radius:8px}
.grid{display:grid;grid-template-columns:1fr;gap:.4rem}
table{border-collapse:collapse;width:100%;margin:.7rem 0 1.2rem;font-size:.9rem;background:var(--card);
  border-radius:8px;overflow:hidden}
thead th{background:var(--head);color:#cdd7ea;text-align:left;padding:.5rem .65rem;font-weight:600}
th.num,td.num{text-align:right;font-variant-numeric:tabular-nums}
td{padding:.45rem .65rem;border-top:1px solid var(--line);color:var(--text)}
td.rank{color:var(--muted);width:28px} td.num{color:var(--muted)} td.lead{font-weight:600}
tbody tr:nth-child(odd){background:rgba(255,255,255,.02)}
tbody tr:hover{background:rgba(76,195,138,.08)}
details{margin:.5rem 0} summary{color:var(--muted);cursor:pointer;font-size:.9rem;padding:.3rem 0}
.note{color:var(--text);font-size:.95rem;line-height:1.65} .note b{color:var(--accent)}
.pill{display:inline-block;background:var(--head);border:1px solid var(--line);border-radius:999px;
  padding:3px 11px;font-size:12px;color:#cdd7ea;margin:2px 4px 2px 0}
footer{margin:3rem 0 1rem;text-align:center;color:var(--muted);font-size:.8rem;padding:1.5rem 1rem 0;border-top:1px solid var(--line)}
a{color:#7cb8ff;text-decoration:none} a:hover{text-decoration:underline}
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
    return (f"<h3>{tour.upper()} — current {surface.lower()} form</h3>"
            f"<table><thead><tr><th></th><th>Player</th><th class='num'>Blended Elo</th>"
            f"<th class='num'>{surface} Elo</th></tr></thead><tbody>{''.join(trs)}</tbody></table>")


def _name_resolver(elo, tour):
    """Map any 'First Last' name to a rated player key (reusing the market name-bridge)."""
    idx: dict[str, str] = {}
    for k in elo.players:
        if k.startswith(tour + ":"):
            for cand in market.model_namekeys(k.split(":", 1)[1]):
                idx.setdefault(cand, k)
    def resolve(name: str):
        for c in market.model_namekeys(name):
            if c in idx:
                return idx[c]
        return None
    return resolve


def _fmt_when(iso: str) -> str:
    try:
        from datetime import datetime
        dt = datetime.strptime(iso, "%Y-%m-%dT%H:%MZ")
        return dt.strftime("%-d %b %H:%M") + "Z"
    except Exception:
        return (iso or "")[:10]


def _upcoming_section(engines: dict, surface: str, *, cap: int = 24) -> str:
    """Football-style 'upcoming matches' table with model win probabilities.

    Live fixtures come from ESPN; we price each one off current Elo on the inferred
    surface. Resilient: if the feed is down or nothing resolves, the section is omitted."""
    try:
        fixtures = schedule.all_fixtures()
    except Exception:
        return ""
    if not fixtures:
        return ""
    resolvers = {t: _name_resolver(e, t) for t, e in engines.items()}
    main, qual = [], []
    for f in fixtures:
        res = resolvers.get(f.tour)
        if res is None:
            continue
        ka, kb = res(f.player_a), res(f.player_b)
        if not ka or not kb:
            continue
        p = engines[f.tour].win_prob(ka, kb, surface)   # P(player_a beats player_b)
        rec = (f, p)
        (qual if "Qualif" in f.round else main).append(rec)
    picks = (main or qual)
    picks.sort(key=lambda r: r[0].date)        # soonest first
    picks = picks[:cap]
    if not picks:
        return ""

    rows = []
    for f, p in picks:
        fav_a = p >= 0.5
        a = (f"<b style='color:var(--accent)'>{f.player_a}</b>" if fav_a else f.player_a)
        b = (f"<b style='color:var(--accent)'>{f.player_b}</b>" if not fav_a else f.player_b)
        rows.append(
            f"<tr><td class='num' style='text-align:left;color:var(--muted)'>{_fmt_when(f.date)}</td>"
            f"<td style='color:var(--muted)'>{f.tournament} · {f.round}</td>"
            f"<td class='lead' style='text-align:right'>{a}</td>"
            f"<td class='num'>{p*100:.0f}%</td><td class='num' style='color:var(--muted)'>{(1-p)*100:.0f}%</td>"
            f"<td class='lead'>{b}</td><td>{_TOUR_BADGE[f.tour]}</td></tr>")
    note = "" if main else " <em>(qualifying — main draws not yet posted)</em>"
    return (f"<section id='upcoming'><h2>Upcoming matches — win probabilities</h2>"
            f"<p class='sub'>Live fixtures from ESPN, priced by the model on {surface.lower()} "
            f"(surface inferred from the calendar). Favourite in green. Showing the next {len(picks)} "
            f"matches with both players rated.{note}</p>"
            f"<table><thead><tr><th style='text-align:left'>When</th><th>Tournament · round</th>"
            f"<th class='num'>Player A</th><th class='num'>win</th><th class='num'>win</th>"
            f"<th>Player B</th><th>Tour</th></tr></thead><tbody>{''.join(rows)}</tbody></table></section>")


_TOUR_BADGE = {"atp": "<span class='pill' style='padding:1px 8px'>ATP</span>",
               "wta": "<span class='pill' style='padding:1px 8px'>WTA</span>"}


def build(draw_size: int = 32) -> str:
    """Build the full page HTML and write docs/index.html. Returns the HTML."""
    from scripts.scorecard import build as scorecard_build
    cards, raw = scorecard_build()
    scorecard = viz.scorecard_svg(cards, title="Skill vs the ranking & the market")

    slam = calendar.next_slam()                       # next/current Grand Slam — drives everything
    surf = slam.surface
    when = ("underway" if slam.status == "in_progress"
            else f"starts {slam.start.strftime('%-d %b %Y')}")

    proj_sections, rating_cards, asof = [], [], 0
    engines = {}
    for tour, bo, label in (("atp", 5, "ATP — Men's Singles"), ("wta", 3, "WTA — Women's Singles")):
        elo, df = engine.fit(tour)
        engines[tour] = elo
        asof = int(df["tourney_date"].max())
        active = (asof // 10000 - 1) * 10000 + (asof % 10000)
        field = [r.key for r in engine.current_table(elo, surf, tour=tour,
                                                      active_since=active, min_n=25, top=draw_size)]
        slots = seeded_slot_order(field, elo, surf)
        res = simulate(field, elo, surf, best_of=bo, n_sims=40000, slots=slots, bo5_sharpen=0.15)
        fav = ", ".join(f"{n} {w*100:.0f}%" for n, w, _, _ in res.champion_table(2))
        odds = viz.odds_svg(res, top=10, title=label,
                            subtitle=f"{surf} · Bo{bo} · {res.draw_size}-draw · {res.n_sims:,} sims")
        path = viz.path_svg(res, top=8, title=f"{label} — path to the final")
        # NB: no bracket tree — free feeds expose the matchups but not draw-slot
        # positions, so a real tree can't be rebuilt and a rating-seeded one would be
        # fabricated. Real matchups live in the Upcoming-matches section instead.
        proj_sections.append(
            f"<div><div>{odds}</div><div style='margin-top:14px'>{path}</div>"
            f"<p class='note' style='margin-top:8px'>Favourites: <b>{fav}</b></p></div>")
        rating_cards.append(_ratings_table(elo, tour, surf, asof))

    n_total = sum(raw[t]["validation"]["n_eval"] for t in raw)
    atp_v, wta_v = raw["atp"]["validation"], raw["wta"]["validation"]
    upcoming = _upcoming_section(engines, surf)

    proj = "".join(proj_sections)
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🎾 Tennis — ML Predictions (ATP & WTA)</title>
<meta name="description" content="Surface-weighted Elo predictions for ATP & WTA tennis: Grand Slam path-to-the-final projections and an honest market/CLV benchmark.">
<style>{CSS}</style></head>
<body>

<header class="hero">
  <h1>🎾 Tennis — ML Predictions</h1>
  <p>Surface-weighted Elo for ATP &amp; WTA — Grand Slam path-to-the-final projections and an honest market benchmark.</p>
  <div class="meta">
    <span>Data through <b>{_fmt_date(asof)}</b></span>
    <span>Next major <b>{slam.label}</b></span>
    <span><b>360k+</b> matches · both tours</span>
  </div>
</header>

<main>

<section id="scorecard">
  <h2>How good is it?</h2>
  <p class="sub">Two benchmarks, held out from training. Gold marks the winner of each row.</p>
  {scorecard}
  <p class="note">
  <b>Versus the ranking</b> — surface-weighted Elo beats the official ATP/WTA ranking on held-out
  matches (ATP {atp_v['elo']['log_loss']} vs {atp_v['ranking_logistic']['log_loss']} log-loss;
  WTA {wta_v['elo']['log_loss']} vs {wta_v['ranking_logistic']['log_loss']}).
  <b>Versus the market</b> — on main-tour events the de-vigged Pinnacle close is sharper, and a naive
  value strategy returns negative ROI and negative CLV. That's the honest result: a pure-ratings model
  with no serve, injury or matchup signal should not beat the closing line where the market is efficient.
  Edge is expected in lower tiers (Challenger/ITF) and early rounds — not tested by this main-tour odds source.</p>
</section>

<section id="slam">
  <h2>{slam.label} — title projection</h2>
  <p class="sub">Each player's title and round-by-round chances from a Monte Carlo simulation on
  {surf.lower()} (ATP best-of-5, WTA best-of-3) — {when}. This is a <b>strength-based</b> projection
  (balanced seeding by rating) — a "who's most likely to win" power ranking, not the actual draw:
  public feeds publish the matchups but not their bracket positions, so the real tree can't be
  rebuilt. The <b>actual matchups</b>, priced live, are in <a href="#upcoming">Upcoming matches</a>
  below. Rolls to the next Grand Slam automatically once each finishes.</p>
  <div class="grid">{proj}</div>
</section>

{upcoming}

<section id="form">
  <h2>Current {surf.lower()} form</h2>
  <p class="sub">Top of each tour by blended (overall + {surf.lower()}) Elo, active in the last 12 months.</p>
  {''.join(rating_cards)}
</section>

<section id="how">
  <h2>How to read this</h2>
  <p class="note">
  Every match in tour history is replayed in order, updating each player's <b>overall</b> and
  <b>per-surface</b> Elo. A dynamic K-factor lets newcomers move fast and veterans stay stable;
  an inactivity decay keeps ratings current through injuries and off-seasons. A match probability
  is the logistic of the blended rating gap. The projection Monte-Carlos the bracket to get each
  player's <b>path to the final</b>; the scorecard's market column joins bookmaker closing odds and
  measures closing-line value (CLV) — the honest measure, since single matches are high variance.</p>
  <div style="margin-top:14px">
    <span class="pill">surface-weighted Elo</span><span class="pill">inactivity decay</span>
    <span class="pill">Monte Carlo brackets</span><span class="pill">de-vigged market odds</span>
    <span class="pill">closing-line value</span><span class="pill">both tours, 1968–2026</span>
  </div>
</section>

</main>

<footer>
  <p>Built with surface-weighted Elo. Match data: <a href="https://github.com/LuckyLoser91/TennisCourtLog">TennisCourtLog</a>
  (a live mirror of Jeff Sackmann's format). Odds: <a href="http://www.tennis-data.co.uk">tennis-data.co.uk</a>.<br>
  Not affiliated with the ATP, WTA, or Wimbledon. For research, not betting advice.</p>
</footer>

</body></html>"""

    os.makedirs(DOCS, exist_ok=True)
    with open(os.path.join(DOCS, "index.html"), "w") as f:
        f.write(html)
    with open(os.path.join(DOCS, ".nojekyll"), "w") as f:
        f.write("")
    return html


if __name__ == "__main__":
    build()
    print(f"Wrote {os.path.join('docs', 'index.html')}")
