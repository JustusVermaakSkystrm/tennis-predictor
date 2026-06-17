"""
viz.py — SVG rendering for draw projections.

Two views, both pure-string SVG (no deps), themeable via CSS vars so they drop into
the site:
  * odds_svg     — horizontal title-probability bars (works at any draw size; the
                   readable summary of a 128-draw projection)
  * bracket_svg  — the seeded bracket tree (rounds left→right); best for ≤32, still
                   renders larger.
"""
from __future__ import annotations

from .simulator import DrawResult

# Palette via CSS vars with sensible fallbacks (so the file renders standalone too).
CSS = """
<style>
  .bg{fill:var(--bg,#0d1117)} .card{fill:var(--card,#161b22)}
  .txt{fill:var(--txt,#e6edf3);font-family:var(--font,'Inter',system-ui,sans-serif)}
  .mut{fill:var(--mut,#8b949e)} .barbg{fill:var(--barbg,#21262d)}
  .bar{fill:var(--accent,#2f81f7)} .bar2{fill:var(--accent2,#3fb950)}
  .line{stroke:var(--line,#30363d);stroke-width:1.5;fill:none}
  .seed{fill:var(--mut,#8b949e)}
</style>
"""


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def odds_svg(res: DrawResult, *, top: int = 16, title: str = "Title odds",
             subtitle: str = "") -> str:
    rows = res.champion_table(top)
    if not rows:
        return "<svg/>"
    W, pad, top_pad = 720, 16, 64
    rh = 30
    H = top_pad + len(rows) * rh + pad
    maxw = max(w for _, w, _, _ in rows) or 1.0
    label_w, bar_x = 210, 230
    bar_max = W - bar_x - 90

    parts = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">', CSS,
             f'<rect class="bg" x="0" y="0" width="{W}" height="{H}" rx="12"/>',
             f'<text class="txt" x="{pad}" y="30" font-size="20" font-weight="700">{_esc(title)}</text>']
    if subtitle:
        parts.append(f'<text class="mut" x="{pad}" y="50" font-size="13">{_esc(subtitle)}</text>')

    for i, (name, w, f, sf) in enumerate(rows):
        y = top_pad + i * rh
        parts.append(f'<text class="txt" x="{pad}" y="{y+19}" font-size="14">{i+1}. {_esc(name)}</text>')
        parts.append(f'<rect class="barbg" x="{bar_x}" y="{y+6}" width="{bar_max}" height="16" rx="4"/>')
        bw = max(2, bar_max * (w / maxw))
        parts.append(f'<rect class="bar" x="{bar_x}" y="{y+6}" width="{bw:.1f}" height="16" rx="4"/>')
        parts.append(f'<text class="txt" x="{bar_x+bar_max+8}" y="{y+19}" font-size="13" font-weight="600">{w*100:.1f}%</text>')
    parts.append('</svg>')
    return "\n".join(parts)


def scorecard_svg(cards: list[dict], *, title: str = "Model scorecard") -> str:
    """Render a metric scorecard. Each card: {tour, rows:[(label, model, bench, better)]}.
    `better` in {'low','high'} marks which side wins; the winner is tinted."""
    cw, gap, pad, top = 340, 20, 18, 70
    n = len(cards)
    W = pad * 2 + n * cw + (n - 1) * gap
    body_rows = max(len(c["rows"]) for c in cards) if cards else 0
    H = top + body_rows * 30 + 80
    parts = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">', CSS,
             f'<rect class="bg" x="0" y="0" width="{W}" height="{H}" rx="12"/>',
             f'<text class="txt" x="{pad}" y="34" font-size="20" font-weight="700">{_esc(title)}</text>']
    for ci, c in enumerate(cards):
        x = pad + ci * (cw + gap)
        parts.append(f'<rect class="card" x="{x}" y="{top-18}" width="{cw}" height="{H-top-12}" rx="10"/>')
        parts.append(f'<text class="txt" x="{x+16}" y="{top+6}" font-size="15" font-weight="700">{_esc(c["tour"])}</text>')
        parts.append(f'<text class="mut" x="{x+cw-16}" y="{top+6}" font-size="11" text-anchor="end">model · benchmark</text>')
        for ri, (label, mv, bv, better) in enumerate(c["rows"]):
            y = top + 30 + ri * 30
            parts.append(f'<text class="mut" x="{x+16}" y="{y+4}" font-size="12">{_esc(label)}</text>')
            mwin = (better == "low" and mv <= bv) or (better == "high" and mv >= bv) if isinstance(mv,(int,float)) and isinstance(bv,(int,float)) else False
            mcls = "bar2" if mwin else "txt"
            bcls = "bar2" if (not mwin and isinstance(bv,(int,float))) else "txt"
            ms = mv if isinstance(mv, str) else f"{mv}"
            bs = bv if isinstance(bv, str) else f"{bv}"
            parts.append(f'<text class="{mcls}" x="{x+cw-150}" y="{y+4}" font-size="13" font-weight="600" text-anchor="end" '
                         f'style="fill:{"var(--accent2,#3fb950)" if mwin else "var(--txt,#e6edf3)"}">{ms}</text>')
            parts.append(f'<text x="{x+cw-16}" y="{y+4}" font-size="13" text-anchor="end" '
                         f'style="fill:{"var(--accent2,#3fb950)" if (not mwin and isinstance(bv,(int,float))) else "var(--mut,#8b949e)"}">{bs}</text>')
    parts.append('</svg>')
    return "\n".join(parts)


