"""
schedule.py — live upcoming matches from ESPN's (free, undocumented) scoreboard API.

The results archive (TennisCourtLog) is backward-looking, so it can't tell us what's
*about to be played*. ESPN's scoreboard endpoint lists the current week's tournaments
with their draws, including matches that haven't started yet — the "fixtures" object the
brief describes. We pull the matches whose BOTH players are already known (skip the
future-round TBDs) so the model can price each one.

ESPN doesn't expose court surface here, so we infer it from the calendar (the season's
Grand Slam surface) — fine while concurrent events share a surface; flagged as inferred.

Resilient by design: any network/parse failure returns [] so the site still builds.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

ESPN = "https://site.api.espn.com/apis/site/v2/sports/tennis/{lg}/scoreboard"
LEAGUES = {"atp": "atp", "wta": "wta"}


@dataclass
class Fixture:
    tour: str
    tournament: str
    round: str
    date: str            # ISO datetime from ESPN
    player_a: str
    player_b: str


def _get(url: str, timeout: int = 20) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "tennis-predictor/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _round_name(c: dict) -> str:
    rnd = c.get("round") or {}
    if isinstance(rnd, dict):
        return rnd.get("displayName") or rnd.get("shortName") or ""
    return str(rnd or "")


def _tour_of(c: dict, g: dict) -> str | None:
    """Derive the tour from the competition type — combined events carry both
    men's and women's draws, so the FEED is not a reliable tour signal."""
    slug = ((c.get("type") or {}).get("slug")
            or (g.get("grouping") or {}).get("slug") or "").lower()
    text = ((c.get("type") or {}).get("text") or "").lower()
    s = slug + " " + text
    if "double" in s or "mixed" in s:
        return None
    # check women FIRST — "women" contains the substring "men"
    if "wom" in s or "wta" in s or "ladies" in s:
        return "wta"
    if "men" in s or "atp" in s:
        return "atp"
    return None


def fetch_fixtures(tour: str) -> list[Fixture]:
    """Upcoming known singles matches found in one feed (tour derived per competition)."""
    data = _get(ESPN.format(lg=LEAGUES[tour]))
    if not data:
        return []
    out: list[Fixture] = []
    for ev in data.get("events", []):
        tname = ev.get("shortName") or ev.get("name") or ""
        for g in ev.get("groupings", []) or []:
            for c in g.get("competitions", []) or []:
                t = _tour_of(c, g)
                if t is None:
                    continue
                if (c.get("status") or {}).get("type", {}).get("state") != "pre":
                    continue
                names = [((cc.get("athlete") or {}).get("displayName") or "").strip()
                         for cc in c.get("competitors", [])]
                names = [n for n in names if n and n.upper() != "TBD"]
                if len(names) != 2:
                    continue
                out.append(Fixture(t, tname, _round_name(c), c.get("date", ""),
                                   names[0], names[1]))
    return out


def all_fixtures() -> list[Fixture]:
    """Both feeds merged and de-duplicated (combined events appear in both)."""
    seen, out = set(), []
    for f in fetch_fixtures("atp") + fetch_fixtures("wta"):
        key = (f.tour, f.date, tuple(sorted((f.player_a, f.player_b))))
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


if __name__ == "__main__":
    fx = all_fixtures()
    print(f"{len(fx)} known upcoming singles matches")
    for f in fx[:20]:
        print(f"  [{f.tour}] {f.tournament:<18} {f.round:<14} {f.player_a} vs {f.player_b}  ({f.date})")
