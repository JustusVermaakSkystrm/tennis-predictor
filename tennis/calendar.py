"""
calendar.py — Grand Slam schedule, so the site projects the *next* major automatically.

The per-event product targets the next Grand Slam. When one finishes, the projection
rolls to the following Slam — and crucially to its SURFACE: Wimbledon (grass) → US Open
(hard) → Australian Open (hard) → Roland Garros (clay) → Wimbledon again. The site never
needs a manual edit; it always shows the relevant upcoming major on the right surface.

Slam date windows are approximate fixed month/day ranges (they shift a few days year to
year) — accurate enough to decide which Slam is current/next and to label it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# (name, surface, (start_month, start_day), (end_month, end_day))
SLAMS = [
    ("Australian Open", "Hard", (1, 12), (1, 26)),
    ("Roland Garros",   "Clay", (5, 24), (6, 8)),
    ("Wimbledon",       "Grass", (6, 29), (7, 13)),
    ("US Open",         "Hard", (8, 24), (9, 8)),
]


@dataclass
class Slam:
    name: str
    surface: str
    year: int
    start: date
    end: date
    status: str          # 'in_progress' | 'upcoming'

    @property
    def label(self) -> str:
        return f"{self.name} {self.year}"


def next_slam(today: date | None = None) -> Slam:
    """The current Slam (if one is on) else the next upcoming one, with year wrap."""
    today = today or date.today()
    cands = []
    for y in (today.year, today.year + 1):
        for name, surf, (sm, sd), (em, ed) in SLAMS:
            cands.append((date(y, sm, sd), date(y, em, ed), name, surf, y))
    cands.sort()
    for start, end, name, surf, y in cands:
        if end >= today:
            status = "in_progress" if start <= today <= end else "upcoming"
            return Slam(name, surf, y, start, end, status)
    # unreachable (next-year AO always qualifies), but keep the type honest
    s = cands[0]
    return Slam(s[2], s[3], s[4], s[0], s[1], "upcoming")


if __name__ == "__main__":
    for d in (date(2026, 6, 17), date(2026, 7, 20), date(2026, 10, 1),
              date(2027, 2, 1), date(2027, 5, 1)):
        s = next_slam(d)
        print(f"as of {d}: -> {s.label} ({s.surface}, {s.status}, {s.start}..{s.end})")
