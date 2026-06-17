"""
ratings.py — surface-weighted Elo for tennis.

This is the core of the engine (the tennis analogue of the football attack/defence
ratings). Two ratings per player evolve match-by-match in chronological order:

  * overall Elo            — strength across all surfaces
  * surface Elo            — one per {Hard, Clay, Grass, Carpet}

Design choices (grounded in the FiveThirtyEight / Sackmann tennis-Elo tradition):

  * Dynamic K-factor:  K = K0 / (n + offset)^shape, where n is the player's match
    count. Newcomers move fast; veterans are stable. (538 uses 250/(n+5)^0.4.)
  * Surface seeding:   a player's first match on a surface seeds that surface rating
    from their *current overall* rating, not a flat 1500 — so a top player isn't
    treated as average the first time we see them on grass.
  * Inactivity decay:  ratings regress slightly toward the mean after long layoffs
    (off-season, injury) so stale numbers don't dominate.
  * Result hygiene:    walkovers (no play) never update ratings; retirements do (a
    real, if noisy, on-court result) but can be down-weighted.

Prediction blends overall + surface Elo (default 50/50) into a single rating gap,
then maps the gap through the logistic to a win probability.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .dataset import Match, SURFACES

BASE = 1500.0          # newcomer / mean rating
SCALE = 400.0          # logistic scale (standard Elo)


def expected_score(r_a: float, r_b: float) -> float:
    """P(A beats B) from an Elo gap."""
    return 1.0 / (1.0 + 10.0 ** ((r_b - r_a) / SCALE))


@dataclass
class EloConfig:
    # Defaults tuned on 1968–2026 ATP+WTA, held-out 2025-06→2026-06 (see scripts/validate.py).
    # With deep history, inactivity decay is essential: without it stale career ratings
    # over-anchor players and Elo loses to the ranking on ATP; with modest decay Elo wins
    # on both tours.
    k0: float = 200.0          # K-factor numerator
    k_offset: float = 5.0      # K-factor denominator offset
    k_shape: float = 0.4       # K-factor exponent
    surface_weight: float = 0.4  # blend: blended = (1-w)*overall + w*surface
    decay_per_year: float = 0.10  # fraction regressed toward BASE per idle year (recency)
    ret_weight: float = 1.0    # update weight for retirements (1 = full, 0 = ignore)
    seed_surface_from_overall: bool = True


@dataclass
class PlayerState:
    overall: float = BASE
    n: int = 0
    surf: dict = field(default_factory=dict)   # surface -> rating
    surf_n: dict = field(default_factory=dict)  # surface -> match count
    last_date: int | None = None


class EloEngine:
    """Stateful, chronological Elo. Feed matches in date order via `update`."""

    def __init__(self, cfg: EloConfig | None = None):
        self.cfg = cfg or EloConfig()
        self.players: dict[str, PlayerState] = {}

    # -- access -----------------------------------------------------------
    def _state(self, pid: str) -> PlayerState:
        st = self.players.get(pid)
        if st is None:
            st = PlayerState()
            self.players[pid] = st
        return st

    def _k(self, n: int) -> float:
        c = self.cfg
        return c.k0 / ((n + c.k_offset) ** c.k_shape)

    def _apply_decay(self, st: PlayerState, date: int):
        """Regress toward BASE proportional to idle time before a new match."""
        if self.cfg.decay_per_year <= 0 or st.last_date is None:
            return
        days = _days_between(st.last_date, date)
        if days <= 0:
            return
        frac = min(1.0, self.cfg.decay_per_year * (days / 365.25))
        if frac <= 0:
            return
        st.overall += (BASE - st.overall) * frac
        for s in list(st.surf):
            st.surf[s] += (BASE - st.surf[s]) * frac

    def surface_rating(self, pid: str, surface: str) -> float:
        """Surface rating, lazily seeded from overall the first time we ask."""
        st = self._state(pid)
        if surface not in SURFACES:
            return st.overall  # unknown surface -> fall back to overall
        if surface not in st.surf:
            st.surf[surface] = st.overall if self.cfg.seed_surface_from_overall else BASE
            st.surf_n[surface] = 0
        return st.surf[surface]

    def blended(self, pid: str, surface: str) -> float:
        st = self._state(pid)
        w = self.cfg.surface_weight
        if surface not in SURFACES:
            return st.overall
        s = self.surface_rating(pid, surface)
        return (1 - w) * st.overall + w * s

    # -- prediction -------------------------------------------------------
    def win_prob(self, a: str, b: str, surface: str) -> float:
        """P(a beats b) on `surface` using blended ratings (pre-match)."""
        return expected_score(self.blended(a, surface), self.blended(b, surface))

    # -- learning ---------------------------------------------------------
    def update(self, m: Match):
        """Update ratings from one match (winner beat loser)."""
        if m.walkover:  # no play -> no information
            return
        weight = self.cfg.ret_weight if m.retirement else 1.0
        if weight <= 0:
            return

        w_st, l_st = self._state(m.winner), self._state(m.loser)
        self._apply_decay(w_st, m.date)
        self._apply_decay(l_st, m.date)

        surf = m.surface if m.surface in SURFACES else None

        # --- overall update ---
        exp_w = expected_score(w_st.overall, l_st.overall)
        kw = self._k(w_st.n) * weight
        kl = self._k(l_st.n) * weight
        delta = (1.0 - exp_w)
        w_st.overall += kw * delta
        l_st.overall -= kl * delta
        w_st.n += 1
        l_st.n += 1

        # --- surface update ---
        if surf is not None:
            rw = self.surface_rating(m.winner, surf)
            rl = self.surface_rating(m.loser, surf)
            exp_ws = expected_score(rw, rl)
            kws = self._k(w_st.surf_n[surf]) * weight
            kls = self._k(l_st.surf_n[surf]) * weight
            d = (1.0 - exp_ws)
            w_st.surf[surf] = rw + kws * d
            l_st.surf[surf] = rl - kls * d
            w_st.surf_n[surf] += 1
            l_st.surf_n[surf] += 1

        w_st.last_date = m.date
        l_st.last_date = m.date


def _days_between(d_old: int, d_new: int) -> int:
    """Rough day delta between two YYYYMMDD ints (good enough for decay)."""
    from datetime import date
    def _d(x):
        y, m, d = x // 10000, (x // 100) % 100, x % 100
        try:
            return date(y, m, max(1, d))
        except ValueError:
            return date(y, m, 1)
    return (_d(d_new) - _d(d_old)).days
