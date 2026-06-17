"""
dataset.py — load and normalise Sackmann match data for ATP + WTA.

Source resolution (per tour), highest priority first:
  1. data/sackmann/<tour>/   — a full local `git clone` of JeffSackmann/tennis_<tour>
                               (decades of history + serve stats). PREFERRED.
  2. data/fallback/          — partial mirror CSVs (ATP 2023-26) used until (1) lands.

Both layers are globbed for `*_matches_*.csv` in Sackmann's canonical schema, so the
loader transparently upgrades the moment the full clone is dropped in — no code change.

A "match row" is one completed match: winner_* vs loser_*, on a surface, on a date,
in a round, best-of N. We normalise it into a tour-tagged, time-sortable record.
"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PKG_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(PKG_DIR)
DATA = os.path.join(ROOT, "data")
SACKMANN = os.path.join(DATA, "sackmann")   # full local clones go here: sackmann/atp, sackmann/wta
FALLBACK = os.path.join(DATA, "fallback")   # partial mirror

TOURS = ("atp", "wta")
SURFACES = ("Hard", "Clay", "Grass", "Carpet")

# Columns we rely on downstream. Everything else is carried through but optional.
CORE_COLS = [
    "tourney_id", "tourney_name", "surface", "draw_size", "tourney_level",
    "tourney_date", "match_num", "round", "best_of", "score", "minutes",
    "winner_id", "winner_name", "winner_rank", "winner_rank_points",
    "loser_id", "loser_name", "loser_rank", "loser_rank_points",
]
# Serve-stat columns (present in recent years; used by the serve model in v2).
SERVE_COLS = [
    "w_ace", "w_df", "w_svpt", "w_1stIn", "w_1stWon", "w_2ndWon", "w_SvGms", "w_bpSaved", "w_bpFaced",
    "l_ace", "l_df", "l_svpt", "l_1stIn", "l_1stWon", "l_2ndWon", "l_SvGms", "l_bpSaved", "l_bpFaced",
]


# ---------------------------------------------------------------------------
# Source discovery
# ---------------------------------------------------------------------------
def _tour_files(tour: str, include_challengers: bool = True) -> tuple[list[str], str]:
    """Return (csv_paths, source_label) for a tour, preferring the full local clone."""
    assert tour in TOURS, tour
    clone_dir = os.path.join(SACKMANN, tour)
    clone = sorted(glob.glob(os.path.join(clone_dir, f"{tour}_matches_*.csv")))
    # Sackmann splits qual/chall + futures into separate files; the main tour files are
    # `<tour>_matches_YYYY.csv`. Keep main-tour + (optionally) qual_chall, skip doubles/futures noise.
    def _keep(p: str) -> bool:
        b = os.path.basename(p)
        if "doubles" in b:
            return False
        if not include_challengers and ("qual_chall" in b or "futures" in b):
            return False
        return True

    if clone:
        return [p for p in clone if _keep(p)], f"sackmann/{tour} (full clone)"

    fb = sorted(glob.glob(os.path.join(FALLBACK, f"{tour}_matches_*.csv")))
    fb = [p for p in fb if _keep(p)]
    return fb, f"fallback ({tour})"


def data_status() -> dict:
    """Human-facing snapshot of what data is available right now."""
    out = {}
    for tour in TOURS:
        files, label = _tour_files(tour)
        years = sorted({_year_from_name(os.path.basename(f)) for f in files} - {None})
        out[tour] = {
            "source": label,
            "n_files": len(files),
            "year_span": (years[0], years[-1]) if years else None,
        }
    return out


def _year_from_name(name: str):
    # e.g. atp_matches_2024.csv / atp_matches_qual_chall_2024.csv
    for tok in name.replace(".csv", "").split("_"):
        if tok.isdigit() and len(tok) == 4:
            return int(tok)
    return None


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def load_tour(tour: str, include_challengers: bool = True,
              min_year: int | None = None, max_year: int | None = None) -> pd.DataFrame:
    """Load all matches for one tour into a normalised DataFrame, time-sorted."""
    files, label = _tour_files(tour, include_challengers)
    if not files:
        raise FileNotFoundError(
            f"No match CSVs found for {tour!r}. Drop a clone in {os.path.join(SACKMANN, tour)} "
            f"or mirror CSVs in {FALLBACK}."
        )
    frames = []
    for f in files:
        yr = _year_from_name(os.path.basename(f))
        if min_year and yr and yr < min_year:
            continue
        if max_year and yr and yr > max_year:
            continue
        df = pd.read_csv(f, low_memory=False)
        df["src_file"] = os.path.basename(f)
        frames.append(df)
    if not frames:
        raise ValueError(f"No files in year range [{min_year}, {max_year}] for {tour}.")
    raw = pd.concat(frames, ignore_index=True)
    return _normalise(raw, tour)


# Canonical tour tiers. MAIN_TIERS (below) = main-tour singles, excluding
# Challengers / ITF / team events. Used for evaluation filtering and edge-targeting.
MAIN_TIERS = ("GS", "M1000", "T500", "T250", "FINALS")


def _level_category(v) -> str:
    """Map era-mixed tourney_level labels to a canonical tier.

    Old Sackmann letter codes (G/M/A/F/C/S/D, WTA P/PM/I/T1..) and modern verbose
    labels (Grand Slam / Masters 1000 / ATP500 / WTA1000 / …) both occur in the data.
    """
    if v is None or (isinstance(v, float)):
        return "OTHER"
    s = str(v).strip()
    sl = s.lower()
    if "grand slam" in sl or s == "G":
        return "GS"
    if "finals" in sl or "masters cup" in sl or s == "F":
        return "FINALS"
    if "masters 1000" in sl or "wta1000" in sl or s in ("M", "PM", "P"):
        return "M1000"
    if "500" in sl or s == "A":          # 'A' = older lumped ATP main-tour code
        return "T500"
    if "250" in sl or s in ("B", "I"):
        return "T250"
    if "challenger" in sl or s == "C":
        return "CH"
    if "itf" in sl or "futures" in sl or "satellite" in sl or s in ("S", "15", "25"):
        return "ITF"
    if "davis" in sl or "fed cup" in sl or "billie jean" in sl or s == "D":
        return "TEAM"
    if s.startswith("T") and s[1:].isdigit():   # old WTA tiers T1..T5
        return "T250"
    return "OTHER"


def _player_key(df: pd.DataFrame, who: str, tour: str) -> pd.Series:
    """Tour-prefixed player key: numeric id if available, else cleaned name."""
    id_col, name_col = f"{who}_id", f"{who}_name"
    name = df.get(name_col)
    name = (name.astype("string").str.strip().str.replace(r"\s+", " ", regex=True)
            if name is not None else pd.Series(pd.NA, index=df.index, dtype="string"))
    if id_col in df.columns:
        ids = pd.to_numeric(df[id_col], errors="coerce")
        key = ids.map(lambda v: f"{tour}:{int(v)}" if pd.notna(v) else pd.NA).astype("string")
        key = key.fillna(tour + ":" + name)   # fall back to name where id missing
    else:
        key = tour + ":" + name
    key = key.where(name.notna() | key.notna(), pd.NA)
    # blank names -> NA so they get dropped
    return key.where(~key.isin([f"{tour}:", f"{tour}:<NA>"]), pd.NA)


def _normalise(df: pd.DataFrame, tour: str) -> pd.DataFrame:
    df = df.copy()
    df["tour"] = tour

    # Date: the data mixes THREE formats across eras/files —
    #   "19900101" (canonical Sackmann YYYYMMDD int),
    #   "2024-12-29" (ISO, zero-padded),
    #   "2026/1/4"  (slashes, UNpadded).
    # Parse 8-digit ints with an explicit format; let pandas infer the separated forms.
    raw = df.get("tourney_date").astype("string").str.strip()
    is8 = raw.str.fullmatch(r"\d{8}").fillna(False)
    date = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    date.loc[is8] = pd.to_datetime(raw[is8], format="%Y%m%d", errors="coerce")
    sep = ~is8 & raw.notna()
    date.loc[sep] = pd.to_datetime(raw[sep].str.replace("/", "-", regex=False),
                                   errors="coerce")
    df["date"] = date
    df = df.dropna(subset=["date"])
    df["tourney_date"] = (df["date"].dt.year * 10000
                          + df["date"].dt.month * 100 + df["date"].dt.day).astype("int64")

    # Surface: normalise capitalisation; fill blanks as "Unknown" (some Challengers omit it).
    df["surface"] = df.get("surface").astype("string").str.strip().str.title()
    df.loc[~df["surface"].isin(SURFACES), "surface"] = pd.NA

    # best_of: men's slams are 5, almost everything else 3. Default 3 when missing.
    df["best_of"] = pd.to_numeric(df.get("best_of"), errors="coerce").fillna(3).astype(int)

    # Player key for Elo: prefer the stable numeric id (full Sackmann schema), fall
    # back to the player NAME (reduced TennisCourtLog schema has no ids). Keys are
    # tour-prefixed to avoid cross-tour collisions when tours are concatenated.
    df["winner_key"] = _player_key(df, "winner", tour)
    df["loser_key"] = _player_key(df, "loser", tour)
    df = df.dropna(subset=["winner_key", "loser_key"])

    # Carry ids through when present (serve-model sources need them); else NaN.
    for col in ("winner_id", "loser_id"):
        df[col] = pd.to_numeric(df.get(col), errors="coerce") if col in df.columns else pd.NA

    # Ranks (for the baseline model). Missing -> NaN (unranked).
    for col in ("winner_rank", "loser_rank", "winner_rank_points", "loser_rank_points"):
        df[col] = pd.to_numeric(df.get(col), errors="coerce")

    # Level category: unify era-mixed labels (old Sackmann letter codes + modern
    # verbose labels) into a canonical tier used for filtering/weighting.
    df["level_cat"] = df.get("tourney_level").map(_level_category).astype("string")

    # Result-validation flags off the score string (retirements / walkovers).
    score = df.get("score").astype("string").fillna("")
    df["retirement"] = score.str.contains("RET", case=False, na=False)
    df["walkover"] = score.str.contains("W/O|WO|Walkover", case=False, regex=True, na=False)
    df["def_default"] = score.str.contains("DEF", case=False, na=False)
    # A "clean" completed match = a real on-court result with a normal score.
    df["clean"] = ~(df["retirement"] | df["walkover"] | df["def_default"])

    keep = [c for c in (CORE_COLS + SERVE_COLS) if c in df.columns]
    extra = ["tour", "date", "winner_key", "loser_key", "level_cat",
             "retirement", "walkover", "def_default", "clean", "src_file"]
    df = df[list(dict.fromkeys(keep + extra))]

    # Stable chronological order; within a day, use match_num to keep round order roughly intact.
    sort_cols = ["tourney_date"] + (["match_num"] if "match_num" in df.columns else [])
    df = df.sort_values(sort_cols, kind="stable").reset_index(drop=True)
    return df


def load_all(include_challengers: bool = True, **kw) -> pd.DataFrame:
    """Both tours concatenated and time-sorted. Tour stays a column."""
    frames = []
    for tour in TOURS:
        try:
            frames.append(load_tour(tour, include_challengers=include_challengers, **kw))
        except FileNotFoundError:
            continue
    if not frames:
        raise FileNotFoundError("No data for any tour.")
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values("tourney_date", kind="stable").reset_index(drop=True)


@dataclass
class Match:
    """Lightweight view of one row for the rating loop. `winner`/`loser` are player
    keys (tour-prefixed id or name) — see dataset._player_key."""
    date: int
    tour: str
    surface: str
    best_of: int
    winner: str
    loser: str
    clean: bool
    level: str
    retirement: bool = False
    walkover: bool = False


def iter_matches(df: pd.DataFrame):
    """Yield Match tuples in chronological order — the rating engine consumes these."""
    cols = df[["tourney_date", "tour", "surface", "best_of", "winner_key", "loser_key",
               "clean", "tourney_level", "retirement", "walkover"]].itertuples(index=False, name=None)
    for d, tour, surf, bo, w, l, clean, lvl, ret, wo in cols:
        yield Match(int(d), tour, surf if isinstance(surf, str) else "Unknown",
                    int(bo), str(w), str(l), bool(clean), str(lvl),
                    bool(ret), bool(wo))


if __name__ == "__main__":
    import json
    print("Data status:")
    print(json.dumps(data_status(), indent=2, default=str))
    for tour in TOURS:
        try:
            d = load_tour(tour)
            print(f"\n{tour.upper()}: {len(d):,} matches  "
                  f"{d['date'].min().date()} -> {d['date'].max().date()}  "
                  f"surfaces={d['surface'].value_counts(dropna=False).to_dict()}")
        except FileNotFoundError as e:
            print(f"\n{tour.upper()}: {e}")
