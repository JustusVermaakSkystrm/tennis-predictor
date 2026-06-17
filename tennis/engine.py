"""
engine.py — fit Elo over all history and expose current ratings.

Thin orchestration layer over dataset + ratings: run the chronological rating loop
once, then query "where does everyone stand right now" — the inputs the draw
simulator and the site need. Also the first end-to-end sanity check: the top of the
current grass table should look like the players you'd actually back at Wimbledon.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import dataset
from .ratings import EloConfig, EloEngine


@dataclass
class RatingRow:
    key: str
    name: str
    tour: str
    overall: float
    surface: float
    blended: float
    n: int
    last_date: int


def fit(tour: str | None = None, cfg: EloConfig | None = None,
        include_challengers: bool = True, max_date: int | None = None) -> tuple[EloEngine, pd.DataFrame]:
    """Build an EloEngine over a tour's full history (or both tours if tour=None).

    max_date (YYYYMMDD) optionally truncates so you can rate "as of" a past date —
    used by the market benchmark to avoid look-ahead.
    """
    df = (dataset.load_tour(tour, include_challengers=include_challengers)
          if tour else dataset.load_all(include_challengers=include_challengers))
    if max_date is not None:
        df = df[df["tourney_date"] <= max_date]
    elo = EloEngine(cfg)
    for m in dataset.iter_matches(df):
        elo.update(m)
    return elo, df


def _name_of(key: str) -> str:
    return key.split(":", 1)[1] if ":" in key else key


def _tour_of(key: str) -> str:
    return key.split(":", 1)[0] if ":" in key else "?"


def current_table(elo: EloEngine, surface: str, *, tour: str | None = None,
                  active_since: int | None = None, min_n: int = 10,
                  top: int | None = None) -> list[RatingRow]:
    """Players ranked by current blended rating on `surface`.

    active_since (YYYYMMDD) keeps only players who have played since then — so the
    table reflects the live tour, not retired greats whose ratings are frozen high.
    """
    rows: list[RatingRow] = []
    for key, st in elo.players.items():
        if tour and _tour_of(key) != tour:
            continue
        if st.n < min_n:
            continue
        if active_since is not None and (st.last_date is None or st.last_date < active_since):
            continue
        rows.append(RatingRow(
            key=key, name=_name_of(key), tour=_tour_of(key),
            overall=round(st.overall, 1),
            surface=round(elo.surface_rating(key, surface), 1),
            blended=round(elo.blended(key, surface), 1),
            n=st.n, last_date=st.last_date or 0,
        ))
    rows.sort(key=lambda r: r.blended, reverse=True)
    return rows[:top] if top else rows


if __name__ == "__main__":
    # Sanity: who tops the current grass table on each tour?
    for tour in ("atp", "wta"):
        elo, df = fit(tour)
        asof = int(df["tourney_date"].max())
        active = (asof // 10000 - 1) * 10000 + (asof % 10000)  # ~12 months back
        print(f"\n=== {tour.upper()} — current GRASS top 12 (as of {asof}) ===")
        for i, r in enumerate(current_table(elo, "Grass", tour=tour, active_since=active, top=12), 1):
            print(f"{i:>2}. {r.name:<24} blend={r.blended:>6}  (overall={r.overall}, grass={r.surface}, n={r.n})")
