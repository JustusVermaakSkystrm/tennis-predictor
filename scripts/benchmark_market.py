"""
benchmark_market.py — model vs the betting market (log-loss, value ROI, CLV).

Builds Elo chronologically over full history, joins tennis-data.co.uk closing odds to
each main-tour match, and reports:
  1. model vs market (de-vigged Pinnacle) log-loss + accuracy — is the model sharp?
  2. a value backtest — flat-stake every +EV side at Bet365, settled on the real
     result; ROI overall and by tour tier (edge should concentrate in lower tiers).
  3. CLV — average % by which the taken (Bet365) price beat the Pinnacle close.

Usage:
  python -m scripts.benchmark_market --tour atp --eval-start 20190101 --edge 0.05
"""
from __future__ import annotations

import argparse

import numpy as np

from tennis import dataset, market, model
from tennis.dataset import Match
from tennis.ratings import EloConfig, EloEngine


def run(tour: str = "atp", eval_start: int = 20190101, edge: float = 0.05,
        min_matches: int = 5, exec_book: str = "b365", verbose: bool = True) -> dict:
    df = dataset.load_tour(tour, include_challengers=True)
    odds = market.load_odds(tour)
    idx = market.build_index(odds)

    elo = EloEngine(EloConfig())
    seen: dict[str, int] = {}

    # accumulators
    m_p, mk_p = [], []            # model / market P(winner) for matched matches
    n_model_only = 0             # matched-by-name? we only score matched matches
    bets = []                    # (profit, stake, clv, series, side_is_winner)
    n_eval = n_matched = 0

    cols = df[["tourney_date", "tour", "surface", "best_of", "winner_key", "loser_key",
               "clean", "level_cat", "retirement", "walkover"]].itertuples(index=False, name=None)

    for (d, tr, surf, bo, wkey, lkey, clean, lvl, ret, wo) in cols:
        d = int(d); wkey = str(wkey); lkey = str(lkey)
        surf = surf if isinstance(surf, str) else "Unknown"
        warm = seen.get(wkey, 0) >= min_matches and seen.get(lkey, 0) >= min_matches
        in_eval = d >= eval_start and clean and warm and lvl in dataset.MAIN_TIERS

        if in_eval:
            n_eval += 1
            pw = elo.win_prob(wkey, lkey, surf)   # pre-update => no leakage
            row = market.match_odds(idx,
                                    market.model_namekeys(wkey.split(":", 1)[1]),
                                    market.model_namekeys(lkey.split(":", 1)[1]), d)
            if row is not None:
                mkt = market.devig(row.get("psw"), row.get("psl"))
                if mkt is not None:
                    n_matched += 1
                    m_p.append(pw); mk_p.append(mkt)
                    _consider_bets(bets, pw, row, edge, exec_book)

        seen[wkey] = seen.get(wkey, 0) + 1
        seen[lkey] = seen.get(lkey, 0) + 1
        elo.update(Match(d, tr, surf, int(bo), wkey, lkey, bool(clean), str(lvl), bool(ret), bool(wo)))

    res = _summarise(tour, eval_start, edge, n_eval, n_matched, m_p, mk_p, bets)
    if verbose:
        _print(res, bets)
    return res


def _consider_bets(bets, pw, row, edge, exec_book):
    """Place a flat 1u bet on each side whose model EV exceeds `edge`."""
    ow = row.get(f"{exec_book}w"); ol = row.get(f"{exec_book}l")
    psw, psl = row.get("psw"), row.get("psl")
    series = row.get("series")
    # winner side (it won -> profit = odds-1)
    if ow and ow > 1 and not np.isnan(ow):
        ev = pw * ow - 1.0
        if ev > edge:
            clv = (ow / psw - 1.0) if (psw and psw > 1) else np.nan
            bets.append((ow - 1.0, 1.0, clv, series, True))
    # loser side (it lost -> profit = -1)
    if ol and ol > 1 and not np.isnan(ol):
        ev = (1 - pw) * ol - 1.0
        if ev > edge:
            clv = (ol / psl - 1.0) if (psl and psl > 1) else np.nan
            bets.append((-1.0, 1.0, clv, series, False))


def _summarise(tour, eval_start, edge, n_eval, n_matched, m_p, mk_p, bets):
    m_p, mk_p = np.asarray(m_p, float), np.asarray(mk_p, float)
    out = {
        "tour": tour, "eval_start": eval_start, "edge": edge,
        "n_eval": n_eval, "n_matched": n_matched,
        "match_rate": round(n_matched / n_eval, 3) if n_eval else 0,
        "model_logloss": round(model.log_loss(m_p), 4) if len(m_p) else None,
        "market_logloss": round(model.log_loss(mk_p), 4) if len(mk_p) else None,
        "model_acc": round(float(np.mean(m_p > 0.5)), 4) if len(m_p) else None,
        "market_acc": round(float(np.mean(mk_p > 0.5)), 4) if len(mk_p) else None,
    }
    if bets:
        profit = sum(b[0] for b in bets); stake = sum(b[1] for b in bets)
        clvs = np.array([b[2] for b in bets if not np.isnan(b[2])])
        out["bets"] = {
            "n": len(bets),
            "roi": round(profit / stake, 4),
            "profit_units": round(profit, 2),
            "avg_clv": round(float(clvs.mean()), 4) if len(clvs) else None,
            "pct_positive_clv": round(float(np.mean(clvs > 0)), 4) if len(clvs) else None,
        }
    else:
        out["bets"] = {"n": 0}
    return out


def _print(res, bets):
    import json
    print(json.dumps({k: v for k, v in res.items() if k != "_bets"}, indent=2))
    # ROI by tier
    from collections import defaultdict
    agg = defaultdict(lambda: [0.0, 0.0])
    for profit, stake, clv, series, _ in bets:
        key = str(series) if series is not None else "?"
        agg[key][0] += profit; agg[key][1] += stake
    if bets:
        print("\nROI by tier:")
        for k, (p, s) in sorted(agg.items(), key=lambda kv: -kv[1][1]):
            print(f"  {k:<16} n_units={s:>5.0f}  roi={p/s*100:>6.1f}%  profit={p:>7.1f}u")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tour", default="atp")
    ap.add_argument("--eval-start", type=int, default=20190101)
    ap.add_argument("--edge", type=float, default=0.05)
    ap.add_argument("--book", default="b365", choices=["b365", "max", "avg"])
    args = ap.parse_args()
    run(args.tour, args.eval_start, args.edge, exec_book=args.book)


if __name__ == "__main__":
    main()
