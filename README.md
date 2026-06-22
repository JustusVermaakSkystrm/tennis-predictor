# tennis-predictor

**Live site → https://justusvermaakskystrm.github.io/tennis-predictor/**

Prediction engine for professional tennis (ATP + WTA), ported in spirit from the
football World Cup predictor: **ratings → match model → (draw simulation) →
probabilities → market comparison**, headed for an auto-updating public site with a
model scorecard and a market/CLV benchmark.

Tennis draws are single-elimination brackets, so the per-event product is a
"path to the final" projection; the ongoing product is daily match predictions and
value vs the market.

## Status (this session)

**Core is built and validated on both tours, full history (1968–2026).**
Surface-weighted Elo beats the official ATP/WTA ranking at prediction on a held-out
window (2025-06 → 2026-06, main-tour, both ranks known):

| Tour | Model | Log-loss ↓ | Brier ↓ | Accuracy ↑ | n |
|---|---|---|---|---|---|
| **ATP** | **Surface-Elo** | **0.6218** | **0.217** | **64.9%** | 2447 |
| ATP | Ranking baseline | 0.6247 | 0.218 | 64.3% | |
| **WTA** | **Surface-Elo** | **0.6216** | **0.217** | **64.8%** | 2298 |
| WTA | Ranking baseline | 0.6447 | 0.226 | 61.6% | |

Calibration is near-perfect across all probability bins. Elo's edge is larger on WTA
(rankings track strength less well there) — consistent with the brief.

**Key finding — inactivity decay is essential with deep history.** Without it, stale
career ratings over-anchor players and Elo *loses* to the ATP ranking; a modest
`decay_per_year=0.10` (regress toward the mean during idle gaps) restores recency and
Elo wins on both tours. Tuned defaults: `k0=200, surface_weight=0.4, decay=0.10`.

### Draw projection (per-event product)

Monte Carlo bracket simulation → each player's path-to-the-final probabilities.
Sanity: the current grass leaders are exactly who you'd expect (ATP Alcaraz/Sinner/
Djokovic; WTA Sabalenka/Swiatek/Rybakina, with past Wimbledon champs correctly lifted
on grass). `python -m scripts.project_draw` writes `out/wimbledon2026.html`.

### Market / CLV benchmark (the honest test)

`python -m scripts.benchmark_market` joins tennis-data.co.uk closing odds (Bet365 +
Pinnacle) to ~15k matches/tour and reports model vs market log-loss, value ROI, and CLV.

| | ATP | WTA |
|---|---|---|
| Model log-loss | 0.625 | 0.623 |
| **Market** (de-vigged Pinnacle) log-loss | **0.591** | **0.593** |
| Flat value ROI (edge 5%) | −12.6% | −13.4% |
| Avg CLV vs close | −2.9% | −3.7% |

**The model does *not* beat the efficient main-tour market** — negative CLV confirms its
disagreements with the sharp line are mostly model error, not inefficiency. This is the
expected, honest result: a pure Elo with no serve/injury/matchup signal *should* lose to
the close on big matches. Per the brief, exploitable edge is expected in **lower tiers
(Challenger/ITF) and early rounds** — which this main-tour-only odds source can't test.
CLV, not short-run W/L, is the success measure. `scripts/scorecard.py` renders the full
card to `out/scorecard.{html,svg}`.

## Layout

```
tennis/
  dataset.py    # load + normalise Sackmann match CSVs; auto-detects local clones
  ratings.py    # surface-weighted Elo engine (overall + per-surface, dynamic K, decay)
  model.py      # metrics (log-loss/Brier/accuracy/calibration) + ranking baseline
scripts/
  validate.py   # held-out Elo-vs-ranking evaluation
data/
  sackmann/     # DROP FULL CLONES HERE: sackmann/atp, sackmann/wta  (preferred source)
  fallback/     # partial ATP mirror CSVs 2023–26 (used until clones land)
```

## Data

> **Jeff Sackmann's `tennis_atp` / `tennis_wta` repos have been deleted/privatized**
> (his account now exposes only `tennis_MatchChartingProject`). The classic clone
> URLs 404 everywhere, not just here.

**Primary feed: [`LuckyLoser91/TennisCourtLog`](https://github.com/LuckyLoser91/TennisCourtLog)**
— a live mirror of both Sackmann repos, **both tours, 1968–2026, refreshed daily**.
Pull it with:

```bash
./scripts/fetch_data.sh          # -> data/sackmann/{atp,wta}/*.csv  (idempotent; re-run to refresh)
```

This mirror uses a **reduced schema**: player *names* (no numeric ids), and **no
serve stats** (no aces/serve-points). That's sufficient for Elo (the loader keys on
a tour-prefixed id-or-name). Watch out for its quirks, handled in `dataset.py`:
- three date formats coexist (`19900101`, `2024-12-29`, `2026/1/4`)
- era-mixed `tourney_level` labels (old `A`/`G` codes vs modern `ATP250`/`Masters 1000`)

**Live fixtures** for the upcoming-matches section come from ESPN's free tennis
scoreboard API (`tennis/schedule.py`) — the forward schedule the results archive
doesn't carry. Each known matchup is priced off current Elo on the season's surface.

For the **serve model (v2)** we'll overlay richer sources that retain serve stats +
ids: `Tennismylife/TML-Database` (ATP, 1968–2026, + `indoor` flag) and
`AndreaQuirozO/WTA_Players` (WTA Sackmann clone, 1920–2023).

`data/fallback/` holds the original ATP-only 2023–26 mirror; it's only used if
`data/sackmann/` is empty.

## Run

```bash
python -m tennis.dataset                 # show data status + coverage
python -m scripts.validate --tour atp    # Elo vs ranking, last 12 months
python -m scripts.benchmark_market --tour atp   # model vs market + CLV
python -m scripts.project_draw           # Wimbledon 2026 bracket -> out/
python -m scripts.build_site             # regenerate the live site -> docs/index.html
```

## Live site & auto-update

The site (`tennis/site.py` → `docs/index.html`) is served via GitHub Pages and rebuilt
by `.github/workflows/update.yml` every 6 hours: fetch data + odds → `build_site` →
commit `docs/` only if it changed → push (Pages redeploys). Trigger manually with
`gh workflow run update-site`.

**The featured event rolls automatically.** `tennis/calendar.py` knows the four Grand
Slams; the site always projects the next/current one *on its surface*. When Wimbledon
(grass) finishes, the projection and form tables switch themselves to **US Open** (hard),
then Australian Open, then Roland Garros (clay) — no manual edits. The favourite even
flips correctly by surface (Alcaraz on grass → Sinner on hard).

## Roadmap

- [x] Surface-weighted Elo + held-out validation vs ranking baseline (both tours)
- [x] Draw (bracket) simulator + SVG `viz.py` (32/64/128) + auto-rolling Slam projection
- [x] tennis-data.co.uk odds → market / CLV benchmark + model scorecard
- [x] GitHub Pages site + scheduled auto-update workflow
- [x] Live upcoming-matches feed (ESPN) with per-match model win probabilities
- [ ] Serve-based hierarchical model (point→game→set→match Markov) for set/game/handicap markets; Bo3 vs Bo5 — needs serve-stat sources (TML-Database / AndreaQuirozO)
- [ ] Ingest the *official* draw when published (replace seed-by-rating with real slots)
- [ ] Lower-tier (Challenger/ITF) odds to test the real edge thesis
- [ ] Rating-uncertainty shrinkage (fix low-n spikes e.g. Jodar) + retirement/walkover ledger