def bracket_svg(res: DrawResult, seeded_keys: list[str], *, title: str = "") -> str:
    """Render the seeded bracket tree. `seeded_keys` = bracket-slot order (len=draw_size)."""
    size = res.draw_size
    n_match_rounds = len(res.rounds) - 1
    col_w, row_h = 168, 26
    pad_x, pad_top = 16, 56
    H = pad_top + size * row_h + 20
    W = pad_x * 2 + (n_match_rounds + 1) * col_w

    def cell(x, y, key, seed=None):
        nm = res.names.get(key, key.split(":", 1)[-1] if key else "")
        wp = res.reach.get(key, {}).get("W", 0.0) if key else 0.0
        s = []
        s.append(f'<rect class="card" x="{x}" y="{y}" width="{col_w-16}" height="20" rx="4"/>')
        if seed is not None:
            s.append(f'<text class="seed" x="{x+6}" y="{y+14}" font-size="10">{seed}</text>')
        label = _esc(nm) if nm else "—"
        s.append(f'<text class="txt" x="{x+24}" y="{y+14}" font-size="11">{label}</text>')
        if wp >= 0.005:
            s.append(f'<text class="mut" x="{x+col_w-22}" y="{y+14}" font-size="9" text-anchor="end">{wp*100:.0f}%</text>')
        return "".join(s)

    parts = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">', CSS,
             f'<rect class="bg" x="0" y="0" width="{W}" height="{H}" rx="12"/>']
    if title:
        parts.append(f'<text class="txt" x="{pad_x}" y="32" font-size="18" font-weight="700">{_esc(title)}</text>')

    # round 0: all slots
    positions = []  # y-centre per entry in current column
    col0 = []
    seeds_by_key = {}
    # recover seed numbers from rating order for display
    ranked = sorted([k for k in seeded_keys if k], key=lambda k: res.reach.get(k, {}).get("W", 0), reverse=True)
    for i, k in enumerate(ranked, 1):
        seeds_by_key[k] = i
    for slot in range(size):
        y = pad_top + slot * row_h
        key = seeded_keys[slot] if slot < len(seeded_keys) else None
        parts.append(cell(pad_x, y, key, seeds_by_key.get(key)))
        col0.append((y + 10, key))
    positions = col0

    # subsequent rounds: midpoint of the two feeders
    for r in range(1, n_match_rounds + 1):
        x = pad_x + r * col_w
        nxt = []
        for i in range(0, len(positions), 2):
            (y1, _), (y2, _) = positions[i], positions[i + 1]
            yc = (y1 + y2) / 2
            # connector lines
            parts.append(f'<path class="line" d="M{x-16} {y1} H{x-8} V{y2} H{x-16}"/>')
            parts.append(f'<path class="line" d="M{x-8} {yc} H{x}"/>')
            nxt.append((yc, None))
            parts.append(cell(x, yc - 10, None))
        positions = nxt
    parts.append('</svg>')
    return "\n".join(parts)
