"""
validate.py — does surface-weighted Elo beat the ATP/WTA ranking at prediction?

Walks every match in chronological order building Elo as it goes. For matches in a
held-out evaluation window it records the *pre-match* Elo probability (no leakage),
then compares Elo vs a rank-based logistic baseline on the SAME match set.

Ratings are built from ALL matches (incl. Challengers) so lower-ranked players are
rated; evaluation is restricted (by default) to main-tour matches with both ranks
known, so the baseline has something to work with and the comparison is apples-to-apples.

Usage:
    python -m scripts.validate                 # ATP, last 12 months eval
    python -m scripts.validate --tour wta
    python -m scripts.validate --eval-start 20250101 --main-only 0
"""
from __future__ import annotations

import argparse
import json

import numpy as np

from tennis import dataset, model
from tennis.ratings import EloConfig, EloEngine

MAIN_LEVELS = set(dataset.MAIN_TIERS)   # slam / masters / 500 / 250 / finals


def evaluate(tour: str = "atp", eval_start: int = 20250601,
             cfg: EloConfig | None = None, main_only: bool = True,
             min_matches: int = 5, verbose: bool = True) -> dict:
    df = dataset.load_tour(tour, include_challengers=True)
    elo = EloEngine(cfg)
    seen: dict[int, int] = {}   # prior-match counter per player

    # Single chronological pass: build Elo, capture pre-match prob + ranks for eval rows,
    # and collect train ranks for the baseline. df is already date-sorted.
    cols = df[["tourney_date", "tour", "surface", "best_of", "winner_key", "loser_key",
               "clean", "level_cat", "retirement", "walkover",
               "winner_rank", "loser_rank"]].itertuples(index=False, name=None)

    from tennis.dataset import Match  # local import to build Match per row
    eval_elo, eval_rw, eval_rl = [], [], []
    train_rw, train_rl = [], []

    for (d, tr, surf, bo, wkey, lkey, clean, lvl, ret, wo, wrank, lrank) in cols:
        d = int(d); wkey = str(wkey); lkey = str(lkey)
        surf = surf if isinstance(surf, str) else "Unknown"
        ranks_ok = not (np.isnan(wrank) or np.isnan(lrank))

        if d < eval_start:
            if clean and ranks_ok:
                train_rw.append(wrank); train_rl.append(lrank)
        else:
            level_ok = (not main_only) or (lvl in MAIN_LEVELS)
            warm_ok = seen.get(wkey, 0) >= min_matches and seen.get(lkey, 0) >= min_matches
            if clean and ranks_ok and level_ok and warm_ok and surf in dataset.SURFACES:
                eval_elo.append(elo.win_prob(wkey, lkey, surf))   # pre-update => no leakage
                eval_rw.append(wrank); eval_rl.append(lrank)

        seen[wkey] = seen.get(wkey, 0) + 1
        seen[lkey] = seen.get(lkey, 0) + 1
        elo.update(Match(d, tr, surf, int(bo), wkey, lkey, bool(clean), str(lvl),
                         bool(ret), bool(wo)))

    if not eval_elo:
        raise SystemExit("No eval matches — check --eval-start / data coverage.")

    elo_p = np.asarray(eval_elo, float)
    rw = np.asarray(eval_rw, float)
    rl = np.asarray(eval_rl, float)

    base = model.RankingBaseline().fit(np.asarray(train_rw, float), np.asarray(train_rl, float))
    base_p = base.prob(rw, rl)
    naive_acc = float(np.mean(rw < rl))   # "favourite (better rank) always wins"

    results = {
        "tour": tour,
        "eval_start": eval_start,
        "main_only": main_only,
        "min_matches": min_matches,
        "n_eval": int(len(elo_p)),
        "n_train_baseline": int(len(train_rw)),
        "beta_baseline": round(base.beta, 3),
        "elo": model.summarise("surface-elo", elo_p),
        "ranking_logistic": model.summarise("ranking-logistic", base_p),
        "ranking_pick_accuracy": round(naive_acc, 4),
    }
    if verbose:
        print(json.dumps(results, indent=2))
        print("\nElo calibration (mid-prob, mean-pred, empirical, n):")
        for r in model.calibration_table(elo_p):
            print("  ", r)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tour", default="atp")
    ap.add_argument("--eval-start", type=int, default=20250601)
    ap.add_argument("--main-only", type=int, default=1)
    ap.add_argument("--surface-weight", type=float, default=0.4)
    ap.add_argument("--k0", type=float, default=200.0)
    ap.add_argument("--decay", type=float, default=0.10)
    args = ap.parse_args()
    cfg = EloConfig(k0=args.k0, surface_weight=args.surface_weight, decay_per_year=args.decay)
    evaluate(args.tour, args.eval_start, cfg, main_only=bool(args.main_only))


if __name__ == "__main__":
    main()
