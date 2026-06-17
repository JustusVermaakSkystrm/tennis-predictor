"""
market.py — bookmaker odds, de-vigging, name-bridge, and the market/CLV benchmark.

Data: tennis-data.co.uk yearly workbooks (ATP + WTA) with Bet365 (soft), Pinnacle
(sharp), Max and Avg closing odds per match. This is where we find out whether the
model has *real* edge: a model can beat the ATP ranking yet still lose to the market.

Three things this module produces:
  * model vs market log-loss — is the model competitive with the closing line?
  * value backtest — bet model-identified value at a soft book, settle on the real
    result, report ROI by tour tier (edge should live in the lower tiers).
  * CLV — did the price we took beat the sharp (Pinnacle) close? CLV, not short-run
    W/L, is the honest success measure (single matches are high variance).

Name bridge: tennis-data uses "Lastname F."; the model uses "First Last". We reduce
both to a spaceless (surname+initial) key, generating multi-token surname candidates
on the model side to catch compound names (Bautista Agut, Auger-Aliassime, …).
~98%+ of matches join; the unmatched count is always reported (never silently dropped).
"""
from __future__ import annotations

import glob
import os
import re
import unicodedata

import numpy as np
import pandas as pd

ODDS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "odds")


# ---------------------------------------------------------------------------
# Name bridge
# ---------------------------------------------------------------------------
def _strip(s) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c))


def _norm(s) -> str:
    s = _strip(s).lower()
    s = re.sub(r"[.'\-]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def odds_namekey(name: str) -> str:
    """'Bautista Agut R.' -> 'bautistaagutr' (spaceless surname + initial)."""
    toks = _norm(name).split()
    if len(toks) < 2:
        return _norm(name).replace(" ", "")
    return "".join(toks[:-1]) + toks[-1][:1]


def model_namekeys(name: str) -> set[str]:
    """'Roberto Bautista Agut' -> {'agutr','bautistaagutr','bautistaagutr', ...}.
    Generates last-1..4-token surname candidates so compound names match."""
    toks = _norm(name).split()
    if len(toks) < 2:
        return {_norm(name).replace(" ", "")}
    init = toks[0][:1]
    return {"".join(toks[-j:]) + init for j in range(1, min(4, len(toks)) + 1)}


# ---------------------------------------------------------------------------
# Odds loading
# ---------------------------------------------------------------------------
_ODDS_COLS = {
    "B365W": "b365w", "B365L": "b365l", "PSW": "psw", "PSL": "psl",
    "MaxW": "maxw", "MaxL": "maxl", "AvgW": "avgw", "AvgL": "avgl",
}


def load_odds(tour: str, years: list[int] | None = None) -> pd.DataFrame:
    """Load tennis-data.co.uk odds for a tour into a normalised frame."""
    files = sorted(glob.glob(os.path.join(ODDS_DIR, f"{tour}_*.xlsx")))
    if years:
        files = [f for f in files if any(str(y) in os.path.basename(f) for y in years)]
    if not files:
        raise FileNotFoundError(f"No odds files for {tour} in {ODDS_DIR}")
    frames = []
    for f in files:
        d = pd.read_excel(f)
        frames.append(d)
    raw = pd.concat(frames, ignore_index=True)

    out = pd.DataFrame()
    dt = pd.to_datetime(raw["Date"], errors="coerce")
    out["date"] = (dt.dt.year * 10000 + dt.dt.month * 100 + dt.dt.day)
    out["wk"] = raw["Winner"].map(odds_namekey)
    out["lk"] = raw["Loser"].map(odds_namekey)
    out["surface"] = raw.get("Surface")
    out["series"] = raw.get("Series").astype("string") if "Series" in raw else pd.NA
    out["best_of"] = pd.to_numeric(raw.get("Best of"), errors="coerce")
    for src, dst in _ODDS_COLS.items():
        out[dst] = pd.to_numeric(raw.get(src), errors="coerce") if src in raw else np.nan
    out = out.dropna(subset=["date", "wk", "lk"])
    out["date"] = out["date"].astype("int64")
    return out


def devig(odds_w: float, odds_l: float) -> float | None:
    """Two-way proportional de-vig -> P(winner wins). None if odds missing."""
    if not (odds_w and odds_l) or np.isnan(odds_w) or np.isnan(odds_l) or odds_w <= 1 or odds_l <= 1:
        return None
    iw, il = 1.0 / odds_w, 1.0 / odds_l
    return iw / (iw + il)


def build_index(odds: pd.DataFrame) -> dict:
    """(wk, lk) -> list of row dicts, for nearest-date lookup against model matches."""
    idx: dict[tuple, list] = {}
    for r in odds.itertuples(index=False):
        idx.setdefault((r.wk, r.lk), []).append(r._asdict())
    return idx


def match_odds(idx: dict, win_keys: set[str], los_keys: set[str],
               tourney_date: int, window: tuple[int, int] = (-4, 24)):
    """Find the odds row for a model match: try winner/loser namekey candidate pairs,
    pick the temporally nearest within a window around the tournament date."""
    best, best_gap = None, 10 ** 9
    lo, hi = window
    for wk in win_keys:
        for lk in los_keys:
            for row in idx.get((wk, lk), ()):
                gap = _daygap(tourney_date, row["date"])
                if lo <= _signed_daygap(tourney_date, row["date"]) <= hi and gap < best_gap:
                    best, best_gap = row, gap
    return best


def _signed_daygap(d_ref: int, d: int) -> int:
    from datetime import date
    def _d(x):
        return date(x // 10000, (x // 100) % 100, max(1, x % 100))
    return (_d(d) - _d(d_ref)).days


def _daygap(d_ref: int, d: int) -> int:
    return abs(_signed_daygap(d_ref, d))
