"""
model.py — match-level prediction + evaluation metrics + ranking baseline.

The Elo win probability lives in ratings.EloEngine.win_prob. This module adds:
  * the metrics (log-loss, Brier, accuracy, calibration) used to judge any model,
  * a fair ATP/WTA *ranking* baseline to beat (a 1-parameter logistic on the
    log-rank gap, fitted on the train period only).

Evaluation convention: every stored row is (winner beat loser), so the label is
always 1. A model that ignores the winner/loser tag and scores purely from player
identity (Elo) or rank (baseline) is therefore evaluated honestly — it never sees
the outcome it is predicting.
"""
from __future__ import annotations

import math

import numpy as np


# ---------------------------------------------------------------------------
# Metrics  (p = model's P(winner wins); label is implicitly 1)
# ---------------------------------------------------------------------------
def log_loss(p: np.ndarray, eps: float = 1e-15) -> float:
    p = np.clip(np.asarray(p, float), eps, 1 - eps)
    return float(-np.mean(np.log(p)))


def brier(p: np.ndarray) -> float:
    p = np.asarray(p, float)
    return float(np.mean((1.0 - p) ** 2))


def accuracy(p: np.ndarray) -> float:
    p = np.asarray(p, float)
    # ties (p==0.5) count as half-credit
    return float(np.mean(np.where(p > 0.5, 1.0, np.where(p == 0.5, 0.5, 0.0))))


def calibration_table(p: np.ndarray, bins: int = 10) -> list[tuple]:
    """Reliability: for predicted-prob bins, the empirical winner-win rate.

    We symmetrise: each match contributes (p, 1) for the winner and (1-p, 0) for
    the loser, so bins around 0.5 are populated and the curve is interpretable.
    """
    p = np.asarray(p, float)
    pp = np.concatenate([p, 1 - p])
    yy = np.concatenate([np.ones_like(p), np.zeros_like(p)])
    edges = np.linspace(0, 1, bins + 1)
    rows = []
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        m = (pp >= lo) & (pp < hi if i < bins - 1 else pp <= hi)
        if m.sum() == 0:
            continue
        rows.append((round((lo + hi) / 2, 3), round(float(pp[m].mean()), 4),
                     round(float(yy[m].mean()), 4), int(m.sum())))
    return rows


# ---------------------------------------------------------------------------
# Ranking baseline
# ---------------------------------------------------------------------------
class RankingBaseline:
    """1-parameter logistic on the log-rank gap: p = sigmoid(beta * (logRank_l - logRank_w)).

    Lower rank number = stronger, so (logRank_loser - logRank_winner) > 0 when the
    favourite won. beta is fit by 1-D search to minimise train log-loss.
    """

    def __init__(self, beta: float = 1.0):
        self.beta = beta

    @staticmethod
    def _feature(rank_w: np.ndarray, rank_l: np.ndarray) -> np.ndarray:
        # guard: rank>=1; unranked handled by caller (rows dropped)
        return np.log(rank_l) - np.log(rank_w)

    def fit(self, rank_w: np.ndarray, rank_l: np.ndarray) -> "RankingBaseline":
        x = self._feature(np.asarray(rank_w, float), np.asarray(rank_l, float))
        best_beta, best_ll = 1.0, math.inf
        for beta in np.linspace(0.1, 4.0, 79):
            p = 1.0 / (1.0 + np.exp(-beta * x))
            ll = log_loss(p)
            if ll < best_ll:
                best_ll, best_beta = ll, beta
        self.beta = float(best_beta)
        return self

    def prob(self, rank_w: np.ndarray, rank_l: np.ndarray) -> np.ndarray:
        x = self._feature(np.asarray(rank_w, float), np.asarray(rank_l, float))
        return 1.0 / (1.0 + np.exp(-self.beta * x))


def summarise(name: str, p: np.ndarray) -> dict:
    return {
        "model": name,
        "n": int(len(p)),
        "log_loss": round(log_loss(p), 4),
        "brier": round(brier(p), 4),
        "accuracy": round(accuracy(p), 4),
    }
