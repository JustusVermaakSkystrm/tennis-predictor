#!/usr/bin/env bash
# Fetch ATP + WTA match history into data/sackmann/{atp,wta}/.
#
# Primary feed: LuckyLoser91/TennisCourtLog — a live mirror of Jeff Sackmann's
# (now-removed) tennis_atp / tennis_wta repos, both tours, 1968–present, refreshed
# daily. Reduced schema (names, no serve stats / ids) — sufficient for Elo; the
# serve model overlays Tennismylife/TML-Database separately.
#
# Idempotent: re-run any time to refresh. raw.githubusercontent.com is a CDN
# (no API rate limit), so a plain loop is fine.
set -euo pipefail

REPO="LuckyLoser91/TennisCourtLog"
BRANCH="main"
BASE="https://raw.githubusercontent.com/$REPO/$BRANCH"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
START_YEAR="${1:-1968}"
END_YEAR="${2:-2026}"

fetch_tour() {
  local tour="$1" subdir="$2"
  local out="$ROOT/data/sackmann/$tour"
  mkdir -p "$out"
  local ok=0 miss=0
  for y in $(seq "$START_YEAR" "$END_YEAR"); do
    local f="${tour}_matches_${y}.csv"
    if curl -s -f --max-time 30 -o "$out/$f" "$BASE/$subdir/$f"; then
      ok=$((ok+1))
    else
      rm -f "$out/$f"; miss=$((miss+1))
    fi
  done
  echo "  $tour: $ok files fetched, $miss missing  -> $out"
}

echo "Fetching $REPO ($START_YEAR–$END_YEAR)…"
fetch_tour atp tennis_atp
fetch_tour wta tennis_wta
echo "Done. Run: python3 -m tennis.dataset"
