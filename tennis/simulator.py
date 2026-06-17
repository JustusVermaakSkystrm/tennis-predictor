"""
simulator.py — Monte Carlo single-elimination draw (bracket) simulator.

A tennis tournament IS a knockout bracket, so this is the per-event product: feed a
field + surface, simulate the bracket many thousands of times with Elo match
probabilities, and read off each player's probability of reaching every round —
the "path to the final" projection.

Seeding: if you don't supply an explicit draw, the field is seeded by current rating
and placed into a standard bracket template (seed 1 and 2 in opposite halves, 3/4 in
opposite quarters, …). When the real draw is published, pass `slots=` to honour it.

Best-of: pure Elo gives a match probability that already reflects the mix it trained
on. True Bo3-vs-Bo5 amplification (a favourite wins Bo5 more often) arrives with the
serve-based Markov model (v2); `bo5_sharpen` offers a light optional approximation.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .ratings import EloEngine

ROUND_NAMES = {
    128: ["R128", "R64", "R32", "R16", "QF", "SF", "F", "W"],
    64:  ["R64", "R32", "R16", "QF", "SF", "F", "W"],
    32:  ["R32", "R16", "QF", "SF", "F", "W"],
    16:  ["R16", "QF", "SF", "F", "W"],
    8:   ["QF", "SF", "F", "W"],
    4:   ["SF", "F", "W"],
    2:   ["F", "W"],
}


def next_pow2(n: int) -> int:
    return 1 << (max(1, n - 1)).bit_length()


def seed_slots(n: int) -> list[int]:
    """Standard bracket seeding order for n=2^k slots (1-indexed seed numbers)."""
    ts = [1, 2]
    while len(ts) < n:
        m = len(ts) * 2
        nxt = []
        for t in ts:
            nxt.append(t)
            nxt.append(m + 1 - t)
        ts = nxt
    return ts


@dataclass
class Entrant:
    key: str
    name: str
    rating_blend: float  # for seeding/display only


@dataclass
class DrawResult:
    draw_size: int
    rounds: list[str]
    # per entrant key: {round_label: probability of REACHING that round}
    reach: dict
    names: dict
    n_sims: int

    def champion_table(self, top: int = 16) -> list[tuple]:
        order = sorted(self.reach.items(), key=lambda kv: kv[1].get("W", 0), reverse=True)
        out = []
        for key, r in order[:top]:
            out.append((self.names[key], r.get("W", 0.0),
                        r.get("F", 0.0), r.get("SF", 0.0)))
        return out


def _bo5_adjust(p: float, sharpen: float) -> float:
    """Light Bo5 amplification: push the match prob away from 0.5 a touch.
    sharpen=0 -> unchanged. Placeholder until the serve model gives this exactly."""
    if sharpen <= 0:
        return p
    # logit stretch
    p = min(max(p, 1e-6), 1 - 1e-6)
    z = math.log(p / (1 - p)) * (1 + sharpen)
    return 1.0 / (1.0 + math.exp(-z))


def build_field(entrant_keys: list[str], elo: EloEngine, surface: str) -> list[Entrant]:
    out = []
    for k in entrant_keys:
        name = k.split(":", 1)[1] if ":" in k else k
        out.append(Entrant(k, name, elo.blended(k, surface)))
    return out


def seeded_slot_order(entrant_keys: list[str], elo: EloEngine, surface: str) -> list[str | None]:
    """Place a field into standard bracket slots by rating (shared by sim + viz)."""
    field_ = build_field(entrant_keys, elo, surface)
    size = next_pow2(len(field_))
    seeded = sorted(field_, key=lambda e: e.rating_blend, reverse=True)
    order = seed_slots(size)
    slots: list[str | None] = [None] * size
    for slot, seed_no in enumerate(order):
        if seed_no <= len(seeded):
            slots[slot] = seeded[seed_no - 1].key
    return slots


def simulate(entrant_keys: list[str], elo: EloEngine, surface: str, *,
             best_of: int = 3, n_sims: int = 20000, seed_by_rating: bool = True,
             slots: list[str] | None = None, bo5_sharpen: float = 0.0,
             rng_seed: int = 12345) -> DrawResult:
    """Simulate a single-elim draw and return per-player round-reach probabilities."""
    field_ = build_field(entrant_keys, elo, surface)
    size = next_pow2(len(field_))
    rounds = ROUND_NAMES.get(size)
    if rounds is None:
        raise ValueError(f"Unsupported draw size {size} (field {len(field_)}).")

    # --- arrange the bracket as a list of `size` slots (None = bye) ---
    if slots is not None:
        if len(slots) != size:
            raise ValueError(f"slots length {len(slots)} != draw size {size}")
        bracket0 = [None if s in (None, "", "BYE") else s for s in slots]
    else:
        seeded = sorted(field_, key=lambda e: e.rating_blend, reverse=True) if seed_by_rating else field_
        order = seed_slots(size)            # seed number per slot
        bracket0 = [None] * size
        for slot, seed_no in enumerate(order):
            if seed_no <= len(seeded):
                bracket0[slot] = seeded[seed_no - 1].key

    sharpen = bo5_sharpen if best_of == 5 else 0.0
    reach = {e.key: {r: 0 for r in rounds} for e in field_}
    names = {e.key: e.name for e in field_}

    rng = random.Random(rng_seed)
    pcache: dict[tuple, float] = {}

    def winp(a: str, b: str) -> float:
        kk = (a, b)
        p = pcache.get(kk)
        if p is None:
            p = _bo5_adjust(elo.win_prob(a, b, surface), sharpen)
            pcache[kk] = p
        return p

    match_rounds = rounds[:-1]   # all labels except the title "W"
    for _ in range(n_sims):
        cur = bracket0
        for rlabel in match_rounds:
            # everyone still in `cur` has REACHED this round
            nxt = []
            for i in range(0, len(cur), 2):
                a, b = cur[i], cur[i + 1]
                if a is not None:
                    reach[a][rlabel] += 1
                if b is not None:
                    reach[b][rlabel] += 1
                if a is None and b is None:
                    nxt.append(None)
                elif a is None:
                    nxt.append(b)
                elif b is None:
                    nxt.append(a)
                else:
                    nxt.append(a if rng.random() < winp(a, b) else b)
            cur = nxt
        champ = cur[0]            # survivor wins the title
        if champ is not None:
            reach[champ]["W"] += 1

    for key in reach:
        reach[key] = {r: reach[key][r] / n_sims for r in rounds}
    return DrawResult(size, rounds, reach, names, n_sims)
